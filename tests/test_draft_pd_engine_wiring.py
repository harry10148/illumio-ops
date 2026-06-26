"""Wiring tests for the draft-policy-decision feature.

Covers the audit fix that made R01-R05 actually run:
  - RulesEngine.evaluate() now evaluates the DRAFT_PD_RULES (R01-R05) when the
    unified df carries a 'draft_policy_decision' column.
  - flatten_flow_record() carries the genuine PCE 'draft_policy_decision' field
    through to the unified df (only when present on the record).
  - mod_draft_summary / mod_draft_actions accept the unified src_ip/dst_ip schema
    without raising KeyError('src').
"""
from __future__ import annotations

import pandas as pd

from src.report.rules_engine import RulesEngine
from src.report.parsers.api_parser import flatten_flow_record, build_unified_df


def _engine(lang="en"):
    cfg = {
        "thresholds": {},
        "ransomware_risk_ports": {"critical": [{"ports": [3389, 445]}]},
        "lateral_movement_ports": [445, 3389],
    }
    return RulesEngine(cfg, lang=lang)


def _draft_record(decision="allowed", draft="blocked_by_override_deny"):
    rec = {
        "src": {"ip": "10.0.0.1", "workload": {"hostname": "web01",
                "labels": [{"key": "app", "value": "web"}, {"key": "env", "value": "Prod"}]}},
        "dst": {"ip": "10.9.9.9", "workload": {"hostname": "db01",
                "labels": [{"key": "app", "value": "db"}, {"key": "env", "value": "Prod"}]}},
        "service": {"port": 3306, "proto": 6, "process_name": "", "user_name": ""},
        "num_connections": 1, "policy_decision": decision,
        "first_detected": "2026-06-10T00:00:00Z", "last_detected": "2026-06-11T00:00:00Z",
    }
    if draft is not None:
        rec["draft_policy_decision"] = draft
    return rec


# ── Task 2: flatten carries the genuine draft field through ───────────────────

def test_draft_policy_decision_carried_by_flatten_when_present():
    row = flatten_flow_record(_draft_record(draft="blocked_by_boundary"))
    assert row["draft_policy_decision"] == "blocked_by_boundary"


def test_draft_policy_decision_absent_from_flatten_when_not_in_record():
    row = flatten_flow_record(_draft_record(draft=None))
    assert "draft_policy_decision" not in row


def test_draft_unified_df_has_column_only_for_draft_runs():
    with_draft = build_unified_df(
        [flatten_flow_record(_draft_record(draft="blocked_by_boundary"))], "api")
    without_draft = build_unified_df(
        [flatten_flow_record(_draft_record(draft=None))], "api")
    assert "draft_policy_decision" in with_draft.columns
    assert "draft_policy_decision" not in without_draft.columns


# ── Task 1: RulesEngine.evaluate() runs R01-R05 ───────────────────────────────

def test_rules_engine_evaluate_emits_r_rule_findings_with_draft_column():
    df = pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.9.9.9", "port": 3306,
        "policy_decision": "allowed", "draft_policy_decision": "blocked_by_override_deny",
        "src_managed": True, "dst_managed": True, "src_env": "Prod", "dst_env": "Prod",
        "src_app": "web", "dst_app": "db", "user_name": "", "bytes_total": 0,
        "num_connections": 1, "src_role": "", "dst_role": "",
    }])
    findings = _engine().evaluate(df)
    ids = {f.rule_id for f in findings}
    # allowed + blocked_by_override_deny → R01 (draft deny), R02 (override-deny
    # suffix) and R05 (reported allowed vs draft blocked_) all fire.
    assert "R01" in ids
    assert "R02" in ids
    assert "R05" in ids


def test_rules_engine_evaluate_no_r_findings_without_draft_column():
    df = pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.9.9.9", "port": 3306,
        "policy_decision": "allowed",
        "src_managed": True, "dst_managed": True, "src_env": "Prod", "dst_env": "Prod",
        "src_app": "web", "dst_app": "db", "user_name": "", "bytes_total": 0,
        "num_connections": 1, "src_role": "", "dst_role": "",
    }])
    findings = _engine().evaluate(df)
    assert not any(f.rule_id.startswith("R") for f in findings)


def test_rules_engine_draft_findings_are_localized_not_raw_keys():
    df = pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.9.9.9", "port": 3306,
        "policy_decision": "allowed", "draft_policy_decision": "blocked_by_boundary",
        "src_managed": True, "dst_managed": True, "src_env": "Prod", "dst_env": "Prod",
        "src_app": "web", "dst_app": "db", "user_name": "", "bytes_total": 0,
        "num_connections": 1, "src_role": "", "dst_role": "",
    }])
    r01 = [f for f in _engine(lang="zh_TW").evaluate(df) if f.rule_id == "R01"]
    assert r01, "R01 should fire"
    # i18n resolved (not the raw key) for the zh_TW report language
    assert r01[0].description and r01[0].description != "rule_r01_desc"
    assert r01[0].rule_name and r01[0].rule_name != "rule_r01_name"


def test_rules_engine_end_to_end_flatten_to_r_findings():
    """Full wired path: PCE record carrying draft field → flatten → unified df →
    evaluate() → R-rule findings."""
    df = build_unified_df(
        [flatten_flow_record(_draft_record(decision="allowed",
                                           draft="blocked_by_override_deny"))], "api")
    ids = {f.rule_id for f in _engine().evaluate(df)}
    assert {"R01", "R02", "R05"} <= ids


# ── Task 3: mod_draft modules accept the unified src_ip/dst_ip schema ──────────

def test_draft_summary_unified_schema_no_keyerror():
    from src.report.analysis.mod_draft_summary import analyze
    df = pd.DataFrame([
        {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 3306,
         "policy_decision": "allowed", "draft_policy_decision": "blocked_by_boundary"},
    ])
    out = analyze(df)  # must not raise KeyError('src')
    assert out["counts"]["blocked_by_boundary"] == 1
    pairs = out["top_pairs_by_subtype"]["blocked_by_boundary"]
    assert pairs[0]["src"] == "10.0.0.1"
    assert pairs[0]["dst"] == "10.0.0.2"


def test_draft_actions_unified_schema_no_keyerror():
    from src.report.analysis import mod_draft_actions
    df = pd.DataFrame([
        {"src_ip": "web-1", "dst_ip": "db-1", "port": 3306,
         "policy_decision": "allowed", "draft_policy_decision": "blocked_by_override_deny"},
    ])
    out = mod_draft_actions.analyze(df)  # must not raise KeyError('src')
    od = out["override_deny"]
    assert od["count"] == 1
    assert od["top_pairs"][0]["src"] == "web-1"
    assert od["top_pairs"][0]["dst"] == "db-1"
    # _remediation_for_override_deny reads p["src"]/p["dst"] — canonical keys
    assert od["remediation"][0]["src"] == "web-1"
    assert od["remediation"][0]["port"] == 3306
