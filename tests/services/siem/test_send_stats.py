"""What each destination sent and failed over the last hour, 24 hours and 7 days (5.x status page parity; UI redesign
spec §4.8 "sent in the last 24 hours"), and a full DLQ: the destination is held where it is, never silently, and
nothing is sent twice while it waits."""
import json
from datetime import timedelta

from illumio_ops.services.siem import dlq
from illumio_ops.services.siem.dispatch import run_siem, sent_as
from illumio_ops.services.siem.status import siem_status
from illumio_ops.settings.schema import SiemDestination
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


def run(ctx, transport, now=NOW):
    return run_siem(ctx, now=now, transport_factory=lambda d: transport)


def counts(ctx, now=NOW):
    [d] = siem_status(ctx, now=now).destinations
    return d


def sent_ids(transport):
    return [json.loads(line)["pce_event_id"].rsplit("e", 1)[1] for line in transport.lines]


def test_sent_lines_are_counted_in_each_window(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, range(1, 6))
    run(ctx, FakeTransport())
    d = counts(ctx)
    assert (d.last_hour.sent, d.last_24h.sent, d.last_7d.sent) == (5, 5, 5)
    assert (d.last_hour.failed, d.last_24h.failed, d.last_7d.failed) == (0, 0, 0)
    assert d.success_rate_1h == 100.0


def test_older_sends_fall_out_of_the_shorter_windows(ctx):
    run(ctx, FakeTransport())
    with ctx.db() as conn:
        store.record_sends(conn, DEST, NOW - timedelta(days=3), sent=7)
        store.record_sends(conn, DEST, NOW - timedelta(hours=5), sent=2, failed=1)
        store.record_sends(conn, DEST, NOW - timedelta(days=9), sent=100)  # past the 7 days
    d = counts(ctx)
    assert (d.last_hour.sent, d.last_24h.sent, d.last_7d.sent) == (0, 2, 9)
    assert (d.last_24h.failed, d.last_7d.failed) == (1, 1)
    assert d.success_rate_1h is None  # nothing tried in the last hour: unknown, not a 100 %


def test_a_destination_that_is_down_counts_a_failure_each_run(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2])
    for i in range(2):
        run(ctx, FakeTransport(lambda n, line: REFUSED), now=NOW + timedelta(minutes=i))
    run(ctx, FakeTransport(), now=NOW + timedelta(minutes=2))
    d = counts(ctx, NOW + timedelta(minutes=3))
    assert (d.last_hour.sent, d.last_hour.failed) == (2, 2)
    assert d.success_rate_1h == 50.0


def test_a_refused_record_counts_as_failed(ctx):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2, 3])
    run(ctx, FakeTransport(lambda n, line: http_error(400) if "events/e2" in line else None))
    d = counts(ctx)
    assert (d.last_hour.sent, d.last_hour.failed) == (2, 1)


def test_a_dlq_resend_counts_what_went_and_what_failed_again(ctx):
    made = sent_as(SiemDestination.model_validate(destination()))
    with ctx.db() as conn:
        for i in range(3):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=i, external_id=f"audit:{i}",
                             event_time=NOW, payload=f"line {i}", sent_as=made, error="refused: 400", attempts=1,
                             at=NOW)
    t = FakeTransport(lambda n, line: REFUSED if line == "line 1" else None)
    dlq.resend(ctx, ids=None, destination_id=DEST, transport_factory=lambda d: t, now=NOW)
    d = counts(ctx)
    assert (d.last_hour.sent, d.last_hour.failed) == (2, 1)


def test_the_counts_of_one_destination_are_its_own(ctx):
    other = "e" * 32
    configure(ctx, destination(), destination(id=other, name="splunk"))
    with ctx.db() as conn:
        store.record_sends(conn, other, NOW, sent=4)
    by_name = {d.name: d for d in siem_status(ctx, now=NOW).destinations}
    assert by_name["splunk"].last_24h.sent == 4 and by_name["graylog"].last_24h.sent == 0


def fill_dlq(ctx, n=100):
    with ctx.db() as conn:
        for i in range(n):
            store.quarantine(conn, destination_id=DEST, source="audit", record_id=-i, external_id=f"x:{i}",
                             event_time=None, payload="p", sent_as="[]", error="e", attempts=1, at=NOW)


def test_a_full_dlq_holds_a_failing_record_without_sending_the_next_again_and_again(ctx):
    # e1 fails every time while e2 would go through: past max_retries the probe would tell them apart, but with no
    # room in the DLQ the cursor cannot move past e1 — sending e2 each run only to send it again later is a duplicate
    # per run.
    configure(ctx, destination(), dlq_max_per_dest=100)
    run(ctx, FakeTransport())
    fill_dlq(ctx)
    add_events(ctx, [1, 2])
    t = FakeTransport(lambda n, line: REFUSED if "events/e1" in line else None)
    for i in range(6):  # max_retries = 3
        r = run(ctx, t, now=NOW + timedelta(minutes=i)).destinations["graylog"]["audit"]
    assert t.lines == [] and r.dlq_full and r.error == "dlq_full"
    [s] = counts(ctx, NOW + timedelta(minutes=6)).sources
    assert s.state == "dlq_full" and s.pending == 2  # held, and said so
    with ctx.db() as conn:
        store.dlq_purge(conn, DEST)
    run(ctx, t, now=NOW + timedelta(minutes=7))
    assert sent_ids(t) == ["2"]  # room again: e1 goes to the DLQ, e2 is sent once
    with ctx.db() as conn:
        assert [d.external_id for d in store.dlq_page(conn, destination_id=DEST, limit=5, offset=0)] == ["audit:1"]


def test_a_full_dlq_holding_a_refused_record_is_reported_on_its_source(ctx):
    configure(ctx, destination(), dlq_max_per_dest=100)
    run(ctx, FakeTransport())
    fill_dlq(ctx)
    add_events(ctx, [1, 2])
    run(ctx, FakeTransport(lambda n, line: http_error(400) if "events/e1" in line else None))
    [s] = counts(ctx).sources
    assert s.state == "dlq_full" and s.pending == 2 and s.last_error == "dlq_full"
