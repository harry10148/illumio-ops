"""Retention: drop collected data past its configured age. With archiving on, a day is only
dropped after it has been archived. Expired flows go in batches, each in its own hold of the write
lock: one 1M-row day in a single hold took 46 min at 1M rows/day, and collection waited throughout."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger

from illumio_ops.services.collect.backfill import BACKFILL_LOCK
from illumio_ops.services.context import AppContext
from illumio_ops.services.siem import guard as siem_guard
from illumio_ops.store.flowdb import (
    analysis,
    archive,
    ingest_state,
    ransomware,
    workloads,
)
from illumio_ops.store.flowdb.db import FlowDb, StaleGeneration, db_day
from illumio_ops.store.flowdb.events import (
    count_live_events_before,
    delete_events_before,
)
from illumio_ops.store.flowdb.flows import (
    NEW_CONNECTION_LOG_KEEP,
    count_new_connection_log_before,
    delete_baselines_before,
    delete_connections_before,
    delete_new_connection_log_before,
    delete_rollups_before,
    expired_page,
)

FLOW_BATCH = 20_000  # expired flow rows per hold of the write lock


def run_retention(ctx: AppContext, *, now: datetime | None = None) -> dict[str, int]:
    # A backfill writes a day an hour at a time and builds its rollup with the last hour: rows of a
    # day past the raw cutoff deleted in between would leave a partial rollup, kept rollup_days.
    with BACKFILL_LOCK:
        return _run_retention(ctx, now=now)


def _run_retention(ctx: AppContext, *, now: datetime | None) -> dict[str, int]:
    c = ctx.settings.current().collection
    r = c.retention
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb = ctx.flows()
    gen = fdb.generation  # a PCE switch empties the store; see FlowDb.generation
    rollup_day = db_day(at - timedelta(days=r.rollup_days))
    try:
        flows = _expire_flows(fdb, gen, at - timedelta(days=r.flow_days), c.archive.enabled)
        with fdb.writing(gen) as conn:
            event_days = archive.archived_days(conn, "events") if c.archive.enabled else None
            event_cut, detection_cut = at - timedelta(days=r.event_days), at - timedelta(days=r.event_days)
            log_cut = at - NEW_CONNECTION_LOG_KEEP
            # What goes before a SIEM destination sent it is counted on its cursor (it never holds retention back).
            dropped = {
                **siem_guard.expiring(ctx, "audit", lambda after, _d: count_live_events_before(
                    conn, event_cut, archived_days=event_days, after_id=after)),
                **siem_guard.expiring(ctx, "detections", lambda after, _d: analysis.count_detections_before(
                    conn, detection_cut, after_id=after)),
                **siem_guard.expiring(ctx, "new_connections", lambda after, d: count_new_connection_log_before(
                    conn, log_cut, after_id=after, decisions=[x.value for x in d.new_connection_decisions],
                    internal_only=d.new_connection_internal_only)),
            }
            out = {
                "flows": flows,
                "events": delete_events_before(conn, event_cut, archived_days=event_days),
                "rollups": delete_rollups_before(conn, rollup_day),
                "snapshots": workloads.delete_snapshots_before(conn, rollup_day)
                + ransomware.delete_snapshots_before(conn, rollup_day),
                "baselines": delete_baselines_before(conn, at - timedelta(days=r.baseline_days)),
                "new_connection_log": delete_new_connection_log_before(conn, log_cut),
                # Kept as long as the baseline too: the analysis looks back that far and must still see a
                # failed read there (alert mode keeps rollups shorter than the baseline).
                "gaps": ingest_state.delete_gaps_before(conn, at - timedelta(days=max(r.rollup_days, r.baseline_days))),
                "analysis": analysis.delete_expired(conn, detections_before=detection_cut,
                                                    focus_before=at - timedelta(days=r.event_days),
                                                    snapshot_day_before=rollup_day),
            }
        siem_guard.record_dropped(ctx, dropped)
        return out
    except StaleGeneration:
        logger.info("retention: the PCE was switched while it ran; the store was emptied anyway")
        return {}


def _expire_flows(fdb: FlowDb, gen: int, cutoff: datetime, archive_enabled: bool) -> int:
    deleted, after = 0, ("", 0)
    while True:
        with fdb.connect() as conn:  # reading needs no lock
            page = expired_page(conn, cutoff, after, FLOW_BATCH)
        if not page:
            return deleted
        after = (page[-1]["last_detected"], page[-1]["id"])
        keys = list(dict.fromkeys(row["conn_key"] for row in page))
        with fdb.writing(gen) as conn:  # archived days re-read per batch: a backfill can mark one stale
            archived = archive.archived_days(conn, "flows") if archive_enabled else None
            deleted += delete_connections_before(conn, cutoff, conn_keys=keys, archived_days=archived)
