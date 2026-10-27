"""What the reports page reads: the catalog with what is available now, the report list and one report."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from illumio_ops.domain.values import Language, ReportStatus, ReportType
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.generate import availability, enqueue
from illumio_ops.services.reports.registry import ReportParams, specs
from illumio_ops.store import reports as store

PAGE_SIZE = 50


class CatalogEntry(BaseModel):
    report_type: ReportType
    group: str
    available: bool
    reason_key: str | None


class Catalog(BaseModel):
    entries: list[CatalogEntry]
    smtp_enabled: bool
    gui_external_url_set: bool


class ReportItem(BaseModel):
    id: int
    report_type: str
    status: ReportStatus
    trigger: str
    schedule_id: str | None
    schedule_name: str | None  # None also when the schedule was deleted since
    pce_label: str
    period_start: datetime
    period_end: datetime
    created_at: datetime
    finished_at: datetime | None
    error_key: str | None
    error_detail: str | None
    files: list[str]
    email_status: str | None
    email_detail: str | None
    lookback_days: int | None
    lang: Language | None


class ReportPage(BaseModel):
    items: list[ReportItem]
    total: int
    page: int
    page_size: int


def catalog(ctx: AppContext) -> Catalog:
    avail = availability(ctx)
    settings = ctx.settings.current()
    return Catalog(entries=[CatalogEntry(report_type=t, group=s.group, available=avail.get(t) is None,
                                         reason_key=avail.get(t)) for t, s in specs().items()],
                   smtp_enabled=settings.alerts.channels.smtp.enabled,
                   gui_external_url_set=bool(settings.reports.gui_external_url))


def _item(ctx: AppContext, row: store.ReportRow) -> ReportItem:
    names = {s.id: s.name for s in ctx.settings.current().reports.schedules}
    lang = row.params.get("lang")
    return ReportItem(id=row.id, report_type=row.report_type, status=row.status, trigger=row.trigger,
                      schedule_id=row.schedule_id, schedule_name=names.get(row.schedule_id or ""),
                      pce_label=row.pce_label, period_start=row.period_start, period_end=row.period_end,
                      created_at=row.created_at, finished_at=row.finished_at, error_key=row.error_key,
                      error_detail=row.error_detail, files=row.files, email_status=row.email_status,
                      email_detail=row.email_detail, lookback_days=row.params.get("lookback_days"),
                      lang=Language(lang) if lang else None)


def list_reports(ctx: AppContext, *, page: int) -> ReportPage:
    with ctx.db() as conn:
        rows, total = store.list_reports(conn, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    return ReportPage(items=[_item(ctx, r) for r in rows], total=total, page=page, page_size=PAGE_SIZE)


def get_report(ctx: AppContext, report_id: int) -> ReportItem | None:
    with ctx.db() as conn:
        row = store.get(conn, report_id)
    return _item(ctx, row) if row else None


def generate_now(ctx: AppContext, params: ReportParams) -> ReportItem:
    rid = enqueue(ctx, params, trigger="manual", schedule_id=None, now=datetime.now(UTC))
    found = get_report(ctx, rid)
    assert found is not None
    return found


def report_file(ctx: AppContext, report_id: int, name: str) -> Path | None:
    """The file only when it is one of this report's own (never a path built from the request alone)."""
    item = get_report(ctx, report_id)
    if item is None or item.status is not ReportStatus.DONE or name not in item.files:
        return None
    path = ctx.paths.reports_dir / str(report_id) / name
    return path if path.is_file() else None
