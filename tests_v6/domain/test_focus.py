"""The focus list (spec §6.5.4 現在該關注什麼): derived items, ranked by severity, critical assets, novelty
and confidence."""
from datetime import UTC, datetime, timedelta

from illumio_ops.domain.focus import (
    FOCUS_KEYS,
    FocusAction,
    FocusItem,
    contradiction_item,
    coverage_item,
    detection_items,
    exposure_items,
    gap_item,
    health_items,
    mode_switch_item,
    rank,
    ransomware_items,
    score,
    setup_items,
    tamper_items,
    visibility_item,
)
from illumio_ops.domain.values import Confidence, FocusKind, Severity

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)


def item(severity=Severity.MEDIUM, critical=False, confidence=Confidence.HIGH, fp="x"):
    return FocusItem(kind=FocusKind.DETECTION, fingerprint=fp, severity=severity, critical_asset=critical,
                     confidence=confidence, title_key="focus_title_fanout", why_key="focus_why_detection", params={},
                     action=FocusAction(target="workbench"))


def test_score_formula():
    assert score(item(Severity.LOW), new_this_week=False) == 1
    assert score(item(Severity.CRITICAL, critical=True, confidence=Confidence.LOW), new_this_week=True) == \
        8 * 1.5 * 1.3 * 0.6
    assert score(item(Severity.HIGH, confidence=Confidence.MEDIUM), new_this_week=False) == 4 * 0.8


def test_new_this_week_and_persisting_weeks():
    old, fresh = item(Severity.HIGH, fp="old"), item(Severity.HIGH, fp="new")
    ranked = rank([old, fresh], {"old": NOW - timedelta(days=22), "new": NOW - timedelta(days=2)}, NOW)
    assert [r.item.fingerprint for r in ranked] == ["new", "old"]  # same severity: the new one first
    assert (ranked[0].new_this_week, ranked[0].weeks_persisting) == (True, 0)
    assert (ranked[1].new_this_week, ranked[1].weeks_persisting) == (False, 3)


def det(detector, fp, severity="medium", critical=False, summary=None, confidence=None, last=NOW):
    return {"detector": detector, "fingerprint": fp, "subject_key": "/w/a", "severity": severity,
            "critical_asset": critical, "last_seen": last.isoformat(), "summary": summary or {"targets": 12},
            "confidence": confidence or {}, "segment": {"view": "detail"}}


def test_detection_items_from_last_7_days():
    items = detection_items([det("fanout", "fanout|/w/a", "high", summary={"targets": 12, "window_minutes": 60}),
                             det("account_fanout", "acct|bob", confidence={"field": "initiator_user", "covered": 1,
                                                                           "total": 50})],
                            names={"/w/a": "host-a"}, now=NOW)
    fan, acct = items
    assert fan.kind is FocusKind.DETECTION and fan.severity is Severity.HIGH and fan.title_key == "focus_title_fanout"
    assert fan.params["host"] == "host-a" and fan.action.target == "workbench" and fan.action.segment is not None
    assert acct.confidence is Confidence.LOW  # 2% of connections carry a user
    assert detection_items([det("fanout", "f", last=NOW - timedelta(days=8))], names={}, now=NOW) == []


def test_asset_exposure_severity_bands():
    exposure = {"hops": 3, "assets": [{"key": "/w/a", "sources_now": 25}, {"key": "/w/b", "sources_now": 6},
                                      {"key": "/w/c", "sources_now": 1}, {"key": "/w/d", "sources_now": 0}],
                "hosts": [], "cross_env": []}
    items = [i for i in exposure_items(exposure, names={}, baseline_full=True) if i.kind is FocusKind.EXPOSURE_ASSET]
    assert [(i.params["asset"], i.severity) for i in items] == [("/w/a", Severity.HIGH), ("/w/b", Severity.MEDIUM),
                                                                ("/w/c", Severity.LOW)]
    assert all(i.critical_asset for i in items)
    pivots = {"hops": 3, "assets": [], "cross_env": [],
              "hosts": [{"key": f"/w/p{i}", "pivot_now": True, "reach_now": 10 - i} for i in range(7)]}
    assert len([i for i in exposure_items(pivots, names={}, baseline_full=True) if i.kind is FocusKind.PIVOT_HOST]) == 5
    xenv = {"hops": 3, "assets": [], "hosts": [], "cross_env": [{"state": "potentially_blocked"}, {"state": "allowed"}]}
    [x] = exposure_items(xenv, names={}, baseline_full=False)
    assert x.kind is FocusKind.CROSS_ENV and x.severity is Severity.HIGH and x.confidence is Confidence.MEDIUM


def test_tamper_regular_cycle_item_explains_firewall_conflict():
    hosts = [{"href": "/w/a", "hostname": "dev", "n_7d": 40, "unexplained_7d": 40, "pattern": "regular_cycle",
              "has_signal": False},
             {"href": "/w/b", "hostname": "db", "n_7d": 3, "unexplained_7d": 3, "pattern": "burst", "has_signal": True},
             {"href": "/w/c", "hostname": "x", "n_7d": 5, "unexplained_7d": 0, "pattern": "sporadic", "has_signal": False}]
    cycle, burst = tamper_items(hosts)
    assert cycle.why_key == "focus_why_tamper_cycle" and cycle.severity is Severity.MEDIUM
    assert burst.severity is Severity.CRITICAL  # a burst, and a signal-type event: raised once more
    assert cycle.action.target == "host" and cycle.action.host_key == "/w/a"


def test_ransomware_priority_items():
    items = ransomware_items({"priority": [{"host": "/w/a", "hostname": "a", "name": "RDP", "severity": "critical",
                                            "port": 3389}, {"host": "/w/b", "hostname": "b", "name": "FTP",
                                                           "severity": "low", "port": 21}]})
    assert [(i.params["service"], i.severity) for i in items] == [("RDP", Severity.CRITICAL), ("FTP", Severity.MEDIUM)]
    assert ransomware_items({"unsupported": True}) == []


def test_contradiction_item_does_not_reorder():
    [c] = contradiction_item(3)
    assert c.kind is FocusKind.VENDOR_CONTRADICTION and c.severity is Severity.LOW and c.params == {"count": 3}
    assert contradiction_item(0) == []


def test_mode_switch_blocker_item():
    [m] = mode_switch_item(hosts=4, connections=120, truncated=False)
    assert m.kind is FocusKind.MODE_SWITCH_BLOCKER and m.params == {"hosts": 4, "connections": 120, "truncated": False}
    assert mode_switch_item(hosts=0, connections=0, truncated=False) == []


def test_low_coverage_item():
    [c] = coverage_item(total=1000, process=12, user=150)
    assert c.kind is FocusKind.DATA_COVERAGE and c.params["percent"] == 1.2 and c.severity is Severity.LOW
    assert coverage_item(total=1000, process=300, user=400) == [] and coverage_item(total=0, process=0, user=0) == []


def test_visibility_item():
    [v] = visibility_item(["/w/a", "/w/b"])
    assert v.kind is FocusKind.VISIBILITY and v.severity is Severity.MEDIUM and v.params == {"count": 2}


def test_gap_item():
    [g] = gap_item(failed=1, truncated=2)
    assert g.kind is FocusKind.COLLECTION_GAP and g.severity is Severity.HIGH
    assert gap_item(failed=0, truncated=2)[0].severity is Severity.MEDIUM and gap_item(failed=0, truncated=0) == []


def test_system_health_item():
    items = health_items(failing_jobs=["collect_traffic"], probe_ok=False)
    assert {i.title_key for i in items} == {"focus_title_job_failing", "focus_title_pce_probe"}
    assert all(i.severity is Severity.HIGH and i.kind is FocusKind.SYSTEM_HEALTH for i in items)


def test_setup_required_when_unset():
    items = setup_items(critical_set=False, admin_set=False, stale=[], collected=True)
    assert {i.title_key for i in items} == {"focus_title_setup_critical", "focus_title_setup_admin"}
    assert all(i.kind is FocusKind.SETUP_REQUIRED and i.severity is Severity.LOW for i in items)
    assert all(i.action.target == "settings_lateral" for i in items)


def test_stale_selector_item():
    [s] = setup_items(critical_set=True, admin_set=True, stale=[("critical_assets", "app", "Gone")], collected=True)
    assert s.kind is FocusKind.STALE_SELECTOR and s.severity is Severity.MEDIUM
    assert s.params == {"setting": "critical_assets", "key": "app", "value": "Gone"}


def test_events_only_mode_item():
    [e] = setup_items(critical_set=True, admin_set=True, stale=[], collected=False)
    assert e.title_key == "focus_title_events_only" and e.action.target == "settings_collection"


def test_every_focus_key_is_listed():
    every = set(FOCUS_KEYS.values())
    built = (detection_items([det(k, k) for k in ("fanout", "new_admin_connection", "pivot_chain", "blocked_surge",
                                                  "non_admin_group", "cross_env", "account_fanout",
                                                  "unexpected_initiator")], names={}, now=NOW)
             + setup_items(critical_set=False, admin_set=False, stale=[("admin_groups", "a", "b")], collected=False)
             + health_items(failing_jobs=["x"], probe_ok=False) + gap_item(failed=1, truncated=0))
    assert {i.title_key for i in built} | {i.why_key for i in built} <= every
