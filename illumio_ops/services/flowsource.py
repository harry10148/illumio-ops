"""FlowSource: the one way the rest of the product reads flows (spec §6.3 point 3).

Every answer says where it came from. The store covers [store_from, store_to]: from the first
window live collection read (or an earlier finished backfill, clipped by retention) up to the
traffic watermark. Whatever part of the request lies outside it, or inside a recorded failed /
truncated window, is listed as a gap. Gaps are filled from the PCE only when the caller asks
(fill_gaps=True); rows read that way are returned but never written to the store.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
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
    normalize_flow,
    record_key,
)
from illumio_ops.domain.identity import endpoint_key
from illumio_ops.domain.values import FlowDirection, IngestSource
from illumio_ops.pce.async_query import run_traffic_query
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.services.collect.cycle import COVERED_FROM_KEY
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state

Order = Literal["last_detected_desc", "connections_desc"]
GapReason = Literal["before_retention", "not_yet_collected", "ingest_failed", "truncated"]
FILL_MAX_RESULTS = 200_000
FILL_DEADLINE_SECONDS = 900


class Coverage(BaseModel):
    source: Literal["store", "pce", "mixed"]
    store_from: datetime | None
    store_to: datetime | None
    gaps: list[tuple[datetime, datetime, str]]
    filled_from_pce: list[tuple[datetime, datetime]]
    truncated: bool


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


def _subtract(window: tuple[datetime, datetime], cuts: Sequence[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    parts = [window]
    for a, b in cuts:
        nxt = []
        for x, y in parts:
            if b <= x or a >= y:
                nxt.append((x, y))
                continue
            if x < a:
                nxt.append((x, a))
            if b < y:
                nxt.append((b, y))
        parts = nxt
    return parts


def _coverage_bounds(conn: Any, ctx: AppContext, now: datetime) -> tuple[datetime | None, datetime | None]:
    traffic = ingest_state.get(conn, IngestSource.TRAFFIC)
    if traffic is None or traffic.watermark is None:
        return None, None
    covered = (traffic.progress or {}).get(COVERED_FROM_KEY)
    store_from = datetime.fromisoformat(covered) if covered else None
    backfill = ingest_state.get(conn, IngestSource.BACKFILL)
    bp = (backfill.progress or {}) if backfill else {}
    if bp.get("finished") and bp.get("start"):
        bstart = datetime.fromisoformat(bp["start"])
        store_from = bstart if store_from is None else min(store_from, bstart)
    if store_from is None:
        row = conn.execute("SELECT MIN(first_detected) FROM flows").fetchone()
        store_from = datetime.fromisoformat(row[0]) if row and row[0] else traffic.watermark
    retention_floor = now - timedelta(days=ctx.settings.current().collection.retention.flow_days)
    return max(store_from, retention_floor), traffic.watermark


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


def _fill(ctx: AppContext, spec: FilterSpec, window: tuple[datetime, datetime]) -> list[FlowRecord]:
    """Read one gap window from the PCE; raises a PCE failure for the caller to report."""
    sub = spec.model_copy(update={"start": window[0], "end": window[1]})
    payload, residual = to_pce_payload(sub, max_results=FILL_MAX_RESULTS, query_name="illumio-ops query",
                                       label_hrefs={})
    with ctx.pce_client() as client:
        result = run_traffic_query(client, payload, deadline=time.monotonic() + FILL_DEADLINE_SECONDS)
    records = []
    for raw in result.rows:
        try:
            r = normalize_flow(raw)
        except FlowShapeError:
            continue
        if matches(residual, r):
            records.append(r)
    return records


def query_flows(ctx: AppContext, spec: FilterSpec, *, limit: int, order: Order,
                fill_gaps: bool = False, now: datetime | None = None) -> FlowQuery:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    window = (spec.start, spec.end)
    with ctx.flows().connect() as conn:
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        store_from, store_to = _coverage_bounds(conn, ctx, at)
        gaps: list[tuple[datetime, datetime, str]] = []
        if store_from is None or store_to is None:
            gaps.append((spec.start, spec.end, "not_yet_collected"))
        else:
            if spec.start < store_from:
                gaps.append((spec.start, min(store_from, spec.end), "before_retention"))
            if spec.end > store_to:
                gaps.append((max(store_to, spec.start), spec.end, "not_yet_collected"))
            for rec in ingest_state.open_gaps(conn, IngestSource.TRAFFIC):
                if rec.window_start < spec.end and rec.window_end > spec.start:
                    gaps.append((max(rec.window_start, spec.start), min(rec.window_end, spec.end),
                                 "truncated" if rec.kind == "truncated" else "ingest_failed"))
        used_store = store_from is not None and store_to is not None and bool(
            _subtract(window, [(spec.start, store_from), (store_to, spec.end)]))
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
            for g in gaps:
                if g[2] == "truncated":  # re-reading a window that hit the cap would hit it again
                    kept_gaps.append(g)
                    continue
                try:
                    fetched.extend(_fill(ctx, spec, (g[0], g[1])))
                    filled.append((g[0], g[1]))
                except (*PCE_FAILURES, PceNotConfigured) as exc:
                    logger.warning("could not fill a gap from the PCE: {}", exc)
                    kept_gaps.append((g[0], g[1], "ingest_failed"))
            keys = {record_key(r) for r in fetched}
            stored = {k for (k,) in conn.execute(
                f"SELECT record_key FROM flows WHERE record_key IN ({','.join('?' * len(keys))})", sorted(keys))} \
                if keys else set()
            pce_rows = [_row_from_pce(p, partner) for p, partner in group_pairs(
                [r for r in fetched if record_key(r) not in stored])]
        else:
            kept_gaps = gaps
    combined = rows + pce_rows
    if order == "last_detected_desc":
        combined.sort(key=lambda r: r.last_detected, reverse=True)
    else:
        combined.sort(key=lambda r: (r.num_connections, r.last_detected), reverse=True)
    source: Literal["store", "pce", "mixed"] = (
        "mixed" if filled and used_store else "pce" if filled else "store")
    return FlowQuery(
        rows=combined[:limit], limit_hit=len(combined) > limit,
        coverage=Coverage(source=source, store_from=store_from, store_to=store_to,
                          gaps=sorted(kept_gaps), filled_from_pce=filled,
                          truncated=any(g[2] == "truncated" for g in kept_gaps)),
    )
