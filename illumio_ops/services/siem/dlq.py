"""The SIEM DLQ (spec §6.5 SIEM 轉送: DLQ 檢視、重送、清除、匯出, P7). A resend sends the stored line itself — the
source row may be gone — to its destination as it is configured now; a line that goes through leaves the DLQ, one
that fails again stays with the new error. Bounded: one resend handles at most RESEND_MAX lines."""
from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

from loguru import logger
from pydantic import BaseModel

from illumio_ops.services.context import AppContext
from illumio_ops.services.siem.dispatch import TransportFactory, sent_as
from illumio_ops.siem.transports.factory import transport_for
from illumio_ops.store import siem as store

RESEND_MAX = 1_000
EXPORT_PAGE = 1_000


class ResendResult(BaseModel):
    sent: int
    failed: int
    skipped: int        # its destination is gone or turned off
    changed: int        # its destination changed since (masking, host, port, format): not resent, purge or keep
    remaining: int      # still in the DLQ (of the destination asked, or all)
    error: str | None


def resend(ctx: AppContext, *, ids: Sequence[int] | None, destination_id: str | None,
           transport_factory: TransportFactory | None = None) -> ResendResult:
    """ids: those lines; None: the oldest RESEND_MAX of the destination (or of every destination)."""
    with ctx.db() as conn:
        dead = store.dlq_by_ids(conn, list(ids)) if ids is not None else store.dlq_after(
            conn, destination_id=destination_id, after_id=0, limit=RESEND_MAX)
    dead = dead[:RESEND_MAX]
    dests = {d.id: d for d in ctx.settings.current().siem.destinations if d.enabled}
    sent = failed = skipped = changed = 0
    last_error: str | None = None
    by_dest: dict[str, list[store.DeadLetter]] = {}
    for d in dead:
        by_dest.setdefault(d.destination_id, []).append(d)
    for dest_id, letters in by_dest.items():
        dest = dests.get(dest_id)
        if dest is None:
            skipped += len(letters)
            continue
        made_for = sent_as(dest)
        stale = [d for d in letters if d.sent_as != made_for]
        changed += len(stale)
        letters = [d for d in letters if d.sent_as == made_for]
        if not letters:
            continue
        ok: list[int] = []
        transport = (transport_factory or transport_for)(dest)
        try:
            for d in letters:
                try:
                    transport.send_record(d.payload, d.event_time.timestamp() if d.event_time else None)
                    ok.append(d.id)
                except Exception as exc:  # noqa: BLE001 — kept in the DLQ with the new error
                    last_error = str(exc) or type(exc).__name__
                    with ctx.db() as conn:
                        store.dlq_failed_again(conn, d.id, last_error)
                    failed += 1
            if ok:
                try:
                    transport.finish_batch()
                except OSError as exc:  # not confirmed: they stay, to be resent again
                    last_error = f"delivery_unconfirmed: {exc}"
                    failed += len(ok)
                    ok = []
        finally:
            try:
                transport.close()
            except Exception as exc:  # noqa: BLE001 — closing a connection that already failed
                logger.debug("SIEM DLQ resend close: {}", exc)
        with ctx.db() as conn:
            store.dlq_delete(conn, ok)
        sent += len(ok)
    with ctx.db() as conn:
        remaining = store.dlq_count(conn, destination_id)
    return ResendResult(sent=sent, failed=failed, skipped=skipped, changed=changed, remaining=remaining,
                        error=last_error)


def purge(ctx: AppContext, *, ids: Sequence[int] | None, destination_id: str | None) -> int:
    with ctx.db() as conn:
        return store.dlq_delete(conn, list(ids)) if ids is not None else store.dlq_purge(conn, destination_id)


def export_lines(ctx: AppContext, *, destination_id: str | None) -> Iterator[str]:
    """The DLQ as JSON lines, oldest first, a page at a time (a full DLQ of 20 destinations is 200,000 lines). The
    lines are what was formatted for the SIEM: they carry no destination secret."""
    names = {d.id: d.name for d in ctx.settings.current().siem.destinations}
    after = 0
    while True:
        with ctx.db() as conn:
            page = store.dlq_after(conn, destination_id=destination_id, after_id=after, limit=EXPORT_PAGE)
        if not page:
            return
        for d in page:
            yield json.dumps({"id": d.id, "destination": names.get(d.destination_id, d.destination_id),
                              "source": d.source, "external_id": d.external_id,
                              "event_time": d.event_time.isoformat() if d.event_time else None, "error": d.error,
                              "attempts": d.attempts, "quarantined_at": d.quarantined_at.isoformat(),
                              "payload": d.payload}, ensure_ascii=False) + "\n"
        after = page[-1].id


def export_name(now: datetime | None = None) -> str:
    return f"siem-dlq-{(now or datetime.now(UTC)).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
