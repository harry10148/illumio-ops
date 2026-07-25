"""殘項 R3：從沒被查過的規則必須留下紀錄，不得被報表當成「未使用」。

batch_get_rule_traffic_counts 對兩種規則會直接跳過：
  1. _build_rule_query_payload 回 None（payload 建不出來）
  2. submit_async_query 回 None（job 送不出去）
兩者原本都是 bare continue，結果那些規則既不在 hit 名單、也不在
failed_rule_details / pending_rule_details，Policy Usage 報表的
pu_mod03_unused_detail 只好把它們標成 Unused——操作者可能照著這張表去下架
實際上還在承載流量的規則。

修法是把它們記進 failed_rule_details（報表顯示 Query Failed）並計入 failed_jobs，
讓 executive 的 RESOLVE_QUERY_FAILURES blind-spot 訊號也會亮。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock

import orjson

from src.api_client import ApiClient
from src.report.analysis.policy_usage.pu_mod03_unused_detail import pu_unused_detail


def _rule(rule_id):
    return {
        "href": f"/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/{rule_id}",
        "_rule_id": str(rule_id),
        "_rule_no": rule_id,
        "_ruleset_href": "/orgs/1/sec_policy/draft/rule_sets/1",
        "_ruleset_name": "RS1",
        "_ruleset_scopes": [],
        "consumers": [],
        "providers": [],
        "ingress_services": [],
    }


class _Harness(unittest.TestCase):
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

    def _run(self, rules):
        return self.client.batch_get_rule_traffic_counts(
            rules, "2026-04-01T00:00:00Z", "2026-04-02T00:00:00Z")


class TestUnbuildablePayloadIsRecorded(_Harness):
    def test_payload_none_lands_in_failed_details(self):
        bad, good = _rule(1), _rule(2)
        builder = self.client._traffic
        real_build = builder._build_rule_query_payload

        def fake_build(rule, start_date, end_date):
            if rule["href"] == bad["href"]:
                return None
            return real_build(rule, start_date, end_date)

        builder._build_rule_query_payload = fake_build

        job_href = "/orgs/1/traffic_flows/async_queries/1"

        def fake_request(url, method="GET", data=None, timeout=None, rate_limit=False):
            if method == "POST" and url.endswith("/async_queries"):
                return 202, orjson.dumps({"href": job_href, "status": "queued"})
            if url.endswith(job_href):
                return 200, orjson.dumps({"status": "completed",
                                          "result": f"{job_href}/download"})
            if url.endswith("/download"):
                return 200, b""
            self.fail(f"Unexpected request: {url}")

        self.client._request = fake_request

        self._run([bad, good])
        stats = self.client.get_last_rule_usage_batch_stats()

        hrefs = [d["rule_href"] for d in stats["failed_rule_details"]]
        self.assertIn(bad["href"], hrefs)
        self.assertNotIn(good["href"], hrefs)
        self.assertGreaterEqual(stats["failed_jobs"], 1)

    def test_payload_none_only_run_reports_it_on_the_cache_only_return_path(self):
        """整批都建不出 payload 時走的是 `if not job_map` 早退路徑，同樣要記錄。"""
        bad = _rule(1)
        self.client._traffic._build_rule_query_payload = (
            lambda rule, start_date, end_date: None)

        self._run([bad])
        stats = self.client.get_last_rule_usage_batch_stats()

        self.assertEqual([d["rule_href"] for d in stats["failed_rule_details"]],
                         [bad["href"]])
        self.assertEqual(stats["failed_jobs"], 1)


class TestUnsubmittableRuleIsRecorded(_Harness):
    def test_submit_returning_none_lands_in_failed_details(self):
        rule = _rule(3)
        self.client._jobs.submit_async_query = lambda payload: None

        self._run([rule])
        stats = self.client.get_last_rule_usage_batch_stats()

        self.assertEqual([d["rule_href"] for d in stats["failed_rule_details"]],
                         [rule["href"]])
        self.assertEqual(stats["failed_jobs"], 1)


class TestReportMarksSkippedRulesAsQueryFailed(unittest.TestCase):
    """對帳產出端與消費端：記進 failed_rule_details 後，報表要標 Query Failed。"""

    def test_unused_detail_status_is_query_failed(self):
        rule = _rule(1)
        stats = {"failed_rule_details": [{"rule_href": rule["href"], "status": "failed"}]}

        result = pu_unused_detail([rule], {}, set(), stats, None)
        rows = result["unused_df"].to_dict("records")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Status"], "Query Failed")
        # 沒查過就不能宣稱「觀測期間 0 次命中」
        self.assertNotEqual(rows[0]["Observed Hit Ports"], "None in lookback")
        self.assertEqual(result["confirmed_unused"], 0)
        self.assertEqual(result["indeterminate_count"], 1)


if __name__ == "__main__":
    unittest.main()
