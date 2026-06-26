"""Chart specs must localize to the lang PASSED to the module, not the
process-global get_language() singleton (wrong-language charts under the
scheduler / concurrent multi-PCE generation).

Parametrizing over two languages proves the value comes from the parameter: a
single process-global value cannot equal both 'en' and 'zh_TW', so if both
cases pass the lang must be threaded from the argument.

Also covers the mod03 NaN src_managed classification fix.
"""
from __future__ import annotations

import pandas as pd
import pytest


def _traffic_df() -> pd.DataFrame:
    return pd.DataFrame({
        "src_ip":          ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"],
        "dst_ip":          ["10.0.1.1", "10.0.1.2", "10.0.1.3", "10.0.1.4"],
        "src_hostname":    ["a", "b", "c", "d"],
        "dst_hostname":    ["e", "f", "g", "h"],
        "port":            [445, 3389, 22, 80],
        "proto":           ["TCP", "TCP", "TCP", "TCP"],
        "bytes_total":     [10_000, 5_000, 20_000, 3_000],
        "num_connections": [5, 3, 10, 2],
        "bandwidth_mbps":  [1.0, 0.5, 2.0, 0.3],
        "policy_decision": ["allowed", "blocked", "allowed", "potentially_blocked"],
        "src_managed":     [True, True, False, True],
        "dst_managed":     [True, False, True, True],
        "src_app":         ["web", "db", "admin", "web"],
        "dst_app":         ["db", "cache", "web", "api"],
        "src_env":         ["prod", "prod", "dev", "prod"],
        "dst_env":         ["prod", "prod", "dev", "prod"],
        "src_role":        ["fe", "be", "ops", "fe"],
        "dst_role":        ["be", "cache", "fe", "api"],
        "src_loc":         ["us", "us", "eu", "us"],
        "dst_loc":         ["us", "us", "eu", "us"],
        "user_name":       ["alice", "bob", "", "alice"],
        "process_name":    ["nginx", "pg", "", "nginx"],
    })


_RANSOMWARE_CONFIG = {
    "ransomware_risk_ports": {
        "critical": [{"ports": [445], "service": "SMB"}, {"ports": [3389], "service": "RDP"}],
        "high":     [{"ports": [5900], "service": "VNC"}],
        "medium":   [{"ports": [22], "service": "SSH"}, {"ports": [80], "service": "HTTP"}],
        "low":      [],
    }
}


def _exec_results() -> dict:
    return {
        "mod01": {"total_flows": 4, "allowed_flows": 2, "blocked_flows": 1,
                  "potentially_blocked_flows": 1, "policy_coverage_pct": 50.0,
                  "src_managed_pct": 75.0, "total_mb": 0.04, "total_connections": 20,
                  "unique_src_ips": 4, "unique_dst_ips": 4, "date_range": "x"},
        "mod03": {"enforced_coverage_pct": 50.0, "staged_coverage_pct": 25.0,
                  "true_gap_pct": 25.0, "n_allowed": 2, "n_potentially_blocked": 1,
                  "n_blocked": 1},
        "mod04": {"risk_flows_total": 3},
        "mod05": {"total_lateral_flows": 1},
        "mod08": {"unique_unmanaged_src": 1},
        "mod11": {"bytes_data_available": True, "total_mb": 0.04},
        "mod13": {"attack_posture_items": [],
                  "enforcement_mode_distribution": {"full": 2, "visibility_only": 1}},
        "mod14": {"attack_posture_items": []},
        "mod15": {"attack_posture_items": []},
        "findings": [],
    }


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_mod03_chart_spec_uses_passed_lang(lang):
    from src.report.analysis.mod03_uncovered_flows import uncovered_flows
    spec = uncovered_flows(_traffic_df(), lang=lang)["chart_spec"]
    assert spec["i18n"]["lang"] == lang


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_mod04_chart_spec_uses_passed_lang(lang):
    from src.report.analysis.mod04_ransomware_exposure import ransomware_exposure
    spec = ransomware_exposure(_traffic_df(), _RANSOMWARE_CONFIG, lang=lang)["chart_spec"]
    assert spec["i18n"]["lang"] == lang


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_mod12_chart_spec_uses_passed_lang(lang):
    from src.report.analysis.mod12_executive_summary import executive_summary
    spec = executive_summary(_exec_results(), lang=lang)["chart_spec"]
    assert spec["i18n"]["lang"] == lang


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_mod13_chart_spec_uses_passed_lang(lang):
    from src.report.analysis.mod13_readiness import enforcement_readiness
    spec = enforcement_readiness(_traffic_df(), lang=lang)["chart_spec"]
    assert spec["i18n"]["lang"] == lang


@pytest.mark.parametrize("lang", ["en", "zh_TW"])
def test_mod15_chart_spec_uses_passed_lang(lang):
    from src.report.analysis.mod15_lateral_movement import lateral_movement_risk
    spec = lateral_movement_risk(_traffic_df(), lang=lang)["chart_spec"]
    assert spec["i18n"]["lang"] == lang


# ── mod03 NaN src_managed must not be bucketed as a managed flow ──────────────

def test_mod03_nan_src_managed_not_counted_as_managed():
    from src.report.analysis.mod03_uncovered_flows import uncovered_flows
    df = pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 3306,
        "policy_decision": "potentially_blocked",
        "src_managed": float("nan"), "dst_managed": True,
        "src_app": "X", "dst_app": "Y", "proto": "TCP", "num_connections": 1,
    }])
    out = uncovered_flows(df, lang="en")
    cats = set(out["by_recommendation"]["Category"])
    # NaN/unknown source must be surfaced as unmanaged_source, never silently
    # classified into a managed bucket (intra_app / cross_app).
    assert "unmanaged_source" in cats
    assert "cross_app" not in cats
    assert "intra_app" not in cats
