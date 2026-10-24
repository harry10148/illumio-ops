"""EventSource: the one way the rest of the product reads PCE events, with the same coverage
semantics as FlowSource (services.coverage: what was read, recorded gaps, optional filling from
the PCE)."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain.events import EventShapeError, normalize_event
from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.events import events_timeout, fetch_events
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage, merge_gaps, store_coverage
from illumio_ops.store.flowdb.db import db_time

FILL_DEADLINE_SECONDS = 900


class EventRow(BaseModel):
    href: str
    event_type: str
    severity: str | None
    status: str | None
    timestamp: datetime
    created_by_kind: str | None
    created_by_name: str | None
    created_by_href: str | None
    tamper_classification: str | None
    raw: dict[str, Any]
    origin: str  # ingest | backfill | pce


class EventQuery(BaseModel):
    rows: list[EventRow]
    coverage: Coverage
    limit_hit: bool


def _matches(row: EventRow, event_types: tuple[str, ...], ven_hrefs: set[str] | None) -> bool:
    if event_types and row.event_type not in event_types:
        return False
    return ven_hrefs is None or (row.created_by_href or "") in ven_hrefs


def query_events(ctx: AppContext, *, start: datetime, end: datetime, event_types: tuple[str, ...] = (),
                 workload_href: str | None = None, limit: int, fill_gaps: bool = False,
                 now: datetime | None = None) -> EventQuery:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current()
    floor = at - timedelta(days=settings.collection.retention.event_days)
    with ctx.flows().connect() as conn:
        cov = store_coverage(conn, IngestSource.EVENTS, (start, end), floor=floor,
                             collected=collects(settings, IngestSource.EVENTS))
        gaps = cov.gaps
        clauses, params = ["e.timestamp >= ?", "e.timestamp <= ?"], [db_time(start), db_time(end)]
        if event_types:
            clauses.append(f"e.event_type IN ({','.join('?' * len(event_types))})")
            params.extend(event_types)
        ven_hrefs: set[str] | None = None
        if workload_href is not None:
            ven_hrefs = {r[0] for r in conn.execute("SELECT ven_href FROM workloads WHERE href = ? AND ven_href "
                                                    "IS NOT NULL", (workload_href,))}
            clauses.append("(e.workload_href = ? OR e.created_by_href IN "
                           "(SELECT ven_href FROM workloads WHERE href = ?))")
            params.extend([workload_href, workload_href])
        db_rows = conn.execute(
            "SELECT href, event_type, severity, status, timestamp, created_by_kind, created_by_name, created_by_href, "
            f"tamper_classification, raw_json, origin FROM events e WHERE {' AND '.join(clauses)} "
            "ORDER BY e.timestamp DESC, e.id DESC LIMIT ?", [*params, limit + 1]).fetchall()
        rows = [EventRow(href=r["href"], event_type=r["event_type"], severity=r["severity"], status=r["status"],
                         timestamp=datetime.fromisoformat(r["timestamp"]), created_by_kind=r["created_by_kind"],
                         created_by_name=r["created_by_name"], created_by_href=r["created_by_href"],
                         tamper_classification=r["tamper_classification"], raw=json.loads(r["raw_json"]),
                         origin=r["origin"]) for r in db_rows]
        from_store = bool(rows)
        known = {r.href for r in rows}
        filled: list[tuple[datetime, datetime]] = []
        kept: list[tuple[datetime, datetime, str]] = []
        if not fill_gaps:
            kept = gaps
        else:
            for g in gaps:
                if g[2] == "truncated":
                    kept.append(g)
                    continue
                try:
                    with ctx.pce_client(settings.pce) as client:
                        page = fetch_events(client, start=g[0], end=g[1], timeout=events_timeout(settings.pce),
                                            deadline=time.monotonic() + FILL_DEADLINE_SECONDS)
                except (*PCE_FAILURES, PceNotConfigured) as exc:
                    logger.warning("could not fill an event gap from the PCE: {}", exc)
                    kept.append((g[0], g[1], "ingest_failed"))
                    continue
                filled.append((g[0], g[1]))
                if page.capped:
                    kept.append((g[0], g[1], "truncated"))
                for raw in page.items:
                    try:
                        rec = normalize_event(raw)
                    except EventShapeError:
                        continue
                    row = EventRow(href=rec.href, event_type=rec.event_type, severity=rec.severity,
                                   status=rec.status, timestamp=rec.timestamp, created_by_kind=rec.created_by_kind,
                                   created_by_name=rec.created_by_name, created_by_href=rec.created_by_href,
                                   tamper_classification=rec.tamper_classification, raw=dict(raw), origin="pce")
                    if row.href not in known and _matches(row, event_types, ven_hrefs):
                        known.add(row.href)
                        rows.append(row)
    rows.sort(key=lambda r: r.timestamp, reverse=True)
    used_store = from_store or cov.covers_any
    source: Literal["store", "pce", "mixed"] = "mixed" if filled and used_store else "pce" if filled else "store"
    kept = merge_gaps(kept)
    return EventQuery(rows=rows[:limit], limit_hit=len(rows) > limit,
                      coverage=Coverage(source=source, store_from=cov.store_from, store_to=cov.store_to, gaps=kept,
                                        filled_from_pce=sorted(filled),
                                        truncated=any(g[2] == "truncated" for g in kept)))
