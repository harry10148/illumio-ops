"""The previous period's key metrics of reports whose numbers describe a current state (VEN status, readiness,
ransomware protection): the last finished report of the same kind, parameters and PCE whose period ended where
this one starts (spec §6.5.5: every key metric with the previous period's). None when there is none."""
from __future__ import annotations

import json

from illumio_ops.services.reports.generate import pce_target
from illumio_ops.services.reports.registry import BuildInput, ReportParams
from illumio_ops.store import reports as store

_SAME = ("report_type", "lookback_days", "filter")


def previous_values(inp: BuildInput) -> dict[str, float | int | None] | None:
    target = pce_target(inp.ctx.settings.current().pce)
    want = inp.params.model_dump(mode="json", include=set(_SAME))
    with inp.ctx.db() as conn:
        rows = store.done_ending_at(conn, inp.params.report_type.value, inp.start, target)
    for row in rows:
        have = ReportParams.model_validate(row.params).model_dump(mode="json", include=set(_SAME))
        if json.dumps(have, sort_keys=True) == json.dumps(want, sort_keys=True):
            return {str(k["key"]): k.get("value") for k in row.kpis if "key" in k}
    return None
