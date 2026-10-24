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
    fake_traffic.answer = lambda s, e, m: [raw_flow(7, s + minutes(5), s + minutes(6))]
    run_backfill(ctx, start=past, end=past + timedelta(days=1), now=NOW)
    assert _rollup(ctx, past.strftime("%Y-%m-%d")) == 1
