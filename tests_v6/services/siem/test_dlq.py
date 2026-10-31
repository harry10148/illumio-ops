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
