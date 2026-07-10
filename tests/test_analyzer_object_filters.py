"""Phase 4b critical fix：dashboard/analyzer 路徑的 client-side flow 比對。

涵蓋三個 final-review 缺陷：
  C1  list 形 src_ip_in/dst_ip_in（新儲存格式）在 check_flow_match 永不命中
  C2  物件/複數 filter key（src_labels/_iplists/_workloads/any_* 等）被
      check_flow_match 靜默 pass-through——cache 全覆蓋時完全未過濾
  I3  list 形 ex_src_ip/ex_dst_ip 的 client-side 排除 no-op

修法：
  Part A  check_flow_match 的 IP 比對 list-aware（任一值命中）
  Part B  query_flows 殘餘比對將物件/複數 key 委派給報表路徑同一套
          比對器 TrafficQueryBuilder._flow_matches_filters
  Part C  label_groups 類 key 兩套比對器都無法在 client 端評估——
          帶此類 filter 時跳過 cache、強制走 API（PCE native 過濾）
"""
import datetime
import unittest
from unittest.mock import MagicMock

from src.analyzer import Analyzer
from src.api.traffic_query import TrafficQueryBuilder


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


def _make_analyzer(cache_flows=None, api_flows=None):
    """Analyzer + 真 build_traffic_query_spec + mock cache/API。"""
    mock_cm = MagicMock()
    mock_cm.config = {"rules": []}
    mock_api = MagicMock()
    builder = TrafficQueryBuilder(MagicMock())
    mock_api.build_traffic_query_spec.side_effect = builder.build_traffic_query_spec
    mock_api.execute_traffic_query_stream.side_effect = (
        lambda *a, **kw: iter(list(api_flows or []))
    )
    az = Analyzer(mock_cm, mock_api, MagicMock())
    az.load_state = MagicMock()
    az.save_state = MagicMock()
    cr = None
    if cache_flows is not None:
        cr = MagicMock()
        cr.cover_state.return_value = "full"
        cr.read_flows_raw.return_value = list(cache_flows)
        az._cache_reader = cr
    return az, mock_api, cr


def _params(**extra):
    p = {
        "start_time": "2026-06-01T00:00:00Z",
        "end_time": "2026-06-01T01:00:00Z",
        "sort_by": "connections",
    }
    p.update(extra)
    return p


def _ids(results):
    return sorted(r.get("id") for r in results)


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

    # ─── /32、CIDR、range containment（live repro：172.16.15.106/32 → 0 rows）───

    def test_src_ip_in_slash32_hit(self):
        # /32 必須等同 bare IP——修正前這裡是字串精確比對，恆為 False
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.1/32"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_slash32_miss(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.2/32"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_cidr_containment_hit(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.0/24"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_cidr_containment_miss(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.1.0/24"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_range_containment_hit(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.0-10.0.0.10"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_range_containment_miss(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.2-10.0.0.10"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_range_from_gt_to_auto_swaps(self):
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.10-10.0.0.0"]}
        self.assertTrue(self.az.check_flow_match(rule, self.flow, None))

    def test_ex_src_ip_cidr_excludes(self):
        rule = {"type": "connections", "pd": -1, "ex_src_ip": ["10.0.0.0/24"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_src_ip_in_illegal_cidr_no_match(self):
        # 非法 CIDR → 不命中（fail-closed；此路徑把關 live 查詢/告警結果，
        # 不是 df_filter._ip_mask 的 cache 顯示 fail-open 慣例）
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.1/nope"]}
        self.assertFalse(self.az.check_flow_match(rule, self.flow, None))

    def test_ip_value_parse_is_cached_and_behaviour_unchanged(self):
        """本 sweep：CIDR/range 值清單改用 lru_cache 預解析——行為不變釘。
        同一個值跨多個 flow 重複比對，結果逐位一致，且底層解析只發生一次
        （cache hit 遞增），非法值不進命中路徑但仍 fail-closed。"""
        from src.analyzer import Analyzer
        Analyzer._parse_ip_filter_value.cache_clear()
        rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.0/24"]}
        flow_in = _flow("in", src_ip="10.0.0.5")
        flow_out = _flow("out", src_ip="10.0.1.5")
        # 重複呼叫多次，逐位行為不變
        for _ in range(3):
            self.assertTrue(self.az.check_flow_match(rule, flow_in, None))
            self.assertFalse(self.az.check_flow_match(rule, flow_out, None))
        info = Analyzer._parse_ip_filter_value.cache_info()
        self.assertEqual(info.misses, 1)  # 只解析一次
        self.assertGreaterEqual(info.hits, 5)  # 其餘全命中快取

        # range 值與非法值也維持原行為（各自快取一次、行為不變）
        range_rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.0-10.0.0.10"]}
        illegal_rule = {"type": "connections", "pd": -1, "src_ip_in": ["10.0.0.1/nope"]}
        for _ in range(3):
            self.assertTrue(self.az.check_flow_match(range_rule, self.flow, None))
            self.assertFalse(self.az.check_flow_match(illegal_rule, self.flow, None))


# ─── Part B：query_flows 物件 key 委派 _flow_matches_filters（C2 主體）────────

class TestQueryFlowsObjectFilters(unittest.TestCase):
    """cache 全覆蓋（cover_state='full'）：check_flow_match/_flow_matches_filters
    是唯一一道過濾——物件 pill 必須在這裡生效。"""

    FLOWS = [
        _flow("web", src_ip="10.0.0.1", src_labels=[("role", "web"), ("app", "erp")],
              src_wl="web1", dst_iplists=["CorpNet"]),
        _flow("db", src_ip="10.0.0.2", src_labels=[("role", "db"), ("app", "erp")],
              src_wl="db1", dst_iplists=["BadNet"]),
        _flow("lb", src_ip="10.0.0.3", src_labels=[("role", "lb"), ("app", "crm")],
              src_wl="lb1"),
    ]

    def test_src_labels_same_key_or(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_labels=["role=web", "role=db"]))
        self.assertEqual(_ids(res), ["db", "web"])
        self.assertEqual(az.last_query_source, "cache")

    def test_src_labels_cross_key_and(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_labels=["role=web", "app=erp"]))
        self.assertEqual(_ids(res), ["web"])

    def test_src_ip_in_list_on_cache_path(self):
        # C1 實測情境：帶 IP pill 的新儲存查詢，修正前 top10 恆空
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_ip_in=["10.0.0.1"]))
        self.assertEqual(_ids(res), ["web"])

    def test_src_ip_in_slash32_on_cache_path(self):
        # 測試機實測 172.16.15.106/32 → 0 rows（矛盾：/32 應等同 bare IP）
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_ip_in=["10.0.0.1/32"]))
        self.assertEqual(_ids(res), ["web"])

    def test_src_ip_in_cidr_on_cache_path(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_ip_in=["10.0.0.0/24"]))
        self.assertEqual(_ids(res), ["db", "lb", "web"])

    def test_src_ip_in_range_on_cache_path(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_ip_in=["10.0.0.1-10.0.0.2"]))
        self.assertEqual(_ids(res), ["db", "web"])

    def test_src_workloads_href(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_workloads=["/orgs/1/workloads/db1"]))
        self.assertEqual(_ids(res), ["db"])

    def test_ex_dst_iplists_excludes(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(ex_dst_iplists=["BadNet"]))
        self.assertEqual(_ids(res), ["lb", "web"])

    def test_any_iplist_on_cache_path(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(any_iplist="CorpNet"))
        self.assertEqual(_ids(res), ["web"])

    def test_any_workload_on_api_path(self):
        # C2(b)：fallback-capability 的 any_workload 連 API 路徑都要 client 過濾
        az, _, _ = _make_analyzer(api_flows=self.FLOWS)  # 無 cache reader
        res = az.query_flows(_params(any_workload="/orgs/1/workloads/lb1"))
        self.assertEqual(_ids(res), ["lb"])
        self.assertEqual(az.last_query_source, "api")

    def test_ex_any_iplist_on_api_path(self):
        az, _, _ = _make_analyzer(api_flows=self.FLOWS)
        res = az.query_flows(_params(ex_any_iplist="BadNet"))
        self.assertEqual(_ids(res), ["lb", "web"])


class TestQueryFlowsLegacyParity(unittest.TestCase):
    """legacy scalar key 對照：委派後過濾結果必須與 check_flow_match 舊行為一致。"""

    FLOWS = TestQueryFlowsObjectFilters.FLOWS

    def test_scalar_src_label(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_label="role=web"))
        self.assertEqual(_ids(res), ["web"])

    def test_scalar_ex_src_label(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(ex_src_label="role=lb"))
        self.assertEqual(_ids(res), ["db", "web"])

    def test_scalar_src_ip_in(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(src_ip_in="10.0.0.3"))
        self.assertEqual(_ids(res), ["lb"])

    def test_scalar_ex_dst_ip(self):
        flows = [
            _flow("a", dst_ip="10.9.9.9"),
            _flow("b", src_ip="10.0.0.2", dst_ip="10.9.9.8"),
        ]
        az, _, _ = _make_analyzer(cache_flows=flows)
        res = az.query_flows(_params(ex_dst_ip="10.9.9.9"))
        self.assertEqual(_ids(res), ["b"])

    def test_scalar_any_label(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params(any_label="role=db"))
        self.assertEqual(_ids(res), ["db"])

    def test_port_filter(self):
        flows = [_flow("a", port=443), _flow("b", src_ip="10.0.0.2", port=80)]
        az, _, _ = _make_analyzer(cache_flows=flows)
        res = az.query_flows(_params(port=443))
        self.assertEqual(_ids(res), ["a"])

    def test_no_filters_returns_all(self):
        az, _, _ = _make_analyzer(cache_flows=self.FLOWS)
        res = az.query_flows(_params())
        self.assertEqual(_ids(res), ["db", "lb", "web"])


# ─── Part C：label_groups 無法 client 端評估 → cache bypass ───────────────────

class TestQueryFlowsLabelGroupCacheBypass(unittest.TestCase):
    FLOWS = TestQueryFlowsObjectFilters.FLOWS

    def test_label_groups_bypasses_cache(self):
        az, api, cr = _make_analyzer(cache_flows=self.FLOWS, api_flows=self.FLOWS)
        az.query_flows(_params(
            src_label_groups=["/orgs/1/sec_policy/active/label_groups/g1"]))
        cr.read_flows_raw.assert_not_called()
        api.execute_traffic_query_stream.assert_called_once()
        self.assertEqual(az.last_query_source, "api")

    def test_ex_dst_label_groups_bypasses_cache(self):
        az, api, cr = _make_analyzer(cache_flows=self.FLOWS, api_flows=self.FLOWS)
        az.query_flows(_params(
            ex_dst_label_groups=["/orgs/1/sec_policy/active/label_groups/g2"]))
        cr.read_flows_raw.assert_not_called()
        self.assertEqual(az.last_query_source, "api")

    def test_without_label_groups_cache_still_used(self):
        az, api, cr = _make_analyzer(cache_flows=self.FLOWS, api_flows=self.FLOWS)
        az.query_flows(_params(src_labels=["role=web"]))
        cr.read_flows_raw.assert_called_once()
        api.execute_traffic_query_stream.assert_not_called()
        self.assertEqual(az.last_query_source, "cache")


# ─── Phase 4c：規則引擎（_run_rule_engine 路徑）物件/複數 key 比對 ────────────

class TestRuleEngineObjectFilters(unittest.TestCase):
    """修前 check_flow_match 對物件/複數 key pass-through，帶這類 filter 的
    規則會誤發告警（全部 flow 誤命中）——本類鎖住 _match_flow_filters 修正後
    的行為，走 _run_rule_engine 真實路徑，不 stub 比對器。"""

    def setUp(self):
        self.az = Analyzer(MagicMock(), MagicMock(), MagicMock())
        self.flows = [
            _flow("erp-flow", src_ip="10.0.1.1", src_labels=[("app", "erp")]),
            _flow("web-flow", src_ip="10.0.1.2", src_labels=[("app", "web")]),
            _flow("other-flow", src_ip="10.0.1.3", src_labels=[("app", "crm")]),
            _flow("iplist-flow", src_ip="10.0.1.4", src_iplists=["7"]),
            _flow("wl-src-flow", src_ip="10.0.1.5", src_wl="abc"),
            _flow("wl-dst-flow", src_ip="10.0.1.6", dst_wl="abc"),
        ]
        # flow fixture 固定 timestamp 2026-06-01T00:10:00Z；now_utc 貼近避免
        # threshold_window 滑動視窗把 fixture flow 濾掉。
        self.now_utc = datetime.datetime(2026, 6, 1, 0, 15, tzinfo=datetime.timezone.utc)

    def _rule(self, **kw):
        base = {"id": "r1", "type": "traffic", "name": "R", "pd": -1,
                "threshold_type": "count", "threshold_count": 1, "threshold_window": 10}
        base.update(kw)
        return base

    def match(self, rule):
        """走 _run_rule_engine 真實路徑，回傳命中的 flow id 集合。"""
        results = self.az._run_rule_engine(self.flows, [rule], self.now_utc)
        _, res = results[0]
        return {m["id"] for m in res["top_matches"]}

    def test_rule_plural_src_labels_or_semantics(self):
        # src_labels 複數：同 key OR——app=erp 或 app=web 命中
        matched = self.match(self._rule(src_labels=["app=erp", "app=web"]))
        self.assertEqual(matched, {"erp-flow", "web-flow"})

    def test_rule_src_iplists_href_match(self):
        matched = self.match(self._rule(
            src_iplists=["/orgs/1/sec_policy/active/ip_lists/7"]))
        self.assertEqual(matched, {"iplist-flow"})

    def test_rule_any_workload_either_side(self):
        matched = self.match(self._rule(any_workload="/orgs/1/workloads/abc"))
        self.assertEqual(matched, {"wl-src-flow", "wl-dst-flow"})

    def test_rule_object_key_no_false_alert(self):
        # 修前行為：未知 key pass-through → 全部誤命中（本測試是 RED 主鎖）
        matched = self.match(self._rule(src_labels=["app=nonexistent"]))
        self.assertEqual(matched, set())

    def test_rule_legacy_scalar_parity(self):
        # legacy 純量 key 行為逐位不變
        matched = self.match(self._rule(src_label="app=erp"))
        self.assertEqual(matched, {"erp-flow"})


# ─── Task 11 gap fix：_OBJECT_FILTER_KEYS 缺 services/ex_services/ports/
# ex_ports——規則的 Service/Port pill 對 _run_rule_engine 是 no-op（全部
# flow 誤命中），因為 alert 規則永遠走 client-side _match_flow_filters，
# 不會建構 native PCE query。ports/ex_ports 純本地解析；services/
# ex_services 需要 resolve_service href→entries callable 才能展開。

class TestRuleEnginePortServiceFilters(unittest.TestCase):
    def setUp(self):
        self.now_utc = datetime.datetime(2026, 6, 1, 0, 15, tzinfo=datetime.timezone.utc)
        self.flows = [
            _flow("p443", src_ip="10.0.2.1", port=443),
            _flow("p80", src_ip="10.0.2.2", port=80),
        ]

    def _rule(self, **kw):
        base = {"id": "r1", "type": "traffic", "name": "R", "pd": -1,
                "threshold_type": "count", "threshold_count": 1, "threshold_window": 10}
        base.update(kw)
        return base

    def _matched(self, az, rule):
        results = az._run_rule_engine(self.flows, [rule], self.now_utc)
        _, res = results[0]
        return {m["id"] for m in res["top_matches"]}

    def test_rule_ports_filters_by_port(self):
        az = Analyzer(MagicMock(), MagicMock(), MagicMock())
        matched = self._matched(az, self._rule(ports=["443"]))
        self.assertEqual(matched, {"p443"})

    def test_rule_ex_ports_excludes_by_port(self):
        az = Analyzer(MagicMock(), MagicMock(), MagicMock())
        matched = self._matched(az, self._rule(ex_ports=["443"]))
        self.assertEqual(matched, {"p80"})

    def test_rule_services_resolves_href_via_label_resolver(self):
        mock_api = MagicMock()
        mock_api._labels.resolve_service_entries.side_effect = (
            lambda href: [{"port": 443}]
            if href == "/orgs/1/sec_policy/active/services/svc-https" else None
        )
        az = Analyzer(MagicMock(), mock_api, MagicMock())
        rule = self._rule(services=["/orgs/1/sec_policy/active/services/svc-https"])
        matched = self._matched(az, rule)
        self.assertEqual(matched, {"p443"})


if __name__ == "__main__":
    unittest.main()
