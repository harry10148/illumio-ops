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


def test_blank_only_transmission_include_matches_nothing_filtered_both_paths():
    # 全空白 include 清單：matcher 的 _name_values 先去空、清單變空即跳過該
    # key（不限制）；df 路徑須對齊，不可在去空「之前」就判斷 truthy。
    f = TrafficQueryBuilder._flow_matches_filters
    assert f(_flow("broadcast"), {"transmission": [""]})
    assert f(_flow("unicast"), {"transmission": [""]})

    df = pd.DataFrame([
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 137, "transmission": "broadcast"},
        {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "port": 53, "transmission": "unicast"},
    ])
    out = df_filter(df, {"transmission": [""]})
    assert len(out) == len(df)


def test_native_payload_include_side():
    # 真 PCE 驗證（第二次修正）：destinations.include 的 actor schema
    # 根本不接受 transmission 條目（list-of-lists 得到 406；flat dict
    # 也被拒絕，parse 端丟 'str' object has no attribute 'get'）。
    # 因此 transmission include 必須整個走 client-side fallback，
    # 不可出現在 native_filters 或 native payload 的 destinations.include 裡。
    #
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

    spec = b.build_traffic_query_spec({"transmission": ["broadcast"]})
    assert "transmission" in spec.fallback_filters
    assert "transmission" not in spec.native_filters

    payload, _spec = b._build_native_traffic_payload(
        "2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", ["allowed"],
        filters={"transmission": ["broadcast"]})
    for entry in payload["destinations"]["include"]:
        assert not (isinstance(entry, dict) and "transmission" in entry)
