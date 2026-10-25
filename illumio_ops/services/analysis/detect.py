"""The detection pipeline: after each traffic cycle the detectors run over the connections collected since
the last run (plus the collector's own overlap, so late-arriving records are evaluated too), and after the
daily re-read once more over the day it re-read (detections found then are marked late)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from illumio_ops.domain.detectors import (
    Detection,
    DetectorConfig,
    DetectorInput,
    DetectorStatus,
    HostLookup,
    dedup_windows,
    evaluable,
    run_detectors,
)
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.values import DetectorKind, DetectorState, PolicyDecision
from illumio_ops.services.analysis.context import (
    LateralContext,
    host_for,
    load_lateral_context,
)
from illumio_ops.services.collect.traffic import OVERLAP
from illumio_ops.services.context import AppContext
from illumio_ops.services.flowsource import baseline_first_seen, observations
from illumio_ops.settings.schema import DetectorSettings, LateralSettings
from illumio_ops.store.flowdb import analysis
from illumio_ops.store.flowdb.analysis import DetectionWrite
from illumio_ops.store.flowdb.db import StaleGeneration

KIND = "detect"


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
    return DetectorConfig(
        fanout_targets=d.fanout_targets, fanout_window=timedelta(minutes=d.fanout_window_minutes),
        account_fanout_targets=d.account_fanout_targets,
        account_fanout_window=timedelta(minutes=d.account_fanout_window_minutes),
        chain_window=timedelta(minutes=d.chain_window_minutes), blocked_targets=d.blocked_targets,
        blocked_window=timedelta(minutes=d.blocked_window_minutes), blocked_surge_factor=d.blocked_surge_factor,
        exclude_system_accounts=d.exclude_system_accounts, precursor_window=timedelta(hours=d.precursor_hours),
        expected={(e.port, e.proto): frozenset(e.processes) for e in lat.expected_initiators},
        admin_ports=lc.admin_ports, environment_label_key=lat.environment_label_key,
        admin_groups_configured=bool(lat.admin_groups))


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
    """A failure while storing propagates (the job records it) and leaves the watermark where it was, so the
    next run evaluates the same window again."""
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
        admin = observations(ctx, FilterSpec(start=lo - _lookback(cfg), end=hi, ports=cfg.admin_ports.port_filters()),
                             now=at)
        blocked = observations(ctx, FilterSpec(start=lo - cfg.blocked_window, end=hi,
                                               decisions=(PolicyDecision.BLOCKED,)), now=at)
        gaps = tuple(g for g in admin.coverage.gaps if g[0] < hi and g[1] > lo)
        inp0 = DetectorInput(window=(lo, hi), obs=admin.rows, blocked_obs=blocked.rows, hosts=_hosts(lc),
                             baseline_first_seen={}, precursors=[], config=cfg, baseline_days=lc.baseline_days,
                             baseline_required=lc.baseline_required, baseline_full=lc.baseline_full(), gaps=gaps)
        tuples = {(o.src_key, o.dst_key, o.port if o.port is not None else -1, o.proto)
                  for o in admin.rows if evaluable(o, inp0)}
        inp = replace(inp0, baseline_first_seen=baseline_first_seen(ctx, tuples))
        found, statuses = run_detectors(inp)
        status_rows = [_status(s, bool(gaps)) for s in statuses]
        with fdb.writing(lc.generation) as conn:
            new, updated = analysis.upsert_detections(conn, [_write(d) for d in found], dedup=dedup_windows(cfg),
                                                      late=late, at=at)
            analysis.set_run(conn, KIND, watermark=None if window is not None else hi,
                             status={s["detector"]: s for s in status_rows})
        return DetectionRun(window=(lo, hi), new=new, updated=updated, statuses=status_rows, gaps=list(gaps),
                            late=late)
    except StaleGeneration:
        return empty  # the PCE was switched: nothing of the previous one is stored


def _hosts(lc: LateralContext) -> HostLookup:
    def lookup(key: str, ip: str, hostname: str | None, labels: Mapping[str, str]) -> HostInfo:
        return host_for(lc, key, ip=ip, hostname=hostname, labels=labels)
    return lookup
