"""B001 contextual severity must be driven by cross-subnet-SCOPED allowed/PB
counts, not estate-wide counts.

Audit bug: a scenario where cross-subnet flows are all potentially_blocked
(test-mode) while same-subnet flows are allowed (legitimate admin) wrongly fired
the HIGH 'cross-subnet allowed' branch, because n_allowed counted the same-subnet
allows. Correct behaviour: cross-subnet-all-PB → MEDIUM.
"""
from __future__ import annotations

import pandas as pd

from src.report.rules_engine import RulesEngine


def _engine():
    cfg = {
        "thresholds": {},
        "ransomware_risk_ports": {"critical": [{"ports": [3389]}]},
        "lateral_movement_ports": [3389],
    }
    return RulesEngine(cfg, lang="en")


def _row(src_ip, dst_ip, decision):
    return {
        "src_ip": src_ip, "dst_ip": dst_ip, "port": 3389,
        "policy_decision": decision, "src_managed": True, "dst_managed": True,
        "src_env": "Prod", "dst_env": "Prod", "src_app": "web", "dst_app": "db",
        "user_name": "", "bytes_total": 0, "num_connections": 1,
        "src_role": "", "dst_role": "",
    }


def _b001(df):
    return [f for f in _engine().evaluate(df) if f.rule_id == "B001"]


def test_rules_engine_b001_cross_subnet_all_pb_is_medium():
    rows = []
    # same-subnet ALLOWED (legitimate admin) — must NOT escalate cross-subnet severity
    for i in range(3):
        rows.append(_row("10.0.0.1", f"10.0.0.{10 + i}", "allowed"))
    # cross-subnet POTENTIALLY_BLOCKED (test-mode) — the actual cross-subnet exposure
    for i in range(5):
        rows.append(_row("10.0.0.1", f"10.9.9.{10 + i}", "potentially_blocked"))
    b001 = _b001(pd.DataFrame(rows))
    assert b001, "B001 should fire"
    assert b001[0].severity == "MEDIUM", (
        f"cross-subnet-all-PB must be MEDIUM, got {b001[0].severity}")


def test_rules_engine_b001_cross_subnet_allowed_is_high():
    # Contrast: genuine cross-subnet ALLOWED flows → HIGH (the HIGH path still works)
    rows = [_row("10.0.0.1", f"10.9.9.{10 + i}", "allowed") for i in range(4)]
    b001 = _b001(pd.DataFrame(rows))
    assert b001, "B001 should fire"
    assert b001[0].severity == "HIGH", (
        f"cross-subnet allowed must be HIGH, got {b001[0].severity}")


def test_rules_engine_b001_same_subnet_all_pb_is_info():
    # All same-subnet, all potentially_blocked → INFO (unchanged behaviour)
    rows = [_row("10.0.0.1", f"10.0.0.{10 + i}", "potentially_blocked") for i in range(4)]
    b001 = _b001(pd.DataFrame(rows))
    assert b001, "B001 should fire"
    assert b001[0].severity == "INFO", (
        f"same-subnet-all-PB must be INFO, got {b001[0].severity}")
