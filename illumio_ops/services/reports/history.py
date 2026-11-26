"""The previous period's key numbers (spec §6.5.5: every key metric with the previous period's; spec 2026-11-27 §4).
Every finished report's key numbers are recorded apart from the report (store.report_kpi_history), so the comparison
outlives the report: deleting it, or the retention removing it, does not take the next report's "previous" away.

The previous period of a report: the same kind, PCE, filter and custom report, ending where this one starts and as
long (generate.comparable: the same number of days, or both a whole calendar month).

Two readers:
- previous_values: the reports whose numbers describe a state at the time they ran (VEN status, readiness,
  ransomware protection) cannot compute an earlier state, so their builders ask here;
- with_stored_previous: every other report computes its previous period from the traffic and events kept. Where it
  could not (the period before is no longer kept) and the numbers were recorded then by a report that read its
  whole period, they are used, and the data notes say where they come from. Numbers of a report with time missing,
  or of one made before that was recorded, are not."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from illumio_ops.domain.report import ReportDocument
from illumio_ops.services.context import AppContext
from illumio_ops.services.reports.common import tr
from illumio_ops.services.reports.generate import comparable, pce_target
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.services.reports.render_html import fmt_time
from illumio_ops.store import reports as store

KEEP_DAYS = 1100  # three years of periods: a yearly comparison and room to spare


def match_key(params: Mapping[str, Any]) -> str:
    """What two reports must share, beside kind and PCE, for their numbers to be compared: the filter and the
    custom report (a report's stored parameters, or ReportParams dumped as JSON)."""
    return json.dumps({"filter": params.get("filter"), "custom_id": params.get("custom_id")}, sort_keys=True)


def _previous(ctx: AppContext, *, report_type: str, target: str, params: Mapping[str, Any], start: datetime,
              end: datetime, tz: tzinfo | None, whole_only: bool = False) -> store.KpiRecord | None:
    """whole_only: only numbers of a report known to have read its whole period."""
    with ctx.db() as conn:
        found = store.kpis_ending_at(conn, report_type=report_type, pce_target=target, match_json=match_key(params),
                                     period_end=start)
    return next((r for r in found if comparable(r.period_start, r.period_end, start, end, tz)
                 and (r.complete or not whole_only)), None)


def previous_values(inp: BuildInput) -> dict[str, float | int | None] | None:
    install = inp.install or inp.ctx  # the records are the install's, also when the report reads a throwaway store
    found = _previous(install, report_type=inp.params.report_type.value,
                      target=pce_target(install.settings.current().pce), params=inp.params.model_dump(mode="json"),
                      start=inp.start, end=inp.end, tz=inp.tz)
    return None if found is None else {str(k["key"]): k.get("value") for k in found.kpis if "key" in k}


def with_stored_previous(ctx: AppContext, doc: ReportDocument, row: store.ReportRow, params: ReportParams, *,
                         tz: tzinfo | None) -> ReportDocument:
    """The key numbers that have a value and no previous one get the previous period's recorded value, when there is
    one; one data note then says they are the numbers of the report made at that time."""
    if all(k.value is None or k.previous is not None for k in doc.kpis):
        return doc
    # Only a report that read its whole period: a count over a period with time missing is no number to measure
    # this period against (the builder itself gives no previous number then — spec §4.3).
    found = _previous(ctx, report_type=row.report_type, target=row.pce_target, params=row.params,
                      start=row.period_start, end=row.period_end, tz=tz, whole_only=True)
    if found is None:
        return doc
    before = {str(k["key"]): k.get("value") for k in found.kpis if "key" in k}
    filled = 0
    kpis = []
    for k in doc.kpis:
        value = before.get(k.key)
        if k.value is not None and k.previous is None and isinstance(value, (int, float)) and not isinstance(value, bool):
            k = k.model_copy(update={"previous": value})
            filled += 1
        kpis.append(k)
    if not filled:
        return doc
    note = tr(doc.lang, "rpt_quality_previous_stored", at=fmt_time(found.recorded_at.isoformat(), tz))
    return doc.model_copy(update={"kpis": tuple(kpis), "data_quality": (*doc.data_quality, note)})


def record_kept(ctx: AppContext, *, now: datetime | None = None) -> None:
    """At start-up: the key numbers of every finished report still kept, where none are recorded for its period yet
    (reports made before 6.16.0); the newest report of a period first. Periods older than KEEP_DAYS are dropped."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    with ctx.db() as conn:
        for row in reversed(store.done_reports(conn)):
            store.record_kpis(conn, report_type=row.report_type, pce_target=row.pce_target,
                              match_json=match_key(row.params), period_start=row.period_start,
                              period_end=row.period_end, kpis=row.kpis, at=row.finished_at or at, complete=None,
                              replace=False)
        store.forget_kpis_before(conn, at - timedelta(days=KEEP_DAYS))
