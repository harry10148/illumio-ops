"""報表評分語意：Potentially Blocked 不是進度、被封鎖的流量不是曝險。"""
from __future__ import annotations

import pandas as pd

from src.report.analysis import mod03_uncovered_flows, mod12_executive_summary
from src.report.analysis.mod04_ransomware_exposure import ransomware_exposure
from src.report.analysis.mod15_lateral_movement import lateral_movement_risk
from src.report.lateral_ports import DEFAULT_LATERAL_PORTS, lateral_ports
from src.report.rules_engine import RulesEngine


def _flows(decision: str, n: int = 100, port: int = 443, dst_enforcement: str = "") -> pd.DataFrame:
    return pd.DataFrame([{
        "src_ip": f"10.0.0.{i % 50}", "dst_ip": f"10.0.1.{i % 50}",
        "src_app": "web", "dst_app": "db", "src_env": "prod", "dst_env": "prod",
        "src_managed": True, "dst_managed": True, "dst_enforcement": dst_enforcement,
        "port": port, "proto": "TCP", "num_connections": 1, "policy_decision": decision,
    } for i in range(n)])


def _score(df: pd.DataFrame) -> dict:
    results = {
        "mod01": {"total_flows": len(df), "src_managed_pct": 100},
        "mod03": mod03_uncovered_flows.uncovered_flows(df),
        "mod04": {}, "mod15": {},
    }
    return mod12_executive_summary._compute_maturity_score(results)


def test_potentially_blocked_estate_does_not_outscore_enforced_one():
    pb = _score(_flows("potentially_blocked", dst_enforcement="visibility_only"))
    blocked = _score(_flows("blocked", dst_enforcement="full"))
    assert pb["maturity_score"] < blocked["maturity_score"]
    assert pb["maturity_dimensions"]["enforcement_coverage"]["ratio"] == 0.0


def test_enforcement_dimension_unavailable_without_mode_data_is_rescaled():
    out = _score(_flows("allowed"))  # CSV 形狀：沒有 enforcement 模式
    dim = out["maturity_dimensions"]["enforcement_coverage"]
    assert dim["available"] is False and dim["score"] is None
    # 其餘 60 分滿分 → 換算為 100，而不是把缺的 40 分當 0
    assert out["maturity_score"] == 100.0


def test_workload_mode_distribution_drives_enforcement_dimension():
    results = {
        "mod01": {"total_flows": 10, "src_managed_pct": 100},
        "mod03": {"enforced_coverage_pct": 100.0, "dst_enforced_flow_pct": 0.0},
        "mod13": {"enforcement_mode_distribution": {"full": 1, "selective": 2, "visibility_only": 1}},
        "mod04": {}, "mod15": {},
    }
    dim = mod12_executive_summary._compute_maturity_score(results)["maturity_dimensions"]["enforcement_coverage"]
    assert dim["source"] == "workload_modes"
    assert dim["ratio"] == 0.5  # (1 + 0.5*2) / 4


def test_pb_key_finding_warns_it_will_break_on_enforcement():
    df = _flows("potentially_blocked")
    results = {"mod01": {"total_flows": len(df)}, "mod03": mod03_uncovered_flows.uncovered_flows(df),
               "mod04": {}, "mod08": {}, "mod11": {}, "mod15": {}, "findings": []}
    out = mod12_executive_summary.executive_summary(results)
    kf = out["key_findings"][0]
    assert kf["severity"] == "HIGH"
    assert "rules ready" not in kf["finding"]
    assert "blocked" in kf["finding"].lower()


def test_blocked_lateral_flows_are_not_lateral_exposure():
    df = pd.concat([_flows("blocked", 40, port=445), _flows("allowed", 60, port=443)], ignore_index=True)
    out = lateral_movement_risk(df, 20)
    assert out["total_lateral_flows"] == 0
    assert out["lateral_pct"] == 0.0
    assert out["blocked_lateral_flows"] == 40


def test_database_traffic_is_not_lateral_movement():
    out = lateral_movement_risk(_flows("allowed", 50, port=5432), 20)
    assert out["total_lateral_flows"] == 0


def test_rules_engine_and_mod15_share_lateral_ports():
    cfg = {"lateral_movement_ports": [22, 3389]}
    assert set(lateral_ports(cfg)) == {22, 3389}
    assert RulesEngine(cfg)._lateral_ports == {22, 3389}
    assert set(lateral_ports({})) == set(DEFAULT_LATERAL_PORTS)


def test_blocked_ransomware_ports_do_not_lower_risk_control():
    cfg = {"ransomware_risk_ports": {"critical": [{"ports": [445], "service": "SMB"}]}}
    df = pd.concat([_flows("blocked", 30, port=445), _flows("allowed", 70)], ignore_index=True)
    mod04 = ransomware_exposure(df, cfg, 20)
    assert mod04["risk_flows_total"] == 30 and mod04["risk_flows_unblocked"] == 0
    results = {"mod01": {"total_flows": 100, "src_managed_pct": 100},
               "mod03": mod03_uncovered_flows.uncovered_flows(df), "mod04": mod04, "mod15": {}}
    dims = mod12_executive_summary._compute_maturity_score(results)["maturity_dimensions"]
    assert dims["risk_port_control"]["ratio"] == 1.0
