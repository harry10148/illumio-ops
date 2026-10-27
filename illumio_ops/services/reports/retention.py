"""How long generated reports are kept (spec §6.4: every output has a retention period) and removing one."""
from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from typing import Literal

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
        ids = sorted(set(ids))
        store.delete(conn, ids)
    _remove_files(ctx, ids)
    return len(ids)


def remove_report(ctx: AppContext, report_id: int) -> Literal["removed", "running", "missing"]:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
        if row is None:
            return "missing"
        if row.status is ReportStatus.RUNNING:
            return "running"
        store.delete(conn, [report_id])
    _remove_files(ctx, [report_id])
    return "removed"
