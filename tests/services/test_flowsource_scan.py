"""Wide windows scan the flows table instead of walking the last_detected index (P5b-1 Task 9: on 8 million rows a
7-day report read took 30 s through the index and 6.5 s as a scan, and a report makes about nine such reads)."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.filter import FilterSpec, to_sql
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services import flowsource
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.services.collect.conftest import configured_ctx, raw_flow

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


# ── a period's totals (stage 3b): flows with a decision, and the ones without ───────────────────────────────

def _decided_and_not(tmp_path):
    """Allowed 10 connections (4 of them from an unmanaged source, 2 on SSH), potentially blocked 30, blocked none;
    without a decision 50 between two addresses with no VEN and 10 from a managed host on SSH."""
    from tests.services.reports.test_findings import flow
    ctx = configured_ctx(tmp_path)
    flows = [flow(port=443, conns=4), flow(port=22, conns=2), flow(port=443, conns=4, unmanaged_src=True),
             flow(port=8080, decision="potentially_blocked", conns=30),
             flow(port=443, decision="unknown", unmanaged_src=True, unmanaged_dst=True, conns=50),
             flow(port=22, decision="unknown", conns=10)]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, flows, origin=DataOrigin.INGEST, now=NOW)
    return ctx


PERIOD = FilterSpec(start=datetime(2026, 10, 20, tzinfo=UTC), end=datetime(2026, 10, 27, tzinfo=UTC))


def test_totals_tell_decided_from_undecided(tmp_path):
    t = flowsource.flow_totals(_decided_and_not(tmp_path), PERIOD, admin_ports={(22, None)})
    assert (t.flows, t.connections) == (6, 100)  # what was seen: every flow, with or without a decision
    assert (t.decided_flows, t.decided_connections) == (4, 40)
    assert t.undecided == flowsource.Undecided(flows=2, connections=60, unmanaged_flows=1, unmanaged_connections=50,
                                               managed_flows=1, managed_connections=10)
    assert t.undecided.unmanaged_flows + t.undecided.managed_flows == t.undecided.flows
    assert t.undecided.unmanaged_connections + t.undecided.managed_connections == t.undecided.connections
    assert t.decided_flows + t.undecided.flows == t.flows


def test_unmanaged_and_management_port_connections_count_decided_flows_only(tmp_path):
    t = flowsource.flow_totals(_decided_and_not(tmp_path), PERIOD, admin_ports={(22, None)})
    assert t.from_unmanaged_connections == 4  # not 54: the 50 without a decision are not a decided risk
    assert t.admin_open_connections == 2  # the SSH flow without a decision is not "not blocked"
    assert (t.from_unmanaged, t.to_unmanaged) == (2, 1)  # flow counts are what was seen: unchanged


def test_decided_is_the_three_decisions_the_pce_gives():
    assert flowsource.DECIDED == ("allowed", "potentially_blocked", "blocked")
