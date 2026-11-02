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
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.detectors import (
    AnomalyData,
    Detection,
    DetectionConfidence,
    DetectorInput,
    DetectorStatus,
    Obs,
    _coverage_status,
    _dst_host,
    _kinds_without,
    _src_host,
    ends,
    evaluable,
    not_blocked,
)
from illumio_ops.domain.filter import EndpointFilter, FilterSpec, PortProto
from illumio_ops.domain.identity import account_key, is_system_account
from illumio_ops.domain.lateral import EXECUTION, HostInfo
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
SAMPLE = 10                    # target names a summary carries
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
    targets: dict[tuple[str, str, int, int, str], list[Obs]] = {}
    for o in inp.traffic_obs:
        if not (evaluable(o, inp) and not_blocked(o)) or o.port is None or o.port >= DYNAMIC_PORTS:
            continue
        if cfg.admin_ports.matches(o.port, o.proto):
            continue
        first = inp.baseline_first_seen.get((o.src_key, o.dst_key, o.port, o.proto))
        if first is None or not lo < first <= hi:
            continue
        source = _src_host(o, inp)
        group = group_of(source.labels, keys) if source.managed else None  # only managed hosts are peers
        if group is None or data.group_sizes.get(group, 0) < cfg.peer_min_group:
            continue
        sig = target_signature(o.dst_key, o.dst_ip, _dst_host(o, inp), keys)
        if sig is None or sig in data.peer_seen.get((group, o.port, o.proto), frozenset()):
            continue
        found.setdefault((group, sig, o.port, o.proto, o.src_key), o)
        targets.setdefault((group, sig, o.port, o.proto, o.src_key), []).append(o)
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
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps),
            ends=ends((o,), targets[(group, sig, port, proto, src)])))
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
        by_bytes = (cls == "all" and a.bytes is not None and a.previous_bytes is not None
                    and over(a.bytes, a.previous_bytes, cfg.volume_min_bytes))
        if not (over(a.connections, a.previous_connections, min_connections) or by_bytes):
            continue
        ip = src[3:] if src.startswith("ip:") else next((o.src_ip for o in inp.traffic_obs if o.src_key == src), "")
        host = inp.hosts(src, ip, None, {})
        out.append(Detection(
            detector=kind, fingerprint=f"{prefix}|{src}", subject_key=src,
            severity=raise_severity(Severity.MEDIUM) if host.critical else Severity.MEDIUM,
            first_seen=hi - SURGE_WINDOW, last_seen=hi, critical_asset=host.critical,
            # Both metrics, whichever fired: the sentence shows each, "—" where no byte data was there to compare.
            summary={"connections": a.connections, "bytes": a.bytes, "previous_max": a.previous_connections,
                     "previous_max_bytes": a.previous_bytes, "mb": _mb(a.bytes), "previous_max_mb": _mb(a.previous_bytes),
                     "window_minutes": int(SURGE_WINDOW / timedelta(minutes=1))},
            segment=FlowSegment(filter=FilterSpec(start=hi - SURGE_WINDOW, end=hi, src=_endpoint(src, ip),
                                                  decisions=NOT_BLOCKED, ports=ports),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(incomplete_gaps=(*inp.gaps, *data.activity_gaps)),
            ends=(("s", src, ip),)))
    if data.activity_gaps:  # the history compared with has holes: a surge may only look like one
        return out, _status(kind, DetectorState.INCOMPLETE, history_gaps=len(data.activity_gaps))
    return out, _status(kind)


def _mb(value: int | None) -> int | str:
    return "—" if value is None else round(value / 2**20)


def detect_volume_surge(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """B: a source's connections or bytes in the last hour far above any hour of its own last 7 days."""
    cfg = inp.config
    return _surge(inp, DetectorKind.VOLUME_SURGE, "all", cfg.volume_min_connections, "volume")


def _names(rows: Sequence[Obs]) -> list[str]:
    seen: dict[str, str] = {}
    for o in rows:
        seen.setdefault(o.dst_key, o.dst_hostname or o.dst_ip)
    return sorted(seen.values())[:SAMPLE]


def _span(rows: Sequence[Obs]) -> tuple[datetime, datetime]:
    first, last = min(o.first for o in rows), max(o.last for o in rows)
    return first, last if last > first else first + timedelta(seconds=1)


def _in_window(inp: DetectorInput) -> list[Obs]:
    return [o for o in inp.traffic_obs if evaluable(o, inp) and not_blocked(o)]


def detect_account_new_source(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """An account with history (first seen at least account_history before the window) starting connections
    from a source host the baseline never saw it on (spec §6.5.8 C). Only as good as the user field's
    coverage, which every result states."""
    kind = DetectorKind.ACCOUNT_NEW_SOURCE
    cfg, data = inp.config, inp.anomaly
    if not inp.baseline_full:
        return [], _accumulating(kind, inp)
    rows = _in_window(inp)
    covered = [o for o in rows if o.initiator_user]
    if rows and not covered:
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_user_data", covered=0, total=len(rows))
    lo, hi = inp.window
    found: dict[tuple[str, str], list[Obs]] = {}
    for o in covered:
        account = account_key(o.initiator_user)
        if account is None or (cfg.exclude_system_accounts and is_system_account(o.initiator_user)):
            continue
        first, since = data.account_first.get((account, o.src_key)), data.account_since.get(account)
        if first is None or since is None or not lo < first <= hi or since > lo - cfg.account_history:
            continue
        found.setdefault((account, o.src_key), []).append(o)
    out = []
    for (account, src), hits in sorted(found.items()):
        critical = any(_dst_host(o, inp).critical for o in hits)
        start, end = _span(hits)
        out.append(Detection(
            detector=kind, fingerprint=f"acctsrc|{account}|{src}", subject_key=account,
            severity=raise_severity(Severity.MEDIUM) if critical else Severity.MEDIUM,
            first_seen=data.account_first[(account, src)], last_seen=max(o.last for o in hits), critical_asset=critical,
            summary={"user": hits[0].initiator_user, "source": hits[0].src_hostname or hits[0].src_ip,
                     "known_sources": data.account_sources.get(account, 0), "sample_targets": _names(hits)},
            segment=FlowSegment(filter=FilterSpec(start=start, end=end, src=_endpoint(src, hits[0].src_ip),
                                                  initiator_user=hits[0].initiator_user, decisions=NOT_BLOCKED),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(field="initiator_user", covered=len(covered), total=len(rows),
                                           incomplete_gaps=inp.gaps), ends=ends(hits, hits)))
    return out, _coverage_status(kind, ("detector_partial_users", "detector_partial_users_none_from"),
                                 {"covered": len(covered), "total": len(rows)}, len(covered) < len(rows),
                                 _kinds_without(rows, lambda o: bool(o.initiator_user), inp))


def _process_status(kind: DetectorKind, inp: DetectorInput, rows: Sequence[Obs],
                    covered: Sequence[Obs]) -> DetectorStatus:
    return _coverage_status(kind, ("detector_partial_processes", "detector_partial_processes_none_from"),
                            {"covered": len(covered), "total": len(rows)}, len(covered) < len(rows),
                            _kinds_without(rows, lambda o: bool(o.initiator_process), inp))


def _internal(o: Obs, inp: DetectorInput) -> bool:
    return _dst_host(o, inp).managed or not is_public(o.dst_ip)


def detect_suspicious_tool(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A remote-execution, reconnaissance or directory-attack tool (the configured list) starting a connection to
    an internal host (spec §6.5.8 D, E③). A port with an expected-initiator list is left to the unexpected-initiator
    detector, which already judges every process there."""
    kind = DetectorKind.SUSPICIOUS_TOOL
    cfg = inp.config
    if not cfg.suspicious_tools:
        return [], _status(kind, DetectorState.DISABLED, "detector_no_tools")
    rows = _in_window(inp)
    covered = [o for o in rows if o.initiator_process]
    if rows and not covered:
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_process_field", total=len(rows))
    found: dict[tuple[str, str], list[Obs]] = {}
    for o in covered:
        process = o.initiator_process or ""
        if process not in cfg.suspicious_tools or not _internal(o, inp) or _judged_elsewhere(o, inp):
            continue
        found.setdefault((o.src_key, process), []).append(o)
    out = []
    for (src, process), hits in sorted(found.items()):
        critical = any(_dst_host(o, inp).critical for o in hits)
        start, end = _span(hits)
        out.append(Detection(
            detector=kind, fingerprint=f"tool|{src}|{process}", subject_key=src,
            severity=raise_severity(Severity.MEDIUM) if critical else Severity.MEDIUM,
            first_seen=min(o.first for o in hits), last_seen=max(o.last for o in hits), critical_asset=critical,
            summary={"process": process, "port": hits[0].port, "target": hits[0].dst_hostname or hits[0].dst_ip,
                     "targets": len({o.dst_key for o in hits}), "sample_targets": _names(hits)},
            segment=FlowSegment(filter=FilterSpec(start=start, end=end, src=_endpoint(src, hits[0].src_ip),
                                                  initiator_process=process),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(field="initiator_process", covered=len(covered), total=len(rows),
                                           incomplete_gaps=inp.gaps), ends=ends(hits[:1], hits)))
    return out, _process_status(kind, inp, rows, covered)


def _judged_elsewhere(o: Obs, inp: DetectorInput) -> bool:
    cfg = inp.config
    listed = (o.port, o.proto) in cfg.expected or (o.port, None) in cfg.expected
    return listed and cfg.admin_ports.matches(o.port, o.proto, EXECUTION)


def detect_new_process(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A process starting connections on a host for the first time, on a host whose process history reaches
    process_history back (spec §6.5.8 D). Low: software updates do this too; it shows on the focus list and the
    lateral page, and a precursor or a critical target raises it."""
    kind = DetectorKind.NEW_PROCESS
    cfg, data = inp.config, inp.anomaly
    if not inp.baseline_full:
        return [], _accumulating(kind, inp)
    rows = _in_window(inp)
    covered = [o for o in rows if o.initiator_process]
    if rows and not covered:
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_process_field", total=len(rows))
    lo, hi = inp.window
    found: dict[tuple[str, str], list[Obs]] = {}
    for o in covered:
        process = o.initiator_process or ""
        if process in cfg.suspicious_tools:
            continue
        first, since = data.process_first.get((o.src_key, process)), data.process_since.get(o.src_key)
        if first is None or since is None or not lo < first <= hi or since > lo - cfg.process_history:
            continue
        found.setdefault((o.src_key, process), []).append(o)
    out = []
    for (src, process), hits in sorted(found.items()):
        critical = any(_dst_host(o, inp).critical for o in hits)
        start, end = _span(hits)
        out.append(Detection(
            detector=kind, fingerprint=f"newproc|{src}|{process}", subject_key=src,
            severity=raise_severity(Severity.LOW) if critical else Severity.LOW,
            first_seen=data.process_first[(src, process)], last_seen=max(o.last for o in hits),
            critical_asset=critical,
            summary={"process": process, "port": hits[0].port, "target": hits[0].dst_hostname or hits[0].dst_ip},
            segment=FlowSegment(filter=FilterSpec(start=start, end=end, src=_endpoint(src, hits[0].src_ip),
                                                  initiator_process=process),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(field="initiator_process", covered=len(covered), total=len(rows),
                                           baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps),
            ends=ends(hits[:1], hits)))
    return out, _process_status(kind, inp, rows, covered)


# ── E directory and authentication (spec §6.5.8 E) ───────────────────────────
DIRECTORY = frozenset({PortClass.DIRECTORY})
DIRECTORY_DETECTORS = frozenset({DetectorKind.AUTH_TO_NON_DC, DetectorKind.NEW_DC_CLIENT, DetectorKind.DIRECTORY_SURGE})
# What an attacker does after reading the directory: start running things on other hosts (E④).
EXECUTION_DETECTORS = frozenset({
    DetectorKind.FANOUT, DetectorKind.NEW_ADMIN_CONNECTION, DetectorKind.PIVOT_CHAIN, DetectorKind.NON_ADMIN_GROUP,
    DetectorKind.UNEXPECTED_INITIATOR, DetectorKind.SUSPICIOUS_TOOL,
})


def _no_directory_ports(kind: DetectorKind, inp: DetectorInput) -> DetectorStatus | None:
    if any(e.category is PortClass.DIRECTORY for e in inp.config.admin_ports.entries):
        return None
    return _status(kind, DetectorState.DISABLED, "detector_no_directory_ports")


def _directory_rows(inp: DetectorInput) -> list[Obs]:
    ports = inp.config.admin_ports
    return [o for o in _in_window(inp) if ports.matches(o.port, o.proto, DIRECTORY)]


def _is_server(o: Obs, data: AnomalyData) -> bool:
    return o.dst_key in data.directory_servers or o.dst_ip in data.directory_ips


def _servers_status(kind: DetectorKind, data: AnomalyData) -> DetectorStatus:
    """Running, saying how many directory servers traffic showed (and how many declared ones it did not)."""
    if data.directory_declared_missing:
        return _status(kind, reason="detector_directory_mismatch", missing=data.directory_declared_missing,
                       inferred=data.directory_inferred)
    return _status(kind, reason="detector_directory_inferred", inferred=data.directory_inferred)


def detect_auth_to_non_dc(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """① Authentication or directory traffic going to a host that is not a directory server (inferred from traffic,
    or declared). A public destination is high: Kerberos and LDAP have no business leaving."""
    kind = DetectorKind.AUTH_TO_NON_DC
    data = inp.anomaly
    off = _no_directory_ports(kind, inp)
    if off is not None:
        return [], off
    if not data.directory_servers and not data.directory_ips:
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_directory_servers")
    found: dict[tuple[str, str, int], Obs] = {}
    for o in _directory_rows(inp):
        if o.port is not None and not _is_server(o, data):
            found.setdefault((o.src_key, o.dst_key, o.port), o)
    out = []
    for (src, dst, port), o in sorted(found.items()):
        host = _dst_host(o, inp)
        severity = Severity.HIGH if is_public(o.dst_ip) else Severity.MEDIUM
        out.append(Detection(
            detector=kind, fingerprint=f"authdst|{src}|{dst}|{port}", subject_key=src,
            severity=raise_severity(severity) if host.critical else severity, first_seen=o.first, last_seen=o.last,
            critical_asset=host.critical,
            summary={"target": o.dst_hostname or o.dst_ip, "port": port, "decision": o.decision},
            segment=_pair_segment(o),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps), ends=ends((o,), (o,))))
    return out, _servers_status(kind, data)


def _pair_segment(o: Obs) -> FlowSegment:
    end = o.last if o.last > o.first else o.first + timedelta(seconds=1)
    return FlowSegment(filter=FilterSpec(start=o.first, end=end, src=_endpoint(o.src_key, o.src_ip),
                                         dst=_endpoint(o.dst_key, o.dst_ip),
                                         ports=(PortProto(port=o.port, proto=o.proto),) if o.port is not None else ()),
                       view=SegmentView.DETAIL, limit=200)


def detect_new_dc_client(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """② A source that had never talked to any directory server starting to (its connection first seen in this
    window). An unmanaged source is medium, a managed one low: a new domain member does this too."""
    kind = DetectorKind.NEW_DC_CLIENT
    data = inp.anomaly
    off = _no_directory_ports(kind, inp)
    if off is not None:
        return [], off
    if not data.directory_servers and not data.directory_ips:
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_directory_servers")
    if not inp.baseline_full:
        return [], _accumulating(kind, inp)
    lo, hi = inp.window
    found: dict[str, Obs] = {}
    servers: dict[str, list[Obs]] = {}
    for o in _directory_rows(inp):
        if not _is_server(o, data) or o.src_key in data.directory_clients_before:
            continue
        first = inp.baseline_first_seen.get((o.src_key, o.dst_key, o.port if o.port is not None else -1, o.proto))
        if first is not None and lo < first <= hi:
            found.setdefault(o.src_key, o)
            servers.setdefault(o.src_key, []).append(o)
    out = []
    for src, o in sorted(found.items()):
        critical = _dst_host(o, inp).critical
        severity = Severity.LOW if o.src_managed else Severity.MEDIUM
        out.append(Detection(
            detector=kind, fingerprint=f"dcclient|{src}", subject_key=src,
            severity=raise_severity(severity) if critical else severity, first_seen=o.first, last_seen=o.last,
            critical_asset=critical,
            summary={"target": o.dst_hostname or o.dst_ip, "port": o.port, "managed": o.src_managed},
            segment=_pair_segment(o),
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps),
            ends=ends((o,), servers[src])))
    return out, _servers_status(kind, data)


def detect_directory_surge(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """③ A source's directory traffic in the last hour far above any hour of its own last 7 days (the built-in
    directory ports: the flow store counts them without reading settings)."""
    kind = DetectorKind.DIRECTORY_SURGE
    off = _no_directory_ports(kind, inp)
    if off is not None:
        return [], off
    return _surge(inp, kind, "directory", inp.config.directory_min_connections, "dirsurge")


Recent = tuple[str, str, datetime, datetime]  # (subject, detector, first seen, last seen)


def apply_directory_followup(dets: Sequence[Detection], recent: Sequence[Recent], *,
                             window: timedelta) -> list[Detection]:
    """④ An execution detection (fan-out, a new management connection, a pivot, a tool…) of a host that had a
    directory detection shortly before is raised one level and says so: reading the directory, then running
    things elsewhere. Only an execution that ends after the directory activity began and starts within `window`
    of its end counts."""
    by_subject: dict[str, list[Recent]] = {}
    for r in recent:
        by_subject.setdefault(r[0], []).append(r)
    out = []
    for d in dets:
        found = [r for r in by_subject.get(d.subject_key, ())
                 if d.last_seen >= r[2] and d.first_seen <= r[3] + window]
        if d.detector not in EXECUTION_DETECTORS or not found or "after_directory" in d.summary:
            out.append(d)
            continue
        last = max(found, key=lambda r: r[3])
        out.append(replace(d, severity=raise_severity(d.severity),
                           summary=dict(d.summary) | {"after_directory": {"detector": last[1],
                                                                         "last_seen": last[3].isoformat()}}))
    return out


# ── the second batch (spec §6.5.8 第二批) ─────────────────────────────────────
HISTORY_DAYS = 14  # the hourly activity a quiet period and a host's usual hours reach back over (store keeps 15)


def _internal_end(key: str, ip: str, host: HostInfo) -> bool:
    return host.managed or not is_public(ip or (key[3:] if key.startswith("ip:") else ""))


def _pair_candidates(inp: DetectorInput) -> list[Obs]:
    """Connections first seen in this window, on a service port (not management, not dynamic), between two
    internal hosts: what F and G judge."""
    cfg = inp.config
    lo, hi = inp.window
    out = []
    for o in _in_window(inp):
        if o.port is None or o.port >= DYNAMIC_PORTS or cfg.admin_ports.matches(o.port, o.proto):
            continue
        first = inp.baseline_first_seen.get((o.src_key, o.dst_key, o.port, o.proto))
        if first is None or not lo < first <= hi:
            continue
        if _internal_end(o.src_key, o.src_ip, _src_host(o, inp)) and _internal_end(o.dst_key, o.dst_ip,
                                                                                    _dst_host(o, inp)):
            out.append(o)
    return out


def _ports_segment(hits: Sequence[Obs]) -> FlowSegment:
    start, end = _span(hits)
    o = hits[0]
    ports = tuple(PortProto(port=p, proto=pr) for p, pr in sorted({(h.port, h.proto) for h in hits if h.port}))
    return FlowSegment(filter=FilterSpec(start=start, end=end, src=_endpoint(o.src_key, o.src_ip),
                                         dst=_endpoint(o.dst_key, o.dst_ip), ports=ports),
                       view=SegmentView.DETAIL, limit=200)


def detect_direction_reversal(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """F: B starting a connection to A where A had always been the one to start them — A→B on some port before the
    window, B→A on none (blocked attempts count as having happened). Example: a database server connecting to its
    application server."""
    kind = DetectorKind.DIRECTION_REVERSAL
    data = inp.anomaly
    if not inp.baseline_full:
        return [], _accumulating(kind, inp)
    found: dict[tuple[str, str], list[Obs]] = {}
    for o in _pair_candidates(inp):
        if (o.dst_key, o.src_key) in data.pairs_before and (o.src_key, o.dst_key) not in data.pairs_before:
            found.setdefault((o.src_key, o.dst_key), []).append(o)
    out = []
    for (src, dst), hits in sorted(found.items()):
        o = hits[0]
        critical = _dst_host(o, inp).critical
        out.append(Detection(
            detector=kind, fingerprint=f"reverse|{src}|{dst}", subject_key=src,
            severity=raise_severity(Severity.MEDIUM) if critical else Severity.MEDIUM,
            first_seen=min(h.first for h in hits), last_seen=max(h.last for h in hits), critical_asset=critical,
            summary={"target": o.dst_hostname or o.dst_ip, "port": o.port, "proto": o.proto,
                     "ports": sorted({h.port for h in hits if h.port is not None}), "decision": o.decision},
            segment=_ports_segment(hits),
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps),
            ends=ends(hits[:1], hits)))
    return out, _status(kind)


def detect_new_pair_port(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """G: a pair of hosts that already talked starting on a port it had never used. Medium when nobody had ever
    connected to the destination on that port (something new is listening there), low when the destination already
    served it to others. Not when the source's peer group already uses that port toward the same kind of host."""
    kind = DetectorKind.NEW_PAIR_PORT
    cfg, data = inp.config, inp.anomaly
    if not inp.baseline_full:
        return [], _accumulating(kind, inp)
    keys = cfg.peer_group_keys
    found: dict[tuple[str, str, int, int], list[Obs]] = {}
    for o in _pair_candidates(inp):
        if (o.src_key, o.dst_key) not in data.pairs_before or o.port is None:
            continue
        source = _src_host(o, inp)
        group = group_of(source.labels, keys) if source.managed else None
        if group is not None and data.group_sizes.get(group, 0) >= cfg.peer_min_group:
            sig = target_signature(o.dst_key, o.dst_ip, _dst_host(o, inp), keys)
            if sig is not None and sig in data.peer_seen.get((group, o.port, o.proto), frozenset()):
                continue
        found.setdefault((o.src_key, o.dst_key, o.port, o.proto), []).append(o)
    out = []
    for (src, dst, port, proto), hits in sorted(found.items()):
        o = hits[0]
        critical = _dst_host(o, inp).critical
        listener = (dst, port, proto) not in data.ports_served
        base = Severity.MEDIUM if listener else Severity.LOW
        out.append(Detection(
            detector=kind, fingerprint=f"pairport|{src}|{dst}|{port}|{proto}", subject_key=src,
            severity=raise_severity(base) if critical else base,
            first_seen=min(h.first for h in hits), last_seen=max(h.last for h in hits), critical_asset=critical,
            summary={"target": o.dst_hostname or o.dst_ip, "port": port, "proto": proto, "new_listener": listener,
                     "decision": o.decision},
            segment=_ports_segment(hits),
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps),
            ends=ends(hits[:1], hits)))
    return out, _status(kind)


def _hour(inp: DetectorInput) -> datetime:
    return inp.window[1].astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _overlaps(gaps: Sequence[tuple[datetime, datetime, str]], start: datetime, end: datetime) -> bool:
    return any(g[0] < end and g[1] > start for g in gaps)


def _hours_ready(kind: DetectorKind, inp: DetectorInput, required: float) -> DetectorStatus | None:
    data = inp.anomaly
    if not data.live:
        return _status(kind, reason="detector_live_only")
    if data.activity_days < required:
        return _status(kind, DetectorState.ACCUMULATING, "detector_activity_accumulating",
                       days=round(data.activity_days - 0.05, 1) if data.activity_days else 0.0, required=int(required))
    return None


def _src_ip(inp: DetectorInput, src: str) -> str:
    return src[3:] if src.startswith("ip:") else next((o.src_ip for o in inp.traffic_obs if o.src_key == src), "")


def _dst_ip(inp: DetectorInput, dst: str) -> str:
    return dst[3:] if dst.startswith("ip:") else next((o.dst_ip for o in inp.traffic_obs if o.dst_key == dst), "")


def _last_hour(inp: DetectorInput, *, src: EndpointFilter | None = None,
               dst: EndpointFilter | None = None) -> FlowSegment:
    hi = inp.window[1]
    return FlowSegment(filter=FilterSpec(start=hi - SURGE_WINDOW, end=hi, src=src, dst=dst, decisions=NOT_BLOCKED),
                       view=SegmentView.DETAIL, limit=200)


def _host_hour(inp: DetectorInput, kind: DetectorKind, fingerprint: str, src: str, base: Severity,
               summary: dict[str, object], gaps: tuple[tuple[datetime, datetime, str], ...] = ()) -> Detection:
    ip = _src_ip(inp, src)
    host = inp.hosts(src, ip, None, {})
    hi = inp.window[1]
    return Detection(
        detector=kind, fingerprint=fingerprint, subject_key=src,
        severity=raise_severity(base) if host.critical else base, first_seen=hi - SURGE_WINDOW, last_seen=hi,
        critical_asset=host.critical, summary=summary | {"window_minutes": int(SURGE_WINDOW / timedelta(minutes=1))},
        segment=_last_hour(inp, src=_endpoint(src, ip)),
        confidence=DetectionConfidence(incomplete_gaps=(*inp.gaps, *gaps)), ends=(("s", src, ip),))


def _managed_source(inp: DetectorInput, src: str) -> bool:
    return inp.hosts(src, _src_ip(inp, src), None, {}).managed


def detect_quiet_host_wakes(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """H: a managed host that had started no connection for `quiet` (and was known before that) starting at least
    quiet_min_connections in the last hour. A collection gap in the quiet period leaves it unjudged: a host is not
    told quiet from data that was never collected."""
    kind = DetectorKind.QUIET_HOST_WAKES
    cfg, data = inp.config, inp.anomaly
    off = _hours_ready(kind, inp, cfg.quiet / timedelta(days=1))
    if off is not None:
        return [], off
    hour = _hour(inp)
    start, end = hour - cfg.quiet, hour - timedelta(hours=1)
    if _overlaps(data.hours_gaps, start, end):
        return [], _status(kind, DetectorState.INCOMPLETE, "detector_quiet_gaps",
                           gaps=sum(1 for g in data.hours_gaps if g[0] < end and g[1] > start))
    out = []
    for src, n in sorted(data.recent.items()):
        if n < cfg.quiet_min_connections or src not in data.known_before_quiet or not _managed_source(inp, src):
            continue
        hours = data.active_hours.get(src, ())
        if any(start <= h < end for h in hours):
            continue
        last = max((h for h in hours if h < start), default=None)
        out.append(_host_hour(inp, kind, f"quiet|{src}", src, Severity.MEDIUM,
                              {"connections": n, "quiet_days": cfg.quiet.days,
                               "last_active": last.isoformat() if last else None}))
    return out, _status(kind)


def _usual(hours: Sequence[datetime]) -> str:
    """The hours of the day a host was active in, as ranges: "01–09", "08–12, 14"."""
    seen = sorted({h.hour for h in hours})
    runs: list[list[int]] = []
    for h in seen:
        if runs and h == runs[-1][1] + 1:
            runs[-1][1] = h
        else:
            runs.append([h, h])
    return ", ".join(f"{a:02d}" if a == b else f"{a:02d}–{b:02d}" for a, b in runs)


def detect_off_hours(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """J: a managed host with a routine (active on off_hours_min_days days of the kept history) starting at least
    off_hours_min_connections in the last hour, when neither clock hour that hour touches had ever seen it active.
    Low: maintenance windows do this too. A collection gap at those hours on any day leaves it unjudged."""
    kind = DetectorKind.OFF_HOURS
    cfg, data = inp.config, inp.anomaly
    off = _hours_ready(kind, inp, ACTIVITY_DAYS)
    if off is not None:
        return [], off
    hour = _hour(inp)
    slots = {(hour - timedelta(hours=1)).hour, hour.hour}
    # the kept days, from the first live hour on (before it nothing was recorded, gap or not)
    start = max(hour - timedelta(days=HISTORY_DAYS), hour - timedelta(days=data.activity_days))
    end = hour - timedelta(hours=1)
    spans = [(start + timedelta(hours=i), start + timedelta(hours=i + 1))
             for i in range(int((end - start) / timedelta(hours=1)))
             if (start + timedelta(hours=i)).hour in slots]
    if any(_overlaps(data.hours_gaps, a, b) for a, b in spans):
        return [], _status(kind, DetectorState.INCOMPLETE, "detector_off_hours_gaps")
    out = []
    for src, n in sorted(data.recent.items()):
        if n < cfg.off_hours_min_connections or not _managed_source(inp, src):
            continue
        hours = [h for h in data.active_hours.get(src, ()) if start <= h < end]
        days = {h.date() for h in hours}
        if len(days) < cfg.off_hours_min_days or any(h.hour in slots for h in hours):
            continue
        out.append(_host_hour(inp, kind, f"offhours|{src}|{hour.hour}", src, Severity.LOW,
                              {"connections": n, "active_days": len(days), "usual_hours": _usual(hours),
                               "hour": f"{hour.hour:02d}"}))
    return out, _status(kind)


def _public_key(key: str) -> bool:
    return key.startswith("ip:") and is_public(key[3:])


def detect_data_staging(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """I: an internal host receiving, over the last hour, at least staging_min_bytes from at least
    staging_min_sources internal hosts, and volume_surge_factor times its own most in any hour of the 7 days before
    (the floors alone when no hour carried bytes). Bytes are the connections' (both directions): only as good as
    the byte field's coverage, which every result states."""
    kind = DetectorKind.DATA_STAGING
    cfg, data = inp.config, inp.anomaly
    if not data.live:
        return [], _status(kind, reason="detector_live_only")
    if data.destination_days < ACTIVITY_DAYS:
        return [], _status(kind, DetectorState.ACCUMULATING, "detector_activity_accumulating",
                           days=round(data.destination_days - 0.05, 1) if data.destination_days else 0.0,
                           required=ACTIVITY_DAYS)
    with_bytes, total = data.fan_in_coverage
    if total and not with_bytes:
        return [], _status(kind, DetectorState.NO_DATA, "detector_no_byte_data", covered=0, total=total)
    out = []
    for dst, f in sorted(data.fan_in.items()):
        if _public_key(dst):
            continue
        sources = [s for s in f.sources if not _public_key(s)]
        if len(sources) < cfg.staging_min_sources or f.bytes < cfg.staging_min_bytes:
            continue
        if f.previous_bytes is not None and f.bytes < cfg.volume_surge_factor * f.previous_bytes:
            continue
        ip = _dst_ip(inp, dst)
        host = inp.hosts(dst, ip, None, {})
        if not _internal_end(dst, ip, host):
            continue
        hi = inp.window[1]
        names = [inp.hosts(s, _src_ip(inp, s), None, {}).hostname or s for s in sources]
        out.append(Detection(
            detector=kind, fingerprint=f"staging|{dst}", subject_key=dst,
            severity=raise_severity(Severity.MEDIUM) if host.critical else Severity.MEDIUM,
            first_seen=hi - SURGE_WINDOW, last_seen=hi, critical_asset=host.critical,
            summary={"target": host.hostname or ip or dst, "sources": len(sources), "connections": f.connections,
                     "bytes": f.bytes, "mb": _mb(f.bytes), "previous_max_bytes": f.previous_bytes,
                     "previous_max_mb": _mb(f.previous_bytes), "sample_sources": sorted(names)[:SAMPLE],
                     "window_minutes": int(SURGE_WINDOW / timedelta(minutes=1))},
            segment=_last_hour(inp, dst=_endpoint(dst, ip)),
            confidence=DetectionConfidence(field="bytes", covered=with_bytes, total=total,
                                           incomplete_gaps=(*inp.gaps, *data.fan_in_gaps)),
            ends=(*(("s", s, _src_ip(inp, s)) for s in sources), ("t", dst, ip))))
    if data.fan_in_gaps:
        return out, _status(kind, DetectorState.INCOMPLETE, history_gaps=len(data.fan_in_gaps))
    if with_bytes < total:
        return out, _status(kind, reason="detector_partial_bytes", covered=with_bytes, total=total)
    return out, _status(kind)


def drop_covered(dets: Sequence[Detection]) -> list[Detection]:
    """One thing, one detection: a surge (B) of a host covers its waking (H), and either covers its off-hours
    activity (J); a peer-group deviation (A) covers a new port (G) on the same connection."""
    surged = {d.subject_key for d in dets if d.detector is DetectorKind.VOLUME_SURGE}
    woke = {d.subject_key for d in dets if d.detector is DetectorKind.QUIET_HOST_WAKES} - surged
    peer = {(d.subject_key, k, d.summary.get("port")) for d in dets if d.detector is DetectorKind.PEER_DEVIATION
            for role, k, _ in d.ends if role == "t"}
    out = []
    for d in dets:
        if d.detector is DetectorKind.QUIET_HOST_WAKES and d.subject_key in surged:
            continue
        if d.detector is DetectorKind.OFF_HOURS and d.subject_key in surged | woke:
            continue
        if d.detector is DetectorKind.NEW_PAIR_PORT and any(
                (d.subject_key, k, d.summary.get("port")) in peer for role, k, _ in d.ends if role == "t"):
            continue
        out.append(d)
    return out
