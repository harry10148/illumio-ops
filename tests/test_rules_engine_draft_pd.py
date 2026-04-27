"""Tests for R01-R05 draft_policy_decision rules."""
import pytest
import pandas as pd


# ── helpers ──────────────────────────────────────────────────────────────────

def _df(**cols):
    """Build a one-row DataFrame."""
    return pd.DataFrame([cols])


def _has(findings, count=None):
    if count is not None:
        assert len(findings) == count, f"expected {count} finding(s), got {len(findings)}: {findings}"
    assert len(findings) > 0


def _none(findings):
    assert findings == [], f"expected no findings, got {findings}"


# ── R01: Draft Deny Detected ──────────────────────────────────────────────────

def test_r01_fires_blocked_by_boundary():
    from src.report.rules_engine import R01DraftDenyDetected
    df = _df(src="web", dst="db", port=3306,
             policy_decision="allowed", draft_policy_decision="blocked_by_boundary")
    _has(R01DraftDenyDetected().evaluate(df, {}))

def test_r01_fires_blocked_by_override_deny():
    from src.report.rules_engine import R01DraftDenyDetected
    df = _df(src="web", dst="db", port=443,
             policy_decision="allowed", draft_policy_decision="blocked_by_override_deny")
    _has(R01DraftDenyDetected().evaluate(df, {}))

def test_r01_silent_when_draft_matches_allowed():
    from src.report.rules_engine import R01DraftDenyDetected
    df = _df(src="web", dst="db", port=80,
             policy_decision="allowed", draft_policy_decision="allowed")
    _none(R01DraftDenyDetected().evaluate(df, {}))

def test_r01_silent_when_column_missing():
    from src.report.rules_engine import R01DraftDenyDetected
    df = _df(src="a", dst="b", port=80, policy_decision="allowed")
    _none(R01DraftDenyDetected().evaluate(df, {}))

def test_r01_needs_draft_pd():
    from src.report.rules_engine import R01DraftDenyDetected
    assert R01DraftDenyDetected().needs_draft_pd() is True

def test_r01_severity_high():
    from src.report.rules_engine import R01DraftDenyDetected
    assert R01DraftDenyDetected().severity == "HIGH"


# ── R02: Override Deny Detected ───────────────────────────────────────────────

def test_r02_fires_on_override_deny_suffix():
    from src.report.rules_engine import R02OverrideDenyDetected
    df = _df(src="a", dst="b", port=22,
             policy_decision="allowed", draft_policy_decision="blocked_by_override_deny")
    _has(R02OverrideDenyDetected().evaluate(df, {}))

def test_r02_fires_on_potentially_blocked_by_override_deny():
    from src.report.rules_engine import R02OverrideDenyDetected
    df = _df(src="a", dst="b", port=22,
             policy_decision="potentially_blocked",
             draft_policy_decision="potentially_blocked_by_override_deny")
    _has(R02OverrideDenyDetected().evaluate(df, {}))

def test_r02_silent_when_no_override_deny():
    from src.report.rules_engine import R02OverrideDenyDetected
    df = _df(src="a", dst="b", port=22,
             policy_decision="allowed", draft_policy_decision="blocked_by_boundary")
    _none(R02OverrideDenyDetected().evaluate(df, {}))

def test_r02_silent_when_column_missing():
    from src.report.rules_engine import R02OverrideDenyDetected
    df = _df(src="a", dst="b", port=80, policy_decision="allowed")
    _none(R02OverrideDenyDetected().evaluate(df, {}))

def test_r02_severity_high():
    from src.report.rules_engine import R02OverrideDenyDetected
    assert R02OverrideDenyDetected().severity == "HIGH"


# ── R03: Visibility Mode Boundary Breach ──────────────────────────────────────

def test_r03_fires_on_potentially_blocked_with_pb_boundary():
    from src.report.rules_engine import R03VisibilityBoundaryBreach
    df = _df(src="a", dst="b", port=8080,
             policy_decision="potentially_blocked",
             draft_policy_decision="potentially_blocked_by_boundary")
    _has(R03VisibilityBoundaryBreach().evaluate(df, {}))

def test_r03_silent_when_policy_decision_not_potentially_blocked():
    from src.report.rules_engine import R03VisibilityBoundaryBreach
    df = _df(src="a", dst="b", port=8080,
             policy_decision="allowed",
             draft_policy_decision="potentially_blocked_by_boundary")
    _none(R03VisibilityBoundaryBreach().evaluate(df, {}))

def test_r03_silent_when_column_missing():
    from src.report.rules_engine import R03VisibilityBoundaryBreach
    df = _df(src="a", dst="b", port=80, policy_decision="potentially_blocked")
    _none(R03VisibilityBoundaryBreach().evaluate(df, {}))

def test_r03_severity_medium():
    from src.report.rules_engine import R03VisibilityBoundaryBreach
    assert R03VisibilityBoundaryBreach().severity == "MEDIUM"


# ── R04: Allowed Across Boundary ──────────────────────────────────────────────

def test_r04_fires_on_allowed_across_boundary():
    from src.report.rules_engine import R04AllowedAcrossBoundary
    df = _df(src="a", dst="b", port=443,
             policy_decision="allowed",
             draft_policy_decision="allowed_across_boundary")
    _has(R04AllowedAcrossBoundary().evaluate(df, {}))

def test_r04_silent_on_plain_allowed():
    from src.report.rules_engine import R04AllowedAcrossBoundary
    df = _df(src="a", dst="b", port=443,
             policy_decision="allowed", draft_policy_decision="allowed")
    _none(R04AllowedAcrossBoundary().evaluate(df, {}))

def test_r04_silent_when_column_missing():
    from src.report.rules_engine import R04AllowedAcrossBoundary
    df = _df(src="a", dst="b", port=443, policy_decision="allowed")
    _none(R04AllowedAcrossBoundary().evaluate(df, {}))

def test_r04_severity_low():
    from src.report.rules_engine import R04AllowedAcrossBoundary
    assert R04AllowedAcrossBoundary().severity == "LOW"


# ── R05: Draft vs Reported Mismatch ──────────────────────────────────────────

def test_r05_fires_when_allowed_but_draft_blocked():
    from src.report.rules_engine import R05DraftReportedMismatch
    df = _df(src="a", dst="b", port=80,
             policy_decision="allowed", draft_policy_decision="blocked_by_boundary")
    _has(R05DraftReportedMismatch().evaluate(df, {}))

def test_r05_silent_when_draft_not_blocked():
    from src.report.rules_engine import R05DraftReportedMismatch
    df = _df(src="a", dst="b", port=80,
             policy_decision="allowed", draft_policy_decision="allowed")
    _none(R05DraftReportedMismatch().evaluate(df, {}))

def test_r05_silent_when_column_missing():
    from src.report.rules_engine import R05DraftReportedMismatch
    df = _df(src="a", dst="b", port=80, policy_decision="allowed")
    _none(R05DraftReportedMismatch().evaluate(df, {}))

def test_r05_severity_info():
    from src.report.rules_engine import R05DraftReportedMismatch
    # R05 is informational
    assert R05DraftReportedMismatch().severity in ("INFO", "INFORMATIONAL", "LOW")
