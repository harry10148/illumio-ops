"""The home page's focus list (spec §6.5.4, P6b): the hourly result (services/analysis/focus.py) read as stored —
nothing is computed per request — with where each item leads. Not computed yet, stale or a failed source is said,
never shown as an empty list."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError

from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.segment import GroupBy
from illumio_ops.domain.values import (
    PolicyDecision,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
)
from illumio_ops.services import workbench
from illumio_ops.services.analysis.focus import STALE_AFTER
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import host_addresses
from illumio_ops.services.hosts import WORKLOAD_HREF
from illumio_ops.store.flowdb import analysis, workloads

WEEK = timedelta(days=7)
ROUTES = {"settings_lateral": "/system/lateral", "settings_collection": "/system/collection",
          "system_jobs": "/system/jobs", "system_pce": "/system/pce", "alerts": "/alerts"}


class FocusLink(BaseModel):
    route: str
    query: dict[str, str] = {}


class FocusEntry(BaseModel):
    kind: str
    fingerprint: str
    severity: str
    critical_asset: bool
    confidence: str
    title_key: str
    why_key: str
    params: dict[str, Any]
    score: float
    first_seen: datetime
    new_this_week: bool
    weeks_persisting: int
    link: FocusLink | None


class FocusView(BaseModel):
    computed_at: datetime | None
    stale: bool
    items: list[FocusEntry]
    sources_status: dict[str, str]


def _workbench(req: workbench.FlowRequest | workbench.EventRequest) -> FocusLink:
    return FocusLink(route="/investigate", query={"q": req.model_dump_json(exclude_none=True)})


def _link(item: dict[str, Any], computed_at: datetime) -> FocusLink | None:
    action = item.get("action") or {}
    target, key = action.get("target"), action.get("host_key")
    if target in ("host", "lateral") and key:
        return FocusLink(route="/hosts", query={"key": str(key)})  # a lateral item's host until the P6c page
    if target == "workbench" and action.get("segment"):
        try:
            return _workbench(workbench.request_for("flow", action["segment"]))
        except (ValidationError, ValueError):
            return None  # longer than the workbench's period: no link rather than a refused request
    if target == "workbench" and item.get("kind") == "mode_switch_blocker":
        # the item counts the last 7 days' potentially blocked connections, by destination host (focus._traffic)
        return _workbench(workbench.FlowRequest(
            mode="flows", start=computed_at - WEEK, end=computed_at, view=SegmentView.RANKING,
            condition=FlowCondition(decisions=(PolicyDecision.POTENTIALLY_BLOCKED,)), metric=SegmentMetric.CONNECTIONS,
            group_by=(GroupBy(dimension=SegmentDimension.DST_HOST),)))
    route = ROUTES.get(str(target))
    return FocusLink(route=route) if route else None


def _named(ctx: AppContext, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each workload href in an item's words as the host is shown elsewhere: the inventory's hostname or name, else
    an address it was seen with (the PCE sends no hostname for some workloads, lab 2026-10-30)."""
    hrefs = {v for it in items for v in (it.get("params") or {}).values() if isinstance(v, str) and WORKLOAD_HREF.match(v)}
    if not hrefs:
        return items
    with ctx.flows().connect() as conn:
        names = {w.href: w.hostname or w.name for w in workloads.all_workloads(conn) if w.href in hrefs}
    names = {h: n for h, n in names.items() if n}
    names |= host_addresses(ctx, hrefs - set(names))
    return [{**it, "params": {k: names.get(v, v) if isinstance(v, str) else v for k, v in (it.get("params") or {}).items()}}
            for it in items]


def focus_view(ctx: AppContext, *, now: datetime | None = None) -> FocusView:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    with ctx.flows().connect() as conn:
        row = analysis.read_result(conn, "focus")
    if row is None:
        return FocusView(computed_at=None, stale=False, items=[], sources_status={})
    result = json.loads(row["result_json"])
    computed = datetime.fromisoformat(result["computed_at"])
    items = [FocusEntry(**{k: v for k, v in it.items() if k != "action"}, link=_link(it, computed))
             for it in _named(ctx, list(result.get("items") or ()))]
    return FocusView(computed_at=computed, stale=computed < at - STALE_AFTER, items=items,
                     sources_status=dict(result.get("sources_status") or {}))
