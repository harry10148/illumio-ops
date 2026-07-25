"""規則評估失敗必須在 findings 中留下標記。

Audit bug: `_eval_builtin` / `_eval_draft_pd` 吞掉個別規則的例外，只留一行
log warning。報表上「規則沒跑成功」與「乾淨、沒有發現」完全無法區分，操作者
會把不完整的評估當成沒有暴露的證據。
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


def _df():
    return pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 3389,
        "policy_decision": "allowed", "src_managed": True, "dst_managed": True,
        "src_env": "Prod", "dst_env": "Prod", "src_app": "web", "dst_app": "db",
        "user_name": "", "bytes_total": 0, "num_connections": 1,
        "src_role": "", "dst_role": "",
    }])


def test_failed_builtin_rule_is_reported_as_finding(monkeypatch):
    def _b007_user_high_destinations(self, df):  # noqa: ANN001
        raise ValueError("synthetic dtype failure")

    monkeypatch.setattr(RulesEngine, "_b007_user_high_destinations",
                        _b007_user_high_destinations)
    engine = _engine()
    findings = engine.evaluate(_df())

    assert engine.rule_errors == ["_b007_user_high_destinations"]
    incomplete = [f for f in findings if f.rule_id == "ENG01"]
    assert incomplete, "失敗的規則必須在 findings 中留下標記"
    assert incomplete[0].evidence["failed_rules"] == ["_b007_user_high_destinations"]


def test_clean_run_has_no_incomplete_marker():
    engine = _engine()
    findings = engine.evaluate(_df())
    assert engine.rule_errors == []
    assert not [f for f in findings if f.rule_id == "ENG01"]


def test_rule_errors_reset_between_runs(monkeypatch):
    def _b007_user_high_destinations(self, df):  # noqa: ANN001
        raise ValueError("synthetic dtype failure")

    monkeypatch.setattr(RulesEngine, "_b007_user_high_destinations",
                        _b007_user_high_destinations)
    engine = _engine()
    engine.evaluate(_df())
    monkeypatch.undo()
    findings = engine.evaluate(_df())
    assert engine.rule_errors == []
    assert not [f for f in findings if f.rule_id == "ENG01"]
