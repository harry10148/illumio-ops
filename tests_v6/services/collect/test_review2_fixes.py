"""Regression tests for the second adversarial review (Tasks 7-11): each one failed before its fix."""
from datetime import timedelta

import pytest

from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.events import EventsPage
from illumio_ops.services import flowsource
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.backfill import run_backfill
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.services.eventsource import query_events
from illumio_ops.services.flowsource import query_flows
from illumio_ops.store.flowdb import ingest_state

from .conftest import NOW, configured_ctx, minutes, raw_flow

DAY = timedelta(days=1)
HOUR = timedelta(hours=1)


@pytest.fixture
def fake_fill(monkeypatch, fake_traffic):
    """One fake PCE for the collectors and for FlowSource's gap filling."""
    monkeypatch.setattr(flowsource, "run_traffic_query", fake_traffic)
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=[], capped=False))
    return fake_traffic


def _flows(ctx, start, end, *, fill=False, **kw):
    return query_flows(ctx, FilterSpec(start=start, end=end, **kw), limit=1000, order="last_detected_desc",
                       fill_gaps=fill, now=NOW)


def _gaps(q):
    return [(a, b, reason) for a, b, reason in q.coverage.gaps]


# ── Group A: coverage and gap filling ───────────────────────────────────────

def test_fill_that_hits_the_cap_stays_truncated(tmp_path, fake_fill, monkeypatch):  # finding 1
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    monkeypatch.setattr(flowsource, "FILL_MAX_RESULTS", 2)
    fake_fill.answer = lambda s, e, m: [raw_flow(i, e - minutes(3), e - minutes(2)) for i in range(2)]
    q = _flows(ctx, NOW - minutes(60), NOW + minutes(15), fill=True)
    assert _gaps(q) == [(NOW, NOW + minutes(15), "truncated")] and q.coverage.truncated
    assert len(q.rows) == 2


def test_hole_between_backfill_and_live_is_a_gap(tmp_path, fake_fill):  # finding 2
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)  # live covers [NOW-24h, NOW]
    run_backfill(ctx, start=NOW - 10 * DAY, end=NOW - 5 * DAY, now=NOW)
    q = _flows(ctx, NOW - 10 * DAY, NOW)
    assert _gaps(q) == [(NOW - 5 * DAY, NOW - DAY, "not_yet_collected")]
    e = query_events(ctx, start=NOW - 10 * DAY, end=NOW - 5 * DAY, limit=10, now=NOW)
    assert e.coverage.gaps == []


def test_backfill_coverage_and_open_gaps_count_without_live_collection(tmp_path, fake_fill):  # finding 3
    ctx = configured_ctx(tmp_path)
    fake_fill.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    run_traffic_cycle(ctx, now=NOW)  # the first live cycle fails: no watermark
    fake_fill.answer = lambda s, e, m: []
    run_backfill(ctx, start=NOW - 3 * DAY, end=NOW - 2 * DAY, now=NOW)
    cut = (NOW - 3 * DAY + HOUR, NOW - 3 * DAY + HOUR + minutes(10))
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, *cut, "truncated", "cap", NOW)
    q = _flows(ctx, NOW - 3 * DAY, NOW - 2 * DAY)
    assert _gaps(q) == [(*cut, "truncated")] and q.coverage.truncated


def test_before_first_collection_inside_retention_is_not_yet_collected(tmp_path, fake_fill):  # finding 4
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    assert _gaps(_flows(ctx, NOW - 2 * DAY, NOW)) == [(NOW - 2 * DAY, NOW - DAY, "not_yet_collected")]
    assert _gaps(_flows(ctx, NOW - 40 * DAY, NOW - 30 * DAY)) == [
        (NOW - 40 * DAY, NOW - 35 * DAY, "before_retention"),
        (NOW - 35 * DAY, NOW - 30 * DAY, "not_yet_collected")]


def test_store_rows_outside_coverage_make_the_answer_mixed(tmp_path, fake_fill):  # finding 5
    ctx = configured_ctx(tmp_path)
    fake_fill.answer = lambda s, e, m: [raw_flow(1, NOW - 30 * HOUR, NOW - HOUR)]  # began before the window
    run_traffic_cycle(ctx, now=NOW)
    fake_fill.answer = lambda s, e, m: []
    q = _flows(ctx, NOW - 30 * HOUR, NOW - 26 * HOUR, fill=True)
    assert len(q.rows) == 1 and q.rows[0].origin == "ingest" and q.coverage.source == "mixed"


def _pair(user="alice", process="server"):
    out = raw_flow(1, NOW - minutes(30), NOW - minutes(20), user=user)
    inn = raw_flow(1, NOW - minutes(30), NOW - minutes(20), direction="inbound")
    inn["service"]["process_name"] = process
    return out, inn


def test_two_sided_filter_matches_a_filled_pair(tmp_path, fake_fill):  # finding 6
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW - DAY)  # the last hour is not collected yet
    fake_fill.answer = lambda s, e, m: list(_pair())
    q = _flows(ctx, NOW - HOUR, NOW, fill=True, initiator_user="alice", service_process="server")
    assert [(r.initiator_user, r.service_process) for r in q.rows] == [("alice", "server")]
    q = _flows(ctx, NOW - HOUR, NOW, fill=True, initiator_user="alice")
    assert [(r.initiator_user, r.service_process) for r in q.rows] == [("alice", "server")]


def test_same_record_from_two_gap_windows_is_one_row(tmp_path, fake_fill):  # finding 8a
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        for a, b in ((NOW - minutes(50), NOW - minutes(40)), (NOW - minutes(40), NOW - minutes(30))):
            ingest_state.record_gap(conn, IngestSource.TRAFFIC, a, b, "failed", "x", NOW)
    fake_fill.answer = lambda s, e, m: [raw_flow(5, NOW - minutes(45), NOW - minutes(35))]
    q = _flows(ctx, NOW - minutes(60), NOW, fill=True)
    assert len(q.rows) == 1


def test_stored_half_of_a_filled_pair_is_not_counted_twice(tmp_path, fake_fill):  # finding 8b
    ctx = configured_ctx(tmp_path)
    out, inn = _pair()
    fake_fill.answer = lambda s, e, m: [out]
    run_traffic_cycle(ctx, now=NOW)  # stores the outbound half
    with ctx.flows().connect() as conn:
        ingest_state.record_gap(conn, IngestSource.TRAFFIC, NOW - minutes(35), NOW - minutes(25), "failed", "x", NOW)
    fake_fill.answer = lambda s, e, m: [out, inn]
    q = _flows(ctx, NOW - minutes(60), NOW, fill=True)
    assert len(q.rows) == 1
