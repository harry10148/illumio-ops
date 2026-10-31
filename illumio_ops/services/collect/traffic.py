"""Traffic collector: pull flows since the watermark into the flow database.

Window [watermark - 30 min, now] (records reach the PCE late; the overlap re-reads them), read an
hour at a time when it is longer (a cold start, a catch-up). A failed window records a gap and leaves the watermark where it was; a window
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
from illumio_ops.services.analysis.context import baseline_full
from illumio_ops.services.collect import CycleResult, drops_stale
from illumio_ops.services.collect.cycle import begin, fail
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.collect.windows import harvest, slices
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import StaleGeneration, db_day, transaction
from illumio_ops.store.flowdb.flows import refresh_rollups, upsert_flows

SOURCE = IngestSource.TRAFFIC
CATCH_UP_IS_LATE = timedelta(hours=1)
# Records reach the PCE up to ~18 min after they happen (P2 Task 15 probe on lab: 32% later than
# 10 min); a record is caught in every cycle phase only if its delay is within the overlap.
OVERLAP = timedelta(minutes=30)
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


@drops_stale
def run_traffic_cycle(ctx: AppContext, *, now: datetime | None = None) -> CycleResult:
    gen = ctx.flows().generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()  # one snapshot for the client and the binding check
    if not collects(settings, IngestSource.TRAFFIC):
        return CycleResult(0, 0, 0)
    try:
        client = ctx.pce_client(settings.pce)
    except PceNotConfigured:
        return CycleResult(0, 0, 0)
    at = _now(now)
    fdb = ctx.flows()
    start, done_progress = begin(fdb, SOURCE, at, overlap=OVERLAP, cold_start=COLD_START, generation=gen)
    pieces = slices(start, at)  # a cold start or a catch-up is read and written an hour at a time
    log_new = baseline_full(ctx)  # the SIEM's new connections: only once "first seen in the period" holds
    rows = windows = gaps = skipped = 0
    with client:
        for a, b in pieces:
            try:
                raw, w, truncated = fetch_traffic(client, a, b, query_name="illumio-ops traffic")
            except PCE_FAILURES as exc:
                fail(fdb, SOURCE, a, at, exc, generation=gen)  # nothing from a on was read
                logger.warning("traffic collection failed for {} – {}: {}", a, at, exc)
                return CycleResult(rows, windows, gaps + 1, skipped)
            try:
                records, s = normalize_all(raw)
                with fdb.writing(gen) as conn:
                    try:
                        ensure_binding(conn, settings.pce, at)
                    except BindingMismatch as exc:
                        ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                        logger.error("traffic collection refused: {}", exc)
                        return CycleResult(rows, windows + w, gaps, skipped + s)
                    # Flows, gaps and the watermark move together or not at all; the rollups once a
                    # cycle (a dirty day stays dirty until a cycle rebuilds it).
                    with transaction(conn):
                        # A catch-up hour that ended long ago is late data: its growth would look like a
                        # burst happening now, so threshold rules do not count it (P4 plan, alert semantics).
                        upsert_flows(conn, records, origin=DataOrigin.INGEST, now=at,
                                     increments="cycle" if b > at - CATCH_UP_IS_LATE else "late",
                                     log_new_connections=log_new)
                        if b == at:
                            refresh_rollups(conn, at, frozen_through=db_day(
                                at - timedelta(days=settings.collection.retention.flow_days)))
                        for ta, tb, n in truncated:
                            ingest_state.record_gap(conn, SOURCE, ta, tb, "truncated",
                                                    f"{n} rows returned at the PCE's per-query limit", at)
                        ingest_state.add_coverage(conn, SOURCE, a, b)
                        ingest_state.resolve_covered_gaps(conn, SOURCE, at)
                        ingest_state.mark_ok(conn, SOURCE, at, watermark=b, rows=rows + len(records),
                                             progress=done_progress)
            except StaleGeneration:
                raise
            except Exception as exc:
                fail(fdb, SOURCE, a, at, exc, generation=gen)
                raise
            rows += len(records)
            windows += w
            gaps += len(truncated)
            skipped += s
    return CycleResult(rows, windows, gaps, skipped)
