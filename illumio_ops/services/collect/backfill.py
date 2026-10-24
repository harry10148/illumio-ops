"""Backfill: read history the live collectors never saw, one UTC day at a time, oldest first.

Rows are marked origin=backfill: they seed the baseline and the exposure graph (spec §6.4) but
never enter alert evaluation (spec §7). Progress survives restarts; the live watermarks never move.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger

from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.client import PceNotConfigured
from illumio_ops.pce.events import events_timeout
from illumio_ops.services.collect import CycleResult
from illumio_ops.services.collect.events import fetch_event_rows, normalize_events
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.traffic import (
    PCE_FAILURES,
    fetch_traffic,
    normalize_all,
)
from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.events import upsert_events
from illumio_ops.store.flowdb.flows import rebuild_rollup, upsert_flows

SOURCE = IngestSource.BACKFILL


def _days(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    out = []
    cur = start
    while cur < end:
        next_midnight = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        out.append((cur, min(next_midnight, end)))
        cur = next_midnight
    return out


def run_backfill(ctx: AppContext, *, start: datetime, end: datetime, now: datetime | None = None) -> CycleResult:
    settings = ctx.settings.current()
    if not settings.collection.enabled:
        return CycleResult(0, 0, 0)
    try:
        client = ctx.pce_client()
    except PceNotConfigured:
        return CycleResult(0, 0, 0)
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    start, end = start.astimezone(UTC).replace(microsecond=0), end.astimezone(UTC).replace(microsecond=0)
    fdb = ctx.flows()
    with fdb.connect() as conn:
        state = ingest_state.get(conn, SOURCE)
        ingest_state.mark_started(conn, SOURCE, at)
    progress = state.progress if state and state.progress else None
    resume_from = start
    if progress and progress.get("start") == start.isoformat() and progress.get("end") == end.isoformat():
        resume_from = datetime.fromisoformat(progress["done_through"])
    rows = windows = gaps = skipped = 0
    with client:
        for a, b in _days(resume_from, end):
            try:
                traffic_rows, w1, t_trunc = fetch_traffic(client, a, b, query_name="illumio-ops backfill")
                event_rows, w2, e_trunc = fetch_event_rows(client, a, b, timeout=events_timeout(settings.pce))
            except PCE_FAILURES as exc:
                with fdb.write_lock, fdb.connect() as conn:
                    ingest_state.record_gap(conn, IngestSource.TRAFFIC, a, b, "failed", f"backfill: {exc}", at)
                    ingest_state.mark_failed(conn, SOURCE, at, str(exc))
                logger.warning("backfill stopped at {}: {}", a, exc)
                return CycleResult(rows, windows, gaps + 1, skipped)
            flows, s1 = normalize_all(traffic_rows)
            events, s2 = normalize_events(event_rows)
            with fdb.write_lock, fdb.connect() as conn:
                try:
                    ensure_binding(conn, settings.pce, at)
                except BindingMismatch as exc:
                    ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                    return CycleResult(rows, windows, gaps, skipped)
                stats = upsert_flows(conn, flows, origin=DataOrigin.BACKFILL, now=at)
                for day in sorted(stats.days_touched):
                    rebuild_rollup(conn, day)
                upsert_events(conn, events, origin=DataOrigin.BACKFILL, now=at)
                for src, trunc in ((IngestSource.TRAFFIC, t_trunc), (IngestSource.EVENTS, e_trunc)):
                    for ta, tb, n in trunc:
                        ingest_state.record_gap(conn, src, ta, tb, "truncated", f"backfill: {n} rows at the limit", at)
                ingest_state.set_progress(conn, SOURCE, {"start": start.isoformat(), "end": end.isoformat(),
                                                         "done_through": b.isoformat(), "finished": False})
            rows += len(flows) + len(events)
            windows += w1 + w2
            gaps += len(t_trunc) + len(e_trunc)
            skipped += s1 + s2
    with fdb.write_lock, fdb.connect() as conn:
        ingest_state.mark_ok(conn, SOURCE, at, watermark=None, rows=rows,
                             progress={"start": start.isoformat(), "end": end.isoformat(),
                                       "done_through": end.isoformat(), "finished": True})
    return CycleResult(rows, windows, gaps, skipped)


def ensure_initial_backfill(ctx: AppContext, *, now: datetime | None = None) -> CycleResult | None:
    """Run the first backfill of a binding (backfill_days back from the live watermark), or resume an
    unfinished one. Returns None when there is nothing to do."""
    settings = ctx.settings.current()
    if not settings.collection.enabled or settings.collection.backfill_days == 0:
        return None
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    with ctx.flows().connect() as conn:
        state = ingest_state.get(conn, SOURCE)
        traffic = ingest_state.get(conn, IngestSource.TRAFFIC)
    progress = state.progress if state and state.progress else None
    if progress:
        if progress.get("finished"):
            return None
        return run_backfill(ctx, start=datetime.fromisoformat(progress["start"]),
                            end=datetime.fromisoformat(progress["end"]), now=at)
    end = traffic.watermark if traffic and traffic.watermark else at
    return run_backfill(ctx, start=end - timedelta(days=settings.collection.backfill_days), end=end, now=at)
