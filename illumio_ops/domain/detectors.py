"""Lateral-movement detectors (spec §6.5.1 "正在發生"): pure functions over observed connections.

Each run evaluates the connections that arrived live (origin ingest) and were last seen in its window
(lo, hi]; the rows before lo are context only. Backfilled history is never evaluated (spec §7). Every
detector also reports its state, so "nothing detected" is only said when it could have detected
something: a baseline still accumulating, a group not configured, or no data to judge by are states,
not silence (anti-goal 8).

Time is the VEN-reported timestamp_range of a daily flow bucket, at ten-minute granularity at best:
"within the window" means last seen in it.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from illumio_ops.domain.filter import EndpointFilter, FilterSpec
from illumio_ops.domain.lateral import AdminPortSet, HostInfo
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import (
    DetectorKind,
    DetectorState,
    PrecursorKind,
    SegmentView,
    Severity,
    raise_severity,
)

SAMPLE = 10  # target names a detection's summary carries; the count is always the full one
Gap = tuple[datetime, datetime, str]


@dataclass(frozen=True)
class Obs:
    """One observed connection (a primary flow row)."""
    src_key: str
    dst_key: str
    src_href: str | None
    dst_href: str | None
    src_ip: str
    dst_ip: str
    src_hostname: str | None
    dst_hostname: str | None
    port: int | None
    proto: int
    decision: str
    first: datetime
    last: datetime
    num_connections: int
    initiator_user: str | None
    initiator_process: str | None
    src_labels: Mapping[str, str]
    dst_labels: Mapping[str, str]
    src_managed: bool
    origin: str


@dataclass(frozen=True)
class DetectionConfidence:
    field: str | None = None          # the optional flow field the detector depends on
    covered: int | None = None        # observations in the window carrying it
    total: int | None = None
    baseline_days: float | None = None
    incomplete_gaps: tuple[Gap, ...] = ()


@dataclass(frozen=True)
class Detection:
    detector: DetectorKind
    fingerprint: str
    subject_key: str
    severity: Severity
    first_seen: datetime
    last_seen: datetime
    critical_asset: bool
    summary: Mapping[str, Any]
    segment: FlowSegment              # reproduces the evidence: detail view over the evidence period
    confidence: DetectionConfidence


@dataclass(frozen=True)
class DetectorStatus:
    detector: DetectorKind
    state: DetectorState
    reason_key: str | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Precursor:
    host_key: str
    kind: PrecursorKind
    at: datetime
    signal: bool  # a signal-type tamper event (the strongest precursor)


@dataclass(frozen=True)
class DetectorConfig:
    fanout_targets: int
    fanout_window: timedelta
    account_fanout_targets: int
    account_fanout_window: timedelta
    chain_window: timedelta
    blocked_targets: int
    blocked_window: timedelta
    blocked_surge_factor: float
    exclude_system_accounts: bool
    precursor_window: timedelta
    expected: Mapping[tuple[int, int | None], frozenset[str]]
    admin_ports: AdminPortSet
    environment_label_key: str
    admin_groups_configured: bool


HostLookup = Callable[[str, str, str | None, Mapping[str, str]], HostInfo]  # (key, ip, hostname, flow labels)


@dataclass(frozen=True)
class DetectorInput:
    window: tuple[datetime, datetime]
    obs: Sequence[Obs]                # management-port observations, with the lookback before the window
    blocked_obs: Sequence[Obs]        # blocked observations on any port
    hosts: HostLookup
    baseline_first_seen: Mapping[tuple[str, str, int, int], datetime]
    precursors: Sequence[Precursor]
    config: DetectorConfig
    baseline_days: float
    baseline_required: int
    baseline_full: bool
    gaps: tuple[Gap, ...]


def evaluable(o: Obs, inp: DetectorInput) -> bool:
    lo, hi = inp.window
    return o.origin == "ingest" and lo < o.last <= hi


def not_blocked(o: Obs) -> bool:
    return not o.decision.startswith("blocked")


def _dst_host(o: Obs, inp: DetectorInput) -> HostInfo:
    return inp.hosts(o.dst_key, o.dst_ip, o.dst_hostname, o.dst_labels)


def _endpoint(href: str | None, ip: str) -> EndpointFilter:
    return EndpointFilter(hrefs=(href,)) if href else EndpointFilter(ips=(ip,))


def evidence(inp: DetectorInput, start: datetime, end: datetime, *, src: Obs | None = None,
             dst: Obs | None = None) -> FlowSegment:
    """The detail segment that shows a detection's connections in the workbench."""
    spec = FilterSpec(start=start, end=end if end > start else start + timedelta(seconds=1),
                      src=_endpoint(src.src_href, src.src_ip) if src else None,
                      dst=_endpoint(dst.dst_href, dst.dst_ip) if dst else None,
                      ports=inp.config.admin_ports.port_filters())
    return FlowSegment(filter=spec, view=SegmentView.DETAIL, limit=200)


def _names(rows: Sequence[Obs]) -> list[str]:
    seen: dict[str, str] = {}
    for o in rows:
        seen.setdefault(o.dst_key, o.dst_hostname or o.dst_ip)
    return sorted(seen.values())[:SAMPLE]


def detect_fanout(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """One host starting management-port connections to at least fanout_targets hosts within
    fanout_window (5.x B006: high when an allowed connection is among them, else medium)."""
    cfg = inp.config
    by_src: dict[str, list[Obs]] = {}
    for o in inp.obs:
        if not_blocked(o):
            by_src.setdefault(o.src_key, []).append(o)
    out = []
    for src, rows in sorted(by_src.items()):
        rows.sort(key=lambda o: o.last)
        counts: Counter[str] = Counter()
        best: tuple[int, int, int] | None = None  # (targets, start index, end index)
        j = 0
        for i, o in enumerate(rows):
            counts[o.dst_key] += 1
            while rows[j].last < o.last - cfg.fanout_window:
                counts[rows[j].dst_key] -= 1
                if not counts[rows[j].dst_key]:
                    del counts[rows[j].dst_key]
                j += 1
            if evaluable(o, inp) and len(counts) >= cfg.fanout_targets and (best is None or len(counts) > best[0]):
                best = (len(counts), j, i)
        if best is None:
            continue
        window_rows = rows[best[1]:best[2] + 1]
        critical = any(_dst_host(o, inp).critical for o in window_rows)
        severity = Severity.HIGH if any(o.decision == "allowed" for o in window_rows) else Severity.MEDIUM
        if critical:
            severity = raise_severity(severity)
        first, last = min(o.first for o in window_rows), window_rows[-1].last
        out.append(Detection(
            detector=DetectorKind.FANOUT, fingerprint=f"fanout|{src}", subject_key=src, severity=severity,
            first_seen=first, last_seen=last, critical_asset=critical,
            summary={"targets": best[0], "sample_targets": _names(window_rows),
                     "ports": sorted({o.port for o in window_rows if o.port is not None}),
                     "window_minutes": int(cfg.fanout_window / timedelta(minutes=1))},
            segment=evidence(inp, last - cfg.fanout_window, last, src=window_rows[-1]),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.FANOUT, DetectorState.OK)


def detect_new_admin(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A source → destination × management port the baseline first saw in this window. Not before the
    baseline is full: until then everything looks new (the status says how many days have accumulated)."""
    if not inp.baseline_full:
        return [], DetectorStatus(DetectorKind.NEW_ADMIN_CONNECTION, DetectorState.ACCUMULATING,
                                  "detector_baseline_accumulating",
                                  {"days": round(inp.baseline_days, 1), "required": inp.baseline_required})
    lo, hi = inp.window
    seen: dict[tuple[str, str, int, int], Obs] = {}
    for o in inp.obs:
        if not evaluable(o, inp):
            continue
        key = (o.src_key, o.dst_key, o.port if o.port is not None else -1, o.proto)
        first = inp.baseline_first_seen.get(key)
        if first is not None and lo < first <= hi and key not in seen:
            seen[key] = o
    out = []
    for (src, dst, port, proto), o in sorted(seen.items()):
        critical = _dst_host(o, inp).critical
        out.append(Detection(
            detector=DetectorKind.NEW_ADMIN_CONNECTION, fingerprint=f"new|{src}|{dst}|{port}|{proto}",
            subject_key=src, severity=Severity.HIGH if critical else Severity.MEDIUM,
            first_seen=inp.baseline_first_seen[(src, dst, port, proto)], last_seen=o.last, critical_asset=critical,
            summary={"target": o.dst_hostname or o.dst_ip, "port": port, "proto": proto, "decision": o.decision},
            segment=evidence(inp, o.first, o.last, src=o, dst=o),
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.NEW_ADMIN_CONNECTION, DetectorState.OK)


def _pending(kind: DetectorKind) -> Callable[[DetectorInput], tuple[list[Detection], DetectorStatus]]:
    def run(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
        return [], DetectorStatus(kind, DetectorState.DISABLED, "detector_pending")
    return run


DETECTORS: dict[DetectorKind, Callable[[DetectorInput], tuple[list[Detection], DetectorStatus]]] = {
    DetectorKind.FANOUT: detect_fanout,
    DetectorKind.NEW_ADMIN_CONNECTION: detect_new_admin,
} | {k: _pending(k) for k in DetectorKind if k not in (DetectorKind.FANOUT, DetectorKind.NEW_ADMIN_CONNECTION)}


def dedup_windows(cfg: DetectorConfig) -> dict[str, timedelta]:
    """How long a repeat of a detector's fingerprint extends the same detection (store dedup)."""
    day = timedelta(hours=24)
    return {
        DetectorKind.FANOUT: cfg.fanout_window, DetectorKind.NEW_ADMIN_CONNECTION: timedelta(days=30),
        DetectorKind.PIVOT_CHAIN: day, DetectorKind.NON_ADMIN_GROUP: day, DetectorKind.CROSS_ENV: day,
        DetectorKind.UNEXPECTED_INITIATOR: day, DetectorKind.ACCOUNT_FANOUT: cfg.account_fanout_window,
        DetectorKind.BLOCKED_SURGE: cfg.blocked_window,
    }


def run_detectors(inp: DetectorInput) -> tuple[list[Detection], list[DetectorStatus]]:
    detections: list[Detection] = []
    statuses: list[DetectorStatus] = []
    for kind in DetectorKind:
        found, status = DETECTORS[kind](inp)
        detections += found
        statuses.append(status)
    return detections, statuses
