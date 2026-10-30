"""The lateral movement page (spec §6.5.1, P6c): exposure, what is happening, and deny rule simulation.

Full and alert mode read the hourly exposure result as stored (services/analysis/exposure.py) — nothing is computed
per request — and name its hosts. Lightweight mode keeps no traffic, so the page asks for it: the graph's
management ports for the chosen days are read from the PCE (the ports pushed to the PCE, spec §6.4: "只取管理 port"),
the same computation runs on them, and the result and its edges are held KEEP for the clicks that follow. Detections
need the traffic of every collection cycle: in lightweight mode the page says so instead of listing none."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from illumio_ops.domain.deny import DenyProposal, proposal_filter
from illumio_ops.domain.exposure import EdgeIn, ExposureResult
from illumio_ops.domain.filter import FilterSpec, PortProto
from illumio_ops.domain.focus import DETECTION_TITLE_KEYS
from illumio_ops.domain.lateral import GRAPH_CLASSES
from illumio_ops.domain.values import CapabilityState, CollectionMode, DetectorKind
from illumio_ops.services import workbench
from illumio_ops.services.analysis.context import LateralContext, load_lateral_context
from illumio_ops.services.analysis.deny_sim import DenySimulation, simulate_deny
from illumio_ops.services.analysis.exposure import exposure_from, graph_edges
from illumio_ops.services.analysis.focus import STALE_AFTER
from illumio_ops.services.analysis.status import DetectorStatusView, detector_states
from illumio_ops.services.collect.guard import require_same_pce
from illumio_ops.services.context import AppContext
from illumio_ops.services.hosts import display_names
from illumio_ops.services.ondemand import INTERACTIVE_PULL, pull_period
from illumio_ops.services.workbench_store import PullInfo
from illumio_ops.store.flowdb import analysis, capabilities, workloads
from illumio_ops.store.flowdb import ransomware as ransomware_store
from illumio_ops.store.flowdb.db import StaleGeneration

KEEP = timedelta(minutes=30)
LIGHTWEIGHT_DAYS = (1, 7, 30)
DETECTION_ROWS = 50
WEEK = timedelta(days=7)
HOUR = timedelta(hours=1)


class NotComputed(Exception):
    """Lightweight mode: no exposure is held, so there is no graph to simulate a deny rule on."""


class LateralDetection(BaseModel):
    detector: DetectorKind
    severity: str
    subject: str
    subject_name: str
    critical_asset: bool
    first_seen: datetime
    last_seen: datetime
    title_key: str
    params: dict[str, Any]
    link_q: str | None  # the evidence as a workbench request; None when the workbench cannot open it


class DenySimulationView(BaseModel):
    simulation: DenySimulation
    names: dict[str, str]  # every host key the simulation lists, as the page shows it
    pull: PullInfo | None  # lightweight mode: the proposal's traffic read for it


class LateralPage(BaseModel):
    state: Literal["ok", "not_computed", "collection_off", "lightweight"]
    source: Literal["stored", "pulled"] | None
    computed_at: datetime | None
    stale: bool
    exposure: ExposureResult | None
    names: dict[str, str]
    pull: PullInfo | None
    critical_set: bool
    admin_set: bool
    ransomware_unsupported: bool
    detections_available: bool  # traffic is collected every cycle (not lightweight, collection on)
    detectors: list[DetectorStatusView]
    detections: list[LateralDetection]
    detections_total: int
    collection_stopped: bool  # traffic is no longer collected: the result shown is the last one computed
    last_run_failed: bool     # the latest hourly computation failed: the result shown is older
    detect_state: Literal["ok", "failed", "not_run"]  # the latest detection run; "not_run": none succeeded yet
    ransomware_rated: int     # hosts the PCE gives a ransomware rating
    ransomware_unread: int    # of those, hosts whose details (where footholds come from) were not read, or are older
    observation_days_setting: int
    lightweight_days: list[int]
    port_names: dict[str, str]  # "<port>/<proto>" -> the management port's name (RDP, SMB...)


@dataclass(frozen=True)
class _Held:
    key: tuple[str, str, int, int, str]
    result: ExposureResult
    edges: list[EdgeIn]
    window: tuple[datetime, datetime]
    names: dict[str, str]
    pull: PullInfo
    since: float


_held: _Held | None = None
_lock = threading.Lock()  # bookkeeping only, never held while the PCE answers
_pull_lock = INTERACTIVE_PULL  # one interactive pull at a time, shared with the workbench


def drop() -> None:
    global _held
    with _lock:
        _held = None


def _clock(now: datetime | None, at: datetime) -> float:
    return time.monotonic() if now is None else at.timestamp()


def _key(ctx: AppContext, lc: LateralContext, days: int) -> tuple[str, str, int, int, str]:
    pce = ctx.settings.current().pce
    lateral = hashlib.sha256(lc.settings.model_dump_json().encode()).hexdigest()
    return (pce.url, str(pce.org_id), ctx.flows().generation, days, lateral)


def _current(key_of: Any, clock: float) -> _Held | None:
    """The held result when its PCE, store and lateral settings are still the current ones and KEEP has not passed."""
    global _held
    with _lock:
        h = _held
        if h is None:
            return None
        if clock - h.since > KEEP.total_seconds() or h.key != key_of(h.key[3]):
            _held = None
            return None
        return h


def _lightweight(ctx: AppContext) -> bool:
    return ctx.settings.current().collection.mode is CollectionMode.LIGHTWEIGHT


def _keys_of(result: ExposureResult) -> set[str]:
    keys = {h.key for h in result.hosts} | {a.key for a in result.assets} | {f.host for f in result.footholds}
    for a in result.assets:
        keys |= {k for p in a.paths for k in p}
        keys |= {k for c in a.cuts for k in (c.src, c.dst) if k}
    keys |= {k for x in result.cross_env for k in (x.src, x.dst)}
    return keys


def _detections(ctx: AppContext, conn: Any, at: datetime) -> tuple[list[LateralDetection], int]:
    rows, total = analysis.detections_ranked(conn, at - WEEK, limit=DETECTION_ROWS)
    names = display_names(ctx, {str(r["subject_key"]) for r in rows})
    out = []
    for r in rows:
        kind = DetectorKind(r["detector"])
        summary = json.loads(r["summary_json"] or "{}")
        subject = str(r["subject_key"])
        try:
            link_q: str | None = workbench.request_for("flow", json.loads(r["segment_json"] or "{}")).model_dump_json(
                exclude_none=True)
        except (ValidationError, ValueError):
            link_q = None  # longer than the workbench's period, or not a flow segment
        out.append(LateralDetection(
            detector=kind, severity=str(r["severity"]), subject=subject, subject_name=names.get(subject, subject),
            critical_asset=bool(r["critical_asset"]), first_seen=datetime.fromisoformat(r["first_seen"]),
            last_seen=datetime.fromisoformat(r["last_seen"]), title_key=DETECTION_TITLE_KEYS[kind],
            params={**summary, "host": names.get(subject, subject), "account": subject,
                    "minutes": summary.get("window_minutes")}, link_q=link_q))
    return out, total


def view(ctx: AppContext, *, now: datetime | None = None) -> LateralPage:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)  # a switch not yet cleared: not the previous PCE's graph
    lc = load_lateral_context(ctx, now=at)
    light = _lightweight(ctx)
    with ctx.flows().connect() as conn:
        row = None if light else analysis.read_result(conn, "exposure")
        run = analysis.get_run(conn, "exposure")
        cap = capabilities.all(conn).get("ransomware_risk")
        detectors = detector_states(conn)
        detect_run = analysis.get_run(conn, "detect")
        held_rw = ransomware_store.source_updated(conn)
        inventory = workloads.all_workloads(conn)
        detections, total = _detections(ctx, conn, at) if lc.collected and not light else ([], 0)
    rated = [w for w in inventory if w.risk_percent is not None or w.risk_updated_at is not None]
    unread = sum(1 for w in rated if w.href not in held_rw or (w.risk_updated_at and held_rw[w.href] != w.risk_updated_at))
    detect_state: Literal["ok", "failed", "not_run"] = (
        "failed" if detect_run is not None and detect_run["last_error"]
        else "ok" if detect_run is not None and detect_run["last_ok_at"] else "not_run")
    base: dict[str, Any] = {"collection_stopped": not light and not lc.collected,
                            "last_run_failed": not light and run is not None and bool(run["last_error"]),
                            "detect_state": detect_state, "ransomware_rated": len(rated), "ransomware_unread": unread,
                            "critical_set": bool(lc.settings.critical_assets), "admin_set": bool(lc.settings.admin_groups),
            "ransomware_unsupported": cap is not None and cap.state == CapabilityState.UNSUPPORTED,
            "detections_available": lc.collected and not light, "detectors": [] if light else detectors,
            "detections": detections, "detections_total": total,
            "observation_days_setting": lc.settings.observation_days,
            "lightweight_days": [d for d in LIGHTWEIGHT_DAYS if d <= lc.settings.observation_days] or [1],
            "port_names": {f"{e.port}/{e.proto}": e.name for e in lc.admin_ports.entries
                           if e.name and e.proto is not None}}
    if light:
        h = _current(lambda days: _key(ctx, lc, days), _clock(now, at))
        if h is None:
            return LateralPage(state="lightweight", source=None, computed_at=None, stale=False, exposure=None,
                               names={}, pull=None, **base)
        return LateralPage(state="ok", source="pulled", computed_at=h.result.computed_at, stale=False,
                           exposure=h.result, names=h.names, pull=h.pull, **base)
    if row is None:
        off = run is not None and json.loads(run["status_json"] or "{}").get("state") == "collection_off"
        return LateralPage(state="collection_off" if off or not lc.collected else "not_computed", source=None,
                           computed_at=None, stale=False, exposure=None, names={}, pull=None, **base)
    result = ExposureResult.model_validate_json(row["result_json"])
    computed = datetime.fromisoformat(row["computed_at"])
    return LateralPage(state="ok", source="stored", computed_at=computed, stale=computed < at - STALE_AFTER,
                       exposure=result, names=display_names(ctx, _keys_of(result)), pull=None, **base)


def _floor(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _graph_ports(lc: LateralContext) -> tuple[PortProto, ...]:
    seen = dict.fromkeys((e.port, e.proto) for e in lc.admin_ports.entries if e.category in GRAPH_CLASSES)
    return tuple(PortProto(port=port, proto=proto) for port, proto in seen)


def compute(ctx: AppContext, days: int, *, now: datetime | None = None) -> LateralPage:
    """Lightweight mode: read the graph's management ports for the last `days` from the PCE and compute the exposure
    on them. Raises ValueError outside lightweight mode or for days not offered, OnDemandFailed when the PCE could
    not answer, StaleGeneration when the PCE changed meanwhile."""
    global _held
    at = (now or datetime.now(UTC)).astimezone(UTC)
    if not _lightweight(ctx):
        raise ValueError("the exposure is computed every hour from the collected traffic")
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)
    lc = load_lateral_context(ctx, now=at)
    if days not in LIGHTWEIGHT_DAYS or days > max(lc.settings.observation_days, 1):
        raise ValueError("days not offered")
    key = _key(ctx, lc, days)
    start, end = _floor(at - timedelta(days=days)), _floor(at) + HOUR
    with _pull_lock:
        with pull_period(ctx, start=start, end=end, spec=FilterSpec(start=start, end=end, ports=_graph_ports(lc)),
                         now=at) as res:
            plc = load_lateral_context(res.ctx, now=at)
            edges = graph_edges(res.ctx, plc, since=start)
            result = exposure_from(res.ctx, plc, edges, since=start, now=at)
            names = display_names(res.ctx, _keys_of(result))
        if _key(ctx, lc, days)[:3] != key[:3]:
            raise StaleGeneration  # the PCE changed while it was read: not this PCE's graph
        pull = PullInfo(start=start, end=end, rows=res.rows, capped=res.capped_total, unread_from=res.unread_from,
                        truncated_windows=len(res.truncated), read_at=at)
        with _lock:
            _held = _Held(key=key, result=result, edges=edges, window=(start, end), names=names, pull=pull,
                          since=_clock(now, at))
    return view(ctx, now=now)


def _named(ctx: AppContext, sim: DenySimulation, pull: PullInfo | None) -> DenySimulationView:
    keys = {c.asset for c in sim.reach_change}
    keys |= {k for r in (*sim.sources, *sim.destinations) for k in r.keys if isinstance(k, str)}
    keys |= {k for f in sim.sample for k in (f.src_key, f.dst_key)}
    return DenySimulationView(simulation=sim, names=display_names(ctx, keys), pull=pull)


def simulate(ctx: AppContext, proposal: DenyProposal, *, now: datetime | None = None) -> DenySimulationView:
    """What the deny rule would block and how it changes the reach of each critical asset; read-only, never a write
    to the PCE. The graph is the one the page shows: in full and alert mode the stored result's period, without the
    connections first seen after it was computed; in lightweight mode the held one, with the proposal's own traffic
    read from the PCE for its period (NotComputed when none is held)."""
    at = (now or datetime.now(UTC)).astimezone(UTC)
    with ctx.flows().connect() as conn:
        require_same_pce(conn, ctx.settings.current().pce)
        row = None if _lightweight(ctx) else analysis.read_result(conn, "exposure")
    if not _lightweight(ctx):
        if row is None:
            return _named(ctx, simulate_deny(ctx, proposal, now=at), None)
        shown = ExposureResult.model_validate_json(row["result_json"])
        lc = load_lateral_context(ctx, now=at)
        start, end = shown.observation_from, shown.observation_to
        edges = graph_edges(ctx, lc, since=start, until=end)
        return _named(ctx, simulate_deny(ctx, proposal, now=at, window=(start, end), edges=edges), None)
    lc = load_lateral_context(ctx, now=at)
    h = _current(lambda days: _key(ctx, lc, days), _clock(now, at))
    if h is None:
        raise NotComputed
    start, end = h.window
    with _pull_lock:
        # the PCE may have changed while another pull held the lock: not the previous PCE's graph
        if _key(ctx, lc, h.key[3])[:3] != h.key[:3] or _current(lambda days: _key(ctx, lc, days), _clock(now, at)) is not h:
            raise StaleGeneration
        with pull_period(ctx, start=start, end=end, spec=proposal_filter(proposal, start=start, end=end),
                         now=at) as res:
            sim = simulate_deny(res.ctx, proposal, now=at, window=h.window, edges=h.edges)
            pull = PullInfo(start=start, end=end, rows=res.rows, capped=res.capped_total, unread_from=res.unread_from,
                            truncated_windows=len(res.truncated), read_at=at)
            named = _named(res.ctx, sim, pull)
        if _key(ctx, lc, h.key[3])[:3] != h.key[:3]:
            raise StaleGeneration
        return named
