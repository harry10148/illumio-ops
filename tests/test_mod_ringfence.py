"""mod_ringfence: per-app dependency profile and candidate allow rules."""
import pandas as pd

from src.report.analysis import mod_ringfence


def _flows():
    return pd.DataFrame([
        {"src": "x-web", "dst": "x-db", "port": 5432, "policy_decision": "allowed",
         "src_app": "X", "dst_app": "X"},
        {"src": "x-web", "dst": "shared-dns", "port": 53, "policy_decision": "allowed",
         "src_app": "X", "dst_app": "shared"},
        {"src": "x-web", "dst": "y-db", "port": 5432, "policy_decision": "potentially_blocked",
         "src_app": "X", "dst_app": "Y", "src_env": "prod", "dst_env": "dev"},
    ])


def test_per_app_profile():
    out = mod_ringfence.analyze(_flows(), app="X")
    assert "intra_app_flows" in out
    assert "cross_app_dependencies" in out
    assert "cross_env_exceptions" in out


def test_candidate_allow_rules():
    out = mod_ringfence.analyze(_flows(), app="X")
    candidates = out["candidate_allow_rules"]
    assert len(candidates) >= 1
    for c in candidates:
        assert "src_label" in c and "dst_label" in c and "port" in c


def test_returns_top_apps_when_no_app_specified():
    out = mod_ringfence.analyze(_flows())
    assert "top_apps" in out
