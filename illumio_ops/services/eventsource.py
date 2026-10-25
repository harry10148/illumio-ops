"""EventSource: the one way the rest of the product reads PCE events, with the same coverage
semantics as FlowSource (services.coverage: what was read, recorded gaps, optional filling from
the PCE)."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.detectors import Precursor
from illumio_ops.domain.events import (
    PRECURSOR_EVENT_TYPES,
    EventShapeError,
    normalize_event,
    precursor_of,
)
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.segment import (
    EVENT_FROM,
    EventSegment,
    compile_event_ranking,
    compile_event_where,
)
from illumio_ops.domain.values import IngestSource
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.events import events_timeout, fetch_events
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import Coverage, merge_gaps, store_coverage
from illumio_ops.services.flowsource import AggRow
from illumio_ops.store.flowdb.db import StaleGeneration, db_time

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
        require_same_pce(conn, settings.pce)
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


class EventAggregate(BaseModel):
    rows: list[AggRow]
    coverage: Coverage
    limit_hit: bool


def _event_row(r: Any) -> EventRow:
    return EventRow(href=r["href"], event_type=r["event_type"], severity=r["severity"], status=r["status"],
                    timestamp=datetime.fromisoformat(r["timestamp"]), created_by_kind=r["created_by_kind"],
                    created_by_name=r["created_by_name"], created_by_href=r["created_by_href"],
                    tamper_classification=r["tamper_classification"], raw=json.loads(r["raw_json"]),
                    origin=r["origin"])


def _segment_read(ctx: AppContext, seg: EventSegment, at: datetime,
                  read: Callable[[Any], list[Any]]) -> tuple[list[Any], Coverage]:
    """Run a store-only read of an event segment with its coverage (events never fill from the PCE here:
    a ranking mixed with PCE rows could not be grouped the way the store's rows are)."""
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    floor = at - timedelta(days=settings.collection.retention.event_days)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        cov = store_coverage(conn, IngestSource.EVENTS, (seg.filter.start, seg.filter.end), floor=floor,
                             collected=collects(settings, IngestSource.EVENTS))
        found = read(conn)
    if fdb.generation != gen:
        raise StaleGeneration
    gaps = merge_gaps(cov.gaps)
    return found, Coverage(source="store", store_from=cov.store_from, store_to=cov.store_to, gaps=gaps,
                           filled_from_pce=[], truncated=any(g[2] == "truncated" for g in gaps))


def aggregate_events(ctx: AppContext, seg: EventSegment, *, now: datetime | None = None) -> EventAggregate:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    sql, params = compile_event_ranking(seg)
    found, cov = _segment_read(ctx, seg, at, lambda conn: conn.execute(sql, params).fetchall())
    levels = len(seg.group_by)
    rows = [AggRow(keys=[r[f"k{i}"] for i in range(levels)], display=[None] * levels, value=r["value"],
                   bytes_known=None) for r in found]
    return EventAggregate(rows=rows[:seg.limit], coverage=cov, limit_hit=len(rows) > seg.limit)


def event_detail(ctx: AppContext, seg: EventSegment, *, now: datetime | None = None) -> EventQuery:
    """An event segment's rows, newest first, with the same filter semantics as its ranking."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    where, params = compile_event_where(seg.filter)
    sql = ("SELECT e.href, e.event_type, e.severity, e.status, e.timestamp, e.created_by_kind, e.created_by_name, "
           f"e.created_by_href, e.tamper_classification, e.raw_json, e.origin {EVENT_FROM} WHERE {where} "
           "ORDER BY e.timestamp DESC, e.id DESC LIMIT ?")
    found, cov = _segment_read(ctx, seg, at, lambda conn: conn.execute(sql, [*params, seg.limit + 1]).fetchall())
    rows = [_event_row(r) for r in found]
    return EventQuery(rows=rows[:seg.limit], coverage=cov, limit_hit=len(rows) > seg.limit)


class PrecursorEvents(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    items: list[Precursor]
    unmatched: int  # precursor events whose host could not be told


def precursor_events(ctx: AppContext, *, start: datetime, end: datetime) -> PrecursorEvents:
    """Tampering, suspended and offline VENs in the store, by host. A VEN-sent event names its VEN, joined
    to the host through the inventory; a VEN paired again (a new VEN href, same host) is matched by its
    hostname when that names exactly one host. Events that still match nothing are counted, not dropped."""
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    types = sorted(PRECURSOR_EVENT_TYPES)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        found = conn.execute(f"SELECT raw_json, timestamp FROM events WHERE event_type IN ({','.join('?' * len(types))}) "
                             "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                             [*types, db_time(start), db_time(end)]).fetchall()
        hosts = conn.execute("SELECT href, hostname, ven_href FROM workloads").fetchall()
    if fdb.generation != gen:
        raise StaleGeneration
    by_ven = {h["ven_href"]: h["href"] for h in hosts if h["ven_href"]}
    known = {h["href"] for h in hosts}
    by_name: dict[str, list[str]] = {}
    for h in hosts:
        if h["hostname"]:
            by_name.setdefault(h["hostname"], []).append(h["href"])
    items: list[Precursor] = []
    unmatched = 0
    for r in found:
        res = precursor_of(json.loads(r["raw_json"]))
        if res is None:
            continue
        kind, event_hosts, signal = res
        hrefs = {by_ven[v] for v in event_hosts.ven_hrefs if v in by_ven} | (event_hosts.workload_hrefs & known)
        if not hrefs:
            hrefs = {by_name[n][0] for n in event_hosts.hostnames if len(by_name.get(n, ())) == 1}
        if not hrefs:
            unmatched += 1
            continue
        at = datetime.fromisoformat(r["timestamp"])
        items += [Precursor(host_key=endpoint_key(h, ""), kind=kind, at=at, signal=signal) for h in sorted(hrefs)]
    return PrecursorEvents(items=items, unmatched=unmatched)
