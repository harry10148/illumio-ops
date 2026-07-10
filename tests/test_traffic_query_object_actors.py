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

    # ─── 同 key 多值 = OR（每值一組），非內層 AND ───────────────────────────
    # 依據：Security Policy Guide「labels use an OR between the same label
    # type and an AND between different label types」；SIEM Integration Guide
    # 「If all the labels selected have the same type, the OR operator is
    # applied」。iplist/workload/label_group 皆為物件類 key，same-type-OR 依據
    # 相同，比照 IP 系列（0ea0e94）修法：每個 resolved actor 各自一個 include 組。

    def test_src_iplists_multi_value_is_outer_or_not_inner_and(self):
        self.client._iplist_href_cache["staging-subnets"] = \
            "/orgs/1/sec_policy/draft/ip_lists/8"
        payload, _ = self._build(
            {"src_iplists": ["prod-subnets", "staging-subnets"]})
        include = payload["sources"]["include"]
        self.assertIn([{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}}], include)
        self.assertIn([{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/8"}}], include)
        self.assertNotIn(
            [{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}},
             {"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/8"}}],
            include)

    def test_dst_workloads_multi_value_is_outer_or(self):
        payload, _ = self._build({"dst_workloads": [
            "/orgs/1/workloads/abc-123", "/orgs/1/workloads/def-456"]})
        include = payload["destinations"]["include"]
        self.assertIn([{"workload": {"href": "/orgs/1/workloads/abc-123"}}], include)
        self.assertIn([{"workload": {"href": "/orgs/1/workloads/def-456"}}], include)
        self.assertNotIn(
            [{"workload": {"href": "/orgs/1/workloads/abc-123"}},
             {"workload": {"href": "/orgs/1/workloads/def-456"}}],
            include)

    def test_src_label_groups_multi_value_is_outer_or(self):
        self.client._label_group_href_cache["group-a"] = \
            "/orgs/1/sec_policy/active/label_groups/1"
        self.client._label_group_href_cache["group-b"] = \
            "/orgs/1/sec_policy/active/label_groups/2"
        payload, _ = self._build(
            {"src_label_groups": ["group-a", "group-b"]})
        include = payload["sources"]["include"]
        self.assertIn(
            [{"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/1"}}], include)
        self.assertIn(
            [{"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/2"}}], include)
        self.assertNotIn(
            [{"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/1"}},
             {"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/2"}}],
            include)

    def test_src_iplist_single_value_unchanged(self):
        # 單值行為零變更釘：仍是單一 include 組
        payload, _ = self._build({"src_iplist": "prod-subnets"})
        self.assertEqual(payload["sources"]["include"], [
            [{"ip_list": {"href": "/orgs/1/sec_policy/draft/ip_lists/7"}}]])
