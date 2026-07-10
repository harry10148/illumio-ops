"""Step 0: 同 key 多 IP 值分組語意查驗（inner-AND bug 釘住）+ IP range 端到端支援。"""
from unittest.mock import MagicMock, patch

import pytest

from src.api_client import ApiClient


@pytest.fixture
def client():
    cm = MagicMock()
    cm.config = {"pce": {"fqdn": "pce", "port": 8443, "org_id": 1,
                         "api_key": "k", "api_secret": "s"}}
    with patch.object(ApiClient, "__init__", lambda self, cm: None):
        c = ApiClient(cm)
    from src.api.labels import LabelResolver
    from src.api.traffic_query import TrafficQueryBuilder
    c.label_cache = {}
    c.service_ports_cache = {}
    c._label_href_cache = {}
    c._label_group_href_cache = {}
    c._iplist_href_cache = {}
    c.update_label_cache = MagicMock()  # 避免 unresolved 值 fallback 到 iplist 查找時打真網路
    c._labels = LabelResolver(c)
    c._traffic = TrafficQueryBuilder(c)
    return c


def _payload(client, filters):
    payload, effective_spec = client._traffic._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"], filters)
    client.last_traffic_query_diagnostics = dict(effective_spec.diagnostics)
    return payload


# ─── Step 0: 同 key 多 IP 值必須外層 OR（每值一組），而非內層 AND（同一組）───

def test_src_ip_in_multi_value_is_outer_or_not_inner_and(client):
    p = _payload(client, {"src_ip_in": ["1.1.1.1", "2.2.2.2"]})
    include = p["sources"]["include"]
    # 正確語意：外層 OR，每個 IP 各自一組 [[{ip1}], [{ip2}]]
    assert [{"ip_address": "1.1.1.1"}] in include
    assert [{"ip_address": "2.2.2.2"}] in include
    # 絕不能是內層 AND（同一 flow 的 src 不可能同時等於兩個 IP）
    assert [{"ip_address": "1.1.1.1"}, {"ip_address": "2.2.2.2"}] not in include


def test_dst_ip_in_multi_value_is_outer_or(client):
    p = _payload(client, {"dst_ip_in": ["3.3.3.3", "4.4.4.4"]})
    include = p["destinations"]["include"]
    assert [{"ip_address": "3.3.3.3"}] in include
    assert [{"ip_address": "4.4.4.4"}] in include
    assert [{"ip_address": "3.3.3.3"}, {"ip_address": "4.4.4.4"}] not in include


# ─── Step 1: native 展開（labels._resolve_ip_filter_to_actors）───

def test_resolve_ip_filter_to_actors_single_ip(client):
    assert client._labels._resolve_ip_filter_to_actors("1.1.1.1") == [{"ip_address": "1.1.1.1"}]


# ─── CIDR literal 應直接走 ip_address native actor（非 IP List 名稱查找）───

def test_is_ip_literal_accepts_cidr(client):
    assert client._labels._is_ip_literal("10.0.0.0/24") is True
    assert client._labels._is_ip_literal("172.16.15.106/32") is True


def test_resolve_ip_filter_to_actor_accepts_cidr(client):
    assert client._labels._resolve_ip_filter_to_actor("10.0.0.0/24") == {"ip_address": "10.0.0.0/24"}


def test_resolve_ip_filter_to_actors_single_cidr(client):
    assert client._labels._resolve_ip_filter_to_actors("10.0.0.0/24") == [{"ip_address": "10.0.0.0/24"}]


def test_src_ip_in_cidr_native_payload_consumed(client):
    p = _payload(client, {"src_ip_in": ["10.0.0.0/24"]})
    include = p["sources"]["include"]
    assert [{"ip_address": "10.0.0.0/24"}] in include
    diag = client.last_traffic_query_diagnostics
    assert "src_ip_in" in diag["native_filters"]
    assert "src_ip_in" not in diag.get("unresolved_native_filters", {})


def test_cidr_literal_precedence_over_same_named_ip_list(client):
    """CIDR-shaped literal (e.g. '10.0.0.0/24') takes precedence over IP List name lookup.

    Even if an IP List is named '10.0.0.0/24', the filter value '10.0.0.0/24'
    resolves to a literal ip_address actor, not an ip_list actor.
    """
    # Mock an IP List with name "10.0.0.0/24"
    client._iplist_href_cache["10.0.0.0/24"] = "/orgs/1/sec_policy/draft/ip_lists/abc123"

    result = client._labels._resolve_ip_filter_to_actor("10.0.0.0/24")

    # Should resolve to literal CIDR, not IP List
    assert result == {"ip_address": "10.0.0.0/24"}


def test_resolve_ip_filter_to_actors_range_expands_to_cidrs(client):
    items = client._labels._resolve_ip_filter_to_actors("10.0.0.5-10.0.0.6")
    assert items == [{"ip_address": "10.0.0.5/32"}, {"ip_address": "10.0.0.6/32"}]


def test_resolve_ip_filter_to_actors_range_from_gt_to_auto_swaps(client):
    forward = client._labels._resolve_ip_filter_to_actors("10.0.0.5-10.0.0.6")
    reversed_ = client._labels._resolve_ip_filter_to_actors("10.0.0.6-10.0.0.5")
    assert forward == reversed_


def test_resolve_ip_filter_to_actors_illegal_range_returns_empty(client):
    # 非法 range（右側非合法 IP）→ 空清單，呼叫端走 unresolved 降級
    assert client._labels._resolve_ip_filter_to_actors("10.0.0.5-not-an-ip") == []


def test_src_ip_in_range_native_payload_each_cidr_is_own_or_group(client):
    p = _payload(client, {"src_ip_in": ["10.0.0.5-10.0.0.6"]})
    include = p["sources"]["include"]
    assert [{"ip_address": "10.0.0.5/32"}] in include
    assert [{"ip_address": "10.0.0.6/32"}] in include
    diag = client.last_traffic_query_diagnostics
    assert "src_ip_in" in diag["native_filters"]


def test_dst_ip_range_scalar_key_native(client):
    p = _payload(client, {"dst_ip": "10.0.0.5-10.0.0.6"})
    include = p["destinations"]["include"]
    assert [{"ip_address": "10.0.0.5/32"}] in include
    assert [{"ip_address": "10.0.0.6/32"}] in include


def test_ex_src_ip_range_native_payload_flat_extend(client):
    p = _payload(client, {"ex_src_ip": "10.0.0.5-10.0.0.6"})
    exclude = p["sources"]["exclude"]
    assert {"ip_address": "10.0.0.5/32"} in exclude
    assert {"ip_address": "10.0.0.6/32"} in exclude


def test_src_ip_in_illegal_range_falls_back_unresolved(client):
    p = _payload(client, {"src_ip_in": ["10.0.0.5-nope"]})
    assert p["sources"]["include"] == []
    diag = client.last_traffic_query_diagnostics
    assert "src_ip_in" in diag["unresolved_native_filters"]


# ─── Step 1: df_filter._ip_mask range containment（cache 路徑）───

def test_ip_mask_range_containment():
    import pandas as pd
    from src.report.df_filter import _ip_mask
    df = pd.DataFrame({"src_ip": ["10.0.0.5", "10.0.0.51", "9.9.9.9"]})
    m = _ip_mask(df, "src_ip", "10.0.0.5-10.0.0.50")
    assert list(m) == [True, False, False]


def test_ip_mask_range_from_gt_to_auto_swaps():
    import pandas as pd
    from src.report.df_filter import _ip_mask
    df = pd.DataFrame({"src_ip": ["10.0.0.25"]})
    assert list(_ip_mask(df, "src_ip", "10.0.0.50-10.0.0.5")) == [True]


def test_ip_mask_illegal_range_matches_all_existing_convention():
    """既有慣例：非法 CIDR 回全 True（fail-open，cache 顯示用）；range 比照。"""
    import pandas as pd
    from src.report.df_filter import _ip_mask
    df = pd.DataFrame({"src_ip": ["1.2.3.4"]})
    assert list(_ip_mask(df, "src_ip", "10.0.0.5-not-an-ip")) == [True]


def test_apply_df_traffic_filters_src_ip_in_range():
    import pandas as pd
    from src.report.df_filter import apply_df_traffic_filters
    df = pd.DataFrame({"src_ip": ["10.0.0.5", "10.0.0.100"], "dst_ip": ["2.2.2.2", "2.2.2.2"]})
    out = apply_df_traffic_filters(df, {"src_ip_in": ["10.0.0.5-10.0.0.50"]})
    assert list(out["src_ip"]) == ["10.0.0.5"]


# ─── Step 1: fallback _ip_match range containment（live re-filter 路徑）───

def test_flow_matches_filters_src_ip_range_containment():
    from src.api.traffic_query import TrafficQueryBuilder
    flow = {"src": {"ip": "10.0.0.25"}, "dst": {"ip": "2.2.2.2"}, "service": {}}
    assert TrafficQueryBuilder._flow_matches_filters(flow, {"src_ip": "10.0.0.5-10.0.0.50"}) is True


def test_flow_matches_filters_src_ip_range_no_match():
    from src.api.traffic_query import TrafficQueryBuilder
    flow = {"src": {"ip": "9.9.9.9"}, "dst": {"ip": "2.2.2.2"}, "service": {}}
    assert TrafficQueryBuilder._flow_matches_filters(flow, {"src_ip": "10.0.0.5-10.0.0.50"}) is False


def test_flow_matches_filters_ex_src_ip_range_excludes():
    from src.api.traffic_query import TrafficQueryBuilder
    flow = {"src": {"ip": "10.0.0.25"}, "dst": {"ip": "2.2.2.2"}, "service": {}}
    assert TrafficQueryBuilder._flow_matches_filters(flow, {"ex_src_ip": "10.0.0.5-10.0.0.50"}) is False


# ─── IPv6 range enforcement (fail-open in cache, fail-closed in live) ───

def test_ip_mask_ipv6_range_matches_all():
    """IPv6 ranges are not supported; treated as illegal and fail-open (cache convention)."""
    import pandas as pd
    from src.report.df_filter import _ip_mask
    df = pd.DataFrame({"src_ip": ["a::1", "a::5", "b::1"]})
    m = _ip_mask(df, "src_ip", "a::1-a::2")
    assert list(m) == [True, True, True]


def test_flow_matches_filters_ipv6_range_no_match():
    """IPv6 ranges are not supported; treated as illegal and fail-closed (live convention)."""
    from src.api.traffic_query import TrafficQueryBuilder
    flow = {"src": {"ip": "a::5"}, "dst": {"ip": "2.2.2.2"}, "service": {}}
    # IPv6 range should not match; fall through to False (fail-closed)
    assert TrafficQueryBuilder._flow_matches_filters(flow, {"src_ip": "a::1-a::2"}) is False
