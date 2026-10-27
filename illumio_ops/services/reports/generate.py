"""The one way a report is made (spec §6.5 報表): a manual request and a schedule both enqueue a row; the
reports job runs the oldest queued row through its builder and the renderers. A report that cannot be made
says why and leaves no files; nothing half-made or mixed from two PCEs is kept."""
from __future__ import annotations

import os
import shutil
import traceback
from datetime import UTC, date, datetime, time, timedelta, tzinfo
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
from illumio_ops.services.collect.guard import (
    BindingMismatch,
    normalize_target,
    require_same_pce,
)
from illumio_ops.services.collect.mode import collects, in_mode
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import store_coverage
from illumio_ops.services.reports.deliver import deliver, gui_link
from illumio_ops.services.reports.registry import (
    BuildInput,
    ReportParams,
    app_filter_ok,
    names_app,
    specs,
)
from illumio_ops.services.reports.render_html import fmt_time, render_html
from illumio_ops.services.reports.render_xlsx import render_xlsx
from illumio_ops.settings.schema import PceSettings, Settings
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


def pce_label(pce: PceSettings) -> str:
    host = urlsplit(pce.url).hostname or pce.url
    return f"{host} (org {pce.org_id})" if pce.org_id else host


def _midnight(day: date, tz: tzinfo | None) -> datetime:
    """00:00 of a calendar day in the display zone, as UTC (each end on its own: a DST change between them)."""
    local = datetime.combine(day, time(0))
    return (local.replace(tzinfo=tz) if tz is not None else local.astimezone()).astimezone(UTC)


def period(now: datetime, lookback_days: int, tz: tzinfo | None) -> tuple[datetime, datetime]:
    """The last `lookback_days` whole days in the display zone, ending at today's 00:00 there (end exclusive)."""
    today = now.astimezone(tz).date()
    return _midnight(today - timedelta(days=lookback_days), tz), _midnight(today, tz)


def previous_period(start: datetime, end: datetime, tz: tzinfo | None) -> tuple[datetime, datetime]:
    """The same number of calendar days just before [start, end)."""
    days = (end.astimezone(tz).date() - start.astimezone(tz).date()).days
    return _midnight(start.astimezone(tz).date() - timedelta(days=days), tz), start


def pce_target(pce: PceSettings) -> str:
    """The PCE's identity (normalized URL and org); taken from the same settings snapshot as its label."""
    url, org = normalize_target(pce.url, pce.org_id)
    return f"{url}#{org}"


def traffic_covered(ctx: AppContext, start: datetime, end: datetime, *, now: datetime,
                    flows: bool = False) -> bool:
    """Traffic was collected for all of [start, end) with no recorded gap: only then is a count over it a
    number to compare with (spec §4.3: missing data is never shown as 0). flows: the count reads the flows
    table, kept flow_days, not the rollups' rollup_days."""
    settings = ctx.settings.current()
    retention = settings.collection.retention
    floor = now - timedelta(days=retention.flow_days if flows else retention.rollup_days)
    with ctx.flows().connect() as conn:
        cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=floor,
                             collected=collects(settings, IngestSource.TRAFFIC))
    return cov.covers_any and not cov.gaps


def availability(ctx: AppContext) -> dict[ReportType, str | None]:
    """Each built type -> None when it can be generated now, else the message key saying why not."""
    settings = ctx.settings.current()
    traffic = in_mode(settings, IngestSource.TRAFFIC)
    return {t: ("rpt_unavailable_events_only" if spec.needs_traffic and not traffic else None)
            for t, spec in specs().items()}


# The parameter each refusal is about, for the API's field name.
REFUSAL_FIELDS = {"rpt_err_lookback_beyond_retention": "lookback_days", "rpt_err_app_required": "filter",
                  "rpt_err_filter_not_supported": "filter", "rpt_err_app_filter_shape": "filter"}


def refusal(settings: Settings, params: ReportParams) -> str | None:
    """Why these parameters cannot make this report (the reason is stored on a failed row), or None."""
    spec = specs().get(params.report_type)
    if spec is None:
        return None
    if spec.max_lookback is not None and params.lookback_days > spec.max_lookback(settings):
        return "rpt_err_lookback_beyond_retention"
    if params.filter is not None and not spec.accepts_filter:
        return "rpt_err_filter_not_supported"
    if spec.requires_app and not names_app(params.filter):
        return "rpt_err_app_required"
    if spec.requires_app and not app_filter_ok(params.filter):
        return "rpt_err_app_filter_shape"
    return None


def enqueue(ctx: AppContext, params: ReportParams, *, trigger: str, schedule_id: str | None, now: datetime) -> int:
    """A queued report, or a failed one at once when it cannot be made (the reason is stored, no files)."""
    settings = ctx.settings.current()
    start, end = period(now, params.lookback_days, settings.display.zone())
    reason = availability(ctx).get(params.report_type, "rpt_unavailable_not_built") or refusal(settings, params)
    with ctx.db() as conn:
        return store.insert(conn, report_type=params.report_type.value, params_json=params.model_dump_json(),
                            status=ReportStatus.FAILED if reason else ReportStatus.QUEUED, trigger=trigger,
                            schedule_id=schedule_id, pce_label=pce_label(settings.pce), period_start=start,
                            period_end=end, created_at=now, error_key=reason, pce_target=pce_target(settings.pce))


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
        # Queued for another PCE than the one configured now — or before reports recorded their PCE (''): either
        # way the data read now may not be the PCE the report names.
        if row.pce_target != pce_target(settings.pce):
            raise _Fail("rpt_err_pce_switched")
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
        if params.email:  # the list says so while the email is going out
            store.set_email(conn, row.id, status="sending", detail=None)
    if params.email:
        deliver(ctx, row.id, doc, params, [out_dir / f for f in files], tz=tz)
    return row.id


def coverage_note(ctx: AppContext, start: datetime, end: datetime, lang: Language, *, now: datetime,
                  tz: tzinfo | None, flows: bool = False) -> tuple[str, ...]:
    """The data-quality lines about traffic in the period: whole period, or where it starts and every gap.
    flows: the report reads the flows table (kept flow_days), not the rollups (rollup_days)."""
    settings = ctx.settings.current()
    fdb = ctx.flows()
    retention = settings.collection.retention
    floor = now - timedelta(days=retention.flow_days if flows else retention.rollup_days)
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

