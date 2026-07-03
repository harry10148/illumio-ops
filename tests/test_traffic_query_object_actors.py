"""IP List / Workload 物件 filter keys 的 native actor 解析。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from src.api_client import ApiClient


class TestObjectActorKeys(unittest.TestCase):
    def setUp(self):
        cm = MagicMock()
        cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                             "key": "k", "secret": "s", "verify_ssl": True}}
        self.client = ApiClient(cm)
        self.client._iplist_href_cache = {
            "prod-subnets": "/orgs/1/sec_policy/draft/ip_lists/7"}
        self.client.update_label_cache = MagicMock(return_value=None)
        self._td = tempfile.TemporaryDirectory()
        self.client._state_file = os.path.join(self._td.name, "state.json")

    def tearDown(self):
        self._td.cleanup()

    def _build(self, filters):
        return self.client._build_native_traffic_payload(
            "2026-04-01T00:00:00Z", "2026-04-01T01:00:00Z", ["allowed"], filters=filters)

    def test_src_iplist_by_name_resolves_to_ip_list_actor(self):
        payload, spec = self._build({"src_iplist": "prod-subnets"})
        self.assertEqual(payload["sources"]["include"], [
            [{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}}]])
        self.assertIn("src_iplist", spec.native_filters)

    def test_dst_iplists_by_href_list(self):
        payload, _ = self._build(
            {"dst_iplists": ["/orgs/1/sec_policy/active/ip_lists/9"]})
        self.assertEqual(payload["destinations"]["include"], [
            [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/9"}}]])

    def test_src_workload_href(self):
        payload, _ = self._build({"src_workload": "/orgs/1/workloads/abc-123"})
        self.assertEqual(payload["sources"]["include"], [
            [{"workload": {"href": "/orgs/1/workloads/abc-123"}}]])

    def test_workload_non_href_falls_back(self):
        payload, spec = self._build({"src_workload": "prod-web-01"})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_workload", spec.fallback_filters)

    def test_ex_dst_iplist_goes_to_exclude(self):
        payload, _ = self._build({"ex_dst_iplist": "prod-subnets"})
        self.assertEqual(payload["destinations"]["exclude"], [
            {"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}}])

    def test_iplist_ignores_ip_literal(self):
        payload, spec = self._build({"src_iplist": "10.0.0.1"})
        self.assertEqual(payload["sources"]["include"], [])
        self.assertIn("src_iplist", spec.fallback_filters)
