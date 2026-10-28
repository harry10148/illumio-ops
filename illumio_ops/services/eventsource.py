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
    EventHosts,
    EventShapeError,
    event_hosts,
    normalize_event,
    precursor_of,
)
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.segment import (
    EVENT_FROM,
    EventFilter,
    EventSegment,
    compile_event_ranking,
    compile_event_where,
)
from illumio_ops.domain.values import IngestSource, SegmentView
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


USER_KINDS = ("user", "service_account")  # the creators an audit counts as people; VENs and the system are not


class AuditUser(BaseModel):
    name: str
    events: int
    failures: int
    source_ips: int


class AuditCounts(BaseModel):
    """A period's events counted for the audit report, in one pass over the store."""
    total: int
    by_type: dict[str, int]
    by_minute: dict[str, int]  # UTC minute "YYYY-MM-DDTHH:MM" -> events (a display zone may be a half hour off)
    actors: int  # distinct users and service accounts
    source_ips: int
    users: list[AuditUser]  # busiest first, at most `top`
    users_total: int
    type_users: dict[str, list[tuple[str, int]]]  # event type -> its top 3 users and service accounts
    failed_by_ip: dict[str, list[datetime]]  # failed sign-ins per source address, oldest first
    coverage: Coverage


def audit_counts(ctx: AppContext, *, start: datetime, end: datetime, top: int = 20,
                 now: datetime | None = None) -> AuditCounts:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    seg = EventSegment(filter=EventFilter(start=start, end=end), view=SegmentView.DETAIL, limit=1)
    window = ["e.timestamp >= ?", "e.timestamp < ?"]
    params = [db_time(start), db_time(end)]
    kinds = f"e.created_by_kind IN ({','.join('?' * len(USER_KINDS))}) AND TRIM(COALESCE(e.created_by_name, '')) != ''"
    ip = "json_extract(e.raw_json, '$.action.src_ip')"

    def read(conn: Any) -> Any:
        where = " AND ".join(window)
        by_type = dict(conn.execute(f"SELECT e.event_type, COUNT(*) FROM events e WHERE {where} GROUP BY 1", params)
                       .fetchall())
        by_minute = dict(conn.execute(f"SELECT substr(e.timestamp, 1, 16), COUNT(*) FROM events e WHERE {where} "
                                      "GROUP BY 1", params).fetchall())
        type_users: dict[str, list[tuple[str, int]]] = {}
        for et, name, n in conn.execute(
                f"SELECT e.event_type, e.created_by_name, COUNT(*) AS n FROM events e WHERE {where} AND {kinds} "
                "GROUP BY 1, 2 ORDER BY 1, n DESC, 2", [*params, *USER_KINDS]):
            if len(type_users.setdefault(et, [])) < 3:
                type_users[et].append((name, n))
        actors, ips = conn.execute(
            f"SELECT COUNT(DISTINCT CASE WHEN {kinds} THEN e.created_by_name END), COUNT(DISTINCT {ip}) "
            f"FROM events e WHERE {where}", [*USER_KINDS, *params]).fetchone()
        users = conn.execute(
            f"SELECT e.created_by_name, COUNT(*) AS n, SUM(e.status = 'failure'), COUNT(DISTINCT {ip}) FROM events e "
            f"WHERE {where} AND {kinds} GROUP BY 1 ORDER BY n DESC, 1", [*params, *USER_KINDS]).fetchall()
        failed: dict[str, list[datetime]] = {}
        for addr, ts in conn.execute(f"SELECT {ip}, e.timestamp FROM events e WHERE {where} AND e.event_type = ? "
                                     f"AND {ip} IS NOT NULL ORDER BY e.timestamp", [*params, "request.authentication_failed"]):
            failed.setdefault(str(addr), []).append(datetime.fromisoformat(ts))
        return by_type, by_minute, actors, ips, users, failed, type_users
    (by_type, by_minute, actors, ips, users, failed, type_users), cov = _segment_read(ctx, seg, at, read)
    return AuditCounts(total=sum(by_type.values()), by_type=by_type, by_minute=by_minute, actors=actors or 0,
                       type_users=type_users,
                       source_ips=ips or 0, users_total=len(users), failed_by_ip=failed, coverage=cov,
                       users=[AuditUser(name=u[0], events=u[1], failures=u[2] or 0, source_ips=u[3]) for u in users[:top]])


class PrecursorEvents(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    items: list[Precursor]
    unmatched: int  # hosts named in precursor events that match no host of the inventory


class HostEvents(BaseModel):
    items: list[tuple[str, dict[str, Any]]]  # (host key, raw event), oldest first
    unmatched: int


def _hosts_of(rows: list[Any]) -> Callable[[EventHosts], tuple[set[str], int]]:
    """How an event's hosts become workload hrefs, each host on its own (one matched host must not keep the
    others from the fallback, P3 final review #12): a VEN through the inventory, a workload href as it is,
    and a host paired again (new VEN or workload href, same host) by its hostname when that names exactly
    one host. Returns (the hrefs, how many of the event's hosts matched none)."""
    by_ven: dict[str, str] = {h["ven_href"]: h["href"] for h in rows if h["ven_href"]}
    known = {h["href"] for h in rows}
    by_name: dict[str, list[str]] = {}
    for h in rows:
        if h["hostname"]:
            by_name.setdefault(h["hostname"], []).append(h["href"])

    def one(ven: str | None, workload: str | None, hostname: str | None) -> str | None:
        if ven is not None and ven in by_ven:
            return by_ven[ven]
        if workload is not None and workload in known:
            return workload
        if hostname is not None and len(by_name.get(hostname, ())) == 1:
            return by_name[hostname][0]
        return None

    def resolve(hosts: EventHosts) -> tuple[set[str], int]:
        if not hosts.entities:
            return set(), 1  # an event naming no host at all is unmatched, not invisible
        found = [one(*e) for e in hosts.entities]
        return {h for h in found if h is not None}, sum(1 for h in found if h is None)
    return resolve


def _typed_events(ctx: AppContext, types: list[str], start: datetime, end: datetime) -> tuple[list[Any], list[Any]]:
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        found = conn.execute(f"SELECT raw_json, timestamp FROM events WHERE event_type IN ({','.join('?' * len(types))}) "
                             "AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
                             [*types, db_time(start), db_time(end)]).fetchall()
        hosts = conn.execute("SELECT href, hostname, ven_href FROM workloads").fetchall()
    if fdb.generation != gen:
        raise StaleGeneration
    return found, hosts


def precursor_events(ctx: AppContext, *, start: datetime, end: datetime) -> PrecursorEvents:
    """Tampering, suspended and offline VENs in the store, by host. Events that match no host are counted,
    not dropped."""
    found, hosts = _typed_events(ctx, sorted(PRECURSOR_EVENT_TYPES), start, end)
    resolve = _hosts_of(hosts)
    items: list[Precursor] = []
    unmatched = 0
    for r in found:
        res = precursor_of(json.loads(r["raw_json"]))
        if res is None:
            continue
        kind, event_hosts, signal = res
        hrefs, missed = resolve(event_hosts)
        unmatched += missed
        if not hrefs:
            continue
        at = datetime.fromisoformat(r["timestamp"])
        items += [Precursor(host_key=endpoint_key(h, ""), kind=kind, at=at, signal=signal) for h in sorted(hrefs)]
    return PrecursorEvents(items=items, unmatched=unmatched)


def tamper_events(ctx: AppContext, *, start: datetime, end: datetime) -> HostEvents:
    """Every agent.tampering event in the store with its host, the same host matching as precursors use."""
    found, hosts = _typed_events(ctx, ["agent.tampering"], start, end)
    resolve = _hosts_of(hosts)
    items: list[tuple[str, dict[str, Any]]] = []
    unmatched = 0
    for r in found:
        raw = json.loads(r["raw_json"])
        hrefs, missed = resolve(event_hosts(raw))
        unmatched += missed
        items += [(endpoint_key(h, ""), raw) for h in sorted(hrefs)]
    return HostEvents(items=items, unmatched=unmatched)


# ── new events for alert evaluation ──────────────────────────────────────────

class NewEvent(EventRow):
    id: int
    host_key: str | None   # the workload the event is about (its href), when the store can tell
    hostname: str | None   # that host's name (a VEN-sent event names its host even when no workload matches)
    actor: str | None      # who made the change, when a user or a service account did


_NEW_COLUMNS = ("e.id, e.href, e.event_type, e.severity, e.status, e.timestamp, e.created_by_kind, e.created_by_name, "
                "e.created_by_href, e.tamper_classification, e.raw_json, e.origin, "
                "COALESCE(e.workload_href, w.href) AS host_key, COALESCE(w.hostname, CASE WHEN e.created_by_kind IN "
                "('ven', 'agent') THEN e.created_by_name END) AS hostname, CASE WHEN e.created_by_kind IN "
                "('user', 'service_account') THEN e.created_by_name END AS actor")


def _new_event(r: Any) -> NewEvent:
    return NewEvent(**_event_row(r).model_dump(), id=r["id"], host_key=r["host_key"], hostname=r["hostname"],
                    actor=r["actor"])


def _ingest_read(ctx: AppContext, sql: str, params: list[Any]) -> list[Any]:
    fdb = ctx.flows()
    gen = fdb.generation
    settings = ctx.settings.current()
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        found = conn.execute(sql, params).fetchall()
    if fdb.generation != gen:
        raise StaleGeneration
    return list(found)


def events_after(ctx: AppContext, after_id: int, *, limit: int) -> tuple[list[NewEvent], bool]:
    """Collected events stored after after_id, oldest first (a backfill's history is never evaluated, spec §7).
    The second value says whether more are waiting."""
    found = _ingest_read(ctx, f"SELECT {_NEW_COLUMNS} {EVENT_FROM} WHERE e.id > ? AND e.origin = 'ingest' "
                              "ORDER BY e.id LIMIT ?", [after_id, limit + 1])
    rows = [_new_event(r) for r in found]
    return rows[:limit], len(rows) > limit


def max_event_id(ctx: AppContext) -> int:
    found = _ingest_read(ctx, "SELECT COALESCE(MAX(id), 0) FROM events", [])
    return int(found[0][0])


def events_in_window(ctx: AppContext, *, start: datetime, end: datetime,
                     exact_types: tuple[str, ...] | None) -> list[NewEvent]:
    """Collected events with start < timestamp <= end, optionally of these types only (a count rule)."""
    sql = f"SELECT {_NEW_COLUMNS} {EVENT_FROM} WHERE e.timestamp > ? AND e.timestamp <= ? AND e.origin = 'ingest'"
    params: list[Any] = [db_time(start), db_time(end)]
    if exact_types is not None:
        if not exact_types:
            return []
        sql += f" AND e.event_type IN ({','.join('?' * len(exact_types))})"
        params.extend(exact_types)
    return [_new_event(r) for r in _ingest_read(ctx, sql + " ORDER BY e.timestamp", params)]
