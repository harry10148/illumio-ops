"""Backfill: read history the live collectors never saw, one UTC day at a time, oldest first.

Rows are marked origin=backfill: they seed the baseline and the exposure graph (spec §6.4) but
never enter alert evaluation (spec §7). Progress survives restarts; the live watermarks never move.
The initial backfill (started by the periodic check) and one started by hand keep separate
progress, so a hand-started one never makes an unfinished initial one look done.
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from loguru import logger

from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.events import events_timeout
from illumio_ops.services.collect import CycleResult, drops_stale
from illumio_ops.services.collect.events import fetch_event_rows, normalize_events
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.mode import backfill_sources
from illumio_ops.services.collect.traffic import (
    PCE_FAILURES,
    fetch_traffic,
    normalize_all,
)
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb, StaleGeneration, transaction
from illumio_ops.store.flowdb.events import upsert_events
from illumio_ops.store.flowdb.flows import refresh_rollups, upsert_flows

SOURCE = IngestSource.BACKFILL
Plan = Literal["initial", "manual"]
# One backfill at a time, whether started by the periodic check or from the collection page.
BACKFILL_LOCK = threading.Lock()


def _days(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    out = []
    cur = start
    while cur < end:
        next_midnight = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        out.append((cur, min(next_midnight, end)))
        cur = next_midnight
    return out


def run_backfill(ctx: AppContext, *, start: datetime, end: datetime, plan: Plan = "manual",
                 sources: tuple[IngestSource, ...] | None = None, now: datetime | None = None) -> CycleResult:
    """Read [start, end] one day at a time. `sources` defaults to what the collection mode backfills
    (services.collect.mode.backfill_sources)."""
    if not BACKFILL_LOCK.acquire(blocking=False):
        logger.info("a backfill is already running; this one was not started")
        return CycleResult(0, 0, 0)
    try:
        return _run_backfill(ctx, start=start, end=end, plan=plan, sources=sources, now=now)
    finally:
        BACKFILL_LOCK.release()


def _record_failure(fdb: FlowDb, gen: int, sources: tuple[IngestSource, ...], a: datetime, b: datetime,
                    at: datetime, error: str) -> None:
    """None of the day's sources was stored: each gets the gap, resolved when a retry succeeds."""
    with fdb.writing(gen) as conn:
        for src in sources:
            ingest_state.record_gap(conn, src, a, b, "failed", f"backfill: {error}", at)
        ingest_state.mark_failed(conn, SOURCE, at, error)


@drops_stale
def _run_backfill(ctx: AppContext, *, start: datetime, end: datetime, plan: Plan,
                  sources: tuple[IngestSource, ...] | None, now: datetime | None) -> CycleResult:
    gen = ctx.flows().generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    if not settings.collection.enabled:
        return CycleResult(0, 0, 0)
    try:
        client = ctx.pce_client(settings.pce)
    except PceNotConfigured:
        return CycleResult(0, 0, 0)
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    start, end = start.astimezone(UTC).replace(microsecond=0), end.astimezone(UTC).replace(microsecond=0)
    reads = sources or backfill_sources(settings, manual=plan == "manual")
    names = sorted(str(s) for s in reads)
    fdb = ctx.flows()
    with fdb.writing(gen) as conn:
        state = ingest_state.get(conn, SOURCE)
        ingest_state.mark_started(conn, SOURCE, at)
        plans: dict[str, Any] = dict(state.progress or {}) if state else {}
        mine = plans.get(plan)
        if (mine and not mine.get("finished") and mine.get("start") == start.isoformat()
                and mine.get("end") == end.isoformat() and mine.get("sources") == names):
            resume_from = datetime.fromisoformat(mine["done_through"])
        else:  # pinned before the first PCE call, so a failed first day retries the same range
            resume_from = start
            plans[plan] = {"start": start.isoformat(), "end": end.isoformat(), "done_through": start.isoformat(),
                           "finished": False, "sources": names}
            ingest_state.set_progress(conn, SOURCE, plans)
    rows = windows = gaps = skipped = 0
    with client:
        for a, b in _days(resume_from, end):
            try:
                traffic_rows, w1, t_trunc = (fetch_traffic(client, a, b, query_name="illumio-ops backfill")
                                             if IngestSource.TRAFFIC in reads else ([], 0, []))
                event_rows, w2, e_trunc = fetch_event_rows(client, a, b, timeout=events_timeout(settings.pce))
            except PCE_FAILURES as exc:
                _record_failure(fdb, gen, reads, a, b, at, str(exc))
                logger.warning("backfill stopped at {}: {}", a, exc)
                return CycleResult(rows, windows, gaps + 1, skipped)
            try:
                flows, s1 = normalize_all(traffic_rows)
                events, s2 = normalize_events(event_rows)
                with fdb.writing(gen) as conn:
                    try:
                        ensure_binding(conn, settings.pce, at)
                    except BindingMismatch as exc:
                        ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                        return CycleResult(rows, windows, gaps, skipped)
                    with transaction(conn):  # one day lands completely or not at all
                        upsert_flows(conn, flows, origin=DataOrigin.BACKFILL, now=at)
                        refresh_rollups(conn, at)
                        upsert_events(conn, events, origin=DataOrigin.BACKFILL, now=at)
                        for src, trunc in ((IngestSource.TRAFFIC, t_trunc), (IngestSource.EVENTS, e_trunc)):
                            for ta, tb, n in trunc:
                                ingest_state.record_gap(conn, src, ta, tb, "truncated",
                                                        f"backfill: {n} rows at the limit", at)
                        for src in reads:
                            ingest_state.resolve_failed_gaps(conn, src, a, b, at)
                            ingest_state.add_coverage(conn, src, a, b)
                        plans[plan] = {**plans[plan], "done_through": b.isoformat()}
                        ingest_state.set_progress(conn, SOURCE, plans)
            except StaleGeneration:
                raise
            except Exception as exc:
                _record_failure(fdb, gen, reads, a, b, at, f"{type(exc).__name__}: {exc}")
                raise
            rows += len(flows) + len(events)
            windows += w1 + w2
            gaps += len(t_trunc) + len(e_trunc)
            skipped += s1 + s2
    with fdb.writing(gen) as conn:
        plans[plan] = {**plans[plan], "done_through": end.isoformat(), "finished": True}
        if plan == "initial":  # what the initial backfills have read so far, whatever the mode was
            plans["initial_done"] = sorted({*plans.get("initial_done", []), *names})
        ingest_state.mark_ok(conn, SOURCE, at, watermark=None, rows=rows, progress=plans)
    return CycleResult(rows, windows, gaps, skipped)


def ensure_initial_backfill(ctx: AppContext, *, now: datetime | None = None) -> CycleResult | None:
    """Run the first backfill of a binding (backfill_days back from the live watermark), resume an
    unfinished one, or backfill a source the mode now reads that no initial backfill has read yet
    (events only → full). Returns None when there is nothing to do."""
    settings = ctx.settings.current()
    if not settings.collection.enabled or settings.collection.backfill_days == 0:
        return None
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    with ctx.flows().connect() as conn:
        state = ingest_state.get(conn, SOURCE)
        marks = {src: ingest_state.get(conn, src) for src in (IngestSource.TRAFFIC, IngestSource.EVENTS)}
    progress = (state.progress or {}) if state else {}
    initial = progress.get("initial")
    if initial and not initial.get("finished"):
        # Only what the mode still backfills; a source dropped here is not marked done, so a switch
        # back to full mode backfills it then.
        allowed = backfill_sources(settings, manual=False)
        resumed = tuple(src for s in initial.get("sources", []) if (src := IngestSource(s)) in allowed)
        return run_backfill(ctx, start=datetime.fromisoformat(initial["start"]),
                            end=datetime.fromisoformat(initial["end"]), plan="initial",
                            sources=resumed or None, now=at)
    done = set(progress.get("initial_done", []))
    missing = tuple(s for s in backfill_sources(settings, manual=False) if str(s) not in done)
    if not missing:
        return None
    end = next((m.watermark for src in missing if (m := marks[src]) is not None and m.watermark), at)
    return run_backfill(ctx, start=end - timedelta(days=settings.collection.backfill_days), end=end,
                        plan="initial", sources=missing, now=at)
