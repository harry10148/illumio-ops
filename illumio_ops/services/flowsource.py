"""FlowSource: the one way the rest of the product reads flows (spec §6.3 point 3).

Every answer says where it came from. The store covers what live collection and backfill have
read (services.coverage); whatever part of the request lies outside that, or inside a recorded
failed / truncated window, is listed as a gap. Gaps are filled from the PCE only when the caller
asks (fill_gaps=True); rows read that way are paired, filtered and returned like stored ones, but
never written to the store.
"""
from __future__ import annotations

import sys
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.detectors import Obs
from illumio_ops.domain.filter import (
    FilterSpec,
    FlowCondition,
    PortProto,
    matches,
    port_matches,
    sql_functions,
    to_pce_payload,
    to_sql,
)
from illumio_ops.domain.flows import (
    FlowRecord,
    FlowShapeError,
    group_pairs,
    merge_sightings,
    normalize_flow,
    record_key,
)
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.lateral import AdminPortSet
from illumio_ops.domain.segment import (
    FIELD_COVERAGE_SQL,
    FlowSegment,
    compile_flow_ranking,
)
from illumio_ops.domain.values import FlowDirection, IngestSource, PortClass
from illumio_ops.pce.async_query import run_traffic_query
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import (
    Coverage,
    GapReason,
    merge_gaps,
    store_coverage,
)
from illumio_ops.settings.schema import PceSettings
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import StaleGeneration, db_time

__all__ = [
    "AggRow",
    "BaselineEdge",
    "BaselineEdges",
    "Coverage",
    "FieldCoverage",
    "FlowAggregate",
    "FlowQuery",
    "FlowRow",
    "GapReason",
    "IncrementTop",
    "IncrementTotals",
    "Observations",
    "UserPair",
    "aggregate_flows",
    "baseline_edges",
    "baseline_first_seen",
    "field_coverage",
    "increment_times",
    "increment_totals",
    "increments_watermark",
    "new_user_pairs",
    "observations",
    "query_flows",
]

Order = Literal["last_detected_desc", "connections_desc"]
FILL_MAX_RESULTS = 200_000
# Records one query reads from the PCE over all its gaps, held in memory (~6 KB each once parsed).
FILL_BUDGET = 50_000
FILL_DEADLINE_SECONDS = 900


class FlowRow(BaseModel):
    record_key: str
    conn_key: str
    direction: str
    src_ip: str
    dst_ip: str
    src_key: str
    dst_key: str
    src_href: str | None
    dst_href: str | None
    src_hostname: str | None
    dst_hostname: str | None
    src_managed: bool
    dst_managed: bool
    src_mode: str | None
    dst_mode: str | None
    src_labels: dict[str, str]
    dst_labels: dict[str, str]
    port: int | None
    proto: int
    initiator_process: str | None
    initiator_user: str | None
    service_process: str | None
    service_user: str | None
    windows_service: str | None
    policy_decision: str
    first_detected: datetime
    last_detected: datetime
    num_connections: int
    bytes_in: int | None
    bytes_out: int | None
    state: str | None
    origin: str  # ingest | backfill | pce (read live to fill a gap, not stored)


class FlowQuery(BaseModel):
    rows: list[FlowRow]
    coverage: Coverage
    limit_hit: bool


class AggRow(BaseModel):
    keys: list[str | int | None]       # one per grouping level
    display: list[str | None]          # what to show for each key (a host's name); None = the key itself
    value: int
    bytes_known: int | None            # rows behind a bytes value that had byte data


class FieldCoverage(BaseModel):
    """How many of the matching connections carry each optional field (spec §6.5.7: process and user
    are on few flows, bytes on fewer)."""
    total: int
    initiator_process: int
    initiator_user: int
    service_process: int
    service_user: int
    bytes: int


class FlowAggregate(BaseModel):
    rows: list[AggRow]
    coverage: Coverage
    field_coverage: FieldCoverage | None  # None when the caller skipped it
    limit_hit: bool


class UserPair(BaseModel):
    user: str
    dst_key: str
    port: int | None
    proto: int
    first_seen: datetime


_COLUMNS = ("record_key, conn_key, direction, src_ip, dst_ip, src_key, dst_key, src_href, dst_href, src_hostname, "
            "dst_hostname, src_managed, dst_managed, src_mode, dst_mode, src_label_set, dst_label_set, port, proto, "
            "initiator_process, initiator_user, service_process, service_user, windows_service, policy_decision, "
            "first_detected, last_detected, num_connections, bytes_in, bytes_out, state, origin")
_ORDER_SQL = {"last_detected_desc": "f.last_detected DESC, f.id DESC",
              "connections_desc": "f.num_connections DESC, f.last_detected DESC, f.id DESC"}


def _labels(conn: Any, set_ids: set[int]) -> dict[int, dict[str, str]]:
    if not set_ids:
        return {}
    out: dict[int, dict[str, str]] = {}
    marks = ",".join("?" * len(set_ids))
    for sid, key, value in conn.execute(
            f"SELECT set_id, key, value FROM label_set_members WHERE set_id IN ({marks})", sorted(set_ids)):
        out.setdefault(sid, {})[key] = value
    return out


def _row_from_store(r: Any, labels: dict[int, dict[str, str]]) -> FlowRow:
    d = dict(r)
    d["src_labels"] = labels.get(d.pop("src_label_set") or -1, {})
    d["dst_labels"] = labels.get(d.pop("dst_label_set") or -1, {})
    d["first_detected"] = datetime.fromisoformat(d["first_detected"])
    d["last_detected"] = datetime.fromisoformat(d["last_detected"])
    return FlowRow(**d)


def pair_row(primary: FlowRecord, partner: FlowRecord | None) -> FlowRow:
    """One connection's row from the records the PCE sent for it (one end, or both paired)."""
    return _row_from_pce(primary, partner)


def _row_from_pce(primary: FlowRecord, partner: FlowRecord | None) -> FlowRow:
    out = primary if primary.direction is FlowDirection.OUTBOUND else None
    inn = partner if partner is not None else (primary if primary.direction is FlowDirection.INBOUND else None)
    known_in = [v for v in (primary.bytes_in, partner.bytes_in if partner else None) if v is not None]
    known_out = [v for v in (primary.bytes_out, partner.bytes_out if partner else None) if v is not None]
    return FlowRow(
        record_key=record_key(primary), conn_key=record_key(primary), direction=primary.direction.value,
        src_ip=primary.src_ip, dst_ip=primary.dst_ip,
        src_key=endpoint_key(primary.src_href, primary.src_ip), dst_key=endpoint_key(primary.dst_href, primary.dst_ip),
        src_href=primary.src_href, dst_href=primary.dst_href, src_hostname=primary.src_hostname,
        dst_hostname=primary.dst_hostname, src_managed=primary.src_managed, dst_managed=primary.dst_managed,
        src_mode=primary.src_mode, dst_mode=primary.dst_mode, src_labels=dict(primary.src_labels),
        dst_labels=dict(primary.dst_labels), port=primary.port, proto=primary.proto,
        initiator_process=out.own_process if out else None, initiator_user=out.own_user if out else None,
        service_process=inn.own_process if inn else None, service_user=inn.own_user if inn else None,
        windows_service=primary.windows_service, policy_decision=primary.policy_decision,
        first_detected=primary.first_detected, last_detected=primary.last_detected,
        num_connections=primary.num_connections, bytes_in=max(known_in) if known_in else None,
        bytes_out=max(known_out) if known_out else None, state=primary.state, origin="pce",
    )


def _fetch(ctx: AppContext, pce: PceSettings, spec: FilterSpec,
           window: tuple[datetime, datetime], max_results: int) -> tuple[list[FlowRecord], bool]:
    """Read one gap window from the PCE with the pushable part of the filter: (records, capped).
    Raises a PCE failure for the caller to report."""
    sub = spec.model_copy(update={"start": window[0], "end": window[1]})
    payload, _ = to_pce_payload(sub, max_results=max_results, query_name="illumio-ops query", label_hrefs={})
    with ctx.pce_client(pce) as client:
        result = run_traffic_query(client, payload, deadline=time.monotonic() + FILL_DEADLINE_SECONDS)
    records = []
    for raw in result.rows:
        try:
            records.append(normalize_flow(raw))
        except FlowShapeError:
            continue
    return records, result.capped


_RECORD_COLUMNS = ("record_key, direction, src_ip, dst_ip, src_href, dst_href, src_hostname, dst_hostname, "
                   "src_managed, dst_managed, src_mode, dst_mode, src_label_set, dst_label_set, port, proto, "
                   "initiator_process, initiator_user, service_process, service_user, windows_service, "
                   "policy_decision, first_detected, last_detected, num_connections, "
                   "own_bytes_in AS own_in, own_bytes_out AS own_out, "
                   "state, transmission, network_href")


def _stored_records(conn: Any, tuples: set[tuple[str, str, int | None, int]]) -> dict[str, FlowRecord]:
    """The stored records of these (src, dst, port, proto) tuples, as the records they were stored from."""
    rows = []
    for src, dst, port, proto in sorted(tuples, key=str):
        rows += conn.execute(f"SELECT {_RECORD_COLUMNS} FROM flows WHERE src_ip = ? AND dst_ip = ? AND port IS ? "
                             "AND proto = ?", (src, dst, port, proto)).fetchall()
    labels = _labels(conn, {r[k] for r in rows for k in ("src_label_set", "dst_label_set") if r[k]})
    out: dict[str, FlowRecord] = {}
    for r in rows:
        outbound = r["direction"] == FlowDirection.OUTBOUND.value
        out[r["record_key"]] = FlowRecord(
            direction=FlowDirection(r["direction"]), src_ip=r["src_ip"], dst_ip=r["dst_ip"], src_href=r["src_href"],
            dst_href=r["dst_href"], src_hostname=r["src_hostname"], dst_hostname=r["dst_hostname"],
            src_managed=bool(r["src_managed"]), dst_managed=bool(r["dst_managed"]), src_mode=r["src_mode"],
            dst_mode=r["dst_mode"], src_labels=tuple(sorted(labels.get(r["src_label_set"] or -1, {}).items())),
            dst_labels=tuple(sorted(labels.get(r["dst_label_set"] or -1, {}).items())), port=r["port"],
            proto=r["proto"], own_process=r["initiator_process"] if outbound else r["service_process"],
            own_user=r["initiator_user"] if outbound else r["service_user"], windows_service=r["windows_service"],
            policy_decision=r["policy_decision"], first_detected=datetime.fromisoformat(r["first_detected"]),
            last_detected=datetime.fromisoformat(r["last_detected"]), num_connections=r["num_connections"],
            bytes_in=r["own_in"], bytes_out=r["own_out"], state=r["state"], transmission=r["transmission"],
            network_href=r["network_href"])
    return out


def _live_rows(conn: Any, spec: FilterSpec, fetched: list[FlowRecord]) -> tuple[list[FlowRow], set[str]]:
    """Connections read live, built the way the store builds them: copies of one record are merged, the
    stored records of the same tuples join them (F7: a connection half stored, half only at the PCE is
    still one connection, with both ends' attributes), records are paired, a connection whose records are
    all stored is left to the store, and only then is the rest of the filter applied (process / user
    conditions name either end). Returns the rows and the stored record keys they supersede."""
    merged: dict[str, FlowRecord] = {}
    for r in fetched:
        k = record_key(r)
        merged[k] = merge_sightings(merged[k], r) if k in merged else r
    stored = _stored_records(conn, {(r.src_ip, r.dst_ip, r.port, r.proto) for r in merged.values()})
    for k, rec in stored.items():
        merged[k] = merge_sightings(rec, merged[k]) if k in merged else rec
    # A tuple where the PCE brought a record the store lacks, or more about a stored one, is paired anew as a
    # whole: a new record can take a stored record's partner, and the pair it leaves must be rebuilt too
    # (P3 final review #3). A tuple with nothing new is left to the store.
    changed = {(r.src_ip, r.dst_ip, r.port, r.proto) for k, r in merged.items() if stored.get(k) != r}
    _, residual = to_pce_payload(spec, max_results=FILL_MAX_RESULTS, query_name="illumio-ops query", label_hrefs={})
    out: list[FlowRow] = []
    superseded: set[str] = set()
    for primary, partner in group_pairs(list(merged.values())):
        if (primary.src_ip, primary.dst_ip, primary.port, primary.proto) not in changed:
            continue
        keys = {record_key(primary)} | ({record_key(partner)} if partner is not None else set())
        superseded |= keys & stored.keys()
        row = _row_from_pce(primary, partner)
        if matches(residual, row.model_dump()):
            out.append(row)
    return out, superseded


def query_flows(ctx: AppContext, spec: FilterSpec, *, limit: int, order: Order,
                fill_gaps: bool = False, now: datetime | None = None) -> FlowQuery:
    """Raises StaleGeneration if the PCE was switched while the query ran (its parts would belong to two)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    floor = at - timedelta(days=settings.collection.retention.flow_days)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        cov = store_coverage(conn, IngestSource.TRAFFIC, (spec.start, spec.end), floor=floor,
                             collected=collects(settings, IngestSource.TRAFFIC))
        where, params = to_sql(spec)
        db_rows = conn.execute(f"SELECT {_COLUMNS} FROM flows f WHERE {where} ORDER BY {_ORDER_SQL[order]} LIMIT ?",
                               [*params, limit + 1]).fetchall()
        labels = _labels(conn, {r[k] for r in db_rows for k in ("src_label_set", "dst_label_set") if r[k]})
        rows = [_row_from_store(r, labels) for r in db_rows]
    filled: list[tuple[datetime, datetime]] = []
    kept_gaps: list[tuple[datetime, datetime, str]] = []
    pce_rows: list[FlowRow] = []
    if fill_gaps:
        fetched: list[FlowRecord] = []
        budget = FILL_BUDGET
        for g in cov.gaps:  # no connection is held while the PCE answers (a PCE switch waits for them)
            if g[2] == "truncated" or budget <= 0:  # a capped window would cap again; a spent budget
                kept_gaps.append((g[0], g[1], "truncated"))  # leaves the rest unread, said so
                continue
            try:
                records, capped = _fetch(ctx, settings.pce, spec, (g[0], g[1]), min(budget, FILL_MAX_RESULTS))
            except (*PCE_FAILURES, PceNotConfigured) as exc:
                logger.warning("could not fill a gap from the PCE: {}", exc)
                kept_gaps.append((g[0], g[1], "ingest_failed"))
                continue
            fetched.extend(records)
            budget -= len(records)
            filled.append((g[0], g[1]))
            if capped:
                kept_gaps.append((g[0], g[1], "truncated"))
        with fdb.connect() as conn:
            pce_rows, superseded = _live_rows(conn, spec, fetched)
        rows = [r for r in rows if r.record_key not in superseded]
    else:
        kept_gaps = cov.gaps
    if fdb.generation != gen:
        raise StaleGeneration
    combined = rows + pce_rows
    if order == "last_detected_desc":
        combined.sort(key=lambda r: r.last_detected, reverse=True)
    else:
        combined.sort(key=lambda r: (r.num_connections, r.last_detected), reverse=True)
    used_store = bool(rows) or cov.covers_any
    source: Literal["store", "pce", "mixed"] = (
        "mixed" if filled and used_store else "pce" if filled else "store")
    kept_gaps = merge_gaps(kept_gaps)
    return FlowQuery(
        rows=combined[:limit], limit_hit=len(combined) > limit,
        coverage=Coverage(source=source, store_from=cov.store_from, store_to=cov.store_to,
                          gaps=kept_gaps, filled_from_pce=sorted(filled),
                          truncated=any(g[2] == "truncated" for g in kept_gaps)),
    )


def _store_read(ctx: AppContext) -> tuple[Any, int, Any]:
    """(flow db, generation noted before the settings, settings) for a store-only read."""
    fdb = ctx.flows()
    gen = fdb.generation  # noted before the settings it goes with (FlowDb.generation)
    return fdb, gen, ctx.settings.current()


def _field_coverage(conn: Any, where: str, params: list[Any]) -> FieldCoverage:
    r = conn.execute(FIELD_COVERAGE_SQL.format(where=where), params).fetchone()
    return FieldCoverage(**dict(r))


def aggregate_flows(ctx: AppContext, seg: FlowSegment, *, now: datetime | None = None,
                    with_field_coverage: bool = True) -> FlowAggregate:
    """A segment's ranking, answered from the store only: what lies outside its coverage is listed as gaps
    (a ranking mixed with PCE rows could not be grouped the way the store groups connections). The field
    coverage is a second scan of the same rows; a caller that does not show it skips it."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb, gen, settings = _store_read(ctx)
    floor = at - timedelta(days=settings.collection.retention.flow_days)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        cov = store_coverage(conn, IngestSource.TRAFFIC, (seg.filter.start, seg.filter.end), floor=floor,
                             collected=collects(settings, IngestSource.TRAFFIC))
        sql, params = compile_flow_ranking(seg)
        found = conn.execute(sql, params).fetchall()
        where, where_params = to_sql(seg.filter)
        fields = _field_coverage(conn, where, where_params) if with_field_coverage else None
    if fdb.generation != gen:
        raise StaleGeneration
    levels = len(seg.group_by)
    rows = [AggRow(keys=[r[f"k{i}"] for i in range(levels)], display=[r[f"d{i}"] for i in range(levels)],
                   value=r["value"] or 0, bytes_known=r["bytes_known"]) for r in found]
    gaps = merge_gaps(cov.gaps)
    return FlowAggregate(
        rows=rows[:seg.limit], limit_hit=len(rows) > seg.limit, field_coverage=fields,
        coverage=Coverage(source="store", store_from=cov.store_from, store_to=cov.store_to, gaps=gaps,
                          filled_from_pce=[], truncated=any(g[2] == "truncated" for g in gaps)))


def field_coverage(ctx: AppContext, spec: FilterSpec) -> FieldCoverage:
    """The field coverage of the connections a filter matches in the store."""
    fdb, gen, settings = _store_read(ctx)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        where, params = to_sql(spec)
        fields = _field_coverage(conn, where, params)
    if fdb.generation != gen:
        raise StaleGeneration
    return fields


def new_user_pairs(ctx: AppContext, ports: Sequence[PortProto], *, since: datetime) -> list[UserPair]:
    """User x destination x port combinations first seen since `since` (spec §6.5.7, "new combinations
    against the baseline"). user_baseline holds only connections with a user (about a tenth of them on
    lab), so it is scanned whole."""
    fdb, gen, settings = _store_read(ctx)
    numbers = sorted({p.port for p in ports if p.port is not None})
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        sql = "SELECT initiator_user, dst_key, port, proto, first_seen FROM user_baseline WHERE first_seen >= ?"
        params: list[Any] = [db_time(since)]
        if numbers:
            sql += f" AND port IN ({','.join('?' * len(numbers))})"
            params += numbers
        found = conn.execute(sql + " ORDER BY first_seen, initiator_user", params).fetchall()
    if fdb.generation != gen:
        raise StaleGeneration
    out = []
    for r in found:
        port = None if r["port"] == -1 else r["port"]
        if ports and not any(port_matches(p, port, r["proto"]) for p in ports):
            continue
        out.append(UserPair(user=r["initiator_user"], dst_key=r["dst_key"], port=port, proto=r["proto"],
                            first_seen=datetime.fromisoformat(r["first_seen"])))
    return out



@dataclass(frozen=True, slots=True)  # hundreds of thousands at 1,000 workloads (P3 Task 15 scale)
class BaselineEdge:
    src_key: str
    dst_key: str
    port: int
    proto: int
    decision: str | None  # the reported decision of the newest observation; None before flow db 0002


class BaselineEdges(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    edges: list[BaselineEdge]
    baseline_from: datetime | None  # where the traffic coverage begins
    collected: bool


def baseline_edges(ctx: AppContext, ports: AdminPortSet, *, since: datetime,
                   classes: Collection[PortClass] | None = None) -> BaselineEdges:
    """The management-port connections seen since `since`, from the connection baseline (kept for the
    baseline period in every collection mode). Reads by port through ix_baseline_port; the protocol and
    the time are checked here."""
    fdb, gen, settings = _store_read(ctx)
    collected = collects(settings, IngestSource.TRAFFIC)
    numbers = sorted({e.port for e in ports.entries if classes is None or e.category in classes})
    if not collected or not numbers:
        return BaselineEdges(edges=[], baseline_from=None, collected=collected)
    stamp = db_time(since)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        # Rows are turned into edges as they are read, never all held at once.
        cur = conn.execute(
            "SELECT src_key, dst_key, port, proto, last_decision FROM connection_baseline "
            f"WHERE port IN ({','.join('?' * len(numbers))}) AND last_seen >= ?", [*numbers, stamp])
        # Host keys repeat on every row of a host: one string per host, not one per row.
        edges = [BaselineEdge(src_key=sys.intern(src), dst_key=sys.intern(dst), port=port, proto=proto,
                              decision=decision)
                 for src, dst, port, proto, decision in cur if ports.matches(port, proto, classes)]
        ranges = ingest_state.coverage(conn, IngestSource.TRAFFIC)
    if fdb.generation != gen:
        raise StaleGeneration
    return BaselineEdges(edges=edges, baseline_from=ranges[0][0] if ranges else None, collected=True)


class Observations(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    rows: list[Obs]
    coverage: Coverage


_OBS_COLUMNS = ("src_key, dst_key, src_href, dst_href, src_ip, dst_ip, src_hostname, dst_hostname, port, proto, "
                "policy_decision, first_detected, last_detected, num_connections, initiator_user, initiator_process, "
                "src_label_set, dst_label_set, src_managed, origin")


def observations(ctx: AppContext, spec: FilterSpec, *, now: datetime | None = None) -> Observations:
    """The connections a filter matches in the store, as slim rows for the detectors. No row limit: the
    caller bounds the time window and the ports."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb, gen, settings = _store_read(ctx)
    floor = at - timedelta(days=settings.collection.retention.flow_days)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        cov = store_coverage(conn, IngestSource.TRAFFIC, (spec.start, spec.end), floor=floor,
                             collected=collects(settings, IngestSource.TRAFFIC))
        where, params = to_sql(spec)
        found = conn.execute(f"SELECT {_OBS_COLUMNS} FROM flows f WHERE {where}", params).fetchall()
        labels = _labels(conn, {r[k] for r in found for k in ("src_label_set", "dst_label_set") if r[k]})
    if fdb.generation != gen:
        raise StaleGeneration
    rows = [Obs(src_key=r["src_key"], dst_key=r["dst_key"], src_href=r["src_href"], dst_href=r["dst_href"],
                src_ip=r["src_ip"], dst_ip=r["dst_ip"], src_hostname=r["src_hostname"], dst_hostname=r["dst_hostname"],
                port=r["port"], proto=r["proto"], decision=r["policy_decision"],
                first=datetime.fromisoformat(r["first_detected"]), last=datetime.fromisoformat(r["last_detected"]),
                num_connections=r["num_connections"], initiator_user=r["initiator_user"],
                initiator_process=r["initiator_process"], src_labels=labels.get(r["src_label_set"] or -1, {}),
                dst_labels=labels.get(r["dst_label_set"] or -1, {}), src_managed=bool(r["src_managed"]),
                origin=r["origin"]) for r in found]
    gaps = merge_gaps(cov.gaps)
    return Observations(rows=rows, coverage=Coverage(
        source="store", store_from=cov.store_from, store_to=cov.store_to, gaps=gaps, filled_from_pce=[],
        truncated=any(g[2] == "truncated" for g in gaps)))


def baseline_first_seen(ctx: AppContext,
                        tuples: Collection[tuple[str, str, int, int]]) -> dict[tuple[str, str, int, int], datetime]:
    """When the baseline first saw each (src_key, dst_key, port or -1, proto), by primary key."""
    fdb, gen, settings = _store_read(ctx)
    keys = sorted(set(tuples))
    out: dict[tuple[str, str, int, int], datetime] = {}
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        for i in range(0, len(keys), 200):
            chunk = keys[i:i + 200]
            marks = ",".join("(?, ?, ?, ?)" for _ in chunk)
            for r in conn.execute("SELECT src_key, dst_key, port, proto, first_seen FROM connection_baseline "
                                  f"WHERE (src_key, dst_key, port, proto) IN (VALUES {marks})",
                                  [v for k in chunk for v in k]):
                out[(r[0], r[1], r[2], r[3])] = datetime.fromisoformat(r[4])
    if fdb.generation != gen:
        raise StaleGeneration
    return out


@dataclass(frozen=True)
class TrafficSummary:
    sources: int | None  # None: traffic was not watched over the whole period, so "nobody" cannot be said
    last_seen: datetime | None
    decisions: frozenset[str]


FRESH = timedelta(hours=1)  # how far behind now the newest traffic coverage may end and still count as current


def service_traffic(ctx: AppContext, targets: Collection[tuple[str, int, int]], *, since: datetime,
                    now: datetime) -> dict[tuple[str, int, int], TrafficSummary]:
    """Recent traffic to each (destination key, port, proto), from the connection baseline (read by port
    through ix_baseline_port). A target nobody reached since `since` has sources 0 — only when traffic was
    collected over that whole period; otherwise every target's sources are None (P3 final review #4)."""
    fdb, gen, settings = _store_read(ctx)
    wanted = set(targets)
    numbers = sorted({port for _, port, _ in wanted})
    unknown = {t: TrafficSummary(sources=None, last_seen=None, decisions=frozenset()) for t in wanted}
    if not numbers or not collects(settings, IngestSource.TRAFFIC):
        return unknown
    out = {t: TrafficSummary(sources=0, last_seen=None, decisions=frozenset()) for t in wanted}
    stamp = db_time(since)
    acc: dict[tuple[str, int, int], tuple[set[str], str | None, set[str]]] = {}
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        # Watched without a hole from `since` up to about now, and no read in that stretch failed or was cut
        # short: only then does "nobody connected" hold.
        ranges = ingest_state.coverage(conn, IngestSource.TRAFFIC)
        if not ranges or ranges[-1][0] > since or ranges[-1][1] < now - FRESH or any(
                g.window_end > since for g in ingest_state.open_gaps(conn, IngestSource.TRAFFIC)):
            return unknown
        for r in conn.execute("SELECT src_key, dst_key, port, proto, last_seen, last_decision FROM connection_baseline "
                              f"WHERE port IN ({','.join('?' * len(numbers))})", numbers):
            key = (r["dst_key"], r["port"], r["proto"])
            if key not in wanted or r["last_seen"] < stamp:
                continue
            srcs, last, decisions = acc.setdefault(key, (set(), None, set()))
            srcs.add(r["src_key"])
            if r["last_decision"]:
                decisions.add(r["last_decision"])
            acc[key] = (srcs, max(last or "", r["last_seen"]), decisions)
    if fdb.generation != gen:
        raise StaleGeneration
    for key, (srcs, last, decisions) in acc.items():
        out[key] = TrafficSummary(sources=len(srcs), last_seen=datetime.fromisoformat(last) if last else None,
                                  decisions=frozenset(decisions))
    return out


# ── flow increments (alert thresholds, spec §6.6 F12) ────────────────────────

class IncrementTop(BaseModel):
    src: str
    dst: str
    port: int | None
    proto: int
    connections: int
    mbps: float | None


class IncrementTotals(BaseModel):
    """Growth observed within (start, end] on the connections a condition matches. Late growth (the daily
    re-read, a catch-up) is left out: counted at the moment it arrives it would look like a burst."""
    connections: int
    bytes: int | None        # None: no growth in the window carried byte data
    bytes_rows: int
    rows: int
    new_rows: int            # observed after new_after: whether anything arrived since the last evaluation
    max_mbps: float | None   # bytes over the flow time they span — a lower bound
    top: list[IncrementTop]
    coverage: Coverage


TOP_INCREMENTS = 10
# The connections whose growth was observed in a window were active shortly before it; this much flow time is
# allowed on either side so the join never drops one, while observed_at does the real windowing.
_FLOW_SLACK_BEFORE = timedelta(hours=24)
_FLOW_SLACK_AFTER = timedelta(hours=1)


def _mbps(bytes_: int | None, seconds: float) -> float | None:
    return None if bytes_ is None else bytes_ * 8 / max(seconds, 1.0) / 1_000_000


def increment_totals(ctx: AppContext, cond: FlowCondition, *, start: datetime, end: datetime, new_after: datetime,
                     rank_by: Literal["connections", "mbps"], now: datetime | None = None) -> IncrementTotals:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb, gen, settings = _store_read(ctx)
    floor = at - timedelta(days=settings.collection.retention.flow_days)
    where, params = to_sql(cond.within(start - _FLOW_SLACK_BEFORE, end + _FLOW_SLACK_AFTER))
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=floor,
                             collected=collects(settings, IngestSource.TRAFFIC))
        rows = conn.execute(
            "SELECT i.connections, i.bytes, i.seconds, i.observed_at, f.src_key, f.dst_key, f.src_hostname, "
            "f.dst_hostname, f.port, f.proto FROM flow_increments i "
            # The record measured may have paired since: the connection's current primary row gives its dimensions.
            "JOIN flows r ON r.record_key = i.record_key JOIN flows f ON f.conn_key = r.conn_key AND f.is_primary = 1 "
            f"WHERE i.late = 0 AND i.observed_at > ? AND i.observed_at <= ? AND {where}",
            [db_time(start), db_time(end), *params]).fetchall()
    if fdb.generation != gen:
        raise StaleGeneration
    with_bytes = [r for r in rows if r["bytes"] is not None]
    rates = [(r, _mbps(r["bytes"], r["seconds"])) for r in rows]
    key = (lambda pair: (pair[1] or 0.0)) if rank_by == "mbps" else (lambda pair: pair[0]["connections"])
    top = [IncrementTop(src=r["src_hostname"] or r["src_key"], dst=r["dst_hostname"] or r["dst_key"], port=r["port"],
                        proto=r["proto"], connections=r["connections"], mbps=rate)
           for r, rate in sorted(rates, key=key, reverse=True)[:TOP_INCREMENTS]]
    stamp = db_time(new_after)
    gaps = merge_gaps(cov.gaps)
    return IncrementTotals(
        connections=sum(r["connections"] for r in rows),
        bytes=sum(r["bytes"] for r in with_bytes) if with_bytes else None, bytes_rows=len(with_bytes),
        rows=len(rows), new_rows=sum(1 for r in rows if r["observed_at"] > stamp),
        max_mbps=max((rate for _, rate in rates if rate is not None), default=None), top=top,
        coverage=Coverage(source="store", store_from=cov.store_from, store_to=cov.store_to, gaps=gaps,
                          filled_from_pce=[], truncated=any(g[2] == "truncated" for g in gaps)))


def increments_watermark(ctx: AppContext) -> datetime | None:
    """When growth was last recorded (an alert evaluation's first run starts here, not at history)."""
    fdb, _gen, settings = _store_read(ctx)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        value = conn.execute("SELECT MAX(observed_at) FROM flow_increments").fetchone()[0]
    return datetime.fromisoformat(value) if value else None


def increment_times(ctx: AppContext, *, start: datetime, end: datetime) -> list[datetime]:
    """When growth was recorded within (start, end] — the moments a live evaluation ran (rule preview)."""
    fdb, _gen, settings = _store_read(ctx)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        found = conn.execute("SELECT DISTINCT observed_at FROM flow_increments WHERE late = 0 AND observed_at > ? "
                             "AND observed_at <= ? ORDER BY observed_at", (db_time(start), db_time(end))).fetchall()
    return [datetime.fromisoformat(r[0]) for r in found]
