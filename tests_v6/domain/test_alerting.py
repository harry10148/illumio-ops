"""Pure alert evaluation: thresholds, cooldown, throttle, and what each rule type fires on."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.alerting import (
    DetectionFact,
    EventFact,
    GapFact,
    IncrementFacts,
    JobFact,
    ProbeFact,
    RuleState,
    SourceFact,
    SystemFacts,
    evaluate_bandwidth_rule,
    evaluate_event_rule,
    evaluate_lateral_rule,
    evaluate_system,
    evaluate_traffic_rule,
    evaluate_volume_rule,
    gate,
)
from illumio_ops.domain.alertrules import (
    BandwidthRule,
    EventRule,
    LateralRule,
    SystemRule,
    Throttle,
    TrafficRule,
    VolumeRule,
)
from illumio_ops.domain.filter import FilterSpec, FlowCondition
from illumio_ops.domain.segment import EventSegment, FlowSegment
from illumio_ops.domain.values import (
    DetectorKind,
    PolicyDecision,
    SegmentView,
    Severity,
    SystemCheck,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
BASE = {"id": "b" * 32, "name": "r", "pack_key": None, "enabled": True, "notify": True, "severity": Severity.MEDIUM,
        "cooldown_minutes": 30, "throttle": None}
WINDOW = (NOW - timedelta(minutes=10), NOW)


def event_rule(**kw):
    d = {**BASE, "type": "event", "event_types": ("agent.tampering",), "status": "all", "event_severity": "all",
         "match_fields": {}, "threshold": "immediate", "threshold_count": 1, "window_minutes": 10} | kw
    return EventRule(**d)


def ev(i, *, host="/orgs/1/workloads/w1", minutes_ago=1, severity="warning", event_type="agent.tampering"):
    at = NOW - timedelta(minutes=minutes_ago)
    return EventFact(href=f"/orgs/1/events/{i}", event_type=event_type, status="success", severity=severity,
                     timestamp=at, host_key=host, hostname="h1" if host else None,
                     raw={"event_type": event_type, "status": "success", "severity": severity})


def inc(**kw):
    d = {"connections": 0, "bytes": None, "bytes_rows": 0, "rows": 0, "new_rows": 0, "max_mbps": None, "top": (),
         "gaps": (), "latency_seconds": 60} | kw
    return IncrementFacts(**d)


# ── gate ──

def test_cooldown_blocks_then_releases():
    r = event_rule(cooldown_minutes=30)
    first = gate(r, None, NOW)
    assert first.allowed and first.state.last_fired_at == NOW
    blocked = gate(r, first.state, NOW + timedelta(minutes=29))
    assert (blocked.allowed, blocked.reason, blocked.next_allowed_at) == (False, "cooldown", NOW + timedelta(minutes=30))
    assert gate(r, first.state, NOW + timedelta(minutes=30)).allowed


def test_zero_cooldown_never_blocks():
    r = event_rule(cooldown_minutes=0)
    s = gate(r, None, NOW).state
    assert gate(r, s, NOW).allowed


def test_throttle_period_longer_than_a_day_is_honoured():
    r = event_rule(cooldown_minutes=0, throttle=Throttle(count=2, period_minutes=3 * 1440))
    s = gate(r, None, NOW).state
    s = gate(r, s, NOW + timedelta(days=1)).state
    later = gate(r, s, NOW + timedelta(days=2))  # 5.x pruned at 24 h and would have let this through
    assert (later.allowed, later.reason) == (False, "throttle")
    assert gate(r, s, NOW + timedelta(days=3, seconds=1)).allowed


def test_throttle_next_allowed_at():
    r = event_rule(cooldown_minutes=0, throttle=Throttle(count=1, period_minutes=15))
    s = gate(r, None, NOW).state
    g = gate(r, s, NOW + timedelta(minutes=5))
    assert g.next_allowed_at == NOW + timedelta(minutes=15) and g.state.recent == (NOW,)


# ── events ──

def test_immediate_groups_by_host():
    r = event_rule(threshold_count=2)
    new = [ev(1), ev(2), ev(3, host="/orgs/1/workloads/w2"), ev(4, event_type="user.login")]
    [t] = evaluate_event_rule(r, new, 0, now=NOW)
    assert t.subject_key == "/orgs/1/workloads/w1" and t.facts["matches"] == 2
    assert isinstance(t.evidence, EventSegment) and t.evidence.filter.host_hrefs == ("/orgs/1/workloads/w1",)
    assert t.evidence.filter.event_types == ("agent.tampering",) and t.evidence.view is SegmentView.DETAIL


def test_immediate_without_host_groups_by_event_type():
    [t] = evaluate_event_rule(event_rule(), [ev(1, host=None)], 0, now=NOW)
    assert t.subject_key == "agent.tampering"


def test_count_needs_window_total_and_a_new_match():
    r = event_rule(threshold="count", threshold_count=5)
    [t] = evaluate_event_rule(r, [ev(1)], 5, now=NOW)
    assert t.subject_key == r.id and t.facts == {"matches": 5, "new_matches": 1, "threshold": 5, "window_minutes": 10}
    assert t.evidence.filter.start == NOW - timedelta(minutes=10) and t.evidence.filter.end == NOW
    assert evaluate_event_rule(r, [ev(1)], 4, now=NOW) == []


def test_count_without_new_match_does_not_fire():
    r = event_rule(threshold="count", threshold_count=5)
    assert evaluate_event_rule(r, [ev(1, event_type="user.login")], 9, now=NOW) == []


def test_severity_from_event_takes_highest():
    [t] = evaluate_event_rule(event_rule(severity=None), [ev(1, severity="info"), ev(2, severity="err")], 0, now=NOW)
    assert t.severity is Severity.HIGH
    [t] = evaluate_event_rule(event_rule(), [ev(1, severity="err")], 0, now=NOW)
    assert t.severity is Severity.MEDIUM  # the rule's own severity wins


def test_old_event_marked_late():
    [t] = evaluate_event_rule(event_rule(), [ev(1, minutes_ago=300)], 0, now=NOW)
    assert t.late
    [t] = evaluate_event_rule(event_rule(), [ev(1, minutes_ago=300), ev(2)], 0, now=NOW)
    assert not t.late


# ── flow rules ──

def traffic_rule(**kw):
    return TrafficRule(**({**BASE, "type": "traffic", "condition": FlowCondition(decisions=(PolicyDecision.BLOCKED,)),
                           "threshold_connections": 25, "window_minutes": 10} | kw))


def test_traffic_fires_on_window_growth_not_cumulative():
    [t] = [evaluate_traffic_rule(traffic_rule(), inc(connections=25, rows=3, new_rows=1), now=NOW, window=WINDOW)]
    assert t is not None and t.subject_key == traffic_rule().id and t.facts["connections"] == 25
    assert isinstance(t.evidence, FlowSegment) and t.evidence.filter == FilterSpec(
        start=WINDOW[0], end=WINDOW[1], decisions=(PolicyDecision.BLOCKED,))
    assert evaluate_traffic_rule(traffic_rule(), inc(connections=24, new_rows=1), now=NOW, window=WINDOW) is None


def test_traffic_needs_new_rows():
    assert evaluate_traffic_rule(traffic_rule(), inc(connections=99, new_rows=0), now=NOW, window=WINDOW) is None


def test_traffic_carries_gaps_in_confidence():
    gaps = ((NOW - timedelta(minutes=5), NOW, "ingest_failed"),)
    t = evaluate_traffic_rule(traffic_rule(), inc(connections=30, new_rows=2, gaps=gaps), now=NOW, window=WINDOW)
    assert t.confidence.incomplete_gaps == gaps and t.confidence.latency_seconds == 60


def test_volume_converts_mib():
    r = VolumeRule(**({**BASE, "type": "volume", "condition": FlowCondition(), "threshold_mb": 2.0,
                       "window_minutes": 60}))
    t = evaluate_volume_rule(r, inc(bytes=2 * 2**20, bytes_rows=1, rows=4, new_rows=1), now=NOW, window=WINDOW)
    assert t is not None and t.facts["mb"] == 2.0 and (t.confidence.covered, t.confidence.total) == (1, 4)
    assert evaluate_volume_rule(r, inc(bytes=2 * 2**20 - 1, bytes_rows=1, new_rows=1), now=NOW, window=WINDOW) is None


def test_bandwidth_reports_lower_bound_flag():
    r = BandwidthRule(**({**BASE, "type": "bandwidth", "condition": FlowCondition(), "threshold_mbps": 10.0,
                          "window_minutes": 60}))
    t = evaluate_bandwidth_rule(r, inc(max_mbps=12.5, bytes=1, bytes_rows=1, rows=1, new_rows=1), now=NOW, window=WINDOW)
    assert t.facts["mbps"] == 12.5 and t.params["lower_bound"] is True
    assert evaluate_bandwidth_rule(r, inc(max_mbps=9.9, bytes_rows=1, new_rows=1), now=NOW, window=WINDOW) is None


def test_no_byte_data_is_not_a_pass():
    r = VolumeRule(**({**BASE, "type": "volume", "condition": FlowCondition(), "threshold_mb": 0.001,
                       "window_minutes": 60}))
    assert evaluate_volume_rule(r, inc(bytes=None, bytes_rows=0, rows=50, new_rows=5), now=NOW, window=WINDOW) is None


# ── lateral ──

def det(**kw):
    seg = FlowSegment(filter=FilterSpec(start=NOW - timedelta(hours=1), end=NOW), view=SegmentView.DETAIL, limit=200)
    d = {"id": 1, "detector": DetectorKind.FANOUT, "fingerprint": "fanout|h1", "subject_key": "/orgs/1/workloads/h1",
         "subject_name": "h1", "severity": Severity.MEDIUM,
         "critical_asset": False, "late": False, "first_seen": NOW - timedelta(hours=1), "last_seen": NOW,
         "summary": {"targets": 12}, "segment": seg, "confidence": {}, "is_new": True, "severity_rose": False} | kw
    return DetectionFact(**d)


def lateral_rule(**kw):
    return LateralRule(**({**BASE, "severity": None, "type": "lateral", "detectors": (DetectorKind.FANOUT,),
                           "min_severity": Severity.MEDIUM, "critical_assets_only": False} | kw))


def test_lateral_only_new_or_risen():
    out = evaluate_lateral_rule(lateral_rule(), [det(), det(id=2, fingerprint="fanout|h2", is_new=False),
                                                 det(id=3, fingerprint="fanout|h3", is_new=False, severity_rose=True,
                                                     severity=Severity.HIGH)])
    assert [t.subject_key for t in out] == ["fanout|h1", "fanout|h3"]
    assert out[1].severity is Severity.HIGH  # severity None: as the detection
    assert out[0].message_key == "focus_title_fanout" and out[0].params["host"] == "h1" and out[0].params["targets"] == 12


def test_lateral_min_severity_and_critical_only():
    assert evaluate_lateral_rule(lateral_rule(min_severity=Severity.HIGH), [det()]) == []
    assert evaluate_lateral_rule(lateral_rule(critical_assets_only=True), [det()]) == []
    assert len(evaluate_lateral_rule(lateral_rule(critical_assets_only=True), [det(critical_asset=True)])) == 1
    assert evaluate_lateral_rule(lateral_rule(), [det(detector=DetectorKind.CROSS_ENV)]) == []
    [t] = evaluate_lateral_rule(lateral_rule(), [det(late=True)])
    assert t.late


# ── system ──

def system_rule(check):
    return SystemRule(**({**BASE, "type": "system", "check": check}))


def facts(**kw):
    d = {"probe": None, "sources": (), "new_gaps": (), "jobs": (), "disk_free_bytes": None, "disk_warn_bytes": None} | kw
    return SystemFacts(**d)


def test_collection_failing_at_three():
    f = facts(sources=(SourceFact("traffic", 3, "timeout", NOW), SourceFact("events", 2, "x", NOW)))
    [t] = evaluate_system(system_rule(SystemCheck.COLLECTION_FAILING), f, now=NOW)
    assert t.subject_key == "collection_failing:traffic" and t.facts["failures"] == 3 and t.evidence is None


def test_data_loss_per_new_gap():
    g = (GapFact(7, "traffic", "truncated", NOW - timedelta(hours=1), NOW), GapFact(8, "events", "failed", NOW, NOW))
    out = evaluate_system(system_rule(SystemCheck.DATA_LOSS), facts(new_gaps=g), now=NOW)
    assert [t.subject_key for t in out] == ["data_loss:traffic:truncated", "data_loss:events:failed"]


def test_job_failing_at_three():
    jobs = (JobFact("collect_traffic", 3, "boom"), JobFact("pce_probe", 1, None))
    [t] = evaluate_system(system_rule(SystemCheck.JOB_FAILING), facts(jobs=jobs), now=NOW)
    assert t.subject_key == "job_failing:collect_traffic"


def test_disk_low():
    assert evaluate_system(system_rule(SystemCheck.DISK_LOW), facts(disk_free_bytes=5, disk_warn_bytes=10), now=NOW)
    assert not evaluate_system(system_rule(SystemCheck.DISK_LOW), facts(disk_free_bytes=10, disk_warn_bytes=10), now=NOW)


def test_pce_health_from_probe():
    f = facts(probe=ProbeFact(NOW, ("health",)))
    [t] = evaluate_system(system_rule(SystemCheck.PCE_HEALTH), f, now=NOW)
    assert t.params["failures"] == ["health"]
    assert not evaluate_system(system_rule(SystemCheck.PCE_HEALTH), facts(probe=ProbeFact(NOW, ())), now=NOW)


def test_rule_state_is_hashable_value():
    assert RuleState(None, ()) == RuleState(None, ())
