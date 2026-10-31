"""The SIEM dispatcher (P7 Task 5): cursors, failures, the DLQ, PCE switches, the time budget."""
import json
from datetime import timedelta

from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.collect.reset import reset_for_new_pce
from illumio_ops.services.siem import dispatch
from illumio_ops.services.siem.dispatch import run_siem
from illumio_ops.store import siem as store

from .conftest import (
    DEST,
    NOW,
    REFUSED,
    FakeTransport,
    add_events,
    configure,
    destination,
    http_error,
)


def run(ctx, transport, **kw):
    return run_siem(ctx, now=NOW, transport_factory=lambda d: transport, **kw)


def sent_ids(transport):
    return [json.loads(line)["pce_event_id"].rsplit("e", 1)[1] for line in transport.lines]


def test_a_new_destination_starts_after_what_is_stored(ctx):
    add_events(ctx, range(5))
    t = FakeTransport()
    assert run(ctx, t).destinations["graylog"]["audit"].started
    assert t.lines == []  # 90 days of history is not poured into the SIEM (spec §7)
    add_events(ctx, [5, 6])
    run(ctx, t)
    assert sent_ids(t) == ["5", "6"]


def test_backfilled_events_are_not_sent(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1], origin=DataOrigin.BACKFILL)
    add_events(ctx, [2])
    t = FakeTransport()
    run(ctx, t)
    assert sent_ids(t) == ["2"]


def test_an_unreachable_destination_keeps_its_place_and_charges_only_the_head(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, range(1, 6))
    t = FakeTransport(lambda n, line: REFUSED)
    r = run(ctx, t).destinations["graylog"]["audit"]
    assert r.unreachable and t.attempts == 1  # the rest of the batch is not tried
    with ctx.db() as conn:
        cur = store.get_cursor(conn, DEST, "audit")
    assert cur.head_attempts == 1 and cur.last_error
    ok = FakeTransport()
    run(ctx, ok)
    assert sent_ids(ok) == ["1", "2", "3", "4", "5"]


def test_a_record_that_always_fails_goes_to_the_dlq_after_max_retries(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2, 3])
    poison = FakeTransport(lambda n, line: REFUSED if "events/e2" in line else None)
    for _ in range(3):  # max_retries = 3: on the third, the next record goes through, so e2 is what fails
        run(ctx, poison)
    assert sent_ids(poison) == ["1", "3"]
    with ctx.db() as conn:
        [dead] = store.dlq_page(conn, destination_id=DEST, limit=10, offset=0)
        assert store.get_cursor(conn, DEST, "audit").head_attempts == 0
    assert dead.external_id == "audit:2" and dead.attempts == 3 and "events/e2" in dead.payload
    run(ctx, poison)
    assert sent_ids(poison) == ["1", "3"]


def test_a_refused_record_goes_to_the_dlq_and_the_batch_goes_on(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2, 3])
    t = FakeTransport(lambda n, line: http_error(400) if "events/e2" in line else None)
    r = run(ctx, t).destinations["graylog"]["audit"]
    assert sent_ids(t) == ["1", "3"] and r.quarantined == 1 and not r.unreachable


def test_rate_limits_and_timeouts_are_retried_not_refused(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1])
    t = FakeTransport(lambda n, line: http_error(429))
    assert run(ctx, t).destinations["graylog"]["audit"].unreachable
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 0


def test_a_full_dlq_stops_the_destination_where_it_is(ctx):
    configure(ctx, destination(), dlq_max_per_dest=100)
    run(ctx, FakeTransport())
    with ctx.db() as conn:
        for i in range(100):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=-i, external_id=f"x:{i}",
                             event_time=None, payload="p", sent_as="[]", error="e", attempts=1, at=NOW)
    add_events(ctx, [1, 2])
    t = FakeTransport(lambda n, line: http_error(400) if "events/e1" in line else None)
    r = run(ctx, t).destinations["graylog"]["audit"]
    assert r.dlq_full and t.lines == []
    with ctx.db() as conn:
        assert store.get_cursor(conn, DEST, "audit").last_id < 1 + 1000  # did not move past e1
    with ctx.db() as conn:
        store.dlq_purge(conn, DEST)
    run(ctx, t)
    assert sent_ids(t) == ["2"]


def test_an_unconfirmed_batch_is_sent_again(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2])
    run(ctx, FakeTransport(unconfirmed=True))
    t = FakeTransport()
    run(ctx, t)
    assert sent_ids(t) == ["1", "2"]  # at least once


def test_after_a_pce_switch_the_first_new_event_is_sent(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, range(1, 50))
    run(ctx, FakeTransport())
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update({"url": "https://other.test:8443"}))
    reset_for_new_pce(ctx, now=NOW)  # the flow store is recreated: event ids start again at 1
    t = FakeTransport()
    run(ctx, t)  # starts after what the new store holds (nothing)
    add_events(ctx, [100])
    run(ctx, t)
    assert sent_ids(t) == ["100"]


def test_the_time_budget_ends_the_run(ctx):
    configure(ctx, destination(batch_size=1))
    run(ctx, FakeTransport())
    add_events(ctx, range(1, 11))
    ticks = iter(range(100))
    t = FakeTransport()
    run_siem(ctx, now=NOW, transport_factory=lambda d: t, budget_seconds=3, clock=lambda: next(ticks))
    assert 0 < len(t.lines) < 10


def test_no_flow_store_connection_is_open_while_sending(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2])
    fdb = ctx.flows()
    seen = []

    def check(n, line):
        seen.append(sum(1 for c in fdb._open if not c.closed))
    run(ctx, FakeTransport(check))
    assert seen == [0, 0]


def test_a_disabled_destination_or_siem_off_sends_nothing(ctx):
    configure(ctx, destination(enabled=False))
    add_events(ctx, [1])
    assert run(ctx, FakeTransport()).destinations == {}
    configure(ctx, destination(), enabled=False)
    assert run(ctx, FakeTransport()).destinations == {}


def test_one_run_at_a_time(ctx):
    assert dispatch._RUN_LOCK.acquire(blocking=False)
    try:
        assert run(ctx, FakeTransport()).skipped
    finally:
        dispatch._RUN_LOCK.release()


def test_masked_destination_sends_no_admin_email(ctx):
    configure(ctx, destination(mask_pii=True))
    run(ctx, FakeTransport())
    add_events(ctx, [1])
    t = FakeTransport()
    run(ctx, t)
    assert "admin@lab.local" not in t.lines[0] and "[REDACTED]" in t.lines[0]


def test_retention_counts_what_it_deletes_before_a_destination_sent_it(ctx):
    from illumio_ops.services.collect.retention import run_retention
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2, 3])
    run_retention(ctx, now=NOW + timedelta(days=400))  # every event older than event_days
    with ctx.db() as conn:
        assert store.get_cursor(conn, DEST, "audit").dropped == 3


def test_a_destination_down_for_long_moves_nothing_to_the_dlq(ctx):
    """Every record fails: the destination is down, not a record — nothing trickles into the DLQ however long it is
    down (5.x moved the head record there every max_retries ticks)."""
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2, 3])
    down = FakeTransport(lambda n, line: REFUSED)
    for _ in range(12):
        run(ctx, down)
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 0
        assert store.get_cursor(conn, DEST, "audit").last_id < 1 + 1000
    up = FakeTransport()
    run(ctx, up)
    assert sent_ids(up) == ["1", "2", "3"]


def test_a_lone_record_that_always_fails_still_reaches_the_dlq(ctx):
    """Nothing after it to probe with, but the destination took a record within the hour: after STUCK_FACTOR ×
    max_retries attempts it goes anyway, so one record cannot hold a destination forever (P7 security review)."""
    from illumio_ops.services.siem.dispatch import STUCK_FACTOR
    from illumio_ops.services.siem.status import siem_status
    run(ctx, FakeTransport())
    add_events(ctx, [0])
    run(ctx, FakeTransport())  # the destination is up: it took e0
    add_events(ctx, [1])
    bad = FakeTransport(lambda n, line: REFUSED)
    for _ in range(3 * STUCK_FACTOR - 1):
        run(ctx, bad)
    src = siem_status(ctx).destinations[0].sources[0]
    assert src.state == "failing" and src.head_attempts == 3 * STUCK_FACTOR - 1
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 0
    run(ctx, bad)
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 1


def test_a_lone_record_waits_while_the_destination_has_sent_nothing_lately(ctx):
    """No later record and no recent success: it may as well be an outage — nothing goes to the DLQ."""
    from illumio_ops.services.siem.dispatch import STUCK_FACTOR
    run(ctx, FakeTransport())
    add_events(ctx, [1])
    bad = FakeTransport(lambda n, line: REFUSED)
    for _ in range(3 * STUCK_FACTOR + 5):
        run(ctx, bad)
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 0
