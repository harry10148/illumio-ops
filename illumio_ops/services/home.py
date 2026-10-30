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
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.hosts import WORKLOAD_HREF, display_names
from illumio_ops.store.flowdb import analysis

WEEK = timedelta(days=7)
ROUTES = {"settings_lateral": "/system/lateral", "settings_collection": "/system/collection",
          "system_jobs": "/system/jobs", "system_pce": "/system/pce", "alerts": "/alerts"}
# A lateral item without a host: where on the lateral page it is (the PCE's ransomware ratings contradicting the
# computed ones bear on the footholds the page lists).
LATERAL_SECTIONS = {"cross_env": "cross_env", "vendor_contradiction": "footholds"}


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
    detections_total: int = 0       # detections of the last 7 days ...
    detections_considered: int = 0  # ... of which the list was built from (the builder keeps the top 500)


def _workbench(req: workbench.FlowRequest | workbench.EventRequest) -> FocusLink:
    return FocusLink(route="/investigate", query={"q": req.model_dump_json(exclude_none=True)})


def _link(item: dict[str, Any], computed_at: datetime) -> FocusLink | None:
    action = item.get("action") or {}
    target, key = action.get("target"), action.get("host_key")
    if target == "host" and key:
        return FocusLink(route="/hosts", query={"key": str(key)})
    if target == "lateral":
        # the lateral page (P6c): an asset preselected, a pivot's row shown, else the section the item is about
        kind = item.get("kind")
        if key:
            return FocusLink(route="/lateral", query={"asset" if kind == "exposure_asset" else "host": str(key)})
        section = LATERAL_SECTIONS.get(str(kind))
        return FocusLink(route="/lateral", query={"section": section} if section else {})
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
    """Each workload href in an item's words as the host is shown elsewhere (hosts.display_names)."""
    hrefs = {v for it in items for v in (it.get("params") or {}).values() if isinstance(v, str) and WORKLOAD_HREF.match(v)}
    if not hrefs:
        return items
    names = display_names(ctx, hrefs)
    return [{**it, "params": {k: names.get(v, v) if isinstance(v, str) else v for k, v in (it.get("params") or {}).items()}}
            for it in items]


def focus_view(ctx: AppContext, *, now: datetime | None = None) -> FocusView:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)  # a switch not yet cleared: not the previous PCE's list
        row = analysis.read_result(conn, "focus")
    if row is None:
        return FocusView(computed_at=None, stale=False, items=[], sources_status={})
    result = json.loads(row["result_json"])
    computed = datetime.fromisoformat(result["computed_at"])
    items = [FocusEntry(**{k: v for k, v in it.items() if k != "action"}, link=_link(it, computed))
             for it in _named(ctx, list(result.get("items") or ()))]
    detections = result.get("detections") or {}
    return FocusView(computed_at=computed, stale=computed < at - STALE_AFTER, items=items,
                     sources_status=dict(result.get("sources_status") or {}),
                     detections_total=int(detections.get("total") or 0),
                     detections_considered=int(detections.get("considered") or 0))
