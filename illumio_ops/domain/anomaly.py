"""Anomalies in allowed traffic (spec §6.5.8): what the vendor does not do — look for the unusual in the traffic
that was not blocked. Pure functions over the run's connections (DetectorInput.traffic_obs: every port, not
blocked, last seen in the window) and what the service looked up for them (AnomalyData). They share the
lateral-movement detectors' input, output and states (domain/detectors.py), so detections, the focus list and
the lateral alert rules treat them alike.

Each host and group is compared with its own history, never a global threshold; a detector whose history is
still short says "accumulating", and one whose field is missing says so (anti-goal 8).
"""
from __future__ import annotations

import ipaddress
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import timedelta

from illumio_ops.domain.detectors import (
    Detection,
    DetectionConfidence,
    DetectorInput,
    DetectorStatus,
    Obs,
    _dst_host,
    _src_host,
    evaluable,
    not_blocked,
)
from illumio_ops.domain.filter import EndpointFilter, FilterSpec, PortProto
from illumio_ops.domain.lateral import HostInfo
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import (
    DetectorKind,
    DetectorState,
    PolicyDecision,
    PortClass,
    SegmentView,
    Severity,
    raise_severity,
)

DYNAMIC_PORTS = 49152          # IANA dynamic range: a destination port up here is not a service a group uses
PEER_ROLLOUT = 0.5             # half a group starting the same thing at once is a change to the group, not one host
SURGE_WINDOW = timedelta(minutes=60)
ACTIVITY_DAYS = 7
NOT_BLOCKED = (PolicyDecision.ALLOWED, PolicyDecision.POTENTIALLY_BLOCKED, PolicyDecision.UNKNOWN)


def group_of(labels: Mapping[str, str], keys: Sequence[str]) -> str | None:
    """A host's peer group: the values of these label keys, when it has every one."""
    values = [labels.get(k) for k in keys]
    return "|".join(v for v in values if v) if all(values) else None


def is_public(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def target_signature(key: str, ip: str, host: HostInfo, keys: Sequence[str]) -> str | None:
    """What a destination is to a peer group: its own group when it is a managed host in one, else the host itself;
    a public address is not compared (egress is not peer behavior here)."""
    if host.managed:
        group = group_of(host.labels, keys)
        return f"g:{group}" if group else key
    if is_public(ip):
        return None
    return key


def _shown(group: str) -> str:
    return " / ".join(group.split("|"))


def _endpoint(key: str, ip: str) -> EndpointFilter:
    return EndpointFilter(ips=(ip,)) if key.startswith("ip:") or not key else EndpointFilter(hrefs=(key,))


def _status(kind: DetectorKind, state: DetectorState = DetectorState.OK, reason: str | None = None,
            **params: object) -> DetectorStatus:
    return DetectorStatus(kind, state, reason, params)


def _accumulating(kind: DetectorKind, inp: DetectorInput) -> DetectorStatus:
    return _status(kind, DetectorState.ACCUMULATING, "detector_baseline_accumulating",
                   days=round(inp.baseline_days, 1), required=inp.baseline_required)


def detect_peer_deviation(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """One host of a peer group (≥ peer_min_group managed hosts sharing the group labels) starting a kind of
    connection — destination group × port — none of its group had made before the window (spec §6.5.8 A).
    Management ports are left to the lateral detectors and E (a new one there is already a detection), dynamic
    ports and public destinations are not compared, and half a group starting it at once is a rollout."""
    kind = DetectorKind.PEER_DEVIATION
    cfg, data = inp.config, inp.anomaly
    keys = cfg.peer_group_keys
    if not inp.baseline_full:
        return [], _accumulating(kind, inp)
    if not any(n >= cfg.peer_min_group for n in data.group_sizes.values()):
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_peer_groups", keys=", ".join(keys),
                           min=cfg.peer_min_group)
    lo, hi = inp.window
    found: dict[tuple[str, str, int, int, str], Obs] = {}
    for o in inp.traffic_obs:
        if not (evaluable(o, inp) and not_blocked(o)) or o.port is None or o.port >= DYNAMIC_PORTS:
            continue
        if cfg.admin_ports.matches(o.port, o.proto):
            continue
        first = inp.baseline_first_seen.get((o.src_key, o.dst_key, o.port, o.proto))
        if first is None or not lo < first <= hi:
            continue
        group = group_of(_src_host(o, inp).labels, keys)
        if group is None or data.group_sizes.get(group, 0) < cfg.peer_min_group:
            continue
        sig = target_signature(o.dst_key, o.dst_ip, _dst_host(o, inp), keys)
        if sig is None or sig in data.peer_seen.get((group, o.port, o.proto), frozenset()):
            continue
        found.setdefault((group, sig, o.port, o.proto, o.src_key), o)
    starters = Counter((g, s, p, pr) for g, s, p, pr, _ in found)
    out = []
    for (group, sig, port, proto, src), o in sorted(found.items()):
        size = data.group_sizes[group]
        n = starters[(group, sig, port, proto)]
        if n >= size * PEER_ROLLOUT:
            continue
        dst = _dst_host(o, inp)
        severity = raise_severity(Severity.MEDIUM) if dst.critical else Severity.MEDIUM
        target = o.dst_hostname or o.dst_ip
        out.append(Detection(
            detector=kind, fingerprint=f"peer|{src}|{sig}|{port}|{proto}", subject_key=src, severity=severity,
            first_seen=o.first, last_seen=o.last, critical_asset=dst.critical,
            summary={"target": target, "target_group": _shown(sig[2:]) if sig.startswith("g:") else target,
                     "port": port, "proto": proto, "group": _shown(group), "group_size": size, "starters": n,
                     "decision": o.decision},
            segment=FlowSegment(filter=FilterSpec(start=o.first, end=o.last if o.last > o.first
                                                  else o.first + timedelta(seconds=1),
                                                  src=_endpoint(src, o.src_ip), dst=_endpoint(o.dst_key, o.dst_ip),
                                                  ports=(PortProto(port=port, proto=proto),)),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps)))
    return out, _status(kind)


def _surge(inp: DetectorInput, kind: DetectorKind, cls: str, min_connections: int,
           prefix: str) -> tuple[list[Detection], DetectorStatus]:
    """A source whose live connections (or bytes) over the last hour reached the floor and `volume_surge_factor`
    times its most in any hour of the 7 days before (the floor alone when it had none)."""
    cfg, data = inp.config, inp.anomaly
    if not data.live:
        return [], _status(kind, reason="detector_live_only")
    if data.activity_days < ACTIVITY_DAYS:
        return [], _status(kind, DetectorState.ACCUMULATING, "detector_activity_accumulating",
                           days=round(data.activity_days - 0.05, 1) if data.activity_days else 0.0,
                           required=ACTIVITY_DAYS)

    def over(now: int, previous: int, floor: int) -> bool:
        return now >= floor and (previous == 0 or now >= cfg.volume_surge_factor * previous)

    hi = inp.window[1]
    ports = cfg.admin_ports.port_filters({PortClass.DIRECTORY}) if cls == "directory" else ()
    out = []
    for (src, c), a in sorted(data.activity.items()):
        if c != cls:
            continue
        by_bytes = cls == "all" and a.bytes is not None and over(a.bytes, a.previous_bytes, cfg.volume_min_bytes)
        if not (over(a.connections, a.previous_connections, min_connections) or by_bytes):
            continue
        ip = src[3:] if src.startswith("ip:") else ""
        host = inp.hosts(src, ip, None, {})
        out.append(Detection(
            detector=kind, fingerprint=f"{prefix}|{src}", subject_key=src,
            severity=raise_severity(Severity.MEDIUM) if host.critical else Severity.MEDIUM,
            first_seen=hi - SURGE_WINDOW, last_seen=hi, critical_asset=host.critical,
            summary={"connections": a.connections, "bytes": a.bytes, "previous_max": a.previous_connections,
                     "previous_max_bytes": a.previous_bytes, "window_minutes": int(SURGE_WINDOW / timedelta(minutes=1))},
            segment=FlowSegment(filter=FilterSpec(start=hi - SURGE_WINDOW, end=hi, src=_endpoint(src, ip),
                                                  decisions=NOT_BLOCKED, ports=ports),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps)))
    return out, _status(kind)


def detect_volume_surge(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """B: a source's connections or bytes in the last hour far above any hour of its own last 7 days."""
    cfg = inp.config
    return _surge(inp, DetectorKind.VOLUME_SURGE, "all", cfg.volume_min_connections, "volume")
