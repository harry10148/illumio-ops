"""Daily re-read (P2 final review F12): the last settled UTC day is read once more, off-peak.

Live collection re-reads only its overlap (traffic 30 min, events 5 min), so a record that reaches
the PCE later — from a VEN that buffered while it was offline, say — would never be collected while
coverage says its window is complete. Once a day in the display time zone, from REREAD_LOCAL_HOUR,
the latest UTC day that ended at least SETTLE before is read again, for the sources the mode
collects live and from where the store's coverage of each begins.

It reads one hour at a time (memory and write-lock holds stay small at 1,000 workloads), compares
on a read connection and writes only what the store lacks: a record found late is live data
(origin ingest, so alerting sees it); a stored record that grew keeps its origin. Its progress is
kept with the backfill's, and one runs at a time (BACKFILL_LOCK). A failure is reported on the
backfill source and retried at the next check, at most MAX_ATTEMPTS times a day; it never records a
gap, because the windows it re-reads were collected.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from illumio_ops.domain.values import DataOrigin, IngestSource
from illumio_ops.pce.client import PceClient, PceNotConfigured
from illumio_ops.pce.events import events_timeout
from illumio_ops.services.collect import CycleResult, drops_stale
from illumio_ops.services.collect.backfill import BACKFILL_LOCK
from illumio_ops.services.collect.events import fetch_event_rows, normalize_events
from illumio_ops.services.collect.guard import BindingMismatch, ensure_binding
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.collect.traffic import (
    PCE_FAILURES,
    fetch_traffic,
    normalize_all,
)
from illumio_ops.services.context import AppContext
from illumio_ops.settings.schema import Settings
from illumio_ops.store.flowdb import ingest_state
from illumio_ops.store.flowdb.db import FlowDb, StaleGeneration, db_day, transaction
from illumio_ops.store.flowdb.events import unseen_events, upsert_events
from illumio_ops.store.flowdb.flows import refresh_rollups, split_unseen, upsert_flows

SOURCE = IngestSource.BACKFILL  # whose progress and status the re-read shares
PLAN = "reread"
LIVE = (IngestSource.TRAFFIC, IngestSource.EVENTS)
REREAD_LOCAL_HOUR = 3            # off-peak, in the display time zone
SETTLE = timedelta(hours=6)      # every record of the day had at least this long to reach the PCE
HOUR = timedelta(hours=1)
MAX_ATTEMPTS = 3                 # per day; a PCE that keeps failing is not queried all day
WRITE_BATCH = 20_000             # records per hold of the write lock


def _target(at: datetime) -> datetime:
    """Start of the latest UTC day that ended at least SETTLE before `at`."""
    return (at - SETTLE).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)


def _hours(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    out = []
    cur = start
    while cur < end:
        nxt = min(cur.replace(minute=0, second=0, microsecond=0) + HOUR, end)
        out.append((cur, nxt))
        cur = nxt
    return out


def ensure_daily_reread(ctx: AppContext, *, now: datetime | None = None) -> CycleResult | None:
    """Re-read the last settled day if tonight's re-read is due. None when nothing is due."""
    settings = ctx.settings.current()
    if not settings.collection.enabled:
        return None
    at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    local = at.astimezone(settings.display.zone())
    if local.hour < REREAD_LOCAL_HOUR:
        return None
    if not BACKFILL_LOCK.acquire(blocking=False):
        return None  # a backfill is running; the next check tries again
    try:
        return _reread(ctx, at=at, local_date=local.date().isoformat())
    finally:
        BACKFILL_LOCK.release()


def _reread(ctx: AppContext, *, at: datetime, local_date: str) -> CycleResult | None:
    gen = ctx.flows().generation  # noted before the settings it goes with (FlowDb.generation)
    settings = ctx.settings.current()
    fdb = ctx.flows()
    with fdb.connect() as conn:
        state = ingest_state.get(conn, SOURCE)
        ranges = {src: ingest_state.coverage(conn, src) for src in LIVE if collects(settings, src)}
    plans: dict[str, Any] = dict(state.progress or {}) if state else {}
    initial = plans.get("initial")
    if initial and not initial.get("finished"):
        return None  # the initial backfill reads these days itself
    mine = plans.get(PLAN)
    if mine and mine.get("local_date") == local_date:
        if mine.get("finished") or mine.get("attempts", 0) >= MAX_ATTEMPTS:
            return None
    else:
        day = _target(at)
        mine = {"day": day.date().isoformat(), "local_date": local_date, "done_through": day.isoformat(),
                "finished": False, "attempts": 0}
    start = datetime.fromisoformat(mine["day"]).replace(tzinfo=UTC)
    end = start + timedelta(days=1)
    # Only where the store claims to have collected: a day nobody collected is not re-read.
    begins = {src: max(start, r[0][0]) for src, r in ranges.items() if any(a < end and b > start for a, b in r)}
    if not begins:
        return None
    try:
        client = ctx.pce_client(settings.pce)
    except PceNotConfigured:
        return None
    return _read_day(fdb, gen, settings, client, plans, mine, begins, end, at)


@drops_stale
def _read_day(fdb: FlowDb, gen: int, settings: Settings, client: PceClient, plans: dict[str, Any],
              mine: dict[str, Any], begins: dict[IngestSource, datetime], end: datetime,
              at: datetime) -> CycleResult:
    def failed(error: str) -> None:
        plans[PLAN] = {**mine, "attempts": mine["attempts"] + 1}
        with fdb.writing(gen) as conn:
            ingest_state.set_progress(conn, SOURCE, plans)
            ingest_state.mark_failed(conn, SOURCE, at, f"re-read of {mine['day']}: {error}")
        logger.warning("re-read of {} stopped: {}", mine["day"], error)

    with fdb.writing(gen) as conn:
        ingest_state.mark_started(conn, SOURCE, at)
        plans[PLAN] = mine
        ingest_state.set_progress(conn, SOURCE, plans)
    resume = max(datetime.fromisoformat(mine["done_through"]), min(begins.values()))
    timeout = events_timeout(settings.pce)
    frozen = db_day(at - timedelta(days=settings.collection.retention.flow_days))
    rows = windows = gaps = skipped = 0
    with client:
        for a, b in _hours(resume, end):
            reads = {src: max(a, s) for src, s in begins.items() if s < b}
            try:
                t_rows, w1, t_trunc = (fetch_traffic(client, reads[IngestSource.TRAFFIC], b,
                                                     query_name="illumio-ops re-read")
                                       if IngestSource.TRAFFIC in reads else ([], 0, []))
                e_rows, w2, e_trunc = (fetch_event_rows(client, reads[IngestSource.EVENTS], b, timeout=timeout)
                                       if IngestSource.EVENTS in reads else ([], 0, []))
            except PCE_FAILURES as exc:
                failed(str(exc))
                return CycleResult(rows, windows, gaps, skipped)
            try:
                flows, s1 = normalize_all(t_rows)
                events, s2 = normalize_events(e_rows)
                with fdb.connect() as conn:  # compared outside the write lock
                    new, grown = split_unseen(conn, flows)
                    fresh = unseen_events(conn, events)
                # A late record is live data; a stored one that grew keeps its origin (backfill never
                # turns an ingest row into a backfill one).
                batches = [(new[i:i + WRITE_BATCH], DataOrigin.INGEST) for i in range(0, len(new), WRITE_BATCH)]
                batches += [(grown[i:i + WRITE_BATCH], DataOrigin.BACKFILL) for i in range(0, len(grown), WRITE_BATCH)]
                for batch, origin in batches:
                    with fdb.writing(gen) as conn:
                        try:
                            ensure_binding(conn, settings.pce, at)
                        except BindingMismatch as exc:
                            ingest_state.mark_failed(conn, SOURCE, at, f"binding: {exc}")
                            return CycleResult(rows, windows, gaps, skipped)
                        upsert_flows(conn, batch, origin=origin, now=at)
                    rows += len(batch)
                with fdb.writing(gen) as conn, transaction(conn):
                    rows += upsert_events(conn, fresh, origin=DataOrigin.INGEST, now=at) if fresh else 0
                    for src, trunc in ((IngestSource.TRAFFIC, t_trunc), (IngestSource.EVENTS, e_trunc)):
                        for ta, tb, n in trunc:
                            ingest_state.record_gap(conn, src, ta, tb, "truncated", f"re-read: {n} rows at the limit", at)
                    for src, s in reads.items():
                        ingest_state.resolve_failed_gaps(conn, src, s, b, at)
                        ingest_state.add_coverage(conn, src, s, b)
                    mine = {**mine, "done_through": b.isoformat()}
                    plans[PLAN] = mine
                    ingest_state.set_progress(conn, SOURCE, plans)
            except StaleGeneration:
                raise
            except Exception as exc:
                failed(f"{type(exc).__name__}: {exc}")
                raise
            windows += w1 + w2
            gaps += len(t_trunc) + len(e_trunc)
            skipped += s1 + s2
    with fdb.writing(gen) as conn, transaction(conn):
        refresh_rollups(conn, at, frozen_through=frozen)  # the day's rollup, rebuilt once if it changed
        plans[PLAN] = {**mine, "finished": True}
        ingest_state.mark_ok(conn, SOURCE, at, watermark=None, rows=rows, progress=plans)
    return CycleResult(rows, windows, gaps, skipped)
