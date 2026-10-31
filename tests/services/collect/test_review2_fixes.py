"""Regression tests for the second adversarial review (Tasks 7-11): each one failed before its fix."""
import gzip
import threading
import time
from datetime import datetime, timedelta

import pytest
import responses
from pydantic import ValidationError

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.filter import FilterSpec, matches
from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.events import EventsPage
from illumio_ops.services import flowsource
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.archive import run_archive
from illumio_ops.services.collect.backfill import ensure_initial_backfill, run_backfill
from illumio_ops.services.collect.inventory import run_inventory_cycle
from illumio_ops.services.collect.reset import reset_for_new_pce
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.services.eventsource import query_events
from illumio_ops.services.flowsource import query_flows
from illumio_ops.settings.schema import CollectionSettings, default_collection
from illumio_ops.store.flowdb import archive, binding, ingest_state, ransomware
from illumio_ops.store.flowdb.db import db_day
from illumio_ops.store.flowdb.events import upsert_events
from illumio_ops.store.flowdb.flows import upsert_flows

from .conftest import NOW, configured_ctx, minutes, raw_flow
from .test_inventory import SUMMARY, WL, _details, _workload

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


# ── Group B: backfill ───────────────────────────────────────────────────────

def _starts(calls):
    return [datetime.fromisoformat(s) for s, _ in calls]


def test_initial_backfill_keeps_its_start_after_a_first_day_failure(tmp_path, fake_fill):  # finding 13
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    fake_fill.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    ensure_initial_backfill(ctx, now=NOW)
    fake_fill.answer = lambda s, e, m: []
    run_traffic_cycle(ctx, now=NOW + minutes(10))  # the live watermark moves on
    fake_fill.calls.clear()
    ensure_initial_backfill(ctx, now=NOW + minutes(10))
    assert _starts(fake_fill.calls)[0] == NOW - 30 * DAY


def test_backfill_failure_and_retry_resolve_both_sources(tmp_path, fake_fill):  # finding 14
    ctx = configured_ctx(tmp_path)
    window = (NOW - 3 * DAY, NOW - 2 * DAY)
    fake_fill.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    run_backfill(ctx, start=window[0], end=window[1], now=NOW)
    with ctx.flows().connect() as conn:
        assert {g.source for g in ingest_state.open_gaps(conn)} == {"traffic", "events"}
    fake_fill.answer = lambda s, e, m: []
    run_backfill(ctx, start=window[0], end=window[1], now=NOW)
    with ctx.flows().connect() as conn:
        assert ingest_state.open_gaps(conn) == []
    assert _gaps(_flows(ctx, *window)) == []


def test_manual_backfill_does_not_abandon_an_unfinished_initial_one(tmp_path, fake_fill):
    ctx = configured_ctx(tmp_path, backfill_days=3)
    run_traffic_cycle(ctx, now=NOW)
    seen = []
    def answer(s, e, m):
        seen.append(s)
        if len(seen) == 2:
            raise PceQueryError("timeout")
        return []
    fake_fill.answer = answer
    ensure_initial_backfill(ctx, now=NOW)  # day 1 done, day 2 fails
    fake_fill.answer = lambda s, e, m: []
    run_backfill(ctx, start=NOW - 10 * DAY, end=NOW - 9 * DAY, now=NOW)  # someone backfills by hand
    fake_fill.calls.clear()
    ensure_initial_backfill(ctx, now=NOW)
    assert fake_fill.calls and _starts(fake_fill.calls)[0] == seen[1]  # resumes where it stopped


# ── Group C: archive and retention ──────────────────────────────────────────

def _archiving(ctx, *, archive_days=0):
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"]["archive"].update(
        {"enabled": True, "retention_days": archive_days}))


def _store(ctx, records):
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [normalize_flow(r) for r in records], origin=DataOrigin.BACKFILL, now=NOW)


def _count(ctx, table="flows"):
    with ctx.flows().connect() as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_retention_keeps_a_pair_until_every_day_of_it_is_archived(tmp_path):  # finding 9
    ctx = configured_ctx(tmp_path)
    _archiving(ctx)
    midnight = (NOW - 40 * DAY).replace(hour=0, minute=0)
    out = raw_flow(1, midnight - minutes(10), midnight - minutes(1))  # day D1, 23:59
    inn = raw_flow(1, midnight + minutes(1), midnight + minutes(5), direction="inbound")  # day D2, 00:05
    _store(ctx, [inn])
    with ctx.flows().connect() as conn:
        archive.record(conn, "flows", db_day(midnight), 1, "x", NOW)  # D2 archived before D1's half arrived
    _store(ctx, [out])
    assert run_retention(ctx, now=NOW)["flows"] == 0 and _count(ctx) == 2


def test_rows_added_to_an_archived_day_are_archived_again(tmp_path):  # finding 15
    ctx = configured_ctx(tmp_path)
    _archiving(ctx)
    day = NOW - 40 * DAY
    _store(ctx, [raw_flow(1, day, day + minutes(1))])
    assert run_archive(ctx, now=NOW) == 1
    _store(ctx, [raw_flow(2, day, day + minutes(1))])  # a backfill adds to the archived day
    assert run_retention(ctx, now=NOW)["flows"] == 0 and _count(ctx) == 2  # not archived yet: kept
    assert run_archive(ctx, now=NOW) == 1
    with gzip.open(ctx.paths.archive_dir / f"flows-{db_day(day)}.jsonl.gz", "rt") as fh:
        assert len(fh.readlines()) == 2
    assert run_retention(ctx, now=NOW)["flows"] == 2 and _count(ctx) == 0


def test_events_added_to_an_archived_day_are_archived_again(tmp_path):  # finding 15, events
    ctx = configured_ctx(tmp_path)
    _archiving(ctx)
    day = NOW - 100 * DAY
    def event(i):
        return normalize_event({"href": f"/orgs/1/events/{i}", "event_type": "user.sign_in",
                                "timestamp": day.strftime("%Y-%m-%dT%H:%M:%SZ")})
    with ctx.flows().connect() as conn:
        upsert_events(conn, [event(1)], origin=DataOrigin.INGEST, now=NOW)
    run_archive(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        upsert_events(conn, [event(1), event(2)], origin=DataOrigin.BACKFILL, now=NOW)
    assert run_retention(ctx, now=NOW)["events"] == 0
    run_archive(ctx, now=NOW)
    assert run_retention(ctx, now=NOW)["events"] == 2


@pytest.mark.parametrize(("archive_days", "ok"), [(0, True), (7, False), (89, False), (90, True), (400, True)])
def test_archive_files_must_outlive_the_raw_data(archive_days, ok):  # finding 16
    c = default_collection().model_dump()
    c["archive"] = {"enabled": True, "retention_days": archive_days}  # flows 35, events 90 days
    if ok:
        CollectionSettings.model_validate(c)
    else:
        with pytest.raises(ValidationError, match="archive"):
            CollectionSettings.model_validate(c)


# ── Group D: inventory and ransomware protection ────────────────────────────

def _service(name, state):
    return {"name": name, "port": 445 if name == "SMB" else 3389, "proto": 6, "severity": "critical",
            "protection_state": state, "port_status": "listening"}


def test_a_days_snapshot_is_one_consistent_state(tmp_path):  # finding 10
    ctx = configured_ctx(tmp_path)
    day = db_day(NOW)
    with ctx.flows().connect() as conn:
        ransomware.upsert_services(conn, "/w/1", [_service("SMB", "unprotected")], source_updated_at="a", at=NOW)
        ransomware.write_org_summary(conn, day, {"score": 1})
        ransomware.snapshot_day(conn, day)
        ransomware.upsert_services(conn, "/w/1", [_service("RDP", "protected")], source_updated_at="b", at=NOW)
        ransomware.snapshot_day(conn, day)
        names = [r[0] for r in conn.execute("SELECT name FROM ransomware_snapshot_daily WHERE day = ?", (day,))]
    assert names == ["RDP"]  # the state at the last snapshot of the day, never a mix of two


@responses.activate
def test_org_summary_error_marks_ransomware_failed(tmp_path):  # finding 11
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, status=500)
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(1))
    run_inventory_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        risk = ingest_state.get(conn, IngestSource.RANSOMWARE)
        inv = ingest_state.get(conn, IngestSource.INVENTORY)
    assert risk.consecutive_failures == 1 and "500" in risk.last_error and risk.last_ok_at is None
    assert inv.consecutive_failures == 0 and inv.last_ok_at == NOW


@responses.activate
def test_unreadable_org_summary_does_not_fail_the_inventory(tmp_path):  # finding 11
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, body=b"<html>", content_type="text/html")
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=_details(1))
    run_inventory_cycle(ctx, now=NOW)
    with ctx.flows().connect() as conn:
        risk = ingest_state.get(conn, IngestSource.RANSOMWARE)
        inv = ingest_state.get(conn, IngestSource.INVENTORY)
        snapped = conn.execute("SELECT count(*) FROM workload_snapshot_daily").fetchone()[0]
    assert risk.consecutive_failures == 1 and inv.consecutive_failures == 0 and snapped == 1


@responses.activate
def test_empty_risk_details_are_not_fetched_again(tmp_path):  # finding 12
    ctx = configured_ctx(tmp_path)
    responses.add(responses.GET, WL, json=[_workload(1)])
    responses.add(responses.GET, SUMMARY, json={"ransomware": {}})
    empty = {"risk_details": {"ransomware": {"last_updated_at": "2026-10-24T08:49:37Z", "details": []}}}
    responses.add(responses.GET, f"{WL}/w-1/risk_details", json=empty)
    run_inventory_cycle(ctx, now=NOW)
    run_inventory_cycle(ctx, now=NOW + HOUR)
    assert len([c for c in responses.calls if c.request.url.endswith("/risk_details")]) == 1


# ── Group E: switching PCE while work is in flight ──────────────────────────

def _switch_to_b(ctx):
    ctx.settings.update(ctx.settings.current().revision,
                        lambda d: d["pce"].update({"url": "https://pce-b.example.com:8443"}))
    reset_for_new_pce(ctx, now=NOW)


def _bound_host(ctx):
    with ctx.flows().connect() as conn:
        b = binding.current(conn)
    return b.pce_url if b else None


def test_collector_running_across_a_pce_switch_writes_nothing(tmp_path, fake_fill):  # finding 17
    ctx = configured_ctx(tmp_path)
    def answer(s, e, m):
        _switch_to_b(ctx)  # the switch lands while A's query is in flight
        return [raw_flow(1, NOW - minutes(30), NOW - minutes(20))]
    fake_fill.answer = answer
    run_traffic_cycle(ctx, now=NOW)
    assert _count(ctx) == 0 and _bound_host(ctx) is None
    with ctx.flows().connect() as conn:
        assert ingest_state.all_states(conn) == {} and ingest_state.open_gaps(conn) == []
    fake_fill.answer = lambda s, e, m: [raw_flow(2, NOW - minutes(30), NOW - minutes(20))]
    run_traffic_cycle(ctx, now=NOW + minutes(10))  # B collects normally
    assert _count(ctx) == 1 and "pce-b" in _bound_host(ctx)


def test_archive_running_across_a_pce_switch_writes_nothing(tmp_path, monkeypatch):  # finding 18
    from illumio_ops.services.collect import archive as archive_job
    ctx = configured_ctx(tmp_path)
    _archiving(ctx)
    day = NOW - 3 * DAY
    _store(ctx, [raw_flow(1, day, day + minutes(1))])
    real = archive_job.archive.archived_days
    fdb = ctx.flows()
    switch = threading.Thread(target=lambda: _switch_to_b(ctx))
    def switch_then_list(conn, kind):
        if kind == "flows":  # A's day list is in hand; the switch waits for this read, then B's database
            gen = fdb.generation
            switch.start()
            while fdb.generation == gen:
                time.sleep(0.01)
        return real(conn, kind)
    monkeypatch.setattr(archive_job.archive, "archived_days", switch_then_list)
    assert run_archive(ctx, now=NOW) == 0
    switch.join(10)
    assert not switch.is_alive()
    assert [p.name for p in ctx.paths.archive_dir.iterdir() if p.is_file()] == []
    assert _count(ctx, "archive_log") == 0


# ── Group F: filter bounds ──────────────────────────────────────────────────

@pytest.mark.parametrize("bound", ["start", "end"])
def test_sub_millisecond_bounds_agree_between_store_and_predicate(tmp_path, fake_fill, bound):  # finding 7
    ctx = configured_ctx(tmp_path)
    t = NOW - minutes(30)
    fake_fill.answer = lambda s, e, m: [raw_flow(1, t, t)]
    run_traffic_cycle(ctx, now=NOW)
    us = timedelta(microseconds=1)
    spec = (FilterSpec(start=t + us, end=t + minutes(1)) if bound == "start"
            else FilterSpec(start=t - minutes(1), end=t - us))
    in_store = len(query_flows(ctx, spec, limit=10, order="last_detected_desc", now=NOW).rows) == 1
    assert in_store is matches(spec, normalize_flow(raw_flow(1, t, t))) is False
