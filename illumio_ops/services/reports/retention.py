"""How long generated reports are kept (spec §6.4: every output has a retention period) and removing one."""
from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from typing import Literal

from loguru import logger

from illumio_ops.domain.values import ReportStatus
from illumio_ops.services.context import AppContext
from illumio_ops.store import reports as store


def _remove_files(ctx: AppContext, report_ids: list[int]) -> None:
    for rid in report_ids:
        shutil.rmtree(ctx.paths.reports_dir / str(rid), ignore_errors=True)


def run_report_retention(ctx: AppContext, *, now: datetime | None = None) -> int:
    """Remove reports (rows and files) older than reports.retention_days or beyond their schedule's keep; a
    running one waits for the next day.
    Directories that are not a known report's are never touched."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    settings = ctx.settings.current().reports
    with ctx.db() as conn:
        ids = store.ids_created_before(conn, at - timedelta(days=settings.retention_days))
        for s in settings.schedules:  # each schedule also keeps only its newest `keep` reports
            ids += store.ids_beyond_keep(conn, s.id, s.keep)
        gone = store.delete(conn, sorted(set(ids)))
    _remove_files(ctx, gone)
    if gone:  # a removal leaves no row behind: the log is the only trace of what went and why
        logger.info("reports: retention removed {} report(s) older than {} days or beyond their schedule's keep: {}",
                    len(gone), settings.retention_days, ", ".join(f"#{i}" for i in gone))
    return len(gone)


def remove_report(ctx: AppContext, report_id: int, *, by: str,
                  created_at: datetime | None = None) -> Literal["removed", "running", "missing"]:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
        if row is None or (created_at is not None and row.created_at != created_at):
            return "missing"
        if row.status is ReportStatus.RUNNING:
            return "running"
        gone = store.delete(conn, [report_id], created_at={report_id: created_at} if created_at is not None else None)
        if not gone:
            current = store.get(conn, report_id)
            if current is not None and current.created_at == row.created_at and current.status is ReportStatus.RUNNING:
                return "running"
            return "missing"
    _remove_files(ctx, [report_id])
    logger.info("reports: #{} ({}) removed by {}", report_id, row.report_type, by)
    return "removed"
