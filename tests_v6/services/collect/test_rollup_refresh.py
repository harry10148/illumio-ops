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
