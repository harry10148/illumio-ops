"""ReportsApi.pull_rule_hit_count_report — submit → poll → download state machine."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from src.api.reports import ReportsApi, RuleHitCountPullTimeout


def _client(poll_statuses=("pending", "done"), download=(200, b"Rule HREF,Rule Hit Count\n/r/1,3\n")):
    c = MagicMock()
    c.api_cfg = {"org_id": 1, "url": "https://pce.example.com:8443"}
    c._api_post.return_value = (201, {"href": "/orgs/1/reports/abc-123"})
    polls = [(200, {"status": s}) for s in poll_statuses]
    c._api_get.side_effect = polls
    c._request.return_value = download
    return c


class TestPull(unittest.TestCase):
    def test_happy_path_writes_csv(self):
        c = _client()
        with patch("src.api.reports.time.sleep"):
            path = ReportsApi(c).pull_rule_hit_count_report(last_num_days=30)
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            self.assertIn("Rule HREF", fh.read())
        os.unlink(path)
        # payload shape
        payload = c._api_post.call_args.args[1]
        self.assertEqual(payload["report_template"]["href"],
                         "/orgs/1/report_templates/rule_hit_count_report")
        self.assertEqual(payload["report_parameters"]["rule_sets"], [])
        self.assertEqual(payload["report_parameters"]["report_time_range"],
                         {"last_num_days": 30})
        self.assertEqual(payload["report_format"], "csv")
        # download hits the /download endpoint
        self.assertIn("/orgs/1/reports/abc-123/download", c._request.call_args.args[0])

    def test_explicit_date_range(self):
        c = _client()
        with patch("src.api.reports.time.sleep"):
            path = ReportsApi(c).pull_rule_hit_count_report(
                start_date="2026-06-01T00:00:00Z", end_date="2026-07-01T00:00:00Z")
        os.unlink(path)
        payload = c._api_post.call_args.args[1]
        self.assertEqual(payload["report_parameters"]["report_time_range"],
                         {"start_date": "2026-06-01T00:00:00Z",
                          "end_date": "2026-07-01T00:00:00Z"})

    def test_bare_dates_normalized_to_iso_timestamps(self):
        """PCE rejects bare YYYY-MM-DD with HTTP 406 (real-PCE verified 2026-07-11);
        the CLI/GUI pass bare dates, so the API layer must normalize them."""
        c = _client()
        with patch("src.api.reports.time.sleep"):
            path = ReportsApi(c).pull_rule_hit_count_report(
                start_date="2026-06-01", end_date="2026-07-01")
        os.unlink(path)
        payload = c._api_post.call_args.args[1]
        self.assertEqual(payload["report_parameters"]["report_time_range"],
                         {"start_date": "2026-06-01T00:00:00Z",
                          "end_date": "2026-07-01T23:59:59Z"})

    def test_submit_failure_message_includes_body(self):
        c = _client()
        c._api_post.return_value = (406, {"error": "invalid time range"})
        with self.assertRaises(RuntimeError) as ctx:
            ReportsApi(c).pull_rule_hit_count_report(
                start_date="2026-06-01", end_date="2026-07-01")
        self.assertIn("406", str(ctx.exception))
        self.assertIn("invalid time range", str(ctx.exception))

    def test_report_failed_status_raises(self):
        c = _client(poll_statuses=("pending", "failed"))
        with patch("src.api.reports.time.sleep"):
            with self.assertRaises(RuntimeError):
                ReportsApi(c).pull_rule_hit_count_report(last_num_days=7)

    def test_timeout_raises_with_href(self):
        c = _client(poll_statuses=("pending",) * 50)
        with patch("src.api.reports.time.sleep"), \
             patch("src.api.reports.time.monotonic", side_effect=[0.0] + [1000.0] * 60):
            with self.assertRaises(RuleHitCountPullTimeout) as ctx:
                ReportsApi(c).pull_rule_hit_count_report(last_num_days=7, timeout_seconds=600)
        self.assertEqual(ctx.exception.report_href, "/orgs/1/reports/abc-123")

    def test_submit_failure_raises(self):
        c = _client()
        c._api_post.return_value = (500, None)
        with self.assertRaises(RuntimeError):
            ReportsApi(c).pull_rule_hit_count_report(last_num_days=7)


if __name__ == "__main__":
    unittest.main()
