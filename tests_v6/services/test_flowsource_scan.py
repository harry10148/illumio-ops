"""Wide windows scan the flows table instead of walking the last_detected index (P5b-1 Task 9: on 8 million rows a
7-day report read took 30 s through the index and 6.5 s as a scan, and a report makes about nine such reads)."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.filter import FilterSpec, to_sql
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services import flowsource
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.services.collect.conftest import configured_ctx, raw_flow

NOW = datetime(2026, 10, 28, 1, tzinfo=UTC)


def _store(tmp_path):
    ctx = configured_ctx(tmp_path)
    flows = []
    for day in range(8):
        first = datetime(2026, 10, 20, 3, tzinfo=UTC) + timedelta(days=day)
        flows.append(normalize_flow(raw_flow(day + 1, first, first + timedelta(minutes=5), port=443)))
    with ctx.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)
    return ctx


def test_to_sql_wide_skips_the_time_index():
    spec = FilterSpec(start=NOW - timedelta(days=7), end=NOW)
    assert "+f.last_detected >= ?" in to_sql(spec, wide=True)[0]
    assert "+f.last_detected" not in to_sql(spec)[0]


def test_wide_window_follows_the_stored_span(tmp_path):
    ctx = _store(tmp_path)
    with ctx.flows().connect() as conn:
        assert flowsource.wide_window(conn, FilterSpec(start=NOW - timedelta(days=7), end=NOW))
        assert not flowsource.wide_window(conn, FilterSpec(start=NOW - timedelta(hours=26), end=NOW - timedelta(hours=25)))


def test_report_reads_scan_wide_windows(tmp_path):
    ctx = _store(tmp_path)
    seen: list[str] = []
    real = ctx.flows().connect

    def spy():
        conn = real()
        conn.set_trace_callback(seen.append)
        return conn
    fdb = ctx.flows()
    fdb.connect = spy  # type: ignore[method-assign]
    t = flowsource.flow_totals(ctx, FilterSpec(start=NOW - timedelta(days=7), end=NOW))
    assert t.flows == 7
    reads = [s for s in seen if " FROM flows f " in s]
    assert reads and all("+f.last_detected" in s for s in reads)
