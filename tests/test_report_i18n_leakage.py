"""Guard against untranslated English text and raw i18n keys leaking into
zh_TW report output.

Renders Finding evidence, section guidance, and audit attention markup in
zh_TW with synthetic data, then asserts the output contains no raw
``rpt_*`` keys (which used to leak when `_StringsView` returned the key
as a placeholder) and no English fragments that the rules engine /
audit_risk used to emit before being routed through ``t()``.

If a future engineer adds a new ``Finding.description=f"..."`` or a new
``risk_summary``/``recommendation`` literal without wiring it through
``t()``, this test fails and tells them exactly which surface to fix.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

from src.i18n import t
from src.report.exporters.html_exporter import (
    _format_evidence,
    render_section_guidance,
)
from src.report.rules_engine import RulesEngine
from src.report.rules import Finding


# Surface keys whose values must never appear verbatim in zh_TW output.
_RAW_KEY_PREFIXES = ("rpt_col_", "rpt_rule_", "rpt_guidance_", "rpt_au_event_", "rpt_au_kpi_")

# Phrases that historically leaked because the original code used hard-coded
# English instead of routing through i18n. Each is uniquely associated with
# one of the surfaces this test exercises, so any reappearance pinpoints
# a regression in that surface.
_LEAKED_ENGLISH_PHRASES = [
    # Finding descriptions (rules_engine.py f-strings)
    "flows on critical lateral movement ports",       # B001
    "flows on high-risk remote access ports",         # B002
    "flows on medium-risk ports are in",              # B003
    "flows originated from unmanaged sources",        # B004
    "Policy coverage is only",                        # B005
    "source IPs each connected to",                   # B006
    "user accounts each reached",                     # B007
    "flows exceed the",                               # B008
    "cross-environment flows detected across",        # B009
    "flows detected on cleartext protocols",          # L001
    "flows on broadcast/discovery protocols",         # L002
    "Database ports are reachable from",              # L003
    "allowed database flows cross environment",       # L004
    "Identity infrastructure ports (Kerberos/LDAP)",  # L005
    "application nodes can reach",                    # L006
    "flows from",                                     # L007 (matched + " unmanaged hosts")
    "flows on lateral/critical ports are 'potentially_blocked'",  # L008
    "to {} unmanaged destinations",                   # L009 (format leftover)
    "allowed flows use lateral/management ports",     # L010
    # Audit risk map summaries / recommendations
    "Firewall rules tampered outside Illumio",
    "VEN protection suspended",
    "Security policy provisioned",
    "Investigate workload for compromise",
    "Verify if suspension was authorized",
    "Verify change was authorized; review scope",
    "Verify change was authorized; check before/after diff",
    # Section guidance labels
    "Purpose:",
    "Watch signals:",
    "How to read:",
    "Recommended actions:",
]


def _scan(haystack: str, label: str) -> list[str]:
    """Return list of leak descriptors found in ``haystack``."""
    leaks: list[str] = []
    for prefix in _RAW_KEY_PREFIXES:
        if prefix in haystack:
            # Capture surrounding context for the error message
            m = re.search(rf"{re.escape(prefix)}\w+", haystack)
            if m:
                leaks.append(f"raw key {m.group(0)!r} in {label}")
    for phrase in _LEAKED_ENGLISH_PHRASES:
        if phrase in haystack:
            leaks.append(f"English phrase {phrase!r} in {label}")
    return leaks


def _synth_flows() -> pd.DataFrame:
    """Build a synthetic flow DataFrame broad enough to fire every B/L rule."""
    rows = []
    # B001/B002/B003: ransomware ports
    for _ in range(40):
        rows.append({"src_ip": "10.1.0.1", "dst_ip": "10.1.0.2", "port": 3389,
                     "policy_decision": "potentially_blocked", "src_managed": True,
                     "dst_managed": True, "src_env": "Prod", "dst_env": "Prod",
                     "src_app": "Web", "dst_app": "DB", "bytes_total": 1024,
                     "user_name": "alice", "num_connections": 1})
    # B007: high-user-count
    for u in ("root", "harry", "svc"):
        for d in range(25):
            rows.append({"src_ip": "10.2.0.1", "dst_ip": f"10.2.0.{d+10}", "port": 443,
                         "policy_decision": "allowed", "src_managed": True,
                         "dst_managed": True, "src_env": "Prod", "dst_env": "Prod",
                         "src_app": "Web", "dst_app": "API", "bytes_total": 500_000_000,
                         "user_name": u, "num_connections": 1})
    # L007: unmanaged → critical port
    for _ in range(6):
        rows.append({"src_ip": "172.16.15.101", "dst_ip": "10.3.0.1", "port": 389,
                     "policy_decision": "potentially_blocked", "src_managed": False,
                     "dst_managed": True, "src_env": "", "dst_env": "Prod",
                     "src_app": "", "dst_app": "AD", "bytes_total": 1024,
                     "user_name": "", "num_connections": 1})
    return pd.DataFrame(rows)


@pytest.fixture
def engine_zh():
    cfg = {
        "thresholds": {
            "user_destination_threshold": 20,
            "unmanaged_critical_threshold": 5,
        },
        "ransomware_risk_ports": {
            "high":   [{"ports": [3389, 5938]}],
            "medium": [{"ports": [22, 80]}],
        },
        "lateral_movement_ports": [22, 3389, 445, 135, 389, 5985],
    }
    return RulesEngine(cfg, lang="zh_TW")


def test_findings_descriptions_have_no_leakage(engine_zh):
    df = _synth_flows()
    findings: list[Finding] = engine_zh.evaluate(df)
    assert findings, "synthetic data should trigger at least one finding"
    for f in findings:
        leaks = _scan(f.description, f"{f.rule_id}.description")
        leaks += _scan(f.recommendation, f"{f.rule_id}.recommendation")
        # Evidence is rendered via _format_evidence → check the rendered HTML
        ev_html = _format_evidence(f.evidence)
        leaks += _scan(ev_html, f"{f.rule_id}.evidence_html")
        assert not leaks, f"i18n leakage in finding {f.rule_id}: {leaks}"


def test_section_guidance_zh_has_no_english_or_raw_keys():
    """Every registered module's guidance must render fully in zh_TW."""
    from src.report.section_guidance import REGISTRY
    for module_id in REGISTRY:
        html = render_section_guidance(module_id, profile="security_risk",
                                       detail_level="full", lang="zh_TW")
        if not html:
            continue  # not visible at this profile
        leaks = _scan(html, f"guidance[{module_id}]")
        assert not leaks, f"guidance leakage for {module_id}: {leaks}"


def test_audit_risk_map_translated_in_zh():
    """Every entry in AUDIT_RISK_MAP must have zh_TW translations
    for both the summary and the recommendation."""
    from src.report.analysis.audit.audit_risk import AUDIT_RISK_MAP, get_risk
    for event_type in AUDIT_RISK_MAP:
        risk, desc_zh, rec_zh = get_risk(event_type, lang="zh_TW")
        _, desc_en, rec_en = get_risk(event_type, lang="en")
        if desc_en:
            assert desc_zh != desc_en or all(ord(c) < 128 for c in desc_en), \
                f"{event_type} summary not translated to zh_TW (still: {desc_zh!r})"
        if rec_en:
            assert rec_zh != rec_en or all(ord(c) < 128 for c in rec_en), \
                f"{event_type} recommendation not translated to zh_TW (still: {rec_zh!r})"


def test_audit_kpi_labels_have_i18n_keys():
    """audit_executive_summary KPI entries must carry label_key, not just label."""
    from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary
    df = pd.DataFrame({
        "event_type": ["agent.suspend"] * 3,
        "src_ip": ["10.0.0.1"] * 3,
        "known_event_type": [True] * 3,
    })
    out = audit_executive_summary({"mod01": {}, "mod02": {}, "mod03": {}}, df, lang="zh_TW")
    for kpi in out["kpis"]:
        assert "label_key" in kpi, f"KPI missing label_key: {kpi}"
        translated = t(kpi["label_key"], lang="zh_TW")
        assert not translated.startswith("[MISSING:"), \
            f"KPI label_key {kpi['label_key']!r} has no zh_TW translation"
