"""Backfill: oldest day first, resumable, marked as backfill, seeds the baseline, never moves the
live watermark; the initial backfill runs once per binding."""
from datetime import timedelta

import pytest

from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.backfill import ensure_initial_backfill, run_backfill
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.store.flowdb import ingest_state

from .conftest import NOW, configured_ctx, minutes, raw_flow


@pytest.fixture(autouse=True)
def no_events(monkeypatch):
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=[], capped=False))


def _q(ctx, sql):
    with ctx.flows().connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def test_backfill_oldest_first_and_resumes(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    start = NOW - timedelta(days=3)
    days_seen = []
    def answer(s, e, m):
        days_seen.append(s.date())
        if len(days_seen) == 2:
            raise PceQueryError("timeout")
        return [raw_flow(len(days_seen), s + minutes(1), s + minutes(2))]
    fake_traffic.answer = answer
    first = run_backfill(ctx, start=start, end=NOW, now=NOW)
    assert first.gaps == 1 and days_seen == sorted(days_seen)
    with ctx.flows().connect() as conn:
        progress = ingest_state.get(conn, IngestSource.BACKFILL).progress["manual"]
    assert progress["done_through"] == (start + timedelta(hours=1)).isoformat()  # traffic is read by the hour
    fake_traffic.answer = lambda s, e, m: [raw_flow(9, s + minutes(1), s + minutes(2))]
    calls_before = len(fake_traffic.calls)
    run_backfill(ctx, start=start, end=NOW, now=NOW)
    resumed_from = fake_traffic.calls[calls_before][0]
    assert resumed_from == progress["done_through"].replace("+00:00", "Z").replace(".000", "")
    with ctx.flows().connect() as conn:
        assert ingest_state.get(conn, IngestSource.BACKFILL).progress["manual"]["finished"] is True


def test_backfill_marks_origin_and_seeds_baseline(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    fake_traffic.answer = lambda s, e, m: [raw_flow(1, s + minutes(1), s + minutes(2))]
    run_backfill(ctx, start=NOW - timedelta(days=2), end=NOW - timedelta(days=1), now=NOW)
    assert {r["origin"] for r in _q(ctx, "SELECT origin FROM flows")} == {"backfill"}
    assert len(_q(ctx, "SELECT * FROM connection_baseline")) == 1


def test_backfill_does_not_move_ingest_watermark(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    run_traffic_cycle(ctx, now=NOW)
    run_backfill(ctx, start=NOW - timedelta(days=2), end=NOW - timedelta(days=1), now=NOW + minutes(30))
    with ctx.flows().connect() as conn:
        assert ingest_state.get(conn, IngestSource.TRAFFIC).watermark == NOW


def test_initial_backfill_only_on_fresh_binding(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path, backfill_days=2)
    assert ensure_initial_backfill(ctx, now=NOW) is not None
    n = len(fake_traffic.calls)
    assert n >= 2 and fake_traffic.calls[0][0] == "2026-10-22T12:00:00Z"
    assert ensure_initial_backfill(ctx, now=NOW + timedelta(hours=1)) is None  # finished: never again
    assert len(fake_traffic.calls) == n


def test_initial_backfill_disabled_by_zero_days(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path, backfill_days=0)
    assert ensure_initial_backfill(ctx, now=NOW) is None and fake_traffic.calls == []


def test_unfinished_backfill_is_resumed_by_the_check(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path, backfill_days=2)
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    ensure_initial_backfill(ctx, now=NOW)
    fake_traffic.answer = lambda s, e, m: []
    assert ensure_initial_backfill(ctx, now=NOW + timedelta(minutes=10)) is not None
    with ctx.flows().connect() as conn:
        assert ingest_state.get(conn, IngestSource.BACKFILL).progress["initial"]["finished"] is True


def test_resumed_initial_backfill_reads_only_what_the_mode_now_collects(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path, backfill_days=2)
    fake_traffic.answer = lambda s, e, m: (_ for _ in ()).throw(PceQueryError("timeout"))
    ensure_initial_backfill(ctx, now=NOW)  # full mode: traffic and events, stopped on day 1
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update({"mode": "lightweight"}))
    fake_traffic.calls.clear()
    fake_traffic.answer = lambda s, e, m: []
    ensure_initial_backfill(ctx, now=NOW + timedelta(minutes=10))
    assert fake_traffic.calls == []  # no traffic query in lightweight mode
    with ctx.flows().connect() as conn:
        progress = ingest_state.get(conn, IngestSource.BACKFILL).progress
    assert progress["initial"]["finished"] is True and progress["initial_done"] == ["events"]


def test_backfill_reads_traffic_by_the_hour_and_events_by_the_day(tmp_path, fake_traffic, monkeypatch):
    # A day of traffic at 1,000 workloads is ~6 GB once parsed; events are few, and on SaaS every
    # /events call costs 22-60 s, so they stay one query per day.
    event_calls = []
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: (
        event_calls.append((kw["start"], kw["end"])), EventsPage(items=[], capped=False))[1])
    ctx = configured_ctx(tmp_path)
    day = NOW.replace(hour=0) - timedelta(days=2)
    run_backfill(ctx, start=day, end=day + timedelta(days=1), now=NOW)
    assert len(fake_traffic.calls) == 24 and fake_traffic.calls[1][0] == "2026-10-22T01:00:00Z"
    assert event_calls == [(day, day + timedelta(days=1))]
    with ctx.flows().connect() as conn:
        assert ingest_state.coverage(conn, "traffic") == [(day, day + timedelta(days=1))]
        assert ingest_state.coverage(conn, "events") == [(day, day + timedelta(days=1))]
