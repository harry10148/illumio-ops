"""The focus list step (last of the hourly analysis): items derived from the stored results, persisted so
each keeps the time it first appeared, ranked and stored for the home page and the report e-mails."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from loguru import logger

from illumio_ops.domain import focus
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.segment import FlowSegment, GroupBy
from illumio_ops.domain.values import (
    PolicyDecision,
    SegmentDimension,
    SegmentMetric,
    SegmentView,
    VisibilityLevel,
)
from illumio_ops.jobs.health import list_health
from illumio_ops.services import pce_health
from illumio_ops.services.analysis.context import load_lateral_context
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import aggregate_flows, field_coverage
from illumio_ops.store.flowdb import analysis, ingest_state
from illumio_ops.store.flowdb.analysis import FocusWrite

KIND = "focus"
BLIND = frozenset({VisibilityLevel.FLOW_DROPS.value, VisibilityLevel.FLOW_OFF.value})
SWITCHABLE = frozenset({"visibility_only", "selective"})  # modes whose potentially blocked traffic enforcement stops


def _stored(conn: Any, kind: str) -> dict[str, Any] | None:
    row = analysis.read_result(conn, kind)
    return json.loads(row["result_json"]) if row is not None else None


def _detections(conn: Any, now: datetime) -> list[dict[str, Any]]:
    return [{**dict(r), "summary": json.loads(r["summary_json"]), "segment": json.loads(r["segment_json"]),
             "confidence": json.loads(r["confidence_json"])}
            for r in analysis.detections_since(conn, now - focus.WEEK, limit=500)]


def build_focus(ctx: AppContext, now: datetime) -> None:
    lc = load_lateral_context(ctx, now=now)
    fdb = ctx.flows()
    status: dict[str, str] = {}
    names = {k: h.hostname for k, h in lc.hosts.items()}
    items: list[focus.FocusItem] = focus.setup_items(
        critical_set=bool(lc.settings.critical_assets), admin_set=bool(lc.settings.admin_groups),
        stale=list(lc.stale), collected=lc.collected)
    with fdb.connect() as conn:
        gaps = [g for g in ingest_state.open_gaps(conn) if g.recorded_at >= now - focus.WEEK]
        stored = {k: _stored(conn, k) for k in ("exposure", "ransomware", "tamper")}
        detections = _detections(conn, now)
    status["detections"] = "ok"
    items += focus.gap_item(failed=sum(1 for g in gaps if g.kind == "failed"),
                            truncated=sum(1 for g in gaps if g.kind == "truncated"))
    with ctx.db() as conn:
        failing = sorted(h.job_id for h in list_health(conn) if h.last_ok is False)
    probe = pce_health.latest(ctx)
    items += focus.health_items(failing_jobs=failing, probe_ok=None if probe is None else all(r.ok for r in probe[1]))
    tamper = stored["tamper"]
    status["tamper"] = "ok" if tamper is not None else "missing"
    items += focus.tamper_items(tamper["hosts"] if tamper else [])
    if lc.collected:
        items += focus.detection_items(detections, names=names, now=now)
        exposure, overlay = stored["exposure"], stored["ransomware"]
        status["exposure"] = "ok" if exposure is not None else "missing"
        status["ransomware"] = "ok" if overlay is not None else "missing"
        if exposure is not None:
            items += focus.exposure_items(exposure, names=names, baseline_full=lc.baseline_full())
        if overlay is not None:
            items += focus.ransomware_items(overlay) + focus.contradiction_item(int(overlay.get("contradictions") or 0))
        items += focus.visibility_item(sorted(k for k, h in lc.hosts.items() if h.visibility_level in BLIND))
        week = FilterSpec(start=now - focus.WEEK, end=now)
        try:
            cov = field_coverage(ctx, week)
            items += focus.coverage_item(total=cov.total, process=cov.initiator_process, user=cov.initiator_user)
            pb = aggregate_flows(ctx, FlowSegment(
                filter=week.model_copy(update={"decisions": (PolicyDecision.POTENTIALLY_BLOCKED,)}),
                group_by=(GroupBy(dimension=SegmentDimension.DST_HOST),), metric=SegmentMetric.CONNECTIONS,
                view=SegmentView.RANKING, limit=1000), now=now)
            # Filtered by the inventory's current mode: flows carry the mode of their own day.
            blockers = [r for r in pb.rows if (h := lc.hosts.get(str(r.keys[0]))) and h.enforcement_mode in SWITCHABLE]
            items += focus.mode_switch_item(hosts=len(blockers), connections=sum(r.value for r in blockers),
                                            truncated=pb.limit_hit)
            status["traffic"] = "ok"
        except Exception as exc:  # noqa: BLE001 - one source failing is reported in sources_status
            logger.warning("focus list: traffic sources failed: {}", exc)
            status["traffic"] = f"error: {type(exc).__name__}"
    with fdb.writing(lc.generation) as conn:
        first_seen = analysis.upsert_focus(conn, [FocusWrite(it.fingerprint, it.kind.value, focus.score(
            it, new_this_week=False), "{}") for it in items], at=now)
        ranked = focus.rank(items, first_seen, now)
        analysis.write_result(conn, KIND, params={}, result={
            "computed_at": now.isoformat(), "items": [focus.item_json(r) for r in ranked], "sources_status": status},
            at=now)



