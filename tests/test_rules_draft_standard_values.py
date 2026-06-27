"""R01/R05 must fire on the PCE's standard draft decision values.

Live verification showed real PCE compute_draft returns the standard decisions
(blocked / potentially_blocked / allowed), NOT the Illumio boundary/override-deny
subtypes (blocked_by_boundary, ...) the rules were originally written against. So
R01 (HIGH) and R05 (INFO) — the general "reported=allowed but draft would block"
rules — must also match the standard block values. R02/R03/R04 stay boundary-specific.
"""
from __future__ import annotations

import pandas as pd

from src.report.rules.r01_draft_deny_detected import R01DraftDenyDetected
from src.report.rules.r05_draft_reported_mismatch import R05DraftReportedMismatch


def _df(draft: str, reported: str = "allowed") -> pd.DataFrame:
    return pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443,
        "policy_decision": reported, "draft_policy_decision": draft,
    }])


def test_r01_fires_on_standard_potentially_blocked_draft():
    out = R01DraftDenyDetected().evaluate(_df("potentially_blocked"), {})
    assert out and out[0].rule_id == "R01"


def test_r01_fires_on_standard_blocked_draft():
    out = R01DraftDenyDetected().evaluate(_df("blocked"), {})
    assert out and out[0].rule_id == "R01"


def test_r01_still_fires_on_boundary_subtype():
    out = R01DraftDenyDetected().evaluate(_df("blocked_by_override_deny"), {})
    assert out and out[0].rule_id == "R01"


def test_r01_does_not_fire_when_draft_allowed():
    assert R01DraftDenyDetected().evaluate(_df("allowed"), {}) == []


def test_r05_fires_on_standard_potentially_blocked_draft():
    out = R05DraftReportedMismatch().evaluate(_df("potentially_blocked"), {})
    assert out and out[0].rule_id == "R05"


def test_r05_still_fires_on_boundary_subtype():
    out = R05DraftReportedMismatch().evaluate(_df("blocked_by_boundary"), {})
    assert out and out[0].rule_id == "R05"


def test_r05_does_not_fire_when_draft_allowed():
    assert R05DraftReportedMismatch().evaluate(_df("allowed"), {}) == []
