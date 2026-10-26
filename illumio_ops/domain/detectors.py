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
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from illumio_ops.domain.filter import EndpointFilter, FilterSpec
from illumio_ops.domain.identity import account_key, is_system_account
from illumio_ops.domain.lateral import (
    EXECUTION,
    EXECUTION_OR_DATA,
    AdminPortSet,
    HostInfo,
)
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import (
    DetectorKind,
    DetectorState,
    PortClass,
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
    admin_groups_configured: bool     # at least one admin-group selector names a label that exists
    environment_labels_present: bool  # the inventory carries the environment label key at all
    admin_groups_stale: bool = False  # selectors are set but every one names a label that is gone
    # Anomalies in allowed traffic (spec §6.5.8)
    peer_group_keys: tuple[str, ...] = ("app", "role")
    peer_min_group: int = 5
    volume_surge_factor: float = 3.0
    volume_min_connections: int = 1000
    volume_min_bytes: int = 1024 * 2**20
    directory_min_connections: int = 500
    account_history: timedelta = timedelta(days=7)
    process_history: timedelta = timedelta(days=7)
    suspicious_tools: frozenset[str] = frozenset()
    directory_followup: timedelta = timedelta(minutes=30)


@dataclass(frozen=True)
class Activity:
    """One source's live growth over the last hour, and the most it had in any hour of the 7 days before."""
    connections: int
    bytes: int | None                 # None: none of the growth carried byte counts
    previous_connections: int
    previous_bytes: int


@dataclass(frozen=True)
class AnomalyData:
    """What the service looked up for the anomaly detectors, by the keys this run's connections name."""
    # A: (source group, port, proto) -> destination signatures the group's hosts used before the window
    peer_seen: Mapping[tuple[str, int, int], frozenset[str]] = field(default_factory=dict)
    group_sizes: Mapping[str, int] = field(default_factory=dict)       # group -> managed hosts in it
    # B, E③: (source, 'all' | 'directory') -> activity
    activity: Mapping[tuple[str, str], Activity] = field(default_factory=dict)
    activity_days: float = 0.0                                          # how far back the hourly activity reaches
    live: bool = True                                                   # False in the late pass
    # C: (account, source) -> first seen; account -> its earliest first seen and its sources before the window
    account_first: Mapping[tuple[str, str], datetime] = field(default_factory=dict)
    account_since: Mapping[str, datetime] = field(default_factory=dict)
    account_sources: Mapping[str, int] = field(default_factory=dict)
    # D: (source, process) -> first seen; source -> its earliest process first seen
    process_first: Mapping[tuple[str, str], datetime] = field(default_factory=dict)
    process_since: Mapping[str, datetime] = field(default_factory=dict)
    # E: directory servers (inferred ∪ declared keys), declared addresses, and what the status says about them
    directory_servers: frozenset[str] = frozenset()
    directory_ips: frozenset[str] = frozenset()
    directory_inferred: int = 0
    directory_declared_missing: int = 0
    directory_clients_before: frozenset[str] = frozenset()
    # E④: (subject, detector, first seen, last seen) of directory detections stored by earlier runs
    recent_directory: Sequence[tuple[str, str, datetime, datetime]] = ()


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
    # src -> the most distinct blocked targets it had in any blocked_window of the 7 days before
    blocked_history: Mapping[str, int] = field(default_factory=dict)
    traffic_obs: Sequence[Obs] = ()   # every port, not blocked, last seen in the window (spec §6.5.8)
    anomaly: AnomalyData = field(default_factory=AnomalyData)


def evaluable(o: Obs, inp: DetectorInput) -> bool:
    lo, hi = inp.window
    return o.origin == "ingest" and lo < o.last <= hi


def not_blocked(o: Obs) -> bool:
    return not o.decision.startswith("blocked")


def of_class(inp: DetectorInput, classes: Collection[PortClass]) -> list[Obs]:
    """The management-port observations on ports of these classes (spec §6.5.8: each detector reads its own)."""
    ports = inp.config.admin_ports
    return [o for o in inp.obs if ports.matches(o.port, o.proto, classes)]


def _dst_host(o: Obs, inp: DetectorInput) -> HostInfo:
    return inp.hosts(o.dst_key, o.dst_ip, o.dst_hostname, o.dst_labels)


def _endpoint(href: str | None, ip: str) -> EndpointFilter:
    return EndpointFilter(hrefs=(href,)) if href else EndpointFilter(ips=(ip,))


def evidence(inp: DetectorInput, start: datetime, end: datetime, *, src: Obs | None = None,
             dst: Obs | None = None, classes: Collection[PortClass] | None = None) -> FlowSegment:
    """The detail segment that shows a detection's connections in the workbench, on the ports of the classes its
    detector reads."""
    spec = FilterSpec(start=start, end=end if end > start else start + timedelta(seconds=1),
                      src=_endpoint(src.src_href, src.src_ip) if src else None,
                      dst=_endpoint(dst.dst_href, dst.dst_ip) if dst else None,
                      ports=inp.config.admin_ports.port_filters(classes))
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
    for o in of_class(inp, EXECUTION_OR_DATA):
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
        last = window_rows[-1].last
        first = _window_start(window_rows, last, cfg.fanout_window)
        out.append(Detection(
            detector=DetectorKind.FANOUT, fingerprint=f"fanout|{src}", subject_key=src, severity=severity,
            first_seen=first, last_seen=last, critical_asset=critical,
            summary={"targets": best[0], "sample_targets": _names(window_rows),
                     "ports": sorted({o.port for o in window_rows if o.port is not None}),
                     "window_minutes": int(cfg.fanout_window / timedelta(minutes=1))},
            segment=evidence(inp, last - cfg.fanout_window, last, src=window_rows[-1], classes=EXECUTION_OR_DATA),
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
    for o in of_class(inp, EXECUTION_OR_DATA):
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
            segment=evidence(inp, o.first, o.last, src=o, dst=o, classes=EXECUTION_OR_DATA),
            confidence=DetectionConfidence(baseline_days=round(inp.baseline_days, 1), incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.NEW_ADMIN_CONNECTION, DetectorState.OK)


def _src_host(o: Obs, inp: DetectorInput) -> HostInfo:
    return inp.hosts(o.src_key, o.src_ip, o.src_hostname, o.src_labels)


def _window_start(rows: Sequence[Obs], last: datetime, window: timedelta) -> datetime:
    """A windowed detection's first_seen: its rows' earliest start, but not before the window. A PCE record
    can span a day (first 10-25 00:01, last 10-26 00:21 on .106); its start would date the detection a day
    early and stretch the store dedup over a whole day of separate bursts."""
    return max(min(o.first for o in rows), last - window)


def _max_window(rows: list[Obs], window: timedelta, key: Callable[[Obs], str],
                ends: Callable[[Obs], bool]) -> tuple[int, int, int] | None:
    """Over rows sorted by last: the window of at most `window` ending at a row `ends` accepts that holds
    the most distinct key values -> (count, first index, last index)."""
    counts: Counter[str] = Counter()
    best: tuple[int, int, int] | None = None
    j = 0
    for i, o in enumerate(rows):
        counts[key(o)] += 1
        while rows[j].last < o.last - window:
            counts[key(rows[j])] -= 1
            if not counts[key(rows[j])]:
                del counts[key(rows[j])]
            j += 1
        if ends(o) and (best is None or len(counts) > best[0]):
            best = (len(counts), j, i)
    return best


def detect_pivot_chain(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A → B, then B → C, both on management ports and not blocked, "connected in time": B → C last seen no
    earlier than A → B was first seen, and started no later than chain_window after A → B was last seen.
    Flow times come in ten-minute reporting buckets, so the two legs may share one: the summary says the
    legs connect in time, never that it is a proven chain."""
    cfg = inp.config
    legs = [o for o in of_class(inp, EXECUTION) if not_blocked(o)]
    from_host: dict[str, list[Obs]] = {}
    for o in legs:
        from_host.setdefault(o.src_key, []).append(o)
    chains: dict[tuple[str, str, str], tuple[Obs, Obs]] = {}
    for ab in legs:
        for bc in from_host.get(ab.dst_key, ()):
            if bc.dst_key == ab.src_key or not (evaluable(ab, inp) or evaluable(bc, inp)):
                continue
            if bc.last >= ab.first and bc.first <= ab.last + cfg.chain_window:
                chains.setdefault((ab.src_key, ab.dst_key, bc.dst_key), (ab, bc))
    per_pivot: Counter[str] = Counter(b for _, b, _ in chains)
    out, kept = [], Counter[str]()
    for (a, b, c), (ab, bc) in sorted(chains.items()):
        if kept[b] >= 20:  # a busy pivot: the first 20 chains are kept, the summary counts all
            continue
        kept[b] += 1
        critical = _dst_host(bc, inp).critical
        out.append(Detection(
            detector=DetectorKind.PIVOT_CHAIN, fingerprint=f"chain|{a}|{b}|{c}", subject_key=a,
            severity=Severity.HIGH if critical else Severity.MEDIUM, first_seen=min(ab.first, bc.first),
            last_seen=max(ab.last, bc.last), critical_asset=critical,
            summary={"via": ab.dst_hostname or ab.dst_ip, "target": bc.dst_hostname or bc.dst_ip,
                     "ports": [ab.port, bc.port], "chains_through_pivot": per_pivot[b]},
            segment=evidence(inp, min(ab.first, bc.first), max(ab.last, bc.last), src=ab, classes=EXECUTION),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.PIVOT_CHAIN, DetectorState.OK)


def blocked_counts(inp: DetectorInput) -> dict[str, int]:
    """Per source: the most distinct targets it was blocked from within blocked_window, at a window ending
    in this run."""
    by_src: dict[str, list[Obs]] = {}
    for o in inp.blocked_obs:
        by_src.setdefault(o.src_key, []).append(o)
    out = {}
    for src, rows in by_src.items():
        rows.sort(key=lambda o: o.last)
        best = _max_window(rows, inp.config.blocked_window, lambda o: o.dst_key, lambda o: evaluable(o, inp))
        if best is not None:
            out[src] = best[0]
    return out


def max_window_targets(rows: Sequence[Obs], window: timedelta) -> int:
    """The most distinct targets any window of this length holds (the 7-day history of a source)."""
    ordered = sorted(rows, key=lambda o: o.last)
    best = _max_window(ordered, window, lambda o: o.dst_key, lambda o: True)
    return best[0] if best else 0


def window_targets_by_hour(rows: Sequence[Obs], window: timedelta) -> dict[datetime, int]:
    """Per UTC hour: the most distinct targets a window of this length ending in that hour holds (the blocked
    history's hourly cache keeps these, so the 7 days a run needs can be cut at any hour)."""
    ordered = sorted(rows, key=lambda o: o.last)
    counts: Counter[str] = Counter()
    out: dict[datetime, int] = {}
    j = 0
    for o in ordered:
        counts[o.dst_key] += 1
        while ordered[j].last < o.last - window:
            counts[ordered[j].dst_key] -= 1
            if not counts[ordered[j].dst_key]:
                del counts[ordered[j].dst_key]
            j += 1
        hour = o.last.replace(minute=0, second=0, microsecond=0)
        out[hour] = max(out.get(hour, 0), len(counts))
    return out


def detect_blocked_surge(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A source blocked from at least blocked_targets hosts within blocked_window, and at least
    blocked_surge_factor times its most in any such window of the 7 days before (the threshold alone when
    it had none). Any port: a scan does not keep to management ports."""
    cfg = inp.config
    out = []
    for src, n in sorted(blocked_counts(inp).items()):
        previous = inp.blocked_history.get(src, 0)
        if n < cfg.blocked_targets or (previous and n < cfg.blocked_surge_factor * previous):
            continue
        rows = sorted((o for o in inp.blocked_obs if o.src_key == src), key=lambda o: o.last)
        out.append(Detection(
            detector=DetectorKind.BLOCKED_SURGE, fingerprint=f"blocked|{src}", subject_key=src, severity=Severity.MEDIUM,
            first_seen=_window_start(rows, rows[-1].last, cfg.blocked_window), last_seen=rows[-1].last,
            critical_asset=any(_dst_host(o, inp).critical for o in rows),
            summary={"targets": n, "previous_max": previous, "sample_targets": _names(rows),
                     "window_minutes": int(cfg.blocked_window / timedelta(minutes=1))},
            segment=FlowSegment(filter=FilterSpec(start=rows[-1].last - cfg.blocked_window, end=rows[-1].last,
                                                  src=_endpoint(rows[-1].src_href, rows[-1].src_ip)),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.BLOCKED_SURGE, DetectorState.OK)


def _per_tuple(inp: DetectorInput, keep: Callable[[Obs], bool],
               classes: Collection[PortClass]) -> dict[tuple[str, str, int, int], Obs]:
    out: dict[tuple[str, str, int, int], Obs] = {}
    for o in of_class(inp, classes):
        if evaluable(o, inp) and keep(o):
            out.setdefault((o.src_key, o.dst_key, o.port if o.port is not None else -1, o.proto), o)
    return out


def detect_non_admin_group(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A source outside every admin group (unmanaged sources included) using a management port."""
    if not inp.config.admin_groups_configured:
        reason = "detector_admin_groups_stale" if inp.config.admin_groups_stale else "detector_admin_groups_unset"
        return [], DetectorStatus(DetectorKind.NON_ADMIN_GROUP, DetectorState.DISABLED, reason)
    out = []
    for (src, dst, port, proto), o in sorted(_per_tuple(inp, lambda o: not_blocked(o)
                                                        and not _src_host(o, inp).admin_group, EXECUTION).items()):
        critical = _dst_host(o, inp).critical
        out.append(Detection(
            detector=DetectorKind.NON_ADMIN_GROUP, fingerprint=f"nag|{src}|{dst}|{port}|{proto}", subject_key=src,
            severity=Severity.HIGH if critical else Severity.MEDIUM, first_seen=o.first, last_seen=o.last,
            critical_asset=critical,
            summary={"target": o.dst_hostname or o.dst_ip, "port": port, "proto": proto, "decision": o.decision},
            segment=evidence(inp, o.first, o.last, src=o, dst=o, classes=EXECUTION),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.NON_ADMIN_GROUP, DetectorState.OK)


def detect_cross_env(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A management-port connection between two different environments that was not blocked (5.x L010;
    allowed is high, the rest medium — one level is left for a precursor to raise)."""
    cfg = inp.config
    if not cfg.environment_labels_present:
        return [], DetectorStatus(DetectorKind.CROSS_ENV, DetectorState.NO_DATA, "detector_no_env_labels",
                                  {"label_key": cfg.environment_label_key})
    key = cfg.environment_label_key
    out = []
    for (src, dst, port, proto), o in sorted(_per_tuple(inp, not_blocked, EXECUTION_OR_DATA).items()):
        se, de = _src_host(o, inp).labels.get(key), _dst_host(o, inp).labels.get(key)
        if not (se and de and se != de):
            continue
        out.append(Detection(
            detector=DetectorKind.CROSS_ENV, fingerprint=f"xenv|{src}|{dst}|{port}|{proto}", subject_key=src,
            severity=Severity.HIGH if o.decision == "allowed" else Severity.MEDIUM, first_seen=o.first,
            last_seen=o.last, critical_asset=_dst_host(o, inp).critical,
            summary={"target": o.dst_hostname or o.dst_ip, "src_env": se, "dst_env": de, "port": port,
                     "decision": o.decision},
            segment=evidence(inp, o.first, o.last, src=o, dst=o, classes=EXECUTION_OR_DATA),
            confidence=DetectionConfidence(incomplete_gaps=inp.gaps)))
    return out, DetectorStatus(DetectorKind.CROSS_ENV, DetectorState.OK)


def detect_account_fanout(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """One initiating account starting management-port connections to at least account_fanout_targets
    hosts within its window. Only as good as the user field's coverage, which every result states."""
    cfg = inp.config
    rows = [o for o in of_class(inp, EXECUTION) if not_blocked(o)]
    in_window = [o for o in rows if evaluable(o, inp)]
    covered = [o for o in in_window if o.initiator_user]
    if in_window and not covered:
        return [], DetectorStatus(DetectorKind.ACCOUNT_FANOUT, DetectorState.NO_DATA, "detector_no_user_data",
                                  {"covered": 0, "total": len(in_window)})
    by_user: dict[str, list[Obs]] = {}
    for o in rows:
        account = account_key(o.initiator_user)
        if account is None or (cfg.exclude_system_accounts and is_system_account(o.initiator_user)):
            continue
        by_user.setdefault(account, []).append(o)
    out = []
    for account, user_rows in sorted(by_user.items()):
        user_rows.sort(key=lambda o: o.last)
        best = _max_window(user_rows, cfg.account_fanout_window, lambda o: o.dst_key, lambda o: evaluable(o, inp))
        if best is None or best[0] < cfg.account_fanout_targets:
            continue
        window_rows = user_rows[best[1]:best[2] + 1]
        last = window_rows[-1].last
        out.append(Detection(
            detector=DetectorKind.ACCOUNT_FANOUT, fingerprint=f"acct|{account}", subject_key=account,
            severity=Severity.HIGH, first_seen=_window_start(window_rows, last, cfg.account_fanout_window), last_seen=last,
            critical_asset=any(_dst_host(o, inp).critical for o in window_rows),
            summary={"targets": best[0], "sample_targets": _names(window_rows),
                     "sources": sorted({o.src_hostname or o.src_ip for o in window_rows})[:SAMPLE],
                     "window_minutes": int(cfg.account_fanout_window / timedelta(minutes=1))},
            segment=FlowSegment(filter=FilterSpec(start=last - cfg.account_fanout_window, end=last,
                                                  initiator_user=window_rows[-1].initiator_user,
                                                  ports=cfg.admin_ports.port_filters(EXECUTION)),
                                view=SegmentView.DETAIL, limit=200),
            confidence=DetectionConfidence(field="initiator_user", covered=len(covered), total=len(in_window),
                                           incomplete_gaps=inp.gaps)))
    return out, _coverage_status(DetectorKind.ACCOUNT_FANOUT, ("detector_partial_users", "detector_partial_users_none_from"),
                                 {"covered": len(covered), "total": len(in_window)}, len(covered) < len(in_window),
                                 _kinds_without(in_window, lambda o: bool(o.initiator_user), inp))


def detect_unexpected_initiator(inp: DetectorInput) -> tuple[list[Detection], DetectorStatus]:
    """A management-port connection started by a process not on that port's expected list. Ports without
    a list are not evaluated; a connection without process data cannot be judged and is counted, never
    called unexpected."""
    cfg = inp.config
    found: dict[tuple[str, str, int, int], Obs] = {}
    judged = not_evaluable = 0
    listed: list[Obs] = []
    for o in of_class(inp, EXECUTION):
        if not evaluable(o, inp) or o.port is None:
            continue
        expected = cfg.expected.get((o.port, o.proto), cfg.expected.get((o.port, None)))
        if expected is None:
            continue
        listed.append(o)
        if not o.initiator_process:
            not_evaluable += 1
            continue
        judged += 1
        if o.initiator_process not in expected:
            found.setdefault((o.src_key, o.initiator_process, o.port, o.proto), o)
    if not judged and not_evaluable:
        return [], DetectorStatus(DetectorKind.UNEXPECTED_INITIATOR, DetectorState.NO_DATA, "detector_no_process_data",
                                  {"not_evaluable": not_evaluable})
    out = []
    for (src, process, port, proto), o in sorted(found.items()):
        critical = _dst_host(o, inp).critical
        out.append(Detection(
            detector=DetectorKind.UNEXPECTED_INITIATOR, fingerprint=f"proc|{src}|{process}|{port}|{proto}",
            subject_key=src, severity=Severity.HIGH if critical else Severity.MEDIUM, first_seen=o.first,
            last_seen=o.last, critical_asset=critical,
            summary={"process": process, "port": port, "proto": proto, "target": o.dst_hostname or o.dst_ip},
            segment=evidence(inp, o.first, o.last, src=o, classes=EXECUTION),
            confidence=DetectionConfidence(field="initiator_process", covered=judged, total=judged + not_evaluable,
                                           incomplete_gaps=inp.gaps)))
    if not not_evaluable:
        return out, DetectorStatus(DetectorKind.UNEXPECTED_INITIATOR, DetectorState.OK,
                                   params={"not_evaluable": 0})
    return out, _coverage_status(DetectorKind.UNEXPECTED_INITIATOR,
                                 ("detector_partial_process", "detector_partial_process_none_from"),
                                 {"not_evaluable": not_evaluable, "total": judged + not_evaluable}, True,
                                 _kinds_without(listed, lambda o: bool(o.initiator_process), inp))


def _kinds_without(rows: Sequence[Obs], has: Callable[[Obs], bool], inp: DetectorInput) -> str:
    """The kinds of managed source host (Windows, Linux) none of whose rows carry the field."""
    seen: set[str] = set()
    carrying: set[str] = set()
    for o in rows:
        os_id = _src_host(o, inp).os_id
        if not os_id:
            continue
        kind = "Windows" if os_id.lower().startswith("win") else "Linux"
        seen.add(kind)
        if has(o):
            carrying.add(kind)
    return ", ".join(sorted(seen - carrying))


def _coverage_status(kind: DetectorKind, keys: tuple[str, str], params: dict[str, Any], partial: bool,
                     kinds: str) -> DetectorStatus:
    """Running, saying how much of the data carries the field when not all of it does (anti-goal 8);
    keys = (partial, partial and none at all from some kinds of host)."""
    if not partial:
        return DetectorStatus(kind, DetectorState.OK, params=params)
    if kinds:
        return DetectorStatus(kind, DetectorState.OK, keys[1], params | {"kinds": kinds})
    return DetectorStatus(kind, DetectorState.OK, keys[0], params)


# Detections whose subject is an account, not a host: a host's precursor does not raise them.
ACCOUNT_DETECTORS = frozenset({DetectorKind.ACCOUNT_FANOUT, DetectorKind.ACCOUNT_NEW_SOURCE})


def apply_precursors(dets: Sequence[Detection], precursors: Sequence[Precursor], *,
                     window: timedelta) -> list[Detection]:
    """A host-led detection whose host showed a precursor (tampering, a suspended or offline VEN) within
    `window` before it or during it is raised one level and says why (spec §6.5.1 前兆加權)."""
    by_host: dict[str, list[Precursor]] = {}
    for p in precursors:
        by_host.setdefault(p.host_key, []).append(p)
    out = []
    for d in dets:
        found = [p for p in by_host.get(d.subject_key, ()) if d.first_seen - window <= p.at <= d.last_seen]
        if d.detector in ACCOUNT_DETECTORS or not found:
            out.append(d)
            continue
        listed = [{"kind": p.kind.value, "at": p.at.isoformat(), "signal": p.signal}
                  for p in sorted(found, key=lambda p: p.at)]
        out.append(replace(d, severity=raise_severity(d.severity), summary=dict(d.summary) | {"precursors": listed}))
    return out


from illumio_ops.domain import anomaly

DetectorFn = Callable[[DetectorInput], tuple[list[Detection], DetectorStatus]]
DETECTORS: dict[DetectorKind, DetectorFn] = {
    DetectorKind.FANOUT: detect_fanout,
    DetectorKind.NEW_ADMIN_CONNECTION: detect_new_admin,
    DetectorKind.PIVOT_CHAIN: detect_pivot_chain,
    DetectorKind.BLOCKED_SURGE: detect_blocked_surge,
    DetectorKind.NON_ADMIN_GROUP: detect_non_admin_group,
    DetectorKind.CROSS_ENV: detect_cross_env,
    DetectorKind.ACCOUNT_FANOUT: detect_account_fanout,
    DetectorKind.UNEXPECTED_INITIATOR: detect_unexpected_initiator,
    # Through a lambda: anomaly imports this module, so its functions may not exist yet when this line runs.
    DetectorKind.PEER_DEVIATION: lambda i: anomaly.detect_peer_deviation(i),
    DetectorKind.VOLUME_SURGE: lambda i: anomaly.detect_volume_surge(i),
    DetectorKind.ACCOUNT_NEW_SOURCE: lambda i: anomaly.detect_account_new_source(i),
    DetectorKind.SUSPICIOUS_TOOL: lambda i: anomaly.detect_suspicious_tool(i),
    DetectorKind.NEW_PROCESS: lambda i: anomaly.detect_new_process(i),
}


def dedup_windows(cfg: DetectorConfig) -> dict[str, timedelta]:
    """How long a repeat of a detector's fingerprint extends the same detection (store dedup)."""
    day = timedelta(hours=24)
    return {
        DetectorKind.FANOUT: cfg.fanout_window, DetectorKind.NEW_ADMIN_CONNECTION: timedelta(days=30),
        DetectorKind.PIVOT_CHAIN: day, DetectorKind.NON_ADMIN_GROUP: day, DetectorKind.CROSS_ENV: day,
        DetectorKind.UNEXPECTED_INITIATOR: day, DetectorKind.ACCOUNT_FANOUT: cfg.account_fanout_window,
        DetectorKind.BLOCKED_SURGE: cfg.blocked_window,
        DetectorKind.PEER_DEVIATION: timedelta(days=30), DetectorKind.VOLUME_SURGE: anomaly.SURGE_WINDOW,
        DetectorKind.ACCOUNT_NEW_SOURCE: timedelta(days=30), DetectorKind.SUSPICIOUS_TOOL: day,
        DetectorKind.NEW_PROCESS: timedelta(days=30),
    }


# The detectors that read management-port connections, listed (a detector added later is not one by default);
# the blocked-surge detector reads every port.
MANAGEMENT_DETECTORS: frozenset[DetectorKind] = frozenset({
    DetectorKind.FANOUT, DetectorKind.NEW_ADMIN_CONNECTION, DetectorKind.PIVOT_CHAIN, DetectorKind.NON_ADMIN_GROUP,
    DetectorKind.CROSS_ENV, DetectorKind.ACCOUNT_FANOUT, DetectorKind.UNEXPECTED_INITIATOR,
})


def run_detectors(inp: DetectorInput) -> tuple[list[Detection], list[DetectorStatus]]:
    """Every detector over the ingested rows only: backfilled history is baseline, never part of what an
    alert counts (spec §7). Without management ports the management detectors are off, not "any port"."""
    inp = replace(inp, obs=[o for o in inp.obs if o.origin == "ingest"],
                  blocked_obs=[o for o in inp.blocked_obs if o.origin == "ingest"],
                  traffic_obs=[o for o in inp.traffic_obs if o.origin == "ingest"])
    no_ports = not inp.config.admin_ports.entries
    detections: list[Detection] = []
    statuses: list[DetectorStatus] = []
    for kind in DetectorKind:
        if no_ports and kind in MANAGEMENT_DETECTORS:
            statuses.append(DetectorStatus(kind, DetectorState.DISABLED, "detector_no_admin_ports"))
            continue
        found, status = DETECTORS[kind](inp)
        detections += found
        statuses.append(status)
    return apply_precursors(detections, inp.precursors, window=inp.config.precursor_window), statuses
