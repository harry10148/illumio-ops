"""query_flows 截斷統計：500 上限不再無聲（spec §11.3）。"""
from src.analyzer import Analyzer, QUERY_RESULT_CAP
from src.api.traffic_query import TrafficQueryBuilder


def _flow(i):
    return {
        "src": {"ip": f"10.0.{i // 250}.{i % 250}", "workload": {}},
        "dst": {"ip": "10.9.9.9", "workload": {}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "num_connections": 1,
        "timestamp_range": {"first_detected": "2026-07-01T00:00:00Z",
                            "last_detected": "2026-07-01T01:00:00Z"},
    }


def _analyzer_with_flows(monkeypatch, n):
    # 沿用 tests/test_analyzer_with_mock_api.py 的 _make_analyzer 建構方式
    # （stub api + 暫存 config）；此處只覆寫流量來源。
    # _make_analyzer() 回傳 (Analyzer, api, reporter) 三元組。
    from tests.test_analyzer_with_mock_api import _make_analyzer
    ana, api, _rep = _make_analyzer()
    # _StubApiClient 沒有 build_traffic_query_spec/execute_traffic_query_stream
    # （這兩個方法屬於 query_flows 實際使用的路徑，_cache_reader 為 None 時
    # 會走 execute_traffic_query_stream，而非 fetch_traffic_for_report）。
    # build_traffic_query_spec 是純邏輯（不觸碰 PCE），直接借用真正實作。
    qb = TrafficQueryBuilder(client=None)
    monkeypatch.setattr(api, "build_traffic_query_spec", qb.build_traffic_query_spec, raising=False)
    monkeypatch.setattr(api, "execute_traffic_query_stream",
                        lambda *a, **kw: iter([_flow(i) for i in range(n)]), raising=False)
    return ana


def _params():
    return {"start_time": "2026-06-01T00:00:00Z", "end_time": "2026-07-02T00:00:00Z"}


def test_under_cap_not_truncated(monkeypatch):
    ana = _analyzer_with_flows(monkeypatch, 3)
    out = ana.query_flows(_params())
    assert len(out) == 3
    assert ana.last_query_stats == {"total_matches": 3, "cap": QUERY_RESULT_CAP,
                                    "truncated": False}


def test_over_cap_truncated_and_counted(monkeypatch):
    ana = _analyzer_with_flows(monkeypatch, QUERY_RESULT_CAP + 37)
    out = ana.query_flows(_params())
    assert len(out) == QUERY_RESULT_CAP
    assert ana.last_query_stats["total_matches"] == QUERY_RESULT_CAP + 37
    assert ana.last_query_stats["truncated"] is True
