"""ports/ex_ports 與 services/ex_services filter key 的 native payload 與 fallback 行為。"""
from unittest.mock import MagicMock, patch

import pytest

from src.api_client import ApiClient

SVC_HREF = "/orgs/1/sec_policy/active/services/10"


@pytest.fixture
def client():
    cm = MagicMock()
    cm.config = {"pce": {"fqdn": "pce", "port": 8443, "org_id": 1,
                         "api_key": "k", "api_secret": "s"}}
    with patch.object(ApiClient, "__init__", lambda self, cm: None):
        c = ApiClient(cm)
    # 最小可用內部狀態（比照 tests/test_analyzer_object_filters.py 的裸建樣式）
    from src.api.labels import LabelResolver
    from src.api.traffic_query import TrafficQueryBuilder
    c.label_cache = {}
    c.service_ports_cache = {}
    c._labels = LabelResolver(c)
    c._traffic = TrafficQueryBuilder(c)
    return c


def _payload(client, filters):
    payload, effective_spec = client._traffic._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"], filters)
    # execute_traffic_query_stream 平時才會做這個賦值；直接呼叫
    # _build_native_traffic_payload 的測試路徑需自行補上，語意與產品碼一致。
    client.last_traffic_query_diagnostics = dict(effective_spec.diagnostics)
    return payload


def test_ports_include_tokens(client):
    p = _payload(client, {"ports": ["80", "443/tcp", "1000-2000/udp"]})
    assert {"port": 80} in p["services"]["include"]
    assert {"port": 443, "proto": 6} in p["services"]["include"]
    assert {"port": 1000, "to_port": 2000, "proto": 17} in p["services"]["include"]


def test_ex_ports_exclude_tokens(client):
    p = _payload(client, {"ex_ports": ["22", "3389/tcp"]})
    assert {"port": 22} in p["services"]["exclude"]
    assert {"port": 3389, "proto": 6} in p["services"]["exclude"]


def test_ports_invalid_token_unresolved(client):
    p = _payload(client, {"ports": ["80", "notaport"]})
    assert p["services"]["include"] == []
    diag = client.last_traffic_query_diagnostics
    assert "ports" in diag["unresolved_native_filters"]


def test_ports_capability_native(client):
    spec = client._traffic.build_traffic_query_spec({"ports": ["80"], "ex_ports": ["22"]})
    assert "ports" in spec.native_filters and "ex_ports" in spec.native_filters


# ─── fallback：_flow_matches_filters 直接呼叫（比照 test_traffic_query_fallback_semantics.py 樣式）───

def _match(flow, filters):
    from src.api.traffic_query import TrafficQueryBuilder
    return TrafficQueryBuilder._flow_matches_filters(flow, filters)


def _flow_with_service(port, proto):
    return {"src": {}, "dst": {}, "service": {"port": port, "proto": proto}}


def test_fallback_ports_include_hit():
    flow = _flow_with_service(443, 6)
    assert _match(flow, {"ports": ["443/tcp"]}) is True


def test_fallback_ports_include_miss():
    flow = _flow_with_service(443, 6)
    assert _match(flow, {"ports": ["80"]}) is False


def test_fallback_ex_ports_excludes_on_hit():
    flow = _flow_with_service(443, 6)
    assert _match(flow, {"ex_ports": ["443"]}) is False


def test_fallback_ports_include_or_across_tokens():
    flow = _flow_with_service(443, 6)
    assert _match(flow, {"ports": ["80", "443/tcp"]}) is True


def test_fallback_ports_all_unresolved_fails_closed():
    flow = _flow_with_service(443, 6)
    assert _match(flow, {"ports": ["notaport"]}) is False


def test_fallback_ex_ports_skips_unresolved_value():
    flow = _flow_with_service(443, 6)
    # 無法解析的排除值略過、其餘值仍須生效比對——此處只有無法解析值，應維持命中（不排除）
    assert _match(flow, {"ex_ports": ["notaport"]}) is True


# ─── services/ex_services：href 查詢時展開（Task 4）───────────────────────────


def test_services_expand_to_entries(client):
    client.service_ports_cache[SVC_HREF] = [
        {"port": 80, "proto": 6}, {"port": 443, "proto": 6},
        {"windows_service_name": "wuauserv"},
    ]
    p = _payload(client, {"services": [SVC_HREF]})
    assert {"port": 80, "proto": 6} in p["services"]["include"]
    assert {"port": 443, "proto": 6} in p["services"]["include"]
    assert {"windows_service_name": "wuauserv"} in p["services"]["include"]


def test_ex_services_expand_to_exclude(client):
    client.service_ports_cache[SVC_HREF] = [{"port": 22, "proto": 6}]
    p = _payload(client, {"ex_services": [SVC_HREF]})
    assert {"port": 22, "proto": 6} in p["services"]["exclude"]


def test_services_unknown_href_unresolved(client):
    p = _payload(client, {"services": ["/orgs/1/sec_policy/active/services/404"]})
    assert p["services"]["include"] == []
    assert "services" in client.last_traffic_query_diagnostics["unresolved_native_filters"]


def test_services_expansion_cap(client):
    client.service_ports_cache[SVC_HREF] = [{"port": i} for i in range(1, 302)]
    p = _payload(client, {"services": [SVC_HREF]})
    assert p["services"]["include"] == []
    assert "services" in client.last_traffic_query_diagnostics["unresolved_native_filters"]


def test_services_fallback_flow_match(client):
    # 注意：_flow_matches_filters 是 @staticmethod（僅收 flow/filters，無 self/
    # client 存取管道），href 展開需要 client 端的 service_ports_cache，故此處
    # 額外傳入 resolve_service 這個第三參數（bound method）；呼叫慣例與
    # Step 1 brief 原稿的 2-arg 形式不同，原因見 B-task-4-report.md。
    client.service_ports_cache[SVC_HREF] = [{"port": 443, "proto": 6}]
    flow = {"src": {}, "dst": {}, "service": {"port": 443, "proto": 6}}
    resolve = client._labels.resolve_service_entries
    assert client._traffic._flow_matches_filters(flow, {"services": [SVC_HREF]}, resolve)
    assert not client._traffic._flow_matches_filters(flow, {"ex_services": [SVC_HREF]}, resolve)
