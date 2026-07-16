"""Task 4（API layer hardening）：inventory getter 錯誤傳播 + 消費端修復。

涵蓋：
1. 五個 inventory getter（get_active_rulesets/get_ip_lists/get_label_groups/
   get_services/get_all_labels）的 raise_on_error 參數化行為釘：預設 False 回
   []（零行為變更）；raise_on_error=True 時非 200（含 status 0 連線層失敗）
   raise APIError。
2. policy_diff / policy_resolver 報表生成器：PCE 故障時必須讓例外往上炸，
   不得產出「規則全被移除」的誤導 diff/結果。
3. expand_object_filters_for_df 的 _iplist_cidrs：fetch 失敗要 raise；
   fetch 成功但名稱/href 找不到匹配才是合法查無，回 [] 但留 warning log。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest

from src.api_client import ApiClient
from src.exceptions import APIError
from src.report.policy_diff_report import PolicyDiffReport
from src.report.policy_resolver_report import PolicyResolverReport


# ── 1. 五個 getter 的 raise_on_error 參數化行為 ──────────────────────────────

_GETTER_CASES = [
    ("get_active_rulesets", (), "/orgs/1/sec_policy/active/rule_sets"),
    ("get_ip_lists", (), "/orgs/1/sec_policy/active/ip_lists"),
    ("get_label_groups", (), "/orgs/1/sec_policy/active/label_groups"),
    ("get_services", (), "/orgs/1/sec_policy/active/services"),
    ("get_all_labels", (), "/orgs/1/labels"),
]


class TestInventoryGettersRaiseOnError(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def test_default_returns_empty_on_http_error(self):
        for name, args, _path in _GETTER_CASES:
            with self.subTest(getter=name):
                self.client._get_collection = lambda path, *, timeout=15: (503, None, None)
                out = getattr(self.client, name)(*args)
                self.assertEqual(out, [])

    def test_raise_on_error_raises_on_http_error(self):
        for name, args, _path in _GETTER_CASES:
            with self.subTest(getter=name):
                self.client._get_collection = lambda path, *, timeout=15: (503, None, None)
                with self.assertRaises(APIError) as ctx:
                    getattr(self.client, name)(*args, raise_on_error=True)
                self.assertIn("503", str(ctx.exception))

    def test_raise_on_error_raises_on_connection_layer_failure(self):
        # _request 連線層失敗慣例：status 0
        for name, args, _path in _GETTER_CASES:
            with self.subTest(getter=name):
                self.client._get_collection = lambda path, *, timeout=15: (0, None, None)
                with self.assertRaises(APIError):
                    getattr(self.client, name)(*args, raise_on_error=True)

    def test_raise_on_error_empty_200_is_legit_empty(self):
        # 200 且空 list = 合法空 org，不 raise
        for name, args, _path in _GETTER_CASES:
            with self.subTest(getter=name):
                self.client._get_collection = lambda path, *, timeout=15: (200, [], None)
                out = getattr(self.client, name)(*args, raise_on_error=True)
                self.assertEqual(out, [])

    def test_raise_on_error_returns_data_on_200(self):
        for name, args, _path in _GETTER_CASES:
            with self.subTest(getter=name):
                payload = [{"href": "/x/1", "name": "obj"}]
                self.client._get_collection = lambda path, *, timeout=15: (200, payload, None)
                out = getattr(self.client, name)(*args, raise_on_error=True)
                self.assertEqual(out, payload)


# ── 2. policy_diff / policy_resolver：PCE 故障要 raise，不得產出誤導結果 ──────

def test_policy_diff_fails_loud_on_pce_error():
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.side_effect = APIError("get_ip_lists failed: HTTP 503 for /x")
    api.get_services.return_value = []
    api.get_label_groups.return_value = []

    rep = PolicyDiffReport(cm=MagicMock(), api_client=api)
    with pytest.raises(APIError):
        rep.build()


def test_policy_resolver_fails_loud_on_pce_error():
    api = MagicMock()
    api.get_active_rulesets.side_effect = APIError(
        "get_active_rulesets failed: HTTP 503 for /x")
    api.fetch_managed_workloads.return_value = []

    rep = PolicyResolverReport(cm=MagicMock(), api_client=api)
    with pytest.raises(APIError):
        rep.resolve()


def test_policy_diff_object_layers_raise_on_error_true():
    """_OBJECT_SPECS 動態 fetch 迴圈（ip_lists/services/label_groups）也要帶
    raise_on_error=True——不只 rulesets/labels 這兩個直接呼叫站點。"""
    api = MagicMock()
    api.get_all_rulesets.return_value = []
    api.get_active_rulesets.return_value = []
    api.get_ip_lists.return_value = []
    api.get_services.return_value = []
    api.get_label_groups.return_value = []
    api.get_all_labels.return_value = []

    rep = PolicyDiffReport(cm=MagicMock(), api_client=api)
    with patch.object(rep, "_fetch_policy_events",
                       return_value={"draft_events": None}):
        rep.build()

    api.get_all_rulesets.assert_called_once_with(force_refresh=True, raise_on_error=True)
    api.get_active_rulesets.assert_called_once_with(raise_on_error=True)
    api.get_all_labels.assert_called_once_with(raise_on_error=True)
    for m in (api.get_ip_lists, api.get_services, api.get_label_groups):
        for call in m.call_args_list:
            assert call.kwargs.get("raise_on_error") is True


# ── 3. expand_object_filters_for_df 的 _iplist_cidrs ────────────────────────

class TestIplistCidrsFetchFailure(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def test_iplist_cidrs_fetch_failure_raises(self):
        self.client.get_ip_lists = MagicMock(
            side_effect=APIError("get_ip_lists failed: HTTP 503 for /x"))
        with self.assertRaises(APIError):
            self.client.expand_object_filters_for_df({"src_iplist": "prod-subnets"})
        self.client.get_ip_lists.assert_called_once_with(raise_on_error=True)

    def test_iplist_cidrs_name_mismatch_returns_empty(self):
        self.client.get_ip_lists = MagicMock(return_value=[
            {"name": "prod-subnets", "href": "/orgs/1/sec_policy/active/ip_lists/7",
             "ip_ranges": [{"from_ip": "10.10.0.0/16"}]},
        ])
        out = self.client.expand_object_filters_for_df({"src_iplist": "nosuch"})
        self.assertNotIn("_src_object_cidrs", out)


def test_iplist_cidrs_name_mismatch_logs_warning(caplog):
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "k", "secret": "s", "verify_ssl": True}}
    client = ApiClient(cm)
    with tempfile.TemporaryDirectory() as td:
        client._state_file = os.path.join(td, "state.json")
        client.get_ip_lists = MagicMock(return_value=[
            {"name": "prod-subnets", "href": "/orgs/1/sec_policy/active/ip_lists/7",
             "ip_ranges": [{"from_ip": "10.10.0.0/16"}]},
        ])
        client.expand_object_filters_for_df({"src_iplist": "nosuch"})
    assert any("IP List not found" in rec.message for rec in caplog.records)


if __name__ == "__main__":
    unittest.main()
