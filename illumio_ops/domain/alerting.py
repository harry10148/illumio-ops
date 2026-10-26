"""Alert evaluation: pure functions from rules and facts to triggers, and the cooldown / throttle gate.

The service layer reads the facts (new events, flow increments, detections, the collection's own health),
calls these, and stores what they return. A trigger carries a message key and parameters, never text, and
the analysis segment that reproduces its evidence (spec §6.5.2).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from illumio_ops.domain.alertrules import (
    BandwidthRule,
    EventRule,
    LateralRule,
    RuleBase,
    SystemRule,
    TrafficRule,
    VolumeRule,
    event_matches,
)
from illumio_ops.domain.focus import DETECTION_TITLE_KEYS
from illumio_ops.domain.segment import EventFilter, EventSegment, FlowSegment
from illumio_ops.domain.values import (
    SEVERITY_ORDER,
    AlertRuleType,
    DetectorKind,
    SegmentView,
    Severity,
    SystemCheck,
    ThresholdType,
    alert_severity_of_event,
)

Gap = tuple[datetime, datetime, str]
EVIDENCE_ROWS = 200
# An event this much older than the evaluation came in late (the daily re-read, a VEN that was offline).
LATE_AFTER = timedelta(hours=2)
# A source or job failing this many times in a row is reported (5.x's watchdog threshold).
FAILURES_TO_REPORT = 3

EVENT_MESSAGE_KEYS: Mapping[ThresholdType, str] = {
    ThresholdType.IMMEDIATE: "alert_event_immediate", ThresholdType.COUNT: "alert_event_count",
}
# An immediate event alert about no host says who made the change instead, or neither.
EVENT_SUBJECT_KEYS: Mapping[str, str] = {"actor": "alert_event_immediate_actor", "none": "alert_event_immediate_none"}
FLOW_MESSAGE_KEYS: Mapping[AlertRuleType, str] = {
    AlertRuleType.TRAFFIC: "alert_traffic", AlertRuleType.VOLUME: "alert_volume",
    AlertRuleType.BANDWIDTH: "alert_bandwidth",
}
# A lateral alert reads like the focus-list item of its detection: the same sentence in both places.
LATERAL_MESSAGE_KEYS: Mapping[DetectorKind, str] = DETECTION_TITLE_KEYS
SYSTEM_MESSAGE_KEYS: Mapping[SystemCheck, str] = {
    SystemCheck.PCE_HEALTH: "alert_system_pce_health", SystemCheck.COLLECTION_FAILING: "alert_system_collection_failing",
    SystemCheck.DATA_LOSS: "alert_system_data_loss", SystemCheck.JOB_FAILING: "alert_system_job_failing",
    SystemCheck.DISK_LOW: "alert_system_disk_low",
}


@dataclass(frozen=True)
class Confidence:
    """What the reader needs to weigh an alert (anti-goal 8): data delay, the period looked at, how many of
    the records carry the field it depends on, and any collection gap inside it."""
    latency_seconds: int | None = None
    window: tuple[datetime, datetime] | None = None
    field: str | None = None
    covered: int | None = None
    total: int | None = None
    incomplete_gaps: tuple[Gap, ...] = ()


@dataclass(frozen=True)
class Trigger:
    rule_id: str
    rule_type: AlertRuleType
    subject_key: str
    severity: Severity
    first_seen: datetime
    last_seen: datetime
    late: bool
    message_key: str
    params: Mapping[str, Any]
    facts: Mapping[str, Any]
    evidence: FlowSegment | EventSegment | None
    confidence: Confidence
    grouped_annotation: int | None = None


@dataclass(frozen=True)
class RuleState:
    last_fired_at: datetime | None
    recent: tuple[datetime, ...]  # when the throttle let one through, within its period


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: Literal["ok", "cooldown", "throttle"]
    next_allowed_at: datetime | None
    state: RuleState


def gate(rule: RuleBase, state: RuleState | None, now: datetime) -> GateResult:
    """Cooldown first, then a sliding-window throttle whose whole period is honoured (5.x cut it at 24 h)."""
    state = state or RuleState(None, ())
    period = timedelta(minutes=rule.throttle.period_minutes) if rule.throttle else None
    recent = tuple(t for t in state.recent if period is not None and t > now - period)
    kept = RuleState(state.last_fired_at, recent)
    if rule.cooldown_minutes and state.last_fired_at is not None:
        until = state.last_fired_at + timedelta(minutes=rule.cooldown_minutes)
        if now < until:
            return GateResult(False, "cooldown", until, kept)
    if rule.throttle is not None and period is not None and len(recent) >= rule.throttle.count:
        return GateResult(False, "throttle", recent[0] + period, kept)
    return GateResult(True, "ok", None, RuleState(now, (*recent, now) if rule.throttle else ()))


# ── facts ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EventFact:
    href: str
    event_type: str
    status: str | None
    severity: str | None
    timestamp: datetime
    host_key: str | None
    hostname: str | None
    raw: Mapping[str, Any]
    actor: str | None = None  # who made the change, for events about no host (a user, a service account)


@dataclass(frozen=True)
class IncrementTopFact:
    src: str
    dst: str
    port: int | None
    proto: int
    connections: int
    mbps: float | None


@dataclass(frozen=True)
class IncrementFacts:
    connections: int
    bytes: int | None
    bytes_rows: int
    rows: int
    new_rows: int
    max_mbps: float | None
    top: tuple[IncrementTopFact, ...] = ()
    gaps: tuple[Gap, ...] = ()
    latency_seconds: int | None = None


@dataclass(frozen=True)
class DetectionFact:
    id: int
    detector: DetectorKind
    fingerprint: str
    subject_key: str
    subject_name: str      # the host's name (the key itself when the store has none)
    severity: Severity
    critical_asset: bool
    late: bool
    first_seen: datetime
    last_seen: datetime
    summary: Mapping[str, Any]
    segment: FlowSegment
    confidence: Mapping[str, Any]
    is_new: bool
    severity_rose: bool


@dataclass(frozen=True)
class ProbeFact:
    checked_at: datetime
    failures: tuple[str, ...]  # the probes that did not pass


@dataclass(frozen=True)
class SourceFact:
    source: str
    consecutive_failures: int
    last_error: str | None
    since: datetime | None


@dataclass(frozen=True)
class GapFact:
    id: int
    source: str
    kind: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class JobFact:
    job_id: str
    consecutive_failures: int
    last_error: str | None


@dataclass(frozen=True)
class SystemFacts:
    probe: ProbeFact | None
    sources: tuple[SourceFact, ...] = ()
    new_gaps: tuple[GapFact, ...] = ()
    jobs: tuple[JobFact, ...] = ()
    disk_free_bytes: int | None = None
    disk_warn_bytes: int | None = None


# ── events ───────────────────────────────────────────────────────────────────

def _highest(severities: Sequence[Severity]) -> Severity:
    return max(severities, key=SEVERITY_ORDER.index)


def _event_trigger(rule: EventRule, matched: Sequence[EventFact], subject: str, *, now: datetime,
                   facts: Mapping[str, Any], window: tuple[datetime, datetime], host: str | None) -> Trigger:
    severity = rule.severity or _highest([alert_severity_of_event(e.severity) for e in matched])
    types = tuple(sorted({e.event_type for e in matched}))
    evidence = EventSegment(filter=EventFilter(start=window[0], end=window[1], event_types=types,
                                               host_hrefs=(host,) if host else ()),
                            view=SegmentView.DETAIL, limit=EVIDENCE_ROWS)
    first, last = min(e.timestamp for e in matched), max(e.timestamp for e in matched)
    names = sorted({e.hostname for e in matched if e.hostname and e.host_key})
    actors = sorted({e.actor for e in matched if e.actor})
    key = EVENT_MESSAGE_KEYS[rule.threshold]
    if rule.threshold is ThresholdType.IMMEDIATE and not names:
        key = EVENT_SUBJECT_KEYS["actor" if actors else "none"]
    return Trigger(
        rule_id=rule.id, rule_type=AlertRuleType.EVENT, subject_key=subject, severity=severity, first_seen=first,
        last_seen=last, late=all(e.timestamp < now - LATE_AFTER for e in matched),
        message_key=key, params={"event_types": list(types), "hosts": names[:10], "hosts_total": len(names),
                                 "actors": actors[:10]},
        facts=facts, evidence=evidence, confidence=Confidence(window=window))


def evaluate_event_rule(rule: EventRule, new: Sequence[EventFact], window_matches: int, *,
                        now: datetime) -> list[Trigger]:
    """immediate: this evaluation's new matches, per host (per event type when the event names no host), each
    group with at least threshold_count. count: window_matches (the matches within the rule's window, counted by
    the caller) reaches threshold_count and at least one of them is new (5.x semantics)."""
    matched = [e for e in new if event_matches(rule, e.raw)]
    if not matched:
        return []
    if rule.threshold is ThresholdType.COUNT:
        if window_matches < rule.threshold_count:
            return []
        window = (now - timedelta(minutes=rule.window_minutes), now)
        return [_event_trigger(rule, matched, rule.id, now=now, window=window, host=None,
                               facts={"matches": window_matches, "new_matches": len(matched),
                                      "threshold": rule.threshold_count, "window_minutes": rule.window_minutes})]
    groups: dict[str, list[EventFact]] = {}
    for e in matched:
        groups.setdefault(e.host_key or e.event_type, []).append(e)
    out = []
    for subject, events in groups.items():
        if len(events) < rule.threshold_count:
            continue
        first, last = min(e.timestamp for e in events), max(e.timestamp for e in events)
        host = events[0].host_key
        out.append(_event_trigger(rule, events, subject, now=now, host=host,
                                  window=(first, last + timedelta(seconds=1)),
                                  facts={"matches": len(events), "threshold": rule.threshold_count}))
    return out


# ── flow rules ───────────────────────────────────────────────────────────────

def _flow_trigger(rule: TrafficRule | BandwidthRule | VolumeRule, facts: IncrementFacts, *, window: tuple[datetime, datetime],
                  values: Mapping[str, Any], params: Mapping[str, Any] | None = None,
                  bytes_field: bool) -> Trigger:
    assert rule.severity is not None  # flow rules require one
    top = [{"src": t.src, "dst": t.dst, "port": t.port, "proto": t.proto, "connections": t.connections,
            "mbps": t.mbps} for t in facts.top]
    return Trigger(
        rule_id=rule.id, rule_type=AlertRuleType(rule.type), subject_key=rule.id, severity=rule.severity,
        first_seen=window[0], last_seen=window[1], late=False, message_key=FLOW_MESSAGE_KEYS[AlertRuleType(rule.type)],
        params={"window_minutes": rule.window_minutes, "top": top, **(params or {})},
        facts={**values, "rows": facts.rows},
        evidence=FlowSegment(filter=rule.condition.within(*window), view=SegmentView.DETAIL, limit=EVIDENCE_ROWS),
        confidence=Confidence(latency_seconds=facts.latency_seconds, window=window,
                              field="bytes" if bytes_field else None,
                              covered=facts.bytes_rows if bytes_field else None,
                              total=facts.rows if bytes_field else None, incomplete_gaps=facts.gaps))


def evaluate_traffic_rule(rule: TrafficRule, facts: IncrementFacts, *, now: datetime,
                          window: tuple[datetime, datetime]) -> Trigger | None:
    """Connections that grew within the window (spec §6.6 F12: the PCE's counts are daily totals)."""
    if facts.new_rows == 0 or facts.connections < rule.threshold_connections:
        return None
    return _flow_trigger(rule, facts, window=window, bytes_field=False,
                         values={"connections": facts.connections, "threshold": rule.threshold_connections})


def evaluate_volume_rule(rule: VolumeRule, facts: IncrementFacts, *, now: datetime,
                         window: tuple[datetime, datetime]) -> Trigger | None:
    """No byte data is not "below the threshold": the caller records the rule as no_data."""
    if facts.new_rows == 0 or facts.bytes is None or facts.bytes_rows == 0:
        return None
    mb = facts.bytes / 2**20
    if mb < rule.threshold_mb:
        return None
    return _flow_trigger(rule, facts, window=window, bytes_field=True,
                         values={"mb": round(mb, 3), "threshold": rule.threshold_mb})


def evaluate_bandwidth_rule(rule: BandwidthRule, facts: IncrementFacts, *, now: datetime,
                            window: tuple[datetime, datetime]) -> Trigger | None:
    """A rate is bytes over the flow time they span: a lower bound, as in 5.x calculate_mbps."""
    if facts.max_mbps is None or facts.bytes_rows == 0 or facts.max_mbps < rule.threshold_mbps:
        return None
    return _flow_trigger(rule, facts, window=window, bytes_field=True,
                         values={"mbps": round(facts.max_mbps, 3), "threshold": rule.threshold_mbps},
                         params={"lower_bound": True})


# ── lateral ──────────────────────────────────────────────────────────────────

def evaluate_lateral_rule(rule: LateralRule, changed: Sequence[DetectionFact]) -> list[Trigger]:
    """A detection alerts when it is new and again when its severity rises — not on every repeat."""
    floor = SEVERITY_ORDER.index(rule.min_severity)
    out = []
    for d in changed:
        if not (d.is_new or d.severity_rose) or d.detector not in rule.detectors:
            continue
        if SEVERITY_ORDER.index(d.severity) < floor or (rule.critical_assets_only and not d.critical_asset):
            continue
        c = d.confidence
        out.append(Trigger(
            rule_id=rule.id, rule_type=AlertRuleType.LATERAL, subject_key=d.fingerprint,
            severity=rule.severity or d.severity, first_seen=d.first_seen, last_seen=d.last_seen, late=d.late,
            message_key=LATERAL_MESSAGE_KEYS[d.detector],
            params={**dict(d.summary), "detector": d.detector.value, "risen": d.severity_rose and not d.is_new,
                    "host": d.subject_name, "account": d.subject_key, "minutes": d.summary.get("window_minutes")},
            facts={"detection_id": d.id, "critical_asset": d.critical_asset}, evidence=d.segment,
            confidence=Confidence(window=(d.first_seen, d.last_seen), field=c.get("field"), covered=c.get("covered"),
                                  total=c.get("total"),
                                  incomplete_gaps=tuple(tuple(g) for g in c.get("incomplete_gaps", ())))))
    return out


# ── system checks ────────────────────────────────────────────────────────────

def _system(rule: SystemRule, subject: str, now: datetime, params: Mapping[str, Any],
            window: tuple[datetime, datetime] | None = None) -> Trigger:
    assert rule.severity is not None
    return Trigger(rule_id=rule.id, rule_type=AlertRuleType.SYSTEM, subject_key=subject, severity=rule.severity,
                   first_seen=window[0] if window else now, last_seen=window[1] if window else now, late=False,
                   message_key=SYSTEM_MESSAGE_KEYS[rule.check], params=params, facts=dict(params), evidence=None,
                   confidence=Confidence(window=window))


def evaluate_system(rule: SystemRule, facts: SystemFacts, *, now: datetime) -> list[Trigger]:
    check = rule.check
    if check is SystemCheck.PCE_HEALTH:
        if facts.probe is None or not facts.probe.failures:
            return []
        return [_system(rule, check.value, now, {"failures": list(facts.probe.failures),
                                                 "checked_at": facts.probe.checked_at.isoformat()})]
    if check is SystemCheck.COLLECTION_FAILING:
        return [_system(rule, f"{check.value}:{s.source}", now,
                        {"source": s.source, "failures": s.consecutive_failures, "error": s.last_error,
                         "since": s.since.isoformat() if s.since else None})
                for s in facts.sources if s.consecutive_failures >= FAILURES_TO_REPORT]
    if check is SystemCheck.DATA_LOSS:
        return [_system(rule, f"{check.value}:{g.source}:{g.kind}", now,
                        {"source": g.source, "kind": g.kind, "start": g.start.isoformat(), "end": g.end.isoformat()},
                        window=(g.start, g.end)) for g in facts.new_gaps]
    if check is SystemCheck.JOB_FAILING:
        return [_system(rule, f"{check.value}:{j.job_id}", now,
                        {"job": j.job_id, "failures": j.consecutive_failures, "error": j.last_error})
                for j in facts.jobs if j.consecutive_failures >= FAILURES_TO_REPORT]
    if check is SystemCheck.DISK_LOW:
        if facts.disk_free_bytes is None or facts.disk_warn_bytes is None or facts.disk_free_bytes >= facts.disk_warn_bytes:
            return []
        return [_system(rule, check.value, now, {"free_bytes": facts.disk_free_bytes,
                                                 "warn_bytes": facts.disk_warn_bytes})]
    return []
