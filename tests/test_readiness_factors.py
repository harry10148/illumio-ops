"""Readiness 評分因子名實相符。"""
from __future__ import annotations

import pandas as pd

from src.report.analysis.mod13_readiness import enforcement_readiness


def _flows(**over):
    base = dict(src_ip="10.0.0.1", dst_ip="10.0.0.2", src_app="web", dst_app="web", src_env="prod",
                dst_env="prod", src_managed=True, dst_managed=True, port=443, proto="TCP",
                num_connections=1, policy_decision="allowed")
    base.update(over)
    return base


def _row(out, key="web|prod"):
    df = out["app_env_scores"]
    return df[df["app_env_key"] == key].iloc[0]


def test_enforcement_factor_uses_workload_modes_not_managed_flag():
    df = pd.DataFrame([_flows(src_enforcement="visibility_only", dst_enforcement="visibility_only")] * 4)
    assert _row(enforcement_readiness(df))["enforcement_mode_ratio"] == 0.0


def test_enforcement_factor_unavailable_without_mode_data():
    out = enforcement_readiness(pd.DataFrame([_flows()] * 4))
    assert pd.isna(_row(out)["enforcement_mode_ratio"])
    assert "N/A" in out["factor_table"]["Score"].astype(str).tolist()


def test_no_breakage_factor_is_not_policy_coverage():
    df = pd.DataFrame([_flows(policy_decision="blocked")] * 3 + [_flows()])
    row = _row(enforcement_readiness(df))
    assert row["policy_coverage_ratio"] == 0.25
    assert row["staged_readiness_ratio"] == 1.0  # nothing would break: no PB


def test_remote_factor_does_not_apply_without_remote_flows():
    row = _row(enforcement_readiness(pd.DataFrame([_flows()] * 2)))
    assert pd.isna(row["remote_app_coverage_ratio"])


def test_workload_inventory_gives_per_app_modes():
    df = pd.DataFrame([_flows()] * 2)
    workloads = [{"enforcement_mode": "full", "labels": [{"key": "app", "value": "web"}, {"key": "env", "value": "prod"}]},
                 {"enforcement_mode": "idle", "labels": [{"key": "app", "value": "db"}, {"key": "env", "value": "prod"}]}]
    assert _row(enforcement_readiness(df, workloads=workloads))["enforcement_mode_ratio"] == 1.0
