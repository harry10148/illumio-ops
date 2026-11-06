"""The DLQ: resend, purge, export (P7 Task 6)."""
import json

from illumio_ops.services.siem import dlq
from illumio_ops.services.siem.dispatch import sent_as
from illumio_ops.settings.schema import SiemDestination
from illumio_ops.store import siem as store

from .conftest import DEST, NOW, REFUSED, FakeTransport, configure, destination


def fill(ctx, n, dest=DEST, made_for=None):
    made_for = made_for or sent_as(SiemDestination.model_validate(destination()))
    with ctx.db() as conn:
        for i in range(n):
            store.quarantine(conn, destination_id=dest, source="audit", record_id=i, external_id=f"audit:{i}",
                             event_time=NOW, payload=f"line {i}", sent_as=made_for, error="refused: 400", attempts=1,
                             at=NOW)
        return [d.id for d in store.dlq_page(conn, destination_id=dest, limit=100, offset=0)]


def test_a_resent_line_leaves_the_dlq_and_a_failed_one_stays(ctx):
    fill(ctx, 3)
    t = FakeTransport(lambda n, line: REFUSED if line == "line 1" else None)
    r = dlq.resend(ctx, ids=None, destination_id=DEST, transport_factory=lambda d: t)
    assert (r.sent, r.failed, r.remaining) == (2, 1, 1) and t.lines == ["line 0", "line 2"]
    with ctx.db() as conn:
        [left] = store.dlq_page(conn, destination_id=DEST, limit=10, offset=0)
    assert left.payload == "line 1" and left.attempts == 2 and "refused" in left.error.lower()


def test_resend_of_a_removed_destination_is_skipped(ctx):
    fill(ctx, 2, dest="e" * 32)
    r = dlq.resend(ctx, ids=None, destination_id=None, transport_factory=lambda d: FakeTransport())
    assert r.skipped == 2 and r.remaining == 2


def test_an_unconfirmed_resend_keeps_the_lines(ctx):
    ids = fill(ctx, 2)
    r = dlq.resend(ctx, ids=ids, destination_id=None, transport_factory=lambda d: FakeTransport(unconfirmed=True))
    assert r.sent == 0 and r.remaining == 2


def test_purge_selected_or_all(ctx):
    ids = fill(ctx, 3)
    assert dlq.purge(ctx, ids=ids[:1], destination_id=None) == 1
    assert dlq.purge(ctx, ids=None, destination_id=DEST) == 2


def test_export_is_every_line_with_its_payload_and_no_secret(ctx):
    configure(ctx, destination(transport="hec", hec_token="tok-secret"))
    fill(ctx, 1005)
    lines = list(dlq.export_lines(ctx, destination_id=None))
    assert len(lines) == 1005
    first = json.loads(lines[0])
    assert first["destination"] == "graylog" and first["payload"] == "line 0" and first["external_id"] == "audit:0"
    assert not any("tok-secret" in x for x in lines)


def test_a_line_made_before_masking_was_turned_on_is_not_resent(ctx):
    fill(ctx, 2)
    configure(ctx, destination(mask_pii=True))
    t = FakeTransport()
    r = dlq.resend(ctx, ids=None, destination_id=DEST, transport_factory=lambda d: t)
    assert t.lines == [] and r.changed == 2 and r.remaining == 2


def test_a_line_is_not_resent_to_another_host(ctx):
    fill(ctx, 1)
    configure(ctx, destination(host="elsewhere.test"))
    t = FakeTransport()
    assert dlq.resend(ctx, ids=None, destination_id=DEST, transport_factory=lambda d: t).changed == 1
    assert t.lines == []


def quarantine_at(ctx, at, *, error="refused: 400", dest=DEST, payload="line"):
    with ctx.db() as conn:
        store.quarantine(conn, destination_id=dest, source="audit", record_id=1, external_id="audit:1", event_time=at,
                         payload=payload, sent_as="[]", error=error, attempts=1, at=at)


def test_purge_older_than_a_number_of_days(ctx):
    from datetime import timedelta
    quarantine_at(ctx, NOW - timedelta(days=10))
    quarantine_at(ctx, NOW - timedelta(days=2))
    quarantine_at(ctx, NOW - timedelta(days=10), dest="e" * 32)
    assert dlq.purge(ctx, ids=None, destination_id=DEST, older_than_days=5, now=NOW) == 1
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 1 and store.dlq_count(conn, "e" * 32) == 1
    assert dlq.purge(ctx, ids=None, destination_id=None, older_than_days=5, now=NOW) == 1


def test_export_by_error(ctx):
    quarantine_at(ctx, NOW, error="refused: 400 Bad Request")
    quarantine_at(ctx, NOW, error="format: bad value")
    quarantine_at(ctx, NOW, error="refused: 413 100%_full")
    lines = [json.loads(x) for x in dlq.export_lines(ctx, destination_id=None, error="refused")]
    assert [x["error"] for x in lines] == ["refused: 400 Bad Request", "refused: 413 100%_full"]
    # % and _ are matched as written, not as wildcards
    assert len(list(dlq.export_lines(ctx, destination_id=None, error="100%_"))) == 1
    assert list(dlq.export_lines(ctx, destination_id=None, error="4_3")) == []  # as a LIKE pattern: "413"


def test_dlq_retention_deletes_lines_older_than_the_setting_and_old_counts(ctx):
    from datetime import timedelta
    quarantine_at(ctx, NOW - timedelta(days=31))
    quarantine_at(ctx, NOW - timedelta(days=29))
    with ctx.db() as conn:
        store.record_sends(conn, DEST, NOW - timedelta(days=9), sent=3)
        store.record_sends(conn, DEST, NOW - timedelta(days=6), sent=4)
    assert ctx.settings.current().siem.dlq_retention_days == 30  # the default
    assert dlq.run_dlq_retention(ctx, now=NOW) == {"dlq": 1, "sends": 1}
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 1
        assert store.sends_since(conn, NOW - timedelta(days=30))[DEST].sent == 4


def test_dlq_retention_zero_keeps_every_line(ctx):
    from datetime import timedelta
    configure(ctx, destination(), dlq_retention_days=0)
    quarantine_at(ctx, NOW - timedelta(days=400))
    assert dlq.run_dlq_retention(ctx, now=NOW)["dlq"] == 0
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 1


def test_the_retention_job_runs_the_dlq_retention(ctx):
    from datetime import UTC, datetime, timedelta

    from illumio_ops.jobs.scheduler import _collector_jobs
    quarantine_at(ctx, datetime.now(UTC) - timedelta(days=40))
    _collector_jobs(ctx)["collect_retention"]()
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 0
