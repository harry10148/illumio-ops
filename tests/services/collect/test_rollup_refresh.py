"""Daily rollups: past days are rebuilt as soon as they change; today's at most hourly, and the first
cycle of a new day finalises yesterday (P2 Task 14: today's full rebuild was most of every cycle)."""
from datetime import timedelta

from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.backfill import run_backfill
from illumio_ops.services.collect.traffic import run_traffic_cycle

from .conftest import NOW, configured_ctx, minutes, raw_flow

HOUR = timedelta(hours=1)


def _rollup(ctx, day):
    with ctx.flows().connect() as conn:
        return conn.execute("SELECT coalesce(sum(connections), 0) FROM flow_rollup_daily WHERE day = ?",
                            (day,)).fetchone()[0]


def _answer(fake, *flows):
    fake.answer = lambda s, e, m: list(flows)


def test_todays_rollup_is_rebuilt_at_most_hourly(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    today = NOW.strftime("%Y-%m-%d")
    _answer(fake_traffic, raw_flow(1, NOW - minutes(30), NOW - minutes(20)))
    run_traffic_cycle(ctx, now=NOW)
    assert _rollup(ctx, today) == 1  # never built: built now
    _answer(fake_traffic, raw_flow(2, NOW + minutes(1), NOW + minutes(5)))
    run_traffic_cycle(ctx, now=NOW + minutes(10))
    assert _rollup(ctx, today) == 1  # built less than an hour ago
    _answer(fake_traffic, raw_flow(3, NOW + minutes(55), NOW + minutes(58)))
    run_traffic_cycle(ctx, now=NOW + minutes(61))
    assert _rollup(ctx, today) == 3


def test_first_cycle_of_a_new_day_finalises_yesterday(tmp_path, fake_traffic):
    ctx = configured_ctx(tmp_path)
    night = NOW.replace(hour=23, minute=0)
    day = night.strftime("%Y-%m-%d")
    _answer(fake_traffic, raw_flow(1, night - minutes(20), night - minutes(10)))
    run_traffic_cycle(ctx, now=night)
    _answer(fake_traffic, raw_flow(2, night + minutes(40), night + minutes(50)))
    run_traffic_cycle(ctx, now=night + minutes(55))
    assert _rollup(ctx, day) == 1  # today, rebuilt less than an hour ago
    _answer(fake_traffic)  # nothing new after midnight
    run_traffic_cycle(ctx, now=night + minutes(70))
    assert _rollup(ctx, day) == 2  # closed now: final


def test_backfilled_day_is_rolled_up_at_once(tmp_path, fake_traffic, monkeypatch):
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=[], capped=False))
    ctx = configured_ctx(tmp_path)
    past = NOW - timedelta(days=3)
    fake_traffic.answer = lambda s, e, m: [raw_flow(7, s + minutes(5), s + minutes(6))] if s == past else []
    run_backfill(ctx, start=past, end=past + timedelta(days=1), now=NOW)
    assert _rollup(ctx, past.strftime("%Y-%m-%d")) == 1


def _write(ctx, *raws, at=NOW):
    from illumio_ops.domain.flows import normalize_flow
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.flows import upsert_flows
    with ctx.flows().write_lock, ctx.flows().connect() as conn:
        return upsert_flows(conn, [normalize_flow(r) for r in raws], origin=DataOrigin.INGEST, now=at)


def test_a_new_record_touches_only_its_own_day(tmp_path):
    """The same 4-tuple recurs daily; a new record of it must not mark every past day changed
    (that rebuilt 13 rollups per cycle on .106)."""
    ctx = configured_ctx(tmp_path)
    old = NOW - timedelta(days=5)
    _write(ctx, raw_flow(1, old, old + minutes(5)))
    stats = _write(ctx, raw_flow(1, NOW - minutes(30), NOW - minutes(20)))
    assert stats.days_touched == {NOW.strftime("%Y-%m-%d")}


def test_a_pair_across_midnight_touches_both_days(tmp_path):
    ctx = configured_ctx(tmp_path)
    midnight = NOW.replace(hour=0, minute=0)
    _write(ctx, raw_flow(1, midnight - minutes(10), midnight - minutes(1)))  # outbound, day before
    stats = _write(ctx, raw_flow(1, midnight + minutes(1), midnight + minutes(5), direction="inbound"))
    assert stats.paired == 1
    assert stats.days_touched == {(midnight - minutes(1)).strftime("%Y-%m-%d"), midnight.strftime("%Y-%m-%d")}


def test_a_day_retention_has_pruned_keeps_its_rollup_when_touched_again(tmp_path, fake_traffic, monkeypatch):
    # The cutoff day loses its rows before the cutoff time to retention; a backfilled record of the next
    # day that pairs with one of its evening records touched it again, and the rebuild from what was left
    # lowered a rollup that is kept 90 days.
    from illumio_ops.services.collect.retention import run_retention
    from illumio_ops.store.flowdb.flows import refresh_rollups
    ctx = configured_ctx(tmp_path)
    cutoff = NOW - timedelta(days=35)  # flow_days 35: rows of this day before 12:00 expire
    day = cutoff.strftime("%Y-%m-%d")
    morning, evening = cutoff.replace(hour=1), cutoff.replace(hour=23, minute=55)
    _write(ctx, raw_flow(1, morning, morning + minutes(5)), raw_flow(2, evening, evening + minutes(3)))
    with ctx.flows().write_lock, ctx.flows().connect() as conn:
        refresh_rollups(conn, cutoff + timedelta(days=1))
    assert _rollup(ctx, day) == 2
    run_retention(ctx, now=NOW)  # the morning connection goes, the evening one stays
    nxt = (cutoff + timedelta(days=1)).replace(hour=0, minute=1)
    fake_traffic.answer = lambda s, e, m: [raw_flow(2, nxt, nxt + minutes(3), direction="inbound")] if s <= nxt < e else []
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=[], capped=False))
    stats = run_backfill(ctx, start=nxt.replace(minute=0), end=nxt + HOUR, now=NOW)
    with ctx.flows().connect() as conn:
        assert conn.execute("SELECT count(*) FROM flows WHERE is_primary = 0").fetchone()[0] == 1  # paired
    assert stats.rows == 1 and _rollup(ctx, day) == 2


def test_a_backfilled_day_past_the_raw_cutoff_gets_its_whole_rollup(tmp_path, fake_traffic, monkeypatch):
    # The backfill writes a day an hour at a time; a live cycle's refresh between two hours built the
    # day from its first hour, and the freeze rule for days past the raw cutoff then kept that build.
    from illumio_ops.store.flowdb.db import db_day
    from illumio_ops.store.flowdb.flows import refresh_rollups
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=[], capped=False))
    ctx = configured_ctx(tmp_path)  # flow_days 35
    day = (NOW - timedelta(days=40)).replace(hour=0)

    def answer(s, e, m):
        if s == day + timedelta(hours=1):  # the first hour is stored; the live collector refreshes now
            fdb = ctx.flows()
            with fdb.writing(fdb.generation) as conn:
                refresh_rollups(conn, NOW, frozen_through=db_day(NOW - timedelta(days=35)))
        return [raw_flow(s.hour, s + minutes(5), s + minutes(6))]
    fake_traffic.answer = answer
    run_backfill(ctx, start=day, end=day + timedelta(days=1), now=NOW)
    assert _rollup(ctx, day.strftime("%Y-%m-%d")) == 24


def test_a_day_past_the_raw_cutoff_resumes_from_its_midnight(tmp_path, fake_traffic, monkeypatch):
    # Between two runs retention may delete the hours already written; the day is read again whole.
    from illumio_ops.pce.async_query import PceQueryError
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=[], capped=False))
    ctx = configured_ctx(tmp_path)  # flow_days 35
    day = (NOW - timedelta(days=40)).replace(hour=0)

    def failing(s, e, m):
        if s >= day + timedelta(hours=5):
            raise PceQueryError("timeout")
        return []
    fake_traffic.answer = failing
    run_backfill(ctx, start=day, end=day + timedelta(days=1), now=NOW)
    fake_traffic.answer = lambda s, e, m: []
    fake_traffic.calls.clear()
    run_backfill(ctx, start=day, end=day + timedelta(days=1), now=NOW)
    assert fake_traffic.calls[0][0] == day.strftime("%Y-%m-%dT%H:%M:%SZ") and len(fake_traffic.calls) == 24
