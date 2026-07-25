"""get_rule_traffic_count 的「查不到答案」不得偽裝成 0 flows。

序列相容路徑（TrafficQueryBuilder.get_rule_traffic_count）以前在 payload 組
不出來、submit 失敗、poll 逾時、或任何例外時都 return 0，與「這條規則真的沒
流量」完全同形；下游把它列成 unused，操作者就會刪掉一條其實從沒被檢查過的
規則。新契約：0 只代表 PCE 有回答且真的沒流量，其餘一律拋
RuleTrafficQueryError（pending=True 代表 poll 逾時，PCE job 可能還在跑），
對齊 batch 路徑的 failed_rule_details / pending_rule_details 語意。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.api_client import ApiClient
from src.exceptions import AsyncDownloadError, RuleTrafficQueryError

START = "2026-04-01T00:00:00Z"
END = "2026-04-02T00:00:00Z"

RULE = {
    "href": "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/9",
    "_ruleset_scopes": [],
    "consumers": [],
    "providers": [],
    "ingress_services": [],
}


def _classify(client, rule):
    """How a caller turns a per-rule count into the report's Status column.

    Mirrors pu_mod03_unused_detail: count 0 -> Unused, otherwise Hit, and an
    indeterminate query must land on Query Failed / Query Pending instead.
    """
    try:
        return "Unused" if client.get_rule_traffic_count(rule, START, END) == 0 else "Hit"
    except RuleTrafficQueryError as exc:
        return "Query Pending" if exc.pending else "Query Failed"
    except AsyncDownloadError:
        return "Query Failed"


class TestRuleTrafficCountIndeterminate(unittest.TestCase):
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
        self.client.update_label_cache = MagicMock(return_value=None)
        self.jobs = MagicMock()
        self.jobs.find_cached_async_summary.return_value = None
        self.client._jobs = self.jobs
        self.client._request = lambda *a, **kw: self.fail("no HTTP expected")

    # ── 真的沒流量：0 仍然是 0 ─────────────────────────────────────────
    def test_zero_flows_still_returns_zero(self):
        self.jobs.find_cached_async_summary.return_value = {"count": 0}
        self.assertEqual(self.client.get_rule_traffic_count(RULE, START, END), 0)
        self.assertEqual(_classify(self.client, RULE), "Unused")

    def test_hit_count_is_returned(self):
        self.jobs.find_cached_async_summary.return_value = {"count": 12}
        self.assertEqual(self.client.get_rule_traffic_count(RULE, START, END), 12)

    # ── 每種失敗都必須是 indeterminate，不得回 0 ───────────────────────
    def test_payload_build_failure_raises(self):
        self.client._traffic._build_rule_query_payload = MagicMock(return_value=None)
        with self.assertRaises(RuleTrafficQueryError) as ctx:
            self.client.get_rule_traffic_count(RULE, START, END)
        self.assertFalse(ctx.exception.pending)
        self.assertEqual(_classify(self.client, RULE), "Query Failed")

    def test_submit_failure_raises(self):
        self.jobs.submit_async_query.return_value = None
        with self.assertRaises(RuleTrafficQueryError) as ctx:
            self.client.get_rule_traffic_count(RULE, START, END)
        self.assertFalse(ctx.exception.pending)
        self.assertEqual(_classify(self.client, RULE), "Query Failed")

    def test_poll_timeout_raises_as_pending(self):
        self.jobs.submit_async_query.return_value = "/async_queries/1"
        self.jobs.poll_async_query.return_value = False
        with self.assertRaises(RuleTrafficQueryError) as ctx:
            self.client.get_rule_traffic_count(RULE, START, END)
        self.assertTrue(ctx.exception.pending)
        self.assertEqual(_classify(self.client, RULE), "Query Pending")

    def test_download_failure_still_propagates(self):
        self.jobs.submit_async_query.return_value = "/async_queries/1"
        self.jobs.poll_async_query.return_value = True
        self.jobs.summarize_async_query.side_effect = AsyncDownloadError("HTTP 500")
        with self.assertRaises(AsyncDownloadError):
            self.client.get_rule_traffic_count(RULE, START, END)
        self.assertEqual(_classify(self.client, RULE), "Query Failed")

    def test_unexpected_error_is_wrapped_not_swallowed(self):
        self.jobs.find_cached_async_summary.side_effect = RuntimeError("boom")
        with self.assertRaises(RuleTrafficQueryError) as ctx:
            self.client.get_rule_traffic_count(RULE, START, END)
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
        self.assertEqual(_classify(self.client, RULE), "Query Failed")

    def test_no_failure_mode_is_classified_unused(self):
        """The whole point: none of the failure modes may read as 'Unused'."""
        modes = {
            "payload": lambda: setattr(
                self.client._traffic, "_build_rule_query_payload",
                MagicMock(return_value=None)),
            "submit": lambda: setattr(
                self.jobs, "submit_async_query", MagicMock(return_value=None)),
            "poll": lambda: (
                setattr(self.jobs, "submit_async_query", MagicMock(return_value="/j/1")),
                setattr(self.jobs, "poll_async_query", MagicMock(return_value=False))),
            "error": lambda: setattr(
                self.jobs, "find_cached_async_summary",
                MagicMock(side_effect=RuntimeError("boom"))),
        }
        for name, arrange in modes.items():
            with self.subTest(mode=name):
                self.setUp()
                arrange()
                self.assertIn(_classify(self.client, RULE),
                              ("Query Failed", "Query Pending"),
                              f"{name} failure must not read as Unused")


class TestNoCallerSwallowsIndeterminate(unittest.TestCase):
    """AST 守門：呼叫端不得把 indeterminate 吞回 0/None。

    契約只有在沒人 `except: return 0` 時才成立，而這正是本次修掉的原始寫法。
    """

    SRC = Path(__file__).resolve().parents[1] / "src"

    def test_call_sites_do_not_swallow_into_a_falsy_count(self):
        offenders = []
        for path in self.SRC.rglob("*.py"):
            # utf-8-sig: src/reporter.py carries a BOM that plain utf-8 chokes on.
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for func in ast.walk(tree):
                if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = [
                    n for n in ast.walk(func)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get_rule_traffic_count"
                ]
                if not calls:
                    continue
                for handler in [n for n in ast.walk(func) if isinstance(n, ast.ExceptHandler)]:
                    for node in ast.walk(handler):
                        if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant) \
                                and node.value.value in (0, None, False):
                            offenders.append(f"{path.name}:{func.name}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "呼叫端把查詢失敗轉回 0/None，會讓沒查成功的規則被報成 unused：" + str(offenders))


if __name__ == "__main__":
    unittest.main()
