"""Cache-aware app scoping: read_flows_raw filters by workload hrefs; App Summary
derives the app's hrefs and threads them so the cache read only pulls its flows."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from src.report.app_summary_report import _app_workload_hrefs, AppSummaryReport


def _wl(href, app, env=None):
    labels = [{"key": "app", "value": app}]
    if env:
        labels.append({"key": "env", "value": env})
    return {"href": href, "hostname": href, "enforcement_mode": "full", "labels": labels}


def test_app_workload_hrefs_filters_by_app_and_env():
    wls = [_wl("/w/1", "DB", "Prod"), _wl("/w/2", "DB", "Dev"), _wl("/w/3", "Web", "Prod")]
    assert set(_app_workload_hrefs(wls, "DB", None)) == {"/w/1", "/w/2"}
    assert set(_app_workload_hrefs(wls, "DB", "Prod")) == {"/w/1"}
    assert _app_workload_hrefs([], "DB", None) == []


def test_read_flows_raw_workload_filter(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from src.pce_cache.schema import init_schema
    from src.pce_cache.models import PceTrafficFlowRaw
    eng = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(eng); sf = sessionmaker(eng)
    now = datetime.datetime.now(datetime.timezone.utc)
    with sf.begin() as s:
        for i, (sw, dw) in enumerate([("/w/1", "/w/9"), ("/w/8", "/w/2"), ("/w/7", "/w/7")]):
            s.add(PceTrafficFlowRaw(flow_hash=f"h{i}", first_detected=now, last_detected=now,
                                    src_ip="1.1.1.1", src_workload=sw, dst_ip="2.2.2.2", dst_workload=dw,
                                    port=443, protocol="tcp", action="allowed", flow_count=1,
                                    bytes_in=0, bytes_out=0, raw_json=f'{{"n":{i}}}', ingested_at=now))
    from src.pce_cache.reader import CacheReader
    rd = CacheReader(sf, 30, 30)
    start = now - datetime.timedelta(hours=1); end = now + datetime.timedelta(hours=1)
    assert len(rd.read_flows_raw(start, end)) == 3                      # unfiltered
    got = rd.read_flows_raw(start, end, workload_hrefs=["/w/1", "/w/2"])  # src OR dst match
    assert {r["n"] for r in got} == {0, 1}                              # row 2 excluded


def test_app_summary_passes_workload_hrefs_to_cache_read():
    captured = {}
    api = MagicMock()
    api.fetch_managed_workloads.return_value = [_wl("/w/1", "DB"), _wl("/w/2", "DB")]
    rep = AppSummaryReport(cm=MagicMock(), api_client=api)

    def _spy(start_date=None, end_date=None, filters=None, use_cache=True, cache_workload_hrefs=None):
        captured["hrefs"] = cache_workload_hrefs
        return pd.DataFrame()  # empty → build hits empty-state early return
    with patch.object(rep, "_fetch_estate_df", side_effect=_spy):
        rep.build(app="DB", lang="en")
    assert set(captured["hrefs"]) == {"/w/1", "/w/2"}
