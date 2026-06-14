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
