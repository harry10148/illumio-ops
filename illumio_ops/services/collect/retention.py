"""Retention: drop collected data past its configured age. With archiving on, a day is only
dropped after it has been archived."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from illumio_ops.services.context import AppContext
from illumio_ops.store.flowdb import archive, ingest_state, ransomware, workloads
from illumio_ops.store.flowdb.db import db_day
from illumio_ops.store.flowdb.events import delete_events_before
from illumio_ops.store.flowdb.flows import (
    delete_baselines_before,
    delete_connections_before,
    delete_rollups_before,
)


def run_retention(ctx: AppContext, *, now: datetime | None = None) -> dict[str, int]:
    c = ctx.settings.current().collection
    r = c.retention
    at = (now or datetime.now(UTC)).astimezone(UTC)
    fdb = ctx.flows()
    rollup_day = db_day(at - timedelta(days=r.rollup_days))
    with fdb.write_lock, fdb.connect() as conn:
        flows_days = archive.archived_days(conn, "flows") if c.archive.enabled else None
        event_days = archive.archived_days(conn, "events") if c.archive.enabled else None
        return {
            "flows": delete_connections_before(conn, at - timedelta(days=r.flow_days), archived_days=flows_days),
            "events": delete_events_before(conn, at - timedelta(days=r.event_days), archived_days=event_days),
            "rollups": delete_rollups_before(conn, rollup_day),
            "snapshots": workloads.delete_snapshots_before(conn, rollup_day)
            + ransomware.delete_snapshots_before(conn, rollup_day),
            "baselines": delete_baselines_before(conn, at - timedelta(days=r.baseline_days)),
            "gaps": ingest_state.delete_gaps_before(conn, at - timedelta(days=r.rollup_days)),
        }
