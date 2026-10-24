"""Retention: drop collected data past its configured age. With archiving on, a day is only
dropped after it has been archived. Expired flows go in batches, each in its own hold of the write
lock: one 1M-row day in a single hold took 46 min at 1M rows/day, and collection waited throughout."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger

from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import archive, ingest_state, ransomware, workloads
from illumio_ops.store.flowdb.db import FlowDb, StaleGeneration, db_day
from illumio_ops.store.flowdb.events import delete_events_before
from illumio_ops.store.flowdb.flows import (
    delete_baselines_before,
    delete_connections_before,
    delete_rollups_before,
    expired_page,
)

FLOW_BATCH = 20_000  # expired flow rows per hold of the write lock


def run_retention(ctx: AppContext, *, now: datetime | None = None) -> dict[str, int]:
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
            return {
                "flows": flows,
                "events": delete_events_before(conn, at - timedelta(days=r.event_days), archived_days=event_days),
                "rollups": delete_rollups_before(conn, rollup_day),
                "snapshots": workloads.delete_snapshots_before(conn, rollup_day)
                + ransomware.delete_snapshots_before(conn, rollup_day),
                "baselines": delete_baselines_before(conn, at - timedelta(days=r.baseline_days)),
                "gaps": ingest_state.delete_gaps_before(conn, at - timedelta(days=r.rollup_days)),
            }
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
