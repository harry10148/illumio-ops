import pandas as pd

from src.api.traffic_query import TrafficQueryBuilder
# NOTE: brief names this helper `df_filter`; the real function in
# src/report/df_filter.py is `apply_df_traffic_filters` (confirmed against
# tests/test_df_filter.py's existing imports).
from src.report.df_filter import apply_df_traffic_filters as df_filter


def _flow(process="httpd", port=443, proto=6):
    return {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": port, "proto": proto, "process_name": process},
        "policy_decision": "allowed",
    }


def test_process_name_include_matches_case_insensitive():
    f = TrafficQueryBuilder._flow_matches_filters
    assert f(_flow("HTTPD"), {"process_name": "httpd"})
    assert f(_flow("httpd"), {"process_name": ["HTTPD", "nginx"]})
    assert not f(_flow("nginx"), {"process_name": "httpd"})


def test_process_name_exclude():
    f = TrafficQueryBuilder._flow_matches_filters
    assert not f(_flow("httpd"), {"ex_process_name": ["httpd"]})
    assert f(_flow("nginx"), {"ex_process_name": ["httpd"]})


def test_process_missing_on_flow_is_fail_closed_include():
    f = TrafficQueryBuilder._flow_matches_filters
    flow = _flow(); flow["service"].pop("process_name")
    assert not f(flow, {"process_name": "httpd"})   # include 缺值不命中
    assert f(flow, {"ex_process_name": "httpd"})    # exclude 缺值不排除


def _df(rows):
    return pd.DataFrame(rows)


def test_df_filter_process_name():
    df = _df([
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 443, "proto": "TCP", "process_name": "httpd"},
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 80, "proto": "TCP", "process_name": "nginx"},
    ])
    out = df_filter(df, {"process_name": ["HTTPD"]})
    assert len(out) == 1 and out.iloc[0]["port"] == 443
    out = df_filter(df, {"ex_process_name": "nginx"})
    assert len(out) == 1 and out.iloc[0]["process_name"] == "httpd"


def test_df_filter_process_column_missing_null_tolerant():
    df = _df([{"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 443}])
    assert len(df_filter(df, {"process_name": "httpd"})) == 0   # fail-closed
    assert len(df_filter(df, {"ex_process_name": "httpd"})) == 1  # 不排除


def test_native_payload_accepts_list():
    # NOTE: _build_native_traffic_payload(self, start_time_str, end_time_str,
    # policy_decisions, filters=None) takes `filters=`, not `spec=`, and builds
    # the spec internally; it also returns (payload, effective_spec), not just
    # payload. `labels = self._client._labels` is accessed unconditionally
    # inside (used for `_normalize_transmission_values` even when no
    # transmission filter is present), so the client stub needs a `_labels`
    # object exposing the real LabelResolver static helpers.
    import types
    from src.api.traffic_query import TrafficQueryBuilder as B
    from src.api.labels import LabelResolver

    b = B.__new__(B)
    b._client = types.SimpleNamespace(_labels=LabelResolver)
    payload, _spec = b._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"],
        filters={"process_name": ["httpd", "nginx"]})
    entries = [e for e in payload["services"]["include"] if "process_name" in e]
    assert {e["process_name"] for e in entries} == {"httpd", "nginx"}
