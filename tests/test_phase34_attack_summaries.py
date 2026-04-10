import datetime

import pandas as pd

from src.gui import _build_audit_dashboard_summary, _build_policy_usage_dashboard_summary
from src.report.analysis.audit.audit_mod00_executive import audit_executive_summary
from src.report.analysis.policy_usage.pu_mod00_executive import pu_executive_summary
from src.report.exporters.audit_html_exporter import AuditHtmlExporter
from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
from src.report.exporters.report_css import build_css


def _audit_df():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    return pd.DataFrame(
        [
            {
                "timestamp": now,
                "event_type": "agent.tampering",
                "severity": "error",
                "status": "failure",
                "actor": "agent:web-01",
                "created_by": "agent:web-01",
                "src_ip": "10.0.0.1",
                "target_name": "web-01",
                "resource_name": "web-01",
                "workloads_affected": 0,
                "known_event_type": True,
                "parser_note_count": 0,
            },
            {
                "timestamp": now,
                "event_type": "request.authentication_failed",
                "severity": "error",
                "status": "failure",
                "actor": "system",
                "created_by": "system",
                "src_ip": "203.0.113.10",
                "target_name": "admin@lab.local",
                "resource_name": "",
                "workloads_affected": 0,
                "known_event_type": True,
                "parser_note_count": 1,
            },
            {
                "timestamp": now,
                "event_type": "sec_policy.create",
                "severity": "warning",
                "status": "success",
                "actor": "admin@lab.local",
                "created_by": "admin@lab.local",
                "src_ip": "10.0.0.2",
                "target_name": "prod-policy",
                "resource_name": "prod-policy",
                "workloads_affected": 88,
                "known_event_type": True,
                "parser_note_count": 0,
            },
        ]
    )


def test_audit_executive_summary_contains_attack_sections():
    results = {
        "mod01": {"total_health_events": 3, "security_concern_count": 1, "connectivity_event_count": 1},
        "mod02": {"failed_logins": 1},
        "mod03": {"provision_count": 1, "rule_change_count": 2, "high_risk_count": 1, "total_workloads_affected": 88},
    }
    mod00 = audit_executive_summary(results, _audit_df())
    for key in ("boundary_breaches", "suspicious_pivot_behavior", "blast_radius", "blind_spots", "action_matrix"):
        assert key in mod00


def test_policy_usage_executive_summary_contains_attack_sections():
    results = {
        "mod01": {"total_rules": 20, "hit_count": 8, "unused_count": 12, "hit_rate_pct": 40.0},
        "mod03": {"unused_df": pd.DataFrame([{"Ruleset": "RS-Prod"} for _ in range(6)])},
        "meta": {
            "execution_stats": {
                "cached_rules": 2,
                "submitted_rules": 18,
                "pending_jobs": 2,
                "failed_jobs": 3,
                "top_hit_ports": [{"port_proto": "3389/tcp", "flow_count": 20}],
            }
        },
    }
    mod00 = pu_executive_summary(results, lookback_days=30)
    for key in ("boundary_breaches", "suspicious_pivot_behavior", "blast_radius", "blind_spots", "action_matrix"):
        assert key in mod00


def test_audit_html_renders_attack_summary_block():
    results = {
        "mod00": {
            "generated_at": "2026-04-10 00:00:00",
            "kpis": [{"label": "Total Events", "value": "3"}],
            "attention_items": [],
            "top_events_overall": pd.DataFrame(),
            "severity_distribution": pd.DataFrame(),
            "boundary_breaches": [{"severity": "HIGH", "finding": "Policy boundary changed.", "action": "Review scope."}],
            "suspicious_pivot_behavior": [],
            "blast_radius": [],
            "blind_spots": [],
            "action_matrix": [{"action_code": "LOCK_BOUNDARY_PORTS", "action": "Restrict boundaries."}],
        },
        "mod01": {"error": "No data"},
        "mod02": {"error": "No data"},
        "mod03": {"error": "No data"},
    }
    html = AuditHtmlExporter(results, df=pd.DataFrame(), date_range=("2026-04-01", "2026-04-10"))._build()
    assert "Attack Summary" in html
    assert "Boundary Breaches" in html


def test_policy_usage_html_renders_attack_summary_block():
    results = {
        "mod00": {
            "generated_at": "2026-04-10 00:00:00",
            "kpis": [{"label": "Total Rules", "value": "20"}],
            "attention_items": [],
            "execution_stats": {},
            "execution_notes": [],
            "boundary_breaches": [],
            "suspicious_pivot_behavior": [{"severity": "HIGH", "finding": "High-risk port hit concentration.", "action": "Review hit ports."}],
            "blast_radius": [],
            "blind_spots": [],
            "action_matrix": [{"action_code": "INVESTIGATE_HIGH_RISK_PORT_HITS", "action": "Investigate ports."}],
        },
        "mod01": {"total_rules": 20, "hit_count": 8, "unused_count": 12, "hit_rate_pct": 40.0, "summary_df": pd.DataFrame()},
        "mod02": {"hit_df": pd.DataFrame(), "top_ports_df": pd.DataFrame(), "record_count": 0},
        "mod03": {"unused_df": pd.DataFrame(), "record_count": 0, "caveat": ""},
    }
    html = PolicyUsageHtmlExporter(results, df=pd.DataFrame(), date_range=("2026-04-01", "2026-04-10"), lookback_days=30)._build()
    assert "Attack Summary" in html
    assert "Action Matrix" in html


def test_dashboard_summaries_include_attack_sections():
    class _AuditResult:
        module_results = {
            "mod00": {
                "generated_at": "2026-04-10 00:00:00",
                "kpis": [],
                "attention_items": [],
                "top_events_overall": pd.DataFrame(),
                "boundary_breaches": [],
                "suspicious_pivot_behavior": [],
                "blast_radius": [],
                "blind_spots": [],
                "action_matrix": [],
            },
            "mod01": {},
            "mod03": {},
        }
        generated_at = datetime.datetime(2026, 4, 10, 0, 0, 0)
        record_count = 0
        date_range = ("2026-04-01", "2026-04-10")

    class _PuResult:
        module_results = {
            "mod00": {
                "generated_at": "2026-04-10 00:00:00",
                "kpis": [],
                "execution_stats": {},
                "execution_notes": [],
                "boundary_breaches": [],
                "suspicious_pivot_behavior": [],
                "blast_radius": [],
                "blind_spots": [],
                "action_matrix": [],
            }
        }
        generated_at = datetime.datetime(2026, 4, 10, 0, 0, 0)
        record_count = 0
        date_range = ("2026-04-01", "2026-04-10")
        execution_stats = {}

    audit_summary = _build_audit_dashboard_summary(_AuditResult())
    pu_summary = _build_policy_usage_dashboard_summary(_PuResult())

    for key in ("boundary_breaches", "suspicious_pivot_behavior", "blast_radius", "blind_spots", "action_matrix"):
        assert key in audit_summary
        assert key in pu_summary


def test_all_report_hero_css_uses_light_header_style():
    expected_gradient = "linear-gradient(135deg, #FFFFFF, #F7F4EE 62%, #F2EEE6)"
    legacy_dark_gradient = "linear-gradient(135deg, rgba(26,44,50,.98), rgba(45,69,76,.96))"

    for exporter_type in ("traffic", "audit", "policy_usage", "ven"):
        css = build_css(exporter_type)
        assert expected_gradient in css
        assert legacy_dark_gradient not in css
