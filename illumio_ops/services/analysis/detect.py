"""The detection pipeline: after each traffic cycle the detectors run over the connections collected since
the last run (plus the collector's own overlap, so late-arriving records are evaluated too), and after the
daily re-read once more over the day it re-read (detections found then are marked late)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from illumio_ops.domain.detectors import (
    Detection,
    DetectorConfig,
    DetectorInput,
    DetectorStatus,
    HostLookup,
    blocked_counts,
    dedup_windows,
    evaluable,
    run_detectors,
)
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import DetectorKind, DetectorState, PolicyDecision
from illumio_ops.services.analysis import blocked_history
from illumio_ops.services.analysis.context import (
    LateralContext,
    host_for,
    load_lateral_context,
)
from illumio_ops.services.collect.traffic import OVERLAP
from illumio_ops.services.context import AppContext
from illumio_ops.services.eventsource import precursor_events
from illumio_ops.services.flowsource import baseline_first_seen, observations
from illumio_ops.settings.schema import DetectorSettings, LateralSettings
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.analysis import DetectionWrite
from illumio_ops.store.flowdb.db import StaleGeneration

KIND = "detect"
LATE_KIND = "detect_late"  # its status holds the days whose late pass is still owed


class DetectionRun(BaseModel):
    window: tuple[datetime, datetime] | None
    new: int
    updated: int
    statuses: list[dict[str, Any]]
    gaps: list[tuple[datetime, datetime, str]]
    late: bool


def _config(lc: LateralContext) -> DetectorConfig:
    lat: LateralSettings = lc.settings
    d: DetectorSettings = lat.detectors
    gone = {(k, v) for setting, k, v in lc.stale if setting == "admin_groups"}
    live_groups = [g for g in lat.admin_groups if (g.key, g.value) not in gone]
    return DetectorConfig(
        fanout_targets=d.fanout_targets, fanout_window=timedelta(minutes=d.fanout_window_minutes),
        account_fanout_targets=d.account_fanout_targets,
        account_fanout_window=timedelta(minutes=d.account_fanout_window_minutes),
        chain_window=timedelta(minutes=d.chain_window_minutes), blocked_targets=d.blocked_targets,
        blocked_window=timedelta(minutes=d.blocked_window_minutes), blocked_surge_factor=d.blocked_surge_factor,
        exclude_system_accounts=d.exclude_system_accounts, precursor_window=timedelta(hours=d.precursor_hours),
        expected={(e.port, e.proto): frozenset(e.processes) for e in lat.expected_initiators},
        admin_ports=lc.admin_ports, environment_label_key=lat.environment_label_key,
        admin_groups_configured=bool(live_groups), admin_groups_stale=bool(lat.admin_groups) and not live_groups,
        environment_labels_present=any(k == lat.environment_label_key for k, _ in lc.known_labels))


def _status(s: DetectorStatus, incomplete: bool) -> dict[str, Any]:
    state = DetectorState.INCOMPLETE if incomplete and s.state is DetectorState.OK else s.state
    params = dict(s.params) | ({"incomplete": True} if incomplete else {})
    return {"detector": s.detector.value, "state": state.value, "reason_key": s.reason_key, "params": params}


def _write(d: Detection) -> DetectionWrite:
    return DetectionWrite(
        detector=d.detector.value, fingerprint=d.fingerprint, subject_key=d.subject_key, severity=d.severity.value,
        first_seen=d.first_seen, last_seen=d.last_seen, critical_asset=d.critical_asset,
        summary_json=json.dumps(d.summary, default=str), segment_json=d.segment.model_dump_json(),
        confidence_json=json.dumps(asdict(d.confidence), default=str))


def _lookback(cfg: DetectorConfig) -> timedelta:
    return max(cfg.fanout_window, cfg.account_fanout_window, cfg.chain_window, cfg.blocked_window)


def run_detection(ctx: AppContext, *, now: datetime | None = None, window: tuple[datetime, datetime] | None = None,
                  late: bool = False) -> DetectionRun:
    """A failure propagates (the job records it), is kept as the run's last error, and leaves the watermark
    where it was, so the next run evaluates the same window again. last_ok_at is when a run last evaluated."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    lc = load_lateral_context(ctx, now=at)
    fdb = ctx.flows()
    empty = DetectionRun(window=None, new=0, updated=0, statuses=[], gaps=[], late=late)
    try:
        if not lc.collected:
            off = [_status(DetectorStatus(k, DetectorState.COLLECTION_OFF, "detector_collection_off"), False)
                   for k in DetectorKind]
            with fdb.writing(lc.generation) as conn:
                analysis.set_run(conn, KIND, status={s["detector"]: s for s in off})
            return empty.model_copy(update={"statuses": off})
        cfg = _config(lc)
        if window is None:
            hi = lc.traffic_watermark
            with fdb.connect() as conn:
                run = analysis.get_run(conn, KIND)
            previous = datetime.fromisoformat(run["watermark"]) if run is not None and run["watermark"] else None
            if hi is None or (previous is not None and hi <= previous):
                return empty
            lo = (previous if previous is not None else hi - cfg.fanout_window) - OVERLAP
        else:
            lo, hi = window
        start = lo - _lookback(cfg)
        blocked = observations(ctx, FilterSpec(start=lo - cfg.blocked_window, end=hi,
                                               decisions=(PolicyDecision.BLOCKED,)), now=at)
        # No management ports: nothing to read (an empty port filter would mean every port).
        admin = observations(ctx, FilterSpec(start=start, end=hi, ports=cfg.admin_ports.port_filters()),
                             now=at) if cfg.admin_ports.entries else blocked.model_copy(update={"rows": []})
        # A gap anywhere the detectors look — the lookback before the window included — makes the run incomplete.
        gaps = tuple(g for g in admin.coverage.gaps + blocked.coverage.gaps if g[0] < hi and g[1] > start)
        gaps = tuple(dict.fromkeys(gaps))
        inp0 = DetectorInput(window=(lo, hi), obs=admin.rows, blocked_obs=blocked.rows, hosts=_hosts(lc),
                             baseline_first_seen={}, precursors=[], config=cfg, baseline_days=lc.baseline_days,
                             baseline_required=lc.baseline_required, baseline_full=lc.baseline_full(), gaps=gaps)
        tuples = {(o.src_key, o.dst_key, o.port if o.port is not None else -1, o.proto)
                  for o in admin.rows if evaluable(o, inp0)}
        precursors = precursor_events(ctx, start=lo - cfg.precursor_window, end=hi)
        history, history_mode = _blocked_history(ctx, inp0, at)
        inp = replace(inp0, baseline_first_seen=baseline_first_seen(ctx, tuples), precursors=precursors.items,
                      blocked_history=history)
        found, statuses = run_detectors(inp)
        status_rows = [_status(s, bool(gaps)) for s in statuses]
        for row in status_rows:
            if row["detector"] == DetectorKind.BLOCKED_SURGE.value and history_mode is not None:
                row["params"]["history"] = history_mode
        with fdb.writing(lc.generation) as conn:
            new, updated = analysis.upsert_detections(conn, [_write(d) for d in found], dedup=dedup_windows(cfg),
                                                      late=late, at=at)
            analysis.set_run(conn, KIND, watermark=None if window is not None else hi, ok_at=at,
                             status={s["detector"]: s for s in status_rows})
        return DetectionRun(window=(lo, hi), new=new, updated=updated, statuses=status_rows, gaps=list(gaps),
                            late=late)
    except StaleGeneration:
        return empty  # the PCE was switched: nothing of the previous one is stored
    except Exception as exc:
        try:
            with fdb.writing(lc.generation) as conn:
                analysis.set_run(conn, KIND, error=f"{type(exc).__name__}: {exc}"[:500])
        except StaleGeneration:
            pass
        raise


def _hosts(lc: LateralContext) -> HostLookup:
    def lookup(key: str, ip: str, hostname: str | None, labels: Mapping[str, str]) -> HostInfo:
        return host_for(lc, key, ip=ip, hostname=hostname, labels=labels)
    return lookup


HISTORY = blocked_history.HISTORY


def _blocked_history(ctx: AppContext, inp: DetectorInput, at: datetime) -> tuple[dict[str, int], str | None]:
    """For the sources over the blocked threshold now: their most distinct blocked targets in any window of
    the 7 days before this run's window (usually none are over, and nothing is read). The second value says
    whether the hourly cache served it ("cached") or all 7 days were read ("live")."""
    cfg = inp.config
    over = [src for src, n in blocked_counts(inp).items() if n >= cfg.blocked_targets]
    if not over:
        return {}, None
    return blocked_history.history_for(ctx, over, window=cfg.blocked_window, lo=inp.window[0], now=at)


def _pending(conn: Any) -> set[str]:
    run = analysis.get_run(conn, LATE_KIND)
    return set(json.loads(run["status_json"]).get("pending", [])) if run is not None and run["status_json"] else set()


def queue_late_day(ctx: AppContext, day: date) -> None:
    """A day the daily re-read added records to: its late pass is owed until one succeeds."""
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:
        analysis.set_run(conn, LATE_KIND, status={"pending": sorted(_pending(conn) | {day.isoformat()})})


def pending_late_days(ctx: AppContext) -> list[date]:
    with ctx.flows().connect() as conn:
        return [date.fromisoformat(d) for d in sorted(_pending(conn))]


def clear_late_day(ctx: AppContext, day: date) -> None:
    fdb = ctx.flows()
    with fdb.writing(fdb.generation) as conn:
        analysis.set_run(conn, LATE_KIND, status={"pending": sorted(_pending(conn) - {day.isoformat()})})
