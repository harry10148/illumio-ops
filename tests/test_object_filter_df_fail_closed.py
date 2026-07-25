"""不可解析的物件 filter 不得靜默放行（cache DataFrame 路徑，2026-07-25 審查 High）。

不變量：只要 include 側的物件/服務條件有值，展開後套上 df_filter 就不可能
比「條件解析成功」放行更多列。條件解析不出任何 IP/port 時（IP List 只含
FQDN、全為 exclusion、物件被刪、get_workload 因暫時性 5xx 回 {}、Service 只有
名稱型條目…），正確方向是一列都不留（fail-closed），而不是整批流量原封不動
輸出——後者會讓報表掛著「已限定某物件」的標題卻包含全部流量。
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import pandas as pd

from src.api_client import ApiClient
from src.report.df_filter import apply_df_traffic_filters


def _frame():
    return pd.DataFrame([
        {"src_ip": "10.1.2.3", "dst_ip": "10.9.9.9", "port": 443, "proto": "TCP"},
        {"src_ip": "192.0.2.7", "dst_ip": "198.51.100.4", "port": 80, "proto": "TCP"},
    ])


# include 側的每個物件 filter key（值皆指向解析不出 IP 的物件）
_INCLUDE_OBJECT_KEYS = (
    "src_iplist", "src_iplists", "src_workload", "src_workloads",
    "dst_iplist", "dst_iplists", "dst_workload", "dst_workloads",
    "any_iplist", "any_workload",
)


class TestUnresolvableObjectFilterFailsClosed(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")
        # IP List 存在但只有 FQDN（無 ip_ranges）→ 展不出 CIDR
        self.client.get_ip_lists = MagicMock(return_value=[
            {"name": "fqdn-only", "href": "/orgs/1/sec_policy/active/ip_lists/9",
             "fqdns": [{"fqdn": "example.com"}], "ip_ranges": []},
        ])
        # get_workload 對任何非 200/例外都回 {}（暫時性 503 亦然）→ 展不出 IP
        self.client.get_workload = MagicMock(return_value={})
        self.client.service_ports_cache = {}

    def tearDown(self):
        self._td.cleanup()

    def _value_for(self, key):
        if "workload" in key:
            return "/orgs/1/workloads/abc"
        return "fqdn-only"

    def test_every_include_object_key_fails_closed(self):
        for key in _INCLUDE_OBJECT_KEYS:
            with self.subTest(key=key):
                df = _frame()
                filters = {key: self._value_for(key)}
                expanded = self.client.expand_object_filters_for_df(dict(filters))
                out = apply_df_traffic_filters(df, expanded)
                self.assertEqual(
                    len(out), 0,
                    f"{key} 解析失敗時放行了 {len(out)}/{len(df)} 列（fail-open）")

    def test_unresolvable_service_filter_fails_closed(self):
        """services 只解析出名稱型條目（cache 無法比對）→ 一列都不放行。"""
        self.client.service_ports_cache = {
            "/x/services/name-only": [{"windows_service_name": "w"}],
        }
        df = _frame()
        expanded = self.client.expand_object_filters_for_df(
            {"services": ["/x/services/name-only"]})
        self.assertEqual(len(apply_df_traffic_filters(df, expanded)), 0)

    def test_resolvable_value_still_matches(self):
        """哨兵不得污染同一 key 內解析成功的值（OR 語意）。"""
        self.client.get_ip_lists = MagicMock(return_value=[
            {"name": "fqdn-only", "href": "/orgs/1/sec_policy/active/ip_lists/9",
             "ip_ranges": []},
            {"name": "real", "href": "/orgs/1/sec_policy/active/ip_lists/10",
             "ip_ranges": [{"from_ip": "10.1.2.0/24"}]},
        ])
        df = _frame()
        expanded = self.client.expand_object_filters_for_df(
            {"src_iplists": ["fqdn-only", "real"]})
        out = apply_df_traffic_filters(df, expanded)
        self.assertEqual(list(out["src_ip"]), ["10.1.2.3"])

    def test_unresolvable_exclusion_removes_nothing(self):
        """排除側解析失敗維持不排除（對齊 traffic_query residual 的排除語意，
        也對齊 df_filter 對非法排除值的 for_exclude 慣例）——絕不可反過來把
        整張表清空。"""
        df = _frame()
        expanded = self.client.expand_object_filters_for_df(
            {"ex_src_iplist": "fqdn-only"})
        self.assertEqual(len(apply_df_traffic_filters(df, expanded)), len(df))
        expanded = self.client.expand_object_filters_for_df(
            {"ex_services": ["/x/services/name-only"]})
        self.assertEqual(len(apply_df_traffic_filters(df, expanded)), len(df))
