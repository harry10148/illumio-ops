"""The one way a report is made (spec §6.5 報表): a manual request and a schedule both enqueue a row; the
reports job runs the oldest queued row through its builder and the renderers. A report that cannot be made
says why and leaves no files; nothing half-made or mixed from two PCEs is kept."""
from __future__ import annotations

import os
import shutil
import traceback
from datetime import UTC, datetime, time, timedelta, tzinfo
from pathlib import Path
from urllib.parse import urlsplit

from loguru import logger

from illumio_ops.domain.report import ReportDocument
from illumio_ops.domain.values import (
    CollectionMode,
    IngestSource,
    Language,
    ReportFormat,
    ReportStatus,
    ReportType,
)
from illumio_ops.i18n import translate
from illumio_ops.services.collect.guard import BindingMismatch, require_same_pce
from illumio_ops.services.collect.mode import collects, in_mode
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import store_coverage
from illumio_ops.services.reports.deliver import deliver, gui_link
from illumio_ops.services.reports.registry import BuildInput, ReportParams, specs
from illumio_ops.services.reports.render_html import fmt_time, render_html
from illumio_ops.services.reports.render_xlsx import render_xlsx
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb.db import StaleGeneration

ERROR_DETAIL_MAX = 500
MAX_GAP_LINES = 10
GAP_REASON_KEYS = {"before_retention": "rpt_gap_reason_before_retention",
                   "not_yet_collected": "rpt_gap_reason_not_yet_collected",
                   "collection_off": "rpt_gap_reason_collection_off", "ingest_failed": "rpt_gap_reason_ingest_failed",
                   "truncated": "rpt_gap_reason_truncated"}


class _Fail(Exception):
    def __init__(self, key: str, detail: str | None = None) -> None:
        super().__init__(key)
        self.key, self.detail = key, detail


def pce_label(ctx: AppContext) -> str:
    pce = ctx.settings.current().pce
    host = urlsplit(pce.url).hostname or pce.url
    return f"{host} (org {pce.org_id})" if pce.org_id else host


def period(now: datetime, lookback_days: int, tz: tzinfo | None) -> tuple[datetime, datetime]:
    """The last `lookback_days` whole days in the display zone, ending at today's 00:00 there (end exclusive)."""
    local = now.astimezone(tz)
    end = datetime.combine(local.date(), time(0), local.tzinfo).astimezone(UTC)
    return end - timedelta(days=lookback_days), end


def availability(ctx: AppContext) -> dict[ReportType, str | None]:
    """Each built type -> None when it can be generated now, else the message key saying why not."""
    settings = ctx.settings.current()
    traffic = in_mode(settings, IngestSource.TRAFFIC)
    return {t: ("rpt_unavailable_events_only" if spec.needs_traffic and not traffic else None)
            for t, spec in specs().items()}


def enqueue(ctx: AppContext, params: ReportParams, *, trigger: str, schedule_id: str | None, now: datetime) -> int:
    """A queued report, or a failed one at once when it cannot be made (the reason is stored, no files)."""
    settings = ctx.settings.current()
    start, end = period(now, params.lookback_days, settings.display.zone())
    reason = availability(ctx).get(params.report_type, "rpt_unavailable_not_built")
    with ctx.db() as conn:
        return store.insert(conn, report_type=params.report_type.value, params_json=params.model_dump_json(),
                            status=ReportStatus.FAILED if reason else ReportStatus.QUEUED, trigger=trigger,
                            schedule_id=schedule_id, pce_label=pce_label(ctx), period_start=start, period_end=end,
                            created_at=now, error_key=reason)


def recover_running(ctx: AppContext) -> int:
    with ctx.db() as conn:
        return store.requeue_running(conn)


def _file_name(doc: ReportDocument, report_id: int, fmt: ReportFormat, tz: tzinfo | None) -> str:
    last_day = (doc.period_end - timedelta(microseconds=1)).astimezone(tz)
    return f"{doc.report_type.value}-{last_day:%Y%m%d}-{report_id}.{fmt.value}"


def _write(out_dir: Path, doc: ReportDocument, report_id: int, formats: tuple[ReportFormat, ...],
           tz: tzinfo | None) -> list[str]:
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    names = []
    for fmt in formats:
        data = render_html(doc, tz=tz).encode("utf-8") if fmt is ReportFormat.HTML else render_xlsx(doc, tz=tz)
        name = _file_name(doc, report_id, fmt, tz)
        part = out_dir / (name + ".part")
        fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        part.replace(out_dir / name)
        names.append(name)
    return names


def run_queued(ctx: AppContext, *, now: datetime | None = None) -> int | None:
    """Make the oldest queued report; None when nothing is queued. Never raises for a report's own failure."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    with ctx.db() as conn:
        row = store.claim_next(conn, at=at)
    if row is None:
        return None
    out_dir = ctx.paths.reports_dir / str(row.id)
    settings = ctx.settings.current()
    tz = settings.display.zone()
    fdb = ctx.flows()
    generation = fdb.generation
    try:
        params = ReportParams.model_validate(row.params)
        spec = specs().get(params.report_type)
        if spec is None:
            raise _Fail("rpt_unavailable_not_built")
        reason = availability(ctx).get(params.report_type)
        if reason:
            raise _Fail(reason)
        doc = spec.build(BuildInput(ctx=ctx, params=params, start=row.period_start, end=row.period_end,
                                    lang=params.lang or settings.display.language, tz=tz, now=at,
                                    pce_label=row.pce_label))
        if fdb.generation != generation:
            raise _Fail("rpt_err_pce_switched")
        doc = doc.model_copy(update={"gui_link": gui_link(settings.reports.gui_external_url, row.id)})
        files = _write(out_dir, doc, row.id, params.formats, tz)
        kpis = [{"key": k.key, "label": k.label, "value": k.value, "previous": k.previous} for k in doc.kpis]
    except Exception as exc:  # noqa: BLE001 - a report's failure is recorded on the report, never raised to the job
        if isinstance(exc, _Fail):
            key, detail = exc.key, exc.detail
        elif isinstance(exc, (StaleGeneration, BindingMismatch)):
            key, detail = "rpt_err_pce_switched", None
        else:
            logger.error("report {} failed: {}", row.id, traceback.format_exc())
            key, detail = "rpt_err_internal", f"{type(exc).__name__}: {exc}"[:ERROR_DETAIL_MAX]
        shutil.rmtree(out_dir, ignore_errors=True)
        with ctx.db() as conn:
            store.finish(conn, row.id, status=ReportStatus.FAILED, at=datetime.now(UTC), files=[], kpis=[],
                         error_key=key, error_detail=detail)
        return row.id
    with ctx.db() as conn:
        store.finish(conn, row.id, status=ReportStatus.DONE, at=datetime.now(UTC), files=files, kpis=kpis)
    if params.email:
        deliver(ctx, row.id, doc, params, [out_dir / f for f in files], tz=tz)
    return row.id


def coverage_note(ctx: AppContext, start: datetime, end: datetime, lang: Language, *, now: datetime,
                  tz: tzinfo | None) -> tuple[str, ...]:
    """The data-quality lines about traffic in the period: whole period, or where it starts and every gap."""
    settings = ctx.settings.current()
    fdb = ctx.flows()
    floor = now - timedelta(days=settings.collection.retention.rollup_days)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=floor,
                             collected=collects(settings, IngestSource.TRAFFIC))

    def tr(key: str, **params: object) -> str:
        return translate(lang, key, {k: str(v) for k, v in params.items()})

    lines = []
    if settings.collection.mode is CollectionMode.ALERT:
        lines.append(tr("rpt_quality_alert_mode", days=settings.collection.retention.flow_days))
    if not cov.gaps:
        lines.append(tr("rpt_quality_traffic_whole"))
        return tuple(lines)
    for a, b, reason in cov.gaps[:MAX_GAP_LINES]:
        lines.append(tr("rpt_quality_gap", start=fmt_time(a.isoformat(), tz), end=fmt_time(b.isoformat(), tz),
                        reason=tr(GAP_REASON_KEYS.get(reason, "rpt_gap_reason_ingest_failed"))))
    if len(cov.gaps) > MAX_GAP_LINES:
        lines.append(tr("rpt_quality_gaps_more", n=len(cov.gaps) - MAX_GAP_LINES))
    return tuple(lines)

