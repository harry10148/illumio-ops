"""Ransomware protection as the PCE judges it, broken down per service (spec §6.5.6, §6.6 F5/F6)."""
from illumio_ops.domain.ransomware import (
    SEVERITY_WEIGHT,
    classify_traffic,
    host_breakdown,
    service_coverage,
)
from illumio_ops.domain.values import RansomwareTrafficClass as T


def svc(name, port, severity, state, status="inactive", proto=6, active="blocked_by_override_deny", category="admin"):
    return {"name": name, "port": port, "proto": proto, "severity": severity, "category": category,
            "protection_state": state, "port_status": status, "active_policy": active, "recommendation": ""}


def test_weights_40_30_20_10():
    assert SEVERITY_WEIGHT == {"critical": 40, "high": 30, "medium": 20, "low": 10}
    b = host_breakdown("/w/1", "h1", "selective", 50.0, "high", [
        svc("RDP", 3389, "critical", "protected_closed"), svc("SMB", 445, "high", "unprotected", "listening"),
        svc("FTP", 21, "low", "unprotected")], traffic={})
    by = {s.name: s for s in b.services}
    assert (by["RDP"].weight, by["RDP"].coverage, by["RDP"].contribution) == (40, 1.0, 40.0)
    assert (by["SMB"].weight, by["SMB"].coverage, by["SMB"].contribution) == (30, 0.0, 0.0)
    assert round(b.computed_percent, 2) == round(40 / 80 * 100, 2) and b.approximate is True


def test_all_protected_vs_pce_zero_is_contradiction():
    # lab: 13 fully_protected hosts, every service protected_closed, PCE percent 0.0 (spec §6.6 F5)
    b = host_breakdown("/w/1", "h1", "selective", 0.0, "fully_protected",
                       [svc("RDP", 3389, "critical", "protected_closed"), svc("SSH", 22, "medium", "protected_closed")],
                       traffic={})
    assert b.computed_percent == 100.0 and b.contradiction is True
    agree = host_breakdown("/w/2", "h2", "selective", 80.0, "fully_protected",
                           [svc("RDP", 3389, "critical", "protected_closed")], traffic={})
    assert agree.contradiction is False  # within the approximation's 25 points
    off = host_breakdown("/w/3", "h3", "selective", 74.0, "high", [svc("RDP", 3389, "critical", "protected_closed")],
                         traffic={})
    assert off.contradiction is True


def test_unknown_protection_state_excluded_from_percent():
    assert service_coverage("protected_open") == 1.0 and service_coverage("unprotected") == 0.0
    assert service_coverage("something_new") is None and service_coverage(None) is None
    b = host_breakdown("/w/1", "h1", "selective", None, None, [svc("RDP", 3389, "critical", "protected_closed"),
                                                                svc("X", 9, "high", "weird")], traffic={})
    assert b.computed_percent == 100.0 and b.contradiction is False
    none_known = host_breakdown("/w/1", "h1", "selective", 10.0, None, [svc("X", 9, "high", "weird")], traffic={})
    assert none_known.computed_percent is None and none_known.contradiction is False


def test_traffic_classes_five_cases():
    assert classify_traffic("unprotected", "listening", 3) is T.PRIORITY
    assert classify_traffic("unprotected", "listening", 0) is T.SAFE_TO_BLOCK
    assert classify_traffic("unprotected", "inactive", 2) is T.SUSPICIOUS
    assert classify_traffic("protected_closed", "listening", 9) is T.PROTECTED
    assert classify_traffic("unprotected", "inactive", 0) is T.UNKNOWN
    assert classify_traffic("unprotected", "listening", None) is T.UNKNOWN  # traffic not collected: no guess


def test_empty_recommendation_ok():
    b = host_breakdown("/w/1", "h1", None, None, None, [svc("RDP", 3389, "critical", "unprotected", "listening")],
                       traffic={(3389, 6): 2})
    assert b.services[0].traffic is T.PRIORITY and b.services[0].recent_sources == 2


def test_unenforced_hosts_count_nothing():
    """User 2026-10-29, Visualization Guide: only Selective or Full hosts count as protected; a Visibility Only or
    Idle host scores 0 whatever its services' states — the approximation follows the vendor, so it is no gap."""
    for mode in ("visibility_only", "idle"):
        b = host_breakdown("/w/1", "h1", mode, 0.0, "critical",
                           [svc("RDP", 3389, "critical", "protected_closed")], traffic={})
        assert b.computed_percent == 0.0 and b.contradiction is False, mode


def test_full_counts_every_service():
    """Full enforcement: every risky service counts as protected, rule or not."""
    b = host_breakdown("/w/1", "h1", "full", 100.0, "fully_protected",
                       [svc("SMB", 445, "high", "unprotected", "listening")], traffic={})
    assert b.computed_percent == 100.0 and b.contradiction is False


def test_full_host_services_not_in_action_lists():
    """Review #5: a Full host's service counts as protected, so it is not sent to "Fix first"."""
    b = host_breakdown("/w/1", "h1", "full", 100.0, "fully_protected",
                       [svc("SMB", 445, "high", "unprotected", "listening")], traffic={(445, 6): 3})
    assert b.services[0].traffic is T.PROTECTED


def test_unknown_mode_not_judged():
    """Review #6: a missing or new mode is not assumed enforced."""
    for mode in (None, "future_mode"):
        b = host_breakdown("/w/1", "h1", mode, 0.0, None, [svc("RDP", 3389, "critical", "protected_closed")],
                           traffic={})
        assert b.computed_percent is None and b.contradiction is False, mode
