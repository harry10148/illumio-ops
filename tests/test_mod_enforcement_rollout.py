"""mod_enforcement_rollout: rank apps by enforcement readiness vs risk."""
import pandas as pd

from src.report.analysis import mod_enforcement_rollout


def _flows():
    return pd.DataFrame([
        {"src": "a-web", "dst": "a-db", "port": 443, "policy_decision": "allowed",
         "src_app": "A", "dst_app": "A"},
        {"src": "a-web", "dst": "a-db", "port": 80,  "policy_decision": "allowed",
         "src_app": "A", "dst_app": "A"},
        {"src": "b-web", "dst": "b-db", "port": 3306, "policy_decision": "potentially_blocked",
         "src_app": "B", "dst_app": "B"},
        {"src": "b-web", "dst": "b-cache", "port": 6379, "policy_decision": "potentially_blocked",
         "src_app": "B", "dst_app": "B"},
        {"src": "b-web", "dst": "b-svc", "port": 22,   "policy_decision": "potentially_blocked",
         "src_app": "B", "dst_app": "B"},
    ])


def test_rollout_returns_ranked_apps():
    out = mod_enforcement_rollout.analyze(_flows())
    ranked = out["ranked"]
    assert len(ranked) >= 2
    apps_in_order = [r["app"] for r in ranked]
    assert apps_in_order.index("A") < apps_in_order.index("B")


def test_rollout_row_fields():
    out = mod_enforcement_rollout.analyze(_flows())
    row = out["ranked"][0]
    for fld in ("priority", "app", "why_now", "expected_default_deny_impact",
                "required_allow_rules", "risk_reduction"):
        assert fld in row, f"missing {fld}"


def test_rollout_top3_callout():
    out = mod_enforcement_rollout.analyze(_flows())
    top3 = out["top3_callout"]
    assert isinstance(top3, list) and len(top3) <= 3
