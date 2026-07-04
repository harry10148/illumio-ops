"""Phase 4b critical fix：dashboard/analyzer 路徑的 client-side flow 比對。

Part A（C1/I3）：check_flow_match 的 IP 比對 list-aware——list 形
src_ip_in/dst_ip_in/ex_src_ip/ex_dst_ip（Phase 4b FilterBar 新儲存格式）
任一值命中即 match / 命中即排除；scalar 行為逐位不變。
"""
import unittest
from unittest.mock import MagicMock

from src.analyzer import Analyzer


# ─── PCE flow fixture（與 API stream / cache raw_json 同形狀）─────────────────

def _flow(fid, src_ip="10.0.0.1", dst_ip="10.9.9.9",
          src_labels=None, dst_labels=None,
          src_iplists=None, dst_iplists=None,
          src_wl=None, dst_wl=None, port=443):
    """建構與 PCE async 查詢回傳（= cache raw_json）同形狀的 flow dict。"""
    def _side(ip, labels, iplists, wl_name):
        side = {"ip": ip}
        if labels or wl_name:
            side["workload"] = {
                "href": f"/orgs/1/workloads/{wl_name or ip}",
                "name": wl_name or ip,
                "labels": [{"key": k, "value": v} for k, v in (labels or [])],
            }
        if iplists:
            side["ip_lists"] = [
                {"name": n, "href": f"/orgs/1/sec_policy/active/ip_lists/{n}"}
                for n in iplists
            ]
        return side
    return {
        "id": fid,
        "timestamp": "2026-06-01T00:10:00Z",
        "policy_decision": "allowed",
        "src": _side(src_ip, src_labels, src_iplists, src_wl),
        "dst": _side(dst_ip, dst_labels, dst_iplists, dst_wl),
        "service": {"port": port, "proto": 6},
        "num_connections": 1,
    }


# ─── Part A：check_flow_match 的 IP 比對 list-aware（C1/I3）───────────────────

class TestCheckFlowMatchListIp(unittest.TestCase):
    def setUp(self):
        self.az = Analyzer(MagicMock(), MagicMock(), MagicMock())
        self.flow = _flow("f1", src_ip="10.0.0.1", dst_ip="10.9.9.9",
                          src_iplists=["CorpNet"])

    def test_src_ip_in_list_hit(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.7", "10.0.0.1"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_list_miss(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.7", "10.0.0.8"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_list_iplist_name_hit(self):
        # _check_ip_filter 亦比對 flow side 的 ip_lists 名稱——list 形也要保留
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["CorpNet"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_ex_dst_ip_list_excludes(self):
        rule = {"type": "connections", "pd": -1, "ex_dst_ip": ["10.9.9.9", "1.2.3.4"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_ex_src_ip_list_no_hit_passes(self):
        rule = {"type": "connections", "pd": -1, "ex_src_ip": ["1.2.3.4"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_scalar_ip_behaviour_unchanged(self):
        # scalar 行為逐位不變（legacy 儲存格式）
        self.assertTrue(self.az.check_flow_match(
            {"type": "connections", "pd": -1, "src_ip_in": "10.0.0.1"}, self.flow, None))
        self.assertFalse(self.az.check_flow_match(
            {"type": "connections", "pd": -1, "src_ip_in": "10.0.0.2"}, self.flow, None))
        self.assertFalse(self.az.check_flow_match(
            {"type": "connections", "pd": -1, "ex_dst_ip": "10.9.9.9"}, self.flow, None))
        self.assertTrue(self.az.check_flow_match(
            {"type": "connections", "pd": -1, "ex_dst_ip": "1.2.3.4"}, self.flow, None))


if __name__ == "__main__":
    unittest.main()
