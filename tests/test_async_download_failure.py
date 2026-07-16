"""Task 3: async 下載失敗誠實化 — 下載非 200 須拋例外，不得被誤判為 0 flows/unused。

涵蓋：
- iter_async_query_results 下載失敗時拋 AsyncDownloadError，job state 標記 failed，
  不得留下可被後續讀成 completed 的痕跡。
- summarize_async_query 只有真正迭代完成才寫 download_status="completed"；
  下載失敗時例外原樣往上拋，不吞掉。
- batch_get_rule_traffic_counts 的下載迴圈遇到 AsyncDownloadError 時，該 rule
  要落入 failed_rule_details，不得混進 hit/unused 名單。
"""
from __future__ import annotations

import gzip
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import orjson

from src.api_client import ApiClient
from src.exceptions import AsyncDownloadError


class _ClientHarness(unittest.TestCase):
    def setUp(self):
        self.mock_cm = MagicMock()
        self.mock_cm.config = {
            "api": {
                "url": "https://pce.example.com:8443",
                "org_id": "1",
                "key": "key",
                "secret": "secret",
                "verify_ssl": True,
            }
        }
        self.client = ApiClient(self.mock_cm)
        self._temp_dir = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._temp_dir.name, "state.json")

    def tearDown(self):
        self._temp_dir.cleanup()


class TestIterAsyncQueryResultsRaisesOnDownloadFailure(_ClientHarness):
    def test_iter_raises_on_download_failure(self):
        job_href = "/orgs/1/traffic_flows/async_queries/500"
        self.client._request = lambda url, **kwargs: (500, b"")

        with self.assertRaises(AsyncDownloadError):
            list(self.client.iter_async_query_results(job_href))

        with open(self.client._state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        job_state = state["async_query_jobs"][job_href]
        self.assertEqual(job_state["download_status"], "failed:500")
        self.assertNotEqual(job_state.get("download_status"), "completed")


class TestSummarizeAsyncQuerySuccessStillMarksCompleted(_ClientHarness):
    def test_summarize_success_marks_completed(self):
        job_href = "/orgs/1/traffic_flows/async_queries/200"
        payload_lines = b"\n".join([
            json.dumps({"service": {"port": 443, "proto": 6}}).encode("utf-8"),
            json.dumps({"dst_port": 53, "proto": 17}).encode("utf-8"),
        ])
        compressed = gzip.compress(payload_lines)
        self.client._request = lambda url, **kwargs: (200, compressed)

        summary = self.client.summarize_async_query(job_href)

        self.assertEqual(summary["count"], 2)
        with open(self.client._state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        job_state = state["async_query_jobs"][job_href]
        self.assertEqual(job_state["download_status"], "completed")
        self.assertEqual(job_state["flow_count"], 2)

    def test_summarize_raises_and_does_not_overwrite_failed_as_completed(self):
        """迴歸關鍵 bug：下載失敗時原本會被無條件覆寫成 completed + flow_count=0。"""
        job_href = "/orgs/1/traffic_flows/async_queries/500"
        self.client._request = lambda url, **kwargs: (500, b"")

        with self.assertRaises(AsyncDownloadError):
            self.client.summarize_async_query(job_href)

        with open(self.client._state_file, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        job_state = state["async_query_jobs"][job_href]
        self.assertEqual(job_state["download_status"], "failed:500")


class TestBatchGetRuleTrafficCountsRoutesDownloadFailure(_ClientHarness):
    def test_batch_counts_routes_download_failure_to_failed_details(self):
        rule = {
            "href": "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/9",
            "_ruleset_scopes": [],
            "consumers": [],
            "providers": [],
            "ingress_services": [],
        }
        job_href = "/orgs/1/traffic_flows/async_queries/900"

        def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
            if method == "POST" and url.endswith("/async_queries"):
                return 202, orjson.dumps({"href": job_href, "status": "queued"})
            if url.endswith(job_href):
                # poll
                return 200, orjson.dumps({"status": "completed", "result": f"{job_href}/download"})
            if url.endswith("/download"):
                return 500, b""
            self.fail(f"Unexpected request: {url}")

        self.client._request = fake_request

        hit_hrefs, hit_counts = self.client.batch_get_rule_traffic_counts(
            [rule],
            "2026-04-01T00:00:00Z",
            "2026-04-02T00:00:00Z",
        )

        self.assertEqual(hit_hrefs, set())
        self.assertEqual(hit_counts, {})
        stats = self.client.get_last_rule_usage_batch_stats()
        self.assertEqual(len(stats["failed_rule_details"]), 1)
        self.assertEqual(stats["failed_rule_details"][0]["rule_href"], rule["href"])
        self.assertEqual(stats["failed_rule_details"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
