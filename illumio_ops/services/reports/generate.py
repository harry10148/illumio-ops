"""The one way a report is made (spec §6.5 報表): a manual request and a schedule both enqueue a row; the
reports job runs the oldest queued row through its builder and the renderers. A report that cannot be made
says why and leaves no files; nothing half-made or mixed from two PCEs is kept."""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import os
import shutil
import traceback
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from urllib.parse import urlsplit

from loguru import logger

from illumio_ops.domain.filter import FilterSpec
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
from illumio_ops.services import custom_reports, rhc
from illumio_ops.services.collect.guard import (
    BindingMismatch,
    normalize_target,
    require_same_pce,
)
from illumio_ops.services.collect.mode import collects
from illumio_ops.services.context import AppContext
from illumio_ops.services.coverage import store_coverage
from illumio_ops.services.ondemand import OnDemandFailed, OnDemandResult, pull_period
from illumio_ops.services.reports.deliver import deliver, gui_link
from illumio_ops.services.reports.registry import (
    RHC_UNAVAILABLE,
    BuildInput,
    ReportFailed,
    ReportParams,
    ReportSpec,
    app_filter_ok,
    names_app,
    specs,
)
from illumio_ops.services.reports.render_html import fmt_time, render_html
from illumio_ops.services.reports.render_xlsx import render_xlsx, safe
from illumio_ops.settings.schema import PceSettings, Settings
from illumio_ops.store import reports as store
from illumio_ops.store.flowdb.db import StaleGeneration

ERROR_DETAIL_MAX = 500
MAX_GAP_LINES = 10
GAP_REASON_KEYS = {"before_retention": "rpt_gap_reason_before_retention",
                   "not_yet_collected": "rpt_gap_reason_not_yet_collected",
                   "collection_off": "rpt_gap_reason_collection_off", "ingest_failed": "rpt_gap_reason_ingest_failed",
                   "truncated": "rpt_gap_reason_truncated"}


_Fail = ReportFailed


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
    floor = ctx.traffic_floor(retention.flow_days if flows else retention.rollup_days, now)
    with ctx.flows().connect() as conn:
        cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=floor,
                             collected=ctx.ondemand or collects(settings, IngestSource.TRAFFIC))
    return cov.covers_any and not cov.gaps


def availability(ctx: AppContext) -> dict[ReportType, str | None]:
    """Each built type -> None when it can be generated now, else the message key saying why not. Every mode
    can make every type: a flow report the install keeps no traffic for pulls it from the PCE (spec §6.4) — except
    rule_hit_count, greyed out until Rule Hit Count is on (spec §6.5 RHC; a recent check, not one per call)."""
    out: dict[ReportType, str | None] = {t: None for t in specs()}
    if ReportType.RULE_HIT_COUNT in out:
        out[ReportType.RULE_HIT_COUNT] = RHC_UNAVAILABLE.get(rhc.cached_status(ctx).state)
    return out


def pulls_on_demand(ctx: AppContext, spec: ReportSpec, start: datetime, now: datetime,
                    params: ReportParams | None = None) -> bool:
    """The report reads traffic the install does not keep: lightweight mode keeps none, the others keep
    flow_days. A gap inside the kept range stays a disclosed gap (a pull would be slower than the gap is worth)."""
    if not spec.needs_traffic:
        return False
    if spec.needs_traffic_for is not None and params is not None and not spec.needs_traffic_for(ctx, params):
        return False
    settings = ctx.settings.current()
    if settings.collection.mode is CollectionMode.LIGHTWEIGHT:
        return True
    return start < now - timedelta(days=settings.collection.retention.flow_days)


def _ondemand_lines(res: OnDemandResult, start: datetime, lang: Language, tz: tzinfo | None) -> tuple[str, ...]:
    def tr(key: str, **params: object) -> str:
        return translate(lang, key, {k: str(v) for k, v in params.items()})

    lines = [tr("rpt_quality_ondemand")]
    if res.earliest is None:
        lines.append(tr("rpt_quality_ondemand_none"))
    elif res.earliest > start + timedelta(days=1):
        lines.append(tr("rpt_quality_ondemand_earliest", start=fmt_time(res.earliest.isoformat(), tz)))
    if res.truncated:  # the baseline before the period included: a connection it missed would count as new
        lines.append(tr("rpt_quality_ondemand_truncated", n=len(res.truncated),
                        start=fmt_time(res.truncated[0][0].isoformat(), tz),
                        end=fmt_time(res.truncated[-1][1].isoformat(), tz)))
    if res.unread_from is not None:
        lines.append(tr("rpt_quality_ondemand_capped", n=f"{res.rows:,}",
                        start=fmt_time(res.unread_from.isoformat(), tz)))
    return tuple(lines)


def _build(ctx: AppContext, spec: ReportSpec, inp: BuildInput) -> ReportDocument:
    if not pulls_on_demand(ctx, spec, inp.start, inp.now, inp.params):
        return spec.build(inp)
    settings = ctx.settings.current()
    lead = spec.ondemand_lead(settings) if spec.ondemand_lead else timedelta(0)
    try:
        pushed = None if inp.params.filter is None else FilterSpec.model_validate(
            {**inp.params.filter.model_dump(), "start": inp.start - lead, "end": inp.end})
        with pull_period(ctx, start=inp.start - lead, end=inp.end, spec=pushed, now=inp.now) as res:
            if spec.ondemand_prepare is not None:
                spec.ondemand_prepare(res.ctx, inp.now)
            doc = spec.build(dataclasses.replace(inp, ctx=res.ctx, install=ctx))
    except OnDemandFailed as exc:
        raise _Fail("rpt_err_ondemand_failed", str(exc)[:ERROR_DETAIL_MAX]) from exc
    return doc.model_copy(update={"data_quality": (*doc.data_quality,
                                                   *_ondemand_lines(res, inp.start, inp.lang, inp.tz))})


# The parameter each refusal is about, for the API's field name.
REFUSAL_FIELDS = {"rpt_err_custom_required": "custom_id", "rpt_err_custom_not_supported": "custom_id",
                  "rpt_err_custom_missing": "custom_id", "rpt_err_lookback_beyond_retention": "lookback_days", "rpt_err_app_required": "filter",
                  "rpt_err_filter_not_supported": "filter", "rpt_err_app_filter_shape": "filter",
                  "rpt_err_format_unsupported": "formats"}


def refusal(settings: Settings, params: ReportParams, *, now: datetime | None = None) -> str | None:
    """Why these parameters cannot make this report (the reason is stored on a failed row), or None. With
    `now`, the period's actual start is checked against the retention floor (a DST change or a short
    retention can put it a few hours past what the lookback limit allows)."""
    spec = specs().get(params.report_type)
    if spec is None:
        return None
    if not set(params.formats) <= set(spec.formats):
        return "rpt_err_format_unsupported"
    if spec.max_lookback is not None and params.lookback_days > spec.max_lookback(settings):
        return "rpt_err_lookback_beyond_retention"
    if spec.retention is not None and now is not None:
        start, _ = period(now, params.lookback_days, settings.display.zone())
        if start < now - timedelta(days=spec.retention(settings)):
            return "rpt_err_lookback_beyond_retention"
    if params.filter is not None and not spec.accepts_filter:
        return "rpt_err_filter_not_supported"
    if params.report_type is ReportType.CUSTOM and params.custom_id is None:
        return "rpt_err_custom_required"
    if params.report_type is not ReportType.CUSTOM and params.custom_id is not None:
        return "rpt_err_custom_not_supported"
    if spec.requires_app and not names_app(params.filter):
        return "rpt_err_app_required"
    if spec.requires_app and not app_filter_ok(params.filter):
        return "rpt_err_app_filter_shape"
    return None


def enqueue(ctx: AppContext, params: ReportParams, *, trigger: str, schedule_id: str | None, now: datetime) -> int:
    """A queued report, or a failed one at once when it cannot be made (the reason is stored, no files)."""
    settings = ctx.settings.current()
    start, end = period(now, params.lookback_days, settings.display.zone())
    reason = availability(ctx).get(params.report_type, "rpt_unavailable_not_built") or refusal(settings, params,
                                                                                                now=now)
    if reason is None and params.report_type is ReportType.CUSTOM and custom_reports.get(ctx, params.custom_id or 0) is None:
        reason = "rpt_err_custom_missing"
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


def _render(doc: ReportDocument, fmt: ReportFormat, tz: tzinfo | None) -> bytes:
    if fmt is ReportFormat.HTML:
        return render_html(doc, tz=tz).encode("utf-8")
    if fmt is ReportFormat.XLSX:
        return render_xlsx(doc, tz=tz)
    if doc.export is None:
        raise _Fail("rpt_err_internal", f"{doc.report_type.value} made no rows for {fmt.value}")
    ex = doc.export
    if fmt is ReportFormat.JSON:
        body = {"report_type": doc.report_type.value, "pce": doc.pce_label, "generated_at": doc.generated_at.isoformat(),
                "period_start": doc.period_start.isoformat(), "period_end": doc.period_end.isoformat(), **ex.meta,
                "record_count": len(ex.rows), "columns": list(ex.columns),
                "rows": [dict(zip(ex.columns, r, strict=True)) for r in ex.rows]}
        return json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8")
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    # Values come from the PCE (ruleset, service names): the XLSX guard keeps a cell from running as a formula.
    writer.writerow([safe(c) for c in ex.columns])
    writer.writerows([safe(c) for c in r] for r in ex.rows)
    return buf.getvalue().encode("utf-8-sig")  # the BOM: Excel reads UTF-8 only with it


def _write(out_dir: Path, doc: ReportDocument, report_id: int, formats: tuple[ReportFormat, ...],
           tz: tzinfo | None) -> list[str]:
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    names = []
    for fmt in formats:
        data = _render(doc, fmt, tz)
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
    fdb = ctx.flows()
    generation = fdb.generation  # noted before the settings it goes with: a switch in between fails the report
    settings = ctx.settings.current()
    tz = settings.display.zone()
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
        doc = _build(ctx, spec, BuildInput(ctx=ctx, params=params, start=row.period_start, end=row.period_end,
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
    floor = ctx.traffic_floor(retention.flow_days if flows else retention.rollup_days, now)
    with fdb.connect() as conn:
        require_same_pce(conn, settings.pce)
        cov = store_coverage(conn, IngestSource.TRAFFIC, (start, end), floor=floor,
                             collected=ctx.ondemand or collects(settings, IngestSource.TRAFFIC))

    def tr(key: str, **params: object) -> str:
        return translate(lang, key, {k: str(v) for k, v in params.items()})

    lines = []
    if settings.collection.mode is CollectionMode.ALERT and not ctx.ondemand:
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

