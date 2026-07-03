"""iplist/workload filter → CIDR/IP 清單展開（df 路徑用；df 無 href 欄位）。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


class TestExpandObjectFiltersForDf(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")
        self.client.get_ip_lists = MagicMock(return_value=[
            {"name": "prod-subnets", "href": "/orgs/1/sec_policy/active/ip_lists/7",
             "ip_ranges": [{"from_ip": "10.10.0.0/16"},
                           {"from_ip": "10.20.0.1", "to_ip": "10.20.0.3"}]},
        ])
        self.client.get_workload = MagicMock(return_value={
            "href": "/orgs/1/workloads/abc",
            "public_ip": "203.0.113.5",
            "interfaces": [{"address": "10.1.2.3"}, {"address": "fe80::1"}],
        })

    def tearDown(self):
        self._td.cleanup()

    def test_iplist_name_expands_to_cidrs(self):
        out = self.client.expand_object_filters_for_df({"src_iplist": "prod-subnets"})
        cidrs = out["_src_object_cidrs"]
        assert "10.10.0.0/16" in cidrs
        # from/to range 以 summarize_address_range 換算
        assert "10.20.0.1/32" in cidrs and "10.20.0.2/31" in cidrs

    def test_workload_href_expands_to_ips(self):
        out = self.client.expand_object_filters_for_df(
            {"dst_workload": "/orgs/1/workloads/abc"})
        assert "10.1.2.3" in out["_dst_object_cidrs"]
        assert "203.0.113.5" in out["_dst_object_cidrs"]

    def test_unknown_iplist_yields_no_key(self):
        out = self.client.expand_object_filters_for_df({"src_iplist": "nosuch"})
        assert "_src_object_cidrs" not in out

    def test_no_object_keys_passthrough(self):
        f = {"src_labels": ["app=erp"]}
        out = self.client.expand_object_filters_for_df(f)
        assert out == f

    def test_any_iplist_expands_to_any_cidrs(self):
        out = self.client.expand_object_filters_for_df({"any_iplist": "prod-subnets"})
        assert "10.10.0.0/16" in out["_any_object_cidrs"]

    def test_ex_any_iplist_expands_to_ex_any_cidrs(self):
        out = self.client.expand_object_filters_for_df({"ex_any_iplist": "prod-subnets"})
        assert "10.10.0.0/16" in out["_ex_any_object_cidrs"]

    def test_ex_any_workload_expands_to_ex_any_cidrs(self):
        out = self.client.expand_object_filters_for_df(
            {"ex_any_workload": "/orgs/1/workloads/abc"})
        assert "10.1.2.3" in out["_ex_any_object_cidrs"]

    def test_report_generator_expands_before_df_filter(self):
        from src.report.report_generator import ReportGenerator
        rg = ReportGenerator.__new__(ReportGenerator)  # 不跑完整 __init__
        rg.api = self.client
        rg._cache = None
        # _fetch_traffic_df 在 cache 缺席時直接走 API 路徑；驗證展開器在
        # 該路徑一樣被呼叫（filters 傳給 fetch_traffic_for_report 前已含展開 key）
        captured = {}
        def fake_fetch(start_time_str, end_time_str, filters=None, compute_draft=False):
            captured.update(filters or {})
            return []
        self.client.fetch_traffic_for_report = fake_fetch
        rg._parse_api = lambda flows: __import__("pandas").DataFrame()
        import datetime as dt
        rg._fetch_traffic_df(dt.datetime(2026, 7, 1), dt.datetime(2026, 7, 2),
                             filters={"src_iplist": "prod-subnets"}, use_cache=False)
        assert "_src_object_cidrs" in captured
