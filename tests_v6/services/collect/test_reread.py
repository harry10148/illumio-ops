"""Daily re-read (P2 final review F12): once a night, off-peak in the display time zone, the last
settled UTC day is read again hour by hour; only what the store lacks is written, records it finds
late are live data (origin ingest), stored records keep their origin, and a failure never marks
collected windows as failed."""
from datetime import UTC, datetime, timedelta

import pytest

from illumio_ops.domain.timefmt import pce_time
from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect import reread
from illumio_ops.services.collect.backfill import run_backfill
from illumio_ops.services.collect.reread import ensure_daily_reread
from illumio_ops.services.collect.traffic import run_traffic_cycle
from illumio_ops.store.flowdb import ingest_state

from .conftest import configured_ctx, minutes, raw_flow

RUN = datetime(2026, 10, 24, 19, 10, tzinfo=UTC)  # 03:10 on 10/25 in Taipei
DAY = datetime(2026, 10, 23, tzinfo=UTC)          # the last UTC day that ended 6 h before RUN
HOUR = timedelta(hours=1)


class FakeEvents:
    def __init__(self):
        self.calls = []
        self.items = []

    def __call__(self, client, *, start, end, timeout, deadline, max_results=10000):
        self.calls.append((start, end))
        return EventsPage(items=[e for e in self.items if start <= _ts(e) < end], capped=False)


def _ts(e):
    return datetime.fromisoformat(e["timestamp"])


def _event(i, ts):
    return {"href": f"/orgs/1/events/e-{i}", "event_type": "user.sign_in", "timestamp": pce_time(ts),
            "severity": "info", "status": "success", "created_by": {"user": {"href": "/users/1", "username": "u"}}}


@pytest.fixture
def fake_events(monkeypatch):
    fake = FakeEvents()
    monkeypatch.setattr(ev, "fetch_events", fake)
    return fake


def _ctx(tmp_path, **collection):
    ctx = configured_ctx(tmp_path, **collection)
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["display"].update({"timezone": "Asia/Taipei"}))
    return ctx


def _cover(ctx, source, start, end):
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:
        ingest_state.add_coverage(conn, source, start, end)


def _serve(fake_traffic, rows):
    def first(r):
        return datetime.fromisoformat(r["timestamp_range"]["first_detected"])
    fake_traffic.answer = lambda s, e, m: [r for r in rows if s <= first(r) < e]


def _flows(ctx):
    with ctx.flows().connect() as conn:
        return {r["src_ip"]: dict(r) for r in conn.execute(
            "SELECT src_ip, origin, num_connections, ingested_at FROM flows")}


def _progress(ctx):
    with ctx.flows().connect() as conn:
        st = ingest_state.get(conn, IngestSource.BACKFILL)
    return st, (st.progress or {}).get("reread") if st else None


def test_waits_for_the_off_peak_hour(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN)
    assert ensure_daily_reread(ctx, now=RUN - minutes(20)) is None  # 02:50 in Taipei
    assert fake_traffic.calls == [] and fake_events.calls == []


def test_rereads_the_last_settled_day_hour_by_hour(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN)
    _cover(ctx, "events", DAY - timedelta(days=1), RUN)
    assert ensure_daily_reread(ctx, now=RUN) is not None
    hours = [(DAY + HOUR * i, DAY + HOUR * (i + 1)) for i in range(24)]
    assert fake_traffic.calls == [(pce_time(a), pce_time(b)) for a, b in hours]
    assert fake_events.calls == hours
    st, mine = _progress(ctx)
    assert mine["day"] == "2026-10-23" and mine["finished"] is True and st.last_error is None


def test_runs_once_per_local_day(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN + timedelta(days=1))
    ensure_daily_reread(ctx, now=RUN)
    fake_traffic.calls.clear()
    assert ensure_daily_reread(ctx, now=RUN + minutes(20)) is None
    assert ensure_daily_reread(ctx, now=RUN + timedelta(hours=10)) is None  # 13:10 on the same local day
    assert fake_traffic.calls == []
    assert ensure_daily_reread(ctx, now=RUN + timedelta(days=1)) is not None  # the next night: the next day
    assert fake_traffic.calls[0][0] == pce_time(DAY + timedelta(days=1))


def test_late_records_are_live_data_and_stored_ones_keep_their_origin(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    in_backfill = raw_flow(1, DAY + minutes(10), DAY + minutes(20))
    grew_in_backfill = raw_flow(4, DAY + minutes(20), DAY + minutes(30))
    live = raw_flow(2, DAY + timedelta(hours=10), DAY + timedelta(hours=10, minutes=5))
    _serve(fake_traffic, [in_backfill, grew_in_backfill])
    run_backfill(ctx, start=DAY, end=DAY + HOUR, now=DAY + HOUR)
    _serve(fake_traffic, [live])
    run_traffic_cycle(ctx, now=DAY + timedelta(hours=12))  # cold start: live coverage from 10/22 12:00
    before = _flows(ctx)
    grown = {**live, "num_connections": 5}
    late = raw_flow(3, DAY + timedelta(hours=15), DAY + timedelta(hours=15, minutes=1))
    _serve(fake_traffic, [in_backfill, {**grew_in_backfill, "num_connections": 3}, grown, late])
    result = ensure_daily_reread(ctx, now=RUN)
    after = _flows(ctx)
    assert result is not None and result.rows == 3  # the two grown records and the late one
    assert after["10.0.1.1"] == before["10.0.1.1"]  # untouched, still backfill
    assert (after["10.0.1.4"]["origin"], after["10.0.1.4"]["num_connections"]) == ("backfill", 3)
    assert (after["10.0.1.2"]["origin"], after["10.0.1.2"]["num_connections"]) == ("ingest", 5)
    assert after["10.0.1.3"]["origin"] == "ingest"


def test_records_already_stored_take_no_write(tmp_path, fake_traffic, fake_events, monkeypatch):
    ctx = _ctx(tmp_path)
    live = raw_flow(2, DAY + timedelta(hours=10), DAY + timedelta(hours=10, minutes=5))
    _serve(fake_traffic, [live])
    run_traffic_cycle(ctx, now=DAY + timedelta(hours=12))
    written = []
    real = reread.upsert_flows
    monkeypatch.setattr(reread, "upsert_flows", lambda conn, records, **kw: (written.append(len(records)),
                                                                              real(conn, records, **kw))[1])
    assert ensure_daily_reread(ctx, now=RUN).rows == 0
    assert sum(written) == 0


def test_resolves_a_failed_live_window(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), DAY + timedelta(hours=5, minutes=50))
    _cover(ctx, "traffic", DAY + timedelta(hours=6, minutes=20), RUN)
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:  # across an hour boundary: no single hour read contains it
        ingest_state.record_gap(conn, "traffic", DAY + timedelta(hours=5, minutes=50),
                                DAY + timedelta(hours=6, minutes=20), "failed", "timeout", RUN - timedelta(hours=20))
    ensure_daily_reread(ctx, now=RUN)
    with ctx.flows().connect() as conn:
        assert ingest_state.open_gaps(conn, "traffic") == []
        assert ingest_state.coverage(conn, "traffic") == [(DAY - timedelta(days=1), RUN)]


def test_a_failure_marks_nothing_failed_and_is_retried_three_times(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN)

    def answer(s, e, m):
        if s >= DAY + 2 * HOUR:
            raise PceQueryError("timeout")
        return []
    fake_traffic.answer = answer
    ensure_daily_reread(ctx, now=RUN)
    st, mine = _progress(ctx)
    assert st.last_error.startswith("re-read") and mine["attempts"] == 1
    assert mine["done_through"] == (DAY + 2 * HOUR).isoformat()
    with ctx.flows().connect() as conn:
        assert ingest_state.open_gaps(conn) == []  # the live windows were collected; nothing is failed
    fake_traffic.calls.clear()
    ensure_daily_reread(ctx, now=RUN + minutes(10))
    assert fake_traffic.calls[0][0] == pce_time(DAY + 2 * HOUR)  # resumed where it stopped
    ensure_daily_reread(ctx, now=RUN + minutes(20))
    fake_traffic.calls.clear()
    assert ensure_daily_reread(ctx, now=RUN + minutes(30)) is None and fake_traffic.calls == []


def test_reads_only_from_where_collection_began(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY + timedelta(hours=12), RUN)
    ensure_daily_reread(ctx, now=RUN)
    assert fake_traffic.calls[0][0] == pce_time(DAY + timedelta(hours=12)) and len(fake_traffic.calls) == 12
    assert fake_events.calls == []  # events were never collected that day


def test_nothing_to_read_when_the_day_was_never_collected(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    assert ensure_daily_reread(ctx, now=RUN) is None
    assert fake_traffic.calls == [] and fake_events.calls == []


def test_waits_for_an_unfinished_initial_backfill(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN)
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:
        ingest_state.set_progress(conn, IngestSource.BACKFILL, {"initial": {"finished": False}})
    assert ensure_daily_reread(ctx, now=RUN) is None and fake_traffic.calls == []


def test_events_only_mode_rereads_events_and_adds_only_new_ones(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path, mode="events_only")
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN)
    _cover(ctx, "events", DAY - timedelta(days=1), RUN)
    fake_events.items = [_event(1, DAY + HOUR)]
    ev.run_events_cycle(ctx, now=DAY + HOUR + minutes(5))
    fake_events.items.append(_event(2, DAY + timedelta(hours=7)))
    fake_events.calls.clear()
    assert ensure_daily_reread(ctx, now=RUN).rows == 1
    assert fake_traffic.calls == [] and len(fake_events.calls) == 24
    with ctx.flows().connect() as conn:
        assert {r[0]: r[1] for r in conn.execute("SELECT href, origin FROM events")} == {
            "/orgs/1/events/e-1": "ingest", "/orgs/1/events/e-2": "ingest"}


def test_refuses_a_store_bound_to_another_pce(tmp_path, fake_traffic, fake_events):
    from illumio_ops.store.flowdb import binding
    ctx = _ctx(tmp_path)
    _cover(ctx, "traffic", DAY - timedelta(days=1), DAY + timedelta(hours=5))
    _cover(ctx, "events", DAY - timedelta(days=1), DAY + timedelta(hours=5))
    with ctx.flows().connect() as conn:
        binding.bind(conn, "https://other-pce.example.com:8443", "7", RUN)
    fake_events.items = [_event(1, DAY + HOUR)]  # no flows: the check must not hang on flow batches
    ensure_daily_reread(ctx, now=RUN)
    st, _ = _progress(ctx)
    with ctx.flows().connect() as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
        assert ingest_state.coverage(conn, "events") == [(DAY - timedelta(days=1), DAY + timedelta(hours=5))]
    assert "binding" in st.last_error


def test_progress_moves_only_with_what_was_stored(tmp_path, fake_traffic, fake_events, monkeypatch):
    # The hour's events and its progress commit together: a write error after the progress was
    # computed must not leave progress past events that were rolled back.
    import sqlite3
    ctx = _ctx(tmp_path)
    _cover(ctx, "events", DAY - timedelta(days=1), RUN)
    fake_events.items = [_event(1, DAY + minutes(10))]
    real = ingest_state.set_progress

    def flaky(conn, source, progress):
        if (progress or {}).get("reread", {}).get("done_through") == (DAY + HOUR).isoformat():
            raise sqlite3.OperationalError("disk I/O error")
        return real(conn, source, progress)
    monkeypatch.setattr(ingest_state, "set_progress", flaky)
    with pytest.raises(sqlite3.OperationalError):
        ensure_daily_reread(ctx, now=RUN)
    monkeypatch.setattr(ingest_state, "set_progress", real)
    _, mine = _progress(ctx)
    assert mine["done_through"] == DAY.isoformat() and mine["attempts"] == 1
    ensure_daily_reread(ctx, now=RUN + minutes(10))
    with ctx.flows().connect() as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_a_source_added_since_the_last_attempt_is_read_from_the_start(tmp_path, fake_traffic, fake_events):
    ctx = _ctx(tmp_path, mode="events_only")
    _cover(ctx, "traffic", DAY - timedelta(days=1), RUN)
    _cover(ctx, "events", DAY - timedelta(days=1), RUN)

    def failing(client, *, start, end, timeout, deadline, max_results=10000):
        if start >= DAY + timedelta(hours=12):
            raise PceQueryError("timeout")
        return EventsPage(items=[], capped=False)
    import illumio_ops.services.collect.events as events_mod
    real = events_mod.fetch_events
    events_mod.fetch_events = failing
    try:
        ensure_daily_reread(ctx, now=RUN)  # events read up to 12:00, then the PCE failed
    finally:
        events_mod.fetch_events = real
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update({"mode": "full"}))
    ensure_daily_reread(ctx, now=RUN + minutes(10))
    assert fake_traffic.calls[0][0] == pce_time(DAY)  # traffic was never re-read: from the day's start
