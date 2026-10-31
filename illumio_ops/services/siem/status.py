"""What the SIEM page shows for each destination and source (P7): how far behind it is, what it sent last, what
failed, what the DLQ holds, what retention removed first — and, where a source cannot produce anything in the current
collection mode, that it needs alert mode, never "0, normal" (spec §6.4 lightweight table)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from illumio_ops.domain.values import CollectionMode, SiemFormat, SiemTransport
from illumio_ops.services.analysis.context import baseline_full
from illumio_ops.services.context import AppContext
from illumio_ops.services.siem import sources
from illumio_ops.store import siem as store

SourceName = Literal["audit", "alerts", "detections", "new_connections"]
SourceState = Literal["ok", "behind", "failing", "dlq_full", "waiting", "needs_alert_mode", "baseline_building",
                      "off"]
NEEDS_TRAFFIC = ("detections", "new_connections")


class SiemSourceStatus(BaseModel):
    source: SourceName
    state: SourceState
    pending: int | None          # not sent yet (None: not started)
    sent: int
    dropped: int                 # deleted by retention before this destination sent them
    last_sent_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None


class SiemDestinationStatus(BaseModel):
    id: str
    name: str
    enabled: bool
    transport: SiemTransport
    format: SiemFormat
    host: str
    port: int
    dlq: int
    dlq_max: int
    sources: list[SiemSourceStatus]


class SiemStatusView(BaseModel):
    enabled: bool
    lightweight: bool            # detections and traffic alerts are not produced; event alerts are
    baseline_full: bool
    baseline_days: int           # the baseline period a new connection is measured against
    backlog_warn_rows: int
    destinations: list[SiemDestinationStatus]


def _state(source: str, cur: store.Cursor | None, pending: int | None, *, on: bool, light: bool, full: bool,
           dlq_full: bool, warn: int) -> SourceState:
    if not on:
        return "off"
    if light and source in NEEDS_TRAFFIC:
        return "needs_alert_mode"
    if source == "new_connections" and not full:
        return "baseline_building"
    if cur is None:
        return "waiting"
    if dlq_full and cur.last_error == "dlq_full":
        return "dlq_full"
    if cur.head_attempts or (cur.last_error_at and (cur.last_sent_at is None or cur.last_error_at > cur.last_sent_at)):
        return "failing"
    if pending is not None and pending > warn:
        return "behind"
    return "ok"


def siem_status(ctx: AppContext) -> SiemStatusView:
    s = ctx.settings.current()
    light = s.collection.mode is CollectionMode.LIGHTWEIGHT
    full = not light and baseline_full(ctx)
    pce = s.pce
    with ctx.db() as conn:
        cursors = store.cursors(conn)
        dlq = store.dlq_counts(conn)
    out = []
    for d in s.siem.destinations:
        on = s.siem.enabled and d.enabled
        rows = []
        for source in sources.cursor_sources(d):
            cur = cursors.get((d.id, source))
            if cur is not None and (cur.pce_url, cur.org_id) != (pce.url, pce.org_id):
                cur = None  # another PCE's: starts over on the next tick
            pending = sources.pending(ctx, source, cur.last_id) if cur is not None and on else None
            rows.append(SiemSourceStatus(
                source=source,  # type: ignore[arg-type]  # one of SourceName by sources.CURSOR_SOURCES
                state=_state(source, cur, pending, on=on, light=light, full=full,
                             dlq_full=dlq.get(d.id, 0) >= s.siem.dlq_max_per_dest, warn=s.siem.backlog_warn_rows),
                pending=pending, sent=cur.sent if cur else 0, dropped=cur.dropped if cur else 0,
                last_sent_at=cur.last_sent_at if cur else None, last_error=cur.last_error if cur else None,
                last_error_at=cur.last_error_at if cur else None))
        out.append(SiemDestinationStatus(id=d.id, name=d.name, enabled=d.enabled, transport=d.transport,
                                         format=d.format, host=d.host, port=d.port, dlq=dlq.get(d.id, 0),
                                         dlq_max=s.siem.dlq_max_per_dest, sources=rows))
    return SiemStatusView(enabled=s.siem.enabled, lightweight=light, baseline_full=full,
                          baseline_days=s.collection.retention.baseline_days,
                          backlog_warn_rows=s.siem.backlog_warn_rows, destinations=out)
