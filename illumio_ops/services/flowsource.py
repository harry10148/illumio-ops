"""FlowSource: the one way the rest of the product reads flows (spec §6.3 point 3).

Every answer says where it came from. The store covers what live collection and backfill have
read (services.coverage); whatever part of the request lies outside that, or inside a recorded
failed / truncated window, is listed as a gap. Gaps are filled from the PCE only when the caller
asks (fill_gaps=True); rows read that way are paired, filtered and returned like stored ones, but
never written to the store.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel

from illumio_ops.domain.filter import (
    FilterSpec,
    matches,
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
from illumio_ops.domain.values import FlowDirection, IngestSource
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
from illumio_ops.store.flowdb.db import StaleGeneration

__all__ = ["Coverage", "FlowQuery", "FlowRow", "GapReason", "query_flows"]

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


def _live_rows(conn: Any, spec: FilterSpec, fetched: list[FlowRecord]) -> list[FlowRow]:
    """Connections read live, built the way the store builds them: copies of one record are merged,
    records are paired, a connection that has any record already stored is left to the store, and
    only then is the rest of the filter applied (process / user conditions name either end)."""
    merged: dict[str, FlowRecord] = {}
    for r in fetched:
        k = record_key(r)
        merged[k] = merge_sightings(merged[k], r) if k in merged else r
    keys = sorted(merged)
    stored = {k for (k,) in conn.execute(
        f"SELECT record_key FROM flows WHERE record_key IN ({','.join('?' * len(keys))})", keys)} if keys else set()
    _, residual = to_pce_payload(spec, max_results=FILL_MAX_RESULTS, query_name="illumio-ops query", label_hrefs={})
    out = []
    for primary, partner in group_pairs(list(merged.values())):
        if record_key(primary) in stored or (partner is not None and record_key(partner) in stored):
            continue
        row = _row_from_pce(primary, partner)
        if matches(residual, row.model_dump()):
            out.append(row)
    return out


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
            pce_rows = _live_rows(conn, spec, fetched)
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
