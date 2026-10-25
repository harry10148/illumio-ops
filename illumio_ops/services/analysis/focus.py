"""The focus list step (last of the hourly analysis): items derived from the stored results, persisted so
each keeps the time it first appeared, ranked and stored for the home page and the report e-mails."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
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


MAX_DETECTIONS = 500
STALE_AFTER = timedelta(hours=2)    # an hourly result older than this missed at least one run
TRAFFIC_EVERY = timedelta(hours=24)  # the 7-day traffic items move slowly; their scans are the costly part


def _detections(conn: Any, now: datetime) -> tuple[list[dict[str, Any]], int]:
    rows, total = analysis.detections_ranked(conn, now - focus.WEEK, limit=MAX_DETECTIONS)
    return [{**dict(r), "summary": json.loads(r["summary_json"]), "segment": json.loads(r["segment_json"]),
             "confidence": json.loads(r["confidence_json"])} for r in rows], total


def _source_status(conn: Any, kind: str, now: datetime) -> str:
    """ok, missing, error (the latest run failed) or stale (the stored result missed a run)."""
    run, row = analysis.get_run(conn, kind), analysis.read_result(conn, kind)
    if run is not None and run["last_error"]:
        return "error"
    if row is None:
        return "missing"
    return "stale" if datetime.fromisoformat(row["computed_at"]) < now - STALE_AFTER else "ok"


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
        status.update({k: _source_status(conn, k, now) for k in stored})
        detections, detections_total = _detections(conn, now)
        detect_run = analysis.get_run(conn, "detect")
        traffic_cached = _stored(conn, "focus_traffic")
    status["detections"] = "error" if detect_run is not None and detect_run["last_error"] else "ok"
    items += focus.gap_item(failed=sum(1 for g in gaps if g.kind == "failed"),
                            truncated=sum(1 for g in gaps if g.kind == "truncated"))
    with ctx.db() as conn:
        failing = sorted(h.job_id for h in list_health(conn) if h.last_ok is False)
    probe = pce_health.latest(ctx)
    items += focus.health_items(failing_jobs=failing, probe_ok=None if probe is None else all(r.ok for r in probe[1]))
    tamper = stored["tamper"]
    items += focus.tamper_items(tamper["hosts"] if tamper else [])
    traffic_at: str | None = None
    if lc.collected:
        items += focus.detection_items(detections, names=names, now=now)
        exposure, overlay = stored["exposure"], stored["ransomware"]
        if exposure is not None:
            items += focus.exposure_items(exposure, names=names, baseline_full=lc.baseline_full())
        if overlay is not None:
            items += focus.ransomware_items(overlay) + focus.contradiction_item(int(overlay.get("contradictions") or 0))
        items += focus.visibility_item(sorted(k for k, h in lc.hosts.items() if h.visibility_level in BLIND))
        traffic = traffic_cached
        if traffic is None or datetime.fromisoformat(traffic["computed_at"]) <= now - TRAFFIC_EVERY:
            try:
                traffic = _traffic(ctx, now)
            except Exception as exc:  # noqa: BLE001 - one source failing is reported in sources_status
                logger.warning("focus list: traffic sources failed: {}", exc)
                status["traffic"] = f"error: {type(exc).__name__}"
                traffic = None
            else:
                with fdb.writing(lc.generation) as conn:
                    analysis.write_result(conn, "focus_traffic", params={}, result=traffic, at=now)
        if traffic is not None:
            # Filtered by the inventory's current mode: flows carry the mode of their own day.
            blockers = [(k, n) for k, n in traffic["potentially_blocked"]
                        if (h := lc.hosts.get(k)) and h.enforcement_mode in SWITCHABLE]
            items += focus.coverage_item(**traffic["coverage"])
            items += focus.mode_switch_item(hosts=len(blockers), connections=sum(n for _, n in blockers),
                                            truncated=traffic["truncated"])
            status["traffic"] = "ok"
            traffic_at = traffic["computed_at"]
    with fdb.writing(lc.generation) as conn:
        first_seen = analysis.upsert_focus(conn, [FocusWrite(it.fingerprint, it.kind.value, focus.score(
            it, new_this_week=False), "{}") for it in items], at=now)
        ranked = focus.rank(items, first_seen, now)
        analysis.write_result(conn, KIND, params={}, result={
            "computed_at": now.isoformat(), "items": [focus.item_json(r) for r in ranked], "sources_status": status,
            "detections": {"total": detections_total, "considered": len(detections)},
            "traffic_computed_at": traffic_at}, at=now)


def _traffic(ctx: AppContext, now: datetime) -> dict[str, Any]:
    """The two 7-day reads behind the coverage and mode-switch items, kept for a day."""
    week = FilterSpec(start=now - focus.WEEK, end=now)
    cov = field_coverage(ctx, week)
    pb = aggregate_flows(ctx, FlowSegment(
        filter=week.model_copy(update={"decisions": (PolicyDecision.POTENTIALLY_BLOCKED,)}),
        group_by=(GroupBy(dimension=SegmentDimension.DST_HOST),), metric=SegmentMetric.CONNECTIONS,
        view=SegmentView.RANKING, limit=1000), now=now, with_field_coverage=False)
    return {"computed_at": now.isoformat(),
            "coverage": {"total": cov.total, "process": cov.initiator_process, "user": cov.initiator_user},
            "potentially_blocked": [(str(r.keys[0]), r.value) for r in pb.rows], "truncated": pb.limit_hit}



