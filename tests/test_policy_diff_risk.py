# tests/test_policy_diff_risk.py
"""Risk grading for policy diff rows."""
import pandas as pd

from src.report.analysis.policy_diff.risk import grade_changes


def _diff(ruleset_rows, rule_rows):
    cols = ["change_type", "ruleset_name", "field", "draft_value", "active_value"]
    return {
        "ruleset_changes": pd.DataFrame(ruleset_rows, columns=cols),
        "rule_changes": pd.DataFrame(rule_rows, columns=cols),
        "summary": {},
    }


def test_disabling_ruleset_is_high_risk():
    # DRAFT 將停用、ACTIVE 目前啟用 → 即將生效的狀態是停用 → HIGH
    d = _diff([["modified", "Quarantine", "enabled", "False", "True"]], [])
    out = grade_changes(d)
    assert out["ruleset_changes"].iloc[0]["risk"] == "HIGH"


def test_reenabling_is_medium_risk():
    d = _diff([["modified", "Quarantine", "enabled", "True", "False"]], [])
    out = grade_changes(d)
    assert out["ruleset_changes"].iloc[0]["risk"] == "MEDIUM"


def test_removed_rule_is_medium_risk():
    d = _diff([], [["removed", "test", "*", "", "x"]])
    out = grade_changes(d)
    assert out["rule_changes"].iloc[0]["risk"] == "MEDIUM"


def test_plain_modification_has_no_risk_flag():
    d = _diff([], [["modified", "test", "providers", "a", "b"]])
    out = grade_changes(d)
    assert out["rule_changes"].iloc[0]["risk"] == ""


def test_empty_frames_pass_through():
    d = {"ruleset_changes": pd.DataFrame(), "rule_changes": None, "summary": {}}
    out = grade_changes(d)  # 不得 raise
    assert out["rule_changes"] is None
