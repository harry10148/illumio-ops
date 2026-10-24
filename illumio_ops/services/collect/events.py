"""Events collector: pull PCE audit events since the watermark into the flow database.

At its row cap the PCE returns only the newest events of a window, so a capped window is split.
"""
from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from illumio_ops.domain.events import EventRecord, EventShapeError, normalize_event
from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.capabilities import detect_tamper_signal
from illumio_ops.pce.client import PceClient, PceNotConfigured
from illumio_ops.pce.events import EVENTS_PAGE_LIMIT, events_timeout, fetch_events
from illumio_ops.services.collect import CycleResult
from illumio_ops.services.collect.cycle import begin, fail
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.collect.windows import harvest
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import capabilities, ingest_state
from illumio_ops.store.flowdb.db import transaction
from illumio_ops.store.flowdb.events import upsert_events

SOURCE = IngestSource.EVENTS
OVERLAP = timedelta(seconds=300)
COLD_START = timedelta(hours=24)
EVENTS_PAGE = EVENTS_PAGE_LIMIT
FETCH_DEADLINE_SECONDS = 900


def fetch_event_rows(client: PceClient, start: datetime, end: datetime, *, timeout: float) -> tuple[
        list[dict[str, Any]], int, list[tuple[datetime, datetime, int]]]:
    def fetch(a: datetime, b: datetime) -> tuple[list[dict[str, Any]], bool]:
        page = fetch_events(client, start=a, end=b, timeout=timeout,
                            deadline=time.monotonic() + FETCH_DEADLINE_SECONDS, max_results=EVENTS_PAGE)
        return page.items, page.capped
    h = harvest(fetch, start, end)
    return h.rows, h.windows, h.truncated


def normalize_events(rows: list[dict[str, Any]]) -> tuple[list[EventRecord], int]:
    """Unique events (split windows share their boundary second) and how many were unreadable."""
    records: dict[str, EventRecord] = {}
    skipped = 0
    for raw in rows:
        try:
            r = normalize_event(raw)
        except EventShapeError as exc:
            skipped += 1
            logger.warning("skipped an event the PCE sent without {}", exc)
            continue
        records[r.href] = r
    return list(records.values()), skipped


def run_events_cycle(ctx: AppContext, *, now: datetime | None = None) -> CycleResult:
    settings = ctx.settings.current()  # one snapshot for the client and the binding check
    if not settings.collection.enabled:
        return CycleResult(0, 0, 0)
    try:
        client = ctx.pce_client(settings.pce)
    except PceNotConfigured:
        return CycleResult(0, 0, 0)
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    fdb = ctx.flows()
    start, done_progress = begin(fdb, SOURCE, at, overlap=OVERLAP, cold_start=COLD_START)
    try:
        with client:
            rows, windows, truncated = fetch_event_rows(client, start, at, timeout=events_timeout(settings.pce))
    except PCE_FAILURES as exc:
        fail(fdb, SOURCE, start, at, exc)
        logger.warning("events collection failed for {} – {}: {}", start, at, exc)
        return CycleResult(0, 0, 1)
    try:
        records, skipped = normalize_events(rows)
        with fdb.write_lock, fdb.connect() as conn:
            try:
                ensure_binding(conn, settings.pce, at)
            except BindingMismatch as exc:
                ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                logger.error("events collection refused: {}", exc)
                return CycleResult(0, windows, 0, skipped)
            with transaction(conn):
                written = upsert_events(conn, records, origin=DataOrigin.INGEST, now=at)
                signal = detect_tamper_signal(r.tamper_classification for r in records)
                if signal is not None:
                    capabilities.record(conn, "tamper_signal", signal, None, at)
                for a, b, n in truncated:
                    ingest_state.record_gap(conn, SOURCE, a, b, "truncated",
                                            f"{n} events returned at the PCE's per-request limit", at)
                ingest_state.resolve_failed_gaps(conn, SOURCE, start, at, at)
                ingest_state.add_coverage(conn, SOURCE, start, at)
                ingest_state.mark_ok(conn, SOURCE, at, watermark=at, rows=written, progress=done_progress)
    except Exception as exc:
        fail(fdb, SOURCE, start, at, exc)
        raise
    return CycleResult(len(records), windows, len(truncated), skipped)
