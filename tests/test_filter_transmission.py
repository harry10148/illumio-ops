import pandas as pd

from src.api.traffic_query import TrafficQueryBuilder
# NOTE: brief names this helper `df_filter`; the real function in
# src/report/df_filter.py is `apply_df_traffic_filters` (same alias Task 3
# used in tests/test_filter_process_winservice.py).
from src.report.df_filter import apply_df_traffic_filters as df_filter


def _flow(tx="broadcast"):
    f = {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 137, "proto": 17},
        "policy_decision": "potentially_blocked",
    }
    if tx is not None:
        f["transmission"] = tx
    return f


def test_transmission_include_and_exclude():
    f = TrafficQueryBuilder._flow_matches_filters
    assert f(_flow("broadcast"), {"transmission": ["broadcast", "multicast"]})
    assert not f(_flow("unicast"), {"transmission": "broadcast"})
    assert not f(_flow("broadcast"), {"ex_transmission": "broadcast"})
    assert f(_flow("unicast"), {"ex_transmission": ["broadcast"]})


def test_transmission_missing_field_null_tolerant():
    f = TrafficQueryBuilder._flow_matches_filters
    assert not f(_flow(None), {"transmission": "broadcast"})  # include fail-closed
    assert f(_flow(None), {"ex_transmission": "broadcast"})   # exclude 不排除


def test_flatten_carries_transmission():
    from src.report.parsers.api_parser import flatten_flow_record
    rec = {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 137, "proto": 17},
        "num_connections": 1, "policy_decision": "allowed",
        "transmission": "multicast",
    }
    assert flatten_flow_record(rec)["transmission"] == "multicast"


def test_df_filter_transmission():
    df = pd.DataFrame([
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 137, "transmission": "broadcast"},
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 53, "transmission": "unicast"},
    ])
    assert len(df_filter(df, {"transmission": "broadcast"})) == 1
    assert len(df_filter(df, {"ex_transmission": ["broadcast"]})) == 1


def test_native_payload_include_side():
    # NOTE: _build_native_traffic_payload(self, start_time_str, end_time_str,
    # policy_decisions, filters=None) takes `filters=`, not `spec=`, and builds
    # the spec internally; it also returns (payload, effective_spec), not just
    # payload. `labels = self._client._labels` is accessed unconditionally
    # inside, so the client stub needs a `_labels` object exposing the real
    # LabelResolver static helpers (same stub as Task 3's payload test).
    import types
    from src.api.traffic_query import TrafficQueryBuilder as B
    from src.api.labels import LabelResolver

    b = B.__new__(B)
    b._client = types.SimpleNamespace(_labels=LabelResolver)
    payload, _spec = b._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"],
        filters={"transmission": ["broadcast"]})
    flat = str(payload["destinations"]["include"])
    assert "broadcast" in flat  # 形狀細節由 Task 6 真 PCE 定案，此處鎖「有進 include」
