"""Tier-2a: the cache flatten cache (report_json) + vectorized read produce a
DataFrame identical to the live APIParser path."""
from __future__ import annotations

import datetime
import orjson
import pandas as pd

from src.report.parsers.api_parser import (
    APIParser, flatten_flow_record, build_unified_df,
)


def _flow(src_app, dst_app, port, decision, dbi=1000, dbo=2000):
    return {
        "src": {"ip": "10.0.0.1", "workload": {"hostname": "web01", "href": "/w/1",
                "enforcement_mode": "full", "os_type": "linux",
                "labels": [{"key": "app", "value": src_app}, {"key": "env", "value": "Prod"},
                           {"key": "team", "value": "x"}]}},
        "dst": {"ip": "10.0.0.2", "fqdn": "", "workload": {"hostname": "db01", "href": "/w/2",
                "enforcement_mode": "visibility_only", "os_type": "linux",
                "labels": [{"key": "app", "value": dst_app}, {"key": "env", "value": "Prod"}]}},
        "service": {"port": port, "proto": 6, "process_name": "nginx", "user_name": "root"},
        "num_connections": 5, "state": "active", "policy_decision": decision,
        "first_detected": "2026-06-10T00:00:00Z", "last_detected": "2026-06-11T00:00:00Z",
        "dst_dbi": dbi, "dst_dbo": dbo,
    }


def test_report_json_roundtrip_equals_apiparser():
    """report_json (= flatten_flow_record, JSON round-tripped) rebuilds the exact
    same DataFrame the live APIParser produces."""
    flows = [_flow("DB", "DB", 3306, "allowed"),
             _flow("Web", "DB", 443, "potentially_blocked", dbi=0, dbo=0)]
    df_api = APIParser().parse(flows)
    # simulate the cache round-trip: store flatten as JSON, read back, assemble
    rows = [orjson.loads(orjson.dumps(flatten_flow_record(f))) for f in flows]
    df_cache = build_unified_df(rows, "api")
    pd.testing.assert_frame_equal(
        df_api.reset_index(drop=True), df_cache.reset_index(drop=True), check_like=True,
    )


def test_read_flows_df_uses_report_json_and_falls_back(tmp_path):
    """read_flows_df returns the unified frame from report_json, and falls back
    to flattening raw_json for rows that predate report_json."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceTrafficFlowRaw
    from src.pce_cache.reader import CacheReader

    eng = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(eng); sf = sessionmaker(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    f1 = _flow("DB", "DB", 3306, "allowed")
    f2 = _flow("Web", "DB", 443, "potentially_blocked")
    with sf.begin() as s:
        # row WITH report_json (new path)
        s.add(PceTrafficFlowRaw(
            flow_hash="h1", first_detected=now, last_detected=now,
            src_ip="10.0.0.1", src_workload="/w/1", dst_ip="10.0.0.2", dst_workload="/w/2",
            port=3306, protocol="TCP", action="allowed", flow_count=5, bytes_in=0, bytes_out=0,
            raw_json=orjson.dumps(f1).decode(),
            report_json=orjson.dumps(flatten_flow_record(f1)).decode(), ingested_at=now))
        # row WITHOUT report_json (fallback to raw_json)
        s.add(PceTrafficFlowRaw(
            flow_hash="h2", first_detected=now, last_detected=now,
            src_ip="10.0.0.1", src_workload="/w/9", dst_ip="10.0.0.2", dst_workload="/w/2",
            port=443, protocol="TCP", action="potentially_blocked", flow_count=5,
            bytes_in=0, bytes_out=0, raw_json=orjson.dumps(f2).decode(),
            report_json=None, ingested_at=now))
    rd = CacheReader(sf, 30, 30)
    start = now - datetime.timedelta(hours=1); end = now + datetime.timedelta(hours=1)
    df = rd.read_flows_df(start, end)
    assert len(df) == 2
    assert set(df["src_app"]) == {"DB", "Web"}
    assert set(df["proto"]) == {"TCP"}
    assert df["data_source"].unique().tolist() == ["cache"]


def test_read_flows_df_policy_decision_pushdown(tmp_path):
    """policy_decisions filters at the SQL layer — correctness (cache honours the
    report's decision filter) + perf (reads only matching rows)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceTrafficFlowRaw
    from src.pce_cache.reader import CacheReader
    import orjson as _oj

    eng = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(eng); sf = sessionmaker(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    with sf.begin() as s:
        for i, act in enumerate(["allowed", "potentially_blocked", "potentially_blocked", "blocked"]):
            f = _flow("DB", "DB", 443, act)
            s.add(PceTrafficFlowRaw(
                flow_hash=f"h{i}", first_detected=now, last_detected=now,
                src_ip="10.0.0.1", src_workload="/w/1", dst_ip="10.0.0.2", dst_workload="/w/2",
                port=443, protocol="TCP", action=act, flow_count=1, bytes_in=0, bytes_out=0,
                raw_json=_oj.dumps(f).decode(),
                report_json=_oj.dumps(flatten_flow_record(f)).decode(), ingested_at=now))
    rd = CacheReader(sf, 30, 30)
    start = now - datetime.timedelta(hours=1); end = now + datetime.timedelta(hours=1)
    assert len(rd.read_flows_df(start, end)) == 4                                   # no filter
    df = rd.read_flows_df(start, end, policy_decisions=["allowed"])
    assert len(df) == 1 and df["policy_decision"].tolist() == ["allowed"]
    assert len(rd.read_flows_df(start, end, policy_decisions=["allowed", "blocked"])) == 2


def test_read_flows_df_matches_apiparser_with_filters(tmp_path):
    """read_flows_df (raw-cursor fetch) returns a frame identical to the live
    APIParser for the matching flows — across report_json + raw_json-fallback
    rows and with window + workload-href + policy-decision filters pushed to SQL.
    Pins the read contract for the SQLAlchemy→raw-cursor refactor."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceTrafficFlowRaw
    from src.pce_cache.reader import CacheReader

    eng = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(eng); sf = sessionmaker(eng)
    now = datetime.datetime.now(datetime.timezone.utc)

    # In-window, /w/1↔/w/2, allowed — WITH report_json (fast path)
    f_keep = _flow("DB", "DB", 3306, "allowed")
    # In-window, /w/1↔/w/2, allowed — WITHOUT report_json (raw_json fallback)
    f_keep_fb = _flow("Web", "DB", 8080, "allowed", dbi=10, dbo=20)
    # In-window but decision filtered out
    f_drop_dec = _flow("DB", "DB", 443, "potentially_blocked")
    # In-window but different workloads (scoped out)
    f_drop_wl = _flow("DB", "DB", 22, "allowed")

    def add(h, f, src_wl, dst_wl, act, port, with_rj):
        with sf.begin() as s:
            s.add(PceTrafficFlowRaw(
                flow_hash=h, first_detected=now, last_detected=now,
                src_ip="10.0.0.1", src_workload=src_wl, dst_ip="10.0.0.2",
                dst_workload=dst_wl, port=port, protocol="TCP", action=act,
                flow_count=5, bytes_in=0, bytes_out=0,
                raw_json=orjson.dumps(f).decode(),
                report_json=(orjson.dumps(flatten_flow_record(f)).decode()
                             if with_rj else None),
                ingested_at=now))

    add("h1", f_keep, "/w/1", "/w/2", "allowed", 3306, True)
    add("h2", f_keep_fb, "/w/1", "/w/2", "allowed", 8080, False)
    add("h3", f_drop_dec, "/w/1", "/w/2", "potentially_blocked", 443, True)
    add("h4", f_drop_wl, "/w/8", "/w/9", "allowed", 22, True)

    rd = CacheReader(sf, 30, 30)
    start = now - datetime.timedelta(hours=1); end = now + datetime.timedelta(hours=1)
    df = rd.read_flows_df(start, end, workload_hrefs=["/w/1", "/w/2"],
                          policy_decisions=["allowed"])

    # ground truth: APIParser frame of just the two kept flows
    df_api = APIParser().parse([f_keep, f_keep_fb])
    sort_cols = ["src_app", "port"]
    pd.testing.assert_frame_equal(
        df.drop(columns=["data_source"]).sort_values(sort_cols).reset_index(drop=True),
        df_api.drop(columns=["data_source"]).sort_values(sort_cols).reset_index(drop=True),
        check_like=True,
    )


def test_fetch_traffic_df_applies_filters_to_cache():
    """_fetch_traffic_df re-applies the report's label/port filters on the cache
    df (the cache read doesn't filter beyond decision/workload)."""
    from unittest.mock import MagicMock
    import pandas as pd
    from src.report.report_generator import ReportGenerator
    cache = MagicMock()
    cache.cover_state.return_value = "full"
    cache.read_flows_df.return_value = pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 443, "proto": "TCP",
         "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "src_extra_labels": {}, "dst_extra_labels": {}},
        {"src_app": "ERP", "dst_app": "DB", "port": 22, "proto": "TCP",
         "src_ip": "10.0.0.3", "dst_ip": "10.0.0.4", "src_extra_labels": {}, "dst_extra_labels": {}},
    ])
    gen = ReportGenerator(config_manager=MagicMock(), api_client=MagicMock(), cache_reader=cache)
    import datetime
    s = datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc)
    e = datetime.datetime(2026, 6, 8, tzinfo=datetime.timezone.utc)
    df, src = gen._fetch_traffic_df(s, e, {"src_labels": ["app=Web"]}, use_cache=True)
    assert src == "cache"
    assert df["src_app"].tolist() == ["Web"]  # ERP row filtered out post-read
