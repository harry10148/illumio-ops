"""Traffic collector: pull flows since the watermark into the flow database.

Window [watermark - 600 s, now] (VEN reports every 10 minutes; the overlap re-reads records that
were still growing). A failed window records a gap and leaves the watermark where it was; a window
that still hits the 200,000 cap at the smallest split is written and recorded as truncated.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from illumio_ops.domain.flows import (
    FlowRecord,
    FlowShapeError,
    merge_sightings,
    normalize_flow,
    record_key,
)
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.async_query import (
    PceQueryError,
    run_traffic_query,
    traffic_payload,
)
from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceClient,
    PceNotConfigured,
    PceTransportError,
)
from illumio_ops.services.collect import CycleResult
from illumio_ops.services.collect.cycle import begin, fail
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.windows import harvest
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import transaction
from illumio_ops.store.flowdb.flows import rebuild_rollup, upsert_flows

SOURCE = IngestSource.TRAFFIC
OVERLAP = timedelta(seconds=600)
COLD_START = timedelta(hours=24)
MAX_RESULTS = 200_000
QUERY_DEADLINE_SECONDS = 900
PCE_FAILURES = (PceQueryError, PceTransportError, PceBudgetExhausted)


def _now(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)


def fetch_traffic(client: PceClient, start: datetime, end: datetime, *, query_name: str) -> tuple[
        list[dict[str, Any]], int, list[tuple[datetime, datetime, int]]]:
    """Rows for [start, end] with cap splitting: (rows, windows queried, truncated windows)."""
    def fetch(a: datetime, b: datetime) -> tuple[list[dict[str, Any]], bool]:
        payload = traffic_payload(a, b, max_results=MAX_RESULTS, query_name=query_name)
        result = run_traffic_query(client, payload, deadline=time.monotonic() + QUERY_DEADLINE_SECONDS)
        return result.rows, result.capped
    h = harvest(fetch, start, end)
    return h.rows, h.windows, h.truncated


def normalize_all(rows: list[dict[str, Any]]) -> tuple[list[FlowRecord], int]:
    """Unique records (a record spanning a split point comes back from both halves, merged) and how
    many were unreadable."""
    records: dict[str, FlowRecord] = {}
    skipped = 0
    for raw in rows:
        try:
            r = normalize_flow(raw)
        except FlowShapeError as exc:
            skipped += 1
            logger.warning("skipped a traffic record the PCE sent without {}", exc)
            continue
        key = record_key(r)
        prev = records.get(key)
        records[key] = r if prev is None else merge_sightings(prev, r)
    return list(records.values()), skipped


def run_traffic_cycle(ctx: AppContext, *, now: datetime | None = None) -> CycleResult:
    settings = ctx.settings.current()  # one snapshot for the client and the binding check
    if not settings.collection.enabled:
        return CycleResult(0, 0, 0)
    try:
        client = ctx.pce_client(settings.pce)
    except PceNotConfigured:
        return CycleResult(0, 0, 0)
    at = _now(now)
    fdb = ctx.flows()
    start = begin(fdb, SOURCE, at, overlap=OVERLAP, cold_start=COLD_START)
    try:
        with client:
            rows, windows, truncated = fetch_traffic(client, start, at, query_name="illumio-ops traffic")
    except PCE_FAILURES as exc:
        fail(fdb, SOURCE, start, at, exc)
        logger.warning("traffic collection failed for {} – {}: {}", start, at, exc)
        return CycleResult(0, 0, 1)
    try:
        records, skipped = normalize_all(rows)
        with fdb.write_lock, fdb.connect() as conn:
            try:
                ensure_binding(conn, settings.pce, at)
            except BindingMismatch as exc:
                ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                logger.error("traffic collection refused: {}", exc)
                return CycleResult(0, windows, 0, skipped)
            # Flows, rollups, gaps and the watermark move together or not at all.
            with transaction(conn):
                stats = upsert_flows(conn, records, origin=DataOrigin.INGEST, now=at)
                for day in sorted(stats.days_touched):
                    rebuild_rollup(conn, day)
                for a, b, n in truncated:
                    ingest_state.record_gap(conn, SOURCE, a, b, "truncated",
                                            f"{n} rows returned at the PCE's per-query limit", at)
                ingest_state.resolve_failed_gaps(conn, SOURCE, start, at, at)
                ingest_state.mark_ok(conn, SOURCE, at, watermark=at, rows=len(records), progress={})
    except Exception as exc:
        fail(fdb, SOURCE, start, at, exc)
        raise
    return CycleResult(len(records), windows, len(truncated), skipped)
