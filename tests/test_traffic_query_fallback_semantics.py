"""client-side fallback 的同 key OR 語意（與 native 路徑對齊）。"""
from src.api.traffic_query import TrafficQueryBuilder


def _flow(src_labels=(), dst_labels=()):
    def side(labels):
        return {"workload": {"labels": [{"key": k, "value": v} for k, v in labels]}}
    return {"src": side(src_labels), "dst": side(dst_labels), "service": {}}


def _match(flow, filters):
    return TrafficQueryBuilder._flow_matches_filters(flow, filters)


def test_same_key_two_values_is_or():
    flow = _flow(src_labels=[("app", "erp")])
    assert _match(flow, {"src_labels": ["app=erp", "app=web"]}) is True


def test_same_key_no_value_matches_rejects():
    flow = _flow(src_labels=[("app", "hr")])
    assert _match(flow, {"src_labels": ["app=erp", "app=web"]}) is False


def test_cross_key_still_and():
    flow = _flow(src_labels=[("app", "erp")])  # 缺 env=prod
    assert _match(flow, {"src_labels": ["app=erp", "env=prod"]}) is False
    flow2 = _flow(src_labels=[("app", "erp"), ("env", "prod")])
    assert _match(flow2, {"src_labels": ["app=erp", "env=prod"]}) is True


def test_dst_side_same_semantics():
    flow = _flow(dst_labels=[("env", "prod")])
    assert _match(flow, {"dst_labels": ["env=prod", "env=dr"]}) is True


def test_unparseable_spec_must_match_individually():
    # 無 key 可解析的字串維持舊語意：該條件必須自行成立（AND）
    flow = _flow(src_labels=[("app", "erp")])
    assert _match(flow, {"src_labels": ["app=erp", "garbage"]}) is False


def _flow_with_objects(src_iplists=(), dst_iplists=(), src_wl_href="", dst_wl_href=""):
    def side(ipls, href):
        d = {"ip_lists": [{"name": n, "href": h} for n, h in ipls]}
        if href:
            d["workload"] = {"href": href, "labels": []}
        return d
    return {"src": side(src_iplists, src_wl_href),
            "dst": side(dst_iplists, dst_wl_href), "service": {}}


def test_any_iplist_matches_either_side():
    flow = _flow_with_objects(dst_iplists=[("prod-subnets", "/orgs/1/sec_policy/active/ip_lists/7")])
    assert _match(flow, {"any_iplist": "prod-subnets"}) is True
    assert _match(flow, {"any_iplist": "corp-vpn"}) is False


def test_any_workload_matches_either_side_by_href():
    flow = _flow_with_objects(src_wl_href="/orgs/1/workloads/abc")
    assert _match(flow, {"any_workload": "/orgs/1/workloads/abc"}) is True
    assert _match(flow, {"any_workload": "/orgs/1/workloads/zzz"}) is False


def test_ex_any_iplist_rejects_when_hit():
    flow = _flow_with_objects(src_iplists=[("corp-vpn", "/orgs/1/sec_policy/active/ip_lists/3")])
    assert _match(flow, {"ex_any_iplist": "corp-vpn"}) is False
    assert _match(flow, {"ex_any_iplist": "other"}) is True


def test_residual_src_iplist_side_specific():
    flow = _flow_with_objects(src_iplists=[("corp-vpn", "/orgs/1/sec_policy/active/ip_lists/3")])
    assert _match(flow, {"src_iplists": ["corp-vpn"]}) is True
    assert _match(flow, {"dst_iplists": ["corp-vpn"]}) is False


def test_residual_src_workload_side_specific():
    flow = _flow_with_objects(src_wl_href="/orgs/1/workloads/abc")
    assert _match(flow, {"src_workloads": ["/orgs/1/workloads/abc"]}) is True
    assert _match(flow, {"dst_workloads": ["/orgs/1/workloads/abc"]}) is False


def test_ex_src_iplist_excludes_on_src_hit():
    flow = _flow_with_objects(src_iplists=[("corp-vpn", "/orgs/1/sec_policy/active/ip_lists/3")])
    assert _match(flow, {"ex_src_iplists": ["corp-vpn"]}) is False
    assert _match(flow, {"ex_dst_iplists": ["corp-vpn"]}) is True


def test_ex_dst_iplist_excludes_on_dst_hit():
    flow = _flow_with_objects(dst_iplists=[("corp-vpn", "/orgs/1/sec_policy/active/ip_lists/3")])
    assert _match(flow, {"ex_dst_iplists": ["corp-vpn"]}) is False
    assert _match(flow, {"ex_src_iplists": ["corp-vpn"]}) is True


def test_ex_src_workload_excludes_on_src_hit():
    flow = _flow_with_objects(src_wl_href="/orgs/1/workloads/abc")
    assert _match(flow, {"ex_src_workloads": ["/orgs/1/workloads/abc"]}) is False
    assert _match(flow, {"ex_dst_workloads": ["/orgs/1/workloads/abc"]}) is True


def test_ex_dst_workload_excludes_on_dst_hit():
    flow = _flow_with_objects(dst_wl_href="/orgs/1/workloads/abc")
    assert _match(flow, {"ex_dst_workloads": ["/orgs/1/workloads/abc"]}) is False
    assert _match(flow, {"ex_src_workloads": ["/orgs/1/workloads/abc"]}) is True


def _flow_with_ips(src_ip="", dst_ip=""):
    return {"src": {"ip": src_ip, "ip_lists": [], "workload": {"labels": []}},
            "dst": {"ip": dst_ip, "ip_lists": [], "workload": {"labels": []}},
            "service": {}}


def test_ex_src_ip_scalar_excludes_on_src_hit():
    # 舊前端送 scalar：既有行為不可回歸
    flow = _flow_with_ips(src_ip="10.0.0.1")
    assert _match(flow, {"ex_src_ip": "10.0.0.1"}) is False
    assert _match(flow, {"ex_src_ip": "10.0.0.2"}) is True


def test_ex_src_ip_list_excludes_on_src_hit():
    # FilterBar 送 list（filter-bar.js 排除 IP pill 序列化）：任一值命中即排除
    flow = _flow_with_ips(src_ip="10.0.0.1")
    assert _match(flow, {"ex_src_ip": ["10.0.0.1", "10.0.0.9"]}) is False
    assert _match(flow, {"ex_dst_ip": ["10.0.0.1"]}) is True


def test_ex_dst_ip_list_excludes_on_dst_hit():
    flow = _flow_with_ips(dst_ip="10.0.0.5")
    assert _match(flow, {"ex_dst_ip": ["10.0.0.5", "10.0.0.9"]}) is False
    assert _match(flow, {"ex_src_ip": ["10.0.0.5"]}) is True


# ─── src_ip_in/dst_ip_in list 形殘餘比對（native 解析失敗降級時，不得靜默不過濾）───

def test_src_ip_in_list_matches_or():
    flow = _flow_with_ips(src_ip="10.0.0.1")
    assert _match(flow, {"src_ip_in": ["10.0.0.1", "10.0.0.9"]}) is True
    assert _match(flow, {"src_ip_in": ["10.0.0.2", "10.0.0.9"]}) is False


def test_dst_ip_in_list_matches_or():
    flow = _flow_with_ips(dst_ip="10.0.0.5")
    assert _match(flow, {"dst_ip_in": ["10.0.0.5", "10.0.0.9"]}) is True
    assert _match(flow, {"dst_ip_in": ["10.0.0.2", "10.0.0.9"]}) is False


def test_src_ip_in_scalar_still_supported():
    # native 解析失敗仍可能只降級單一 scalar 值（非 list）——沿用既有 scalar 慣例
    flow = _flow_with_ips(src_ip="10.0.0.1")
    assert _match(flow, {"src_ip_in": "10.0.0.1"}) is True
    assert _match(flow, {"src_ip_in": "10.0.0.2"}) is False


# ─── _ip_match CIDR containment（IPv4 強制；語意對齊 df_filter._ip_mask）───

def test_ip_match_cidr_containment_hit():
    flow = _flow_with_ips(src_ip="10.0.0.5")
    assert _match(flow, {"src_ip": "10.0.0.0/24"}) is True


def test_ip_match_cidr_containment_miss():
    flow = _flow_with_ips(src_ip="10.0.1.5")
    assert _match(flow, {"src_ip": "10.0.0.0/24"}) is False


def test_ip_match_cidr_containment_in_list_or():
    flow = _flow_with_ips(src_ip="10.0.0.5")
    assert _match(flow, {"src_ip_in": ["10.0.0.0/24", "192.168.0.0/24"]}) is True
    assert _match(flow, {"src_ip_in": ["172.16.0.0/24", "192.168.0.0/24"]}) is False


def test_ip_match_cidr_illegal_fails_closed():
    flow = _flow_with_ips(src_ip="10.0.0.5")
    assert _match(flow, {"src_ip": "10.0.0.0/not-a-mask"}) is False


def test_ip_match_cidr_ipv6_fails_closed():
    # IPv4 強制：IPv6 CIDR 沿用既有 IPv6 range fail-closed 慣例
    flow = {"src": {"ip": "a::5", "ip_lists": [], "workload": {"labels": []}},
            "dst": {"ip": "", "ip_lists": [], "workload": {"labels": []}},
            "service": {}}
    assert _match(flow, {"src_ip": "a::/64"}) is False


def test_ex_src_ip_cidr_excludes_on_containment():
    flow = _flow_with_ips(src_ip="10.0.0.5")
    assert _match(flow, {"ex_src_ip": "10.0.0.0/24"}) is False
    assert _match(flow, {"ex_src_ip": "192.168.0.0/24"}) is True
