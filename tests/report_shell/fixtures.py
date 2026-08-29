"""One minimal, self-contained document per HTML report type.

``BUILDERS[report_type]()`` returns the full HTML string that exporter produces
for a smallest-useful input. Tasks 3-5 use these both to capture pre-migration
baselines (``scripts/capture_report_baselines.py``) and to run the
old→new conservation check after each batch of exporters moves onto the v2
shell, so every entry must render a real document — never a stub, never a
skip.

Sample data is transcribed from each type's existing tests so the fixtures stay
recognisable to whoever maintains those tests; the source file is named on each
builder. Where a test builds its input through a generator rather than by
constructing the exporter directly, the minimal *exporter-level* construction
from ``tests/test_print_button_all_exporters.py`` is used instead and the
divergence is noted.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

__all__ = ["BUILDERS", "REPORT_TYPES"]

_LANG = "en"

# A minimal but real chart_spec. The baselines record ``chart_count`` as a
# conservation signal, so at least one fixture must actually render a chart —
# otherwise a migration that dropped every chart would still match a baseline
# of zero. ``tests/test_report_shell_conservation_unit.py`` asserts the totals
# across BUILDERS are non-zero so this cannot silently regress.
_CHART_SPEC = {
    "type": "pie",
    "title": "Policy Decision Breakdown",
    "title_key": "rpt_chart_policy_decision_breakdown",
    "data": {"labels": ["Allowed", "Blocked"], "values": [4, 1]},
}


# --------------------------------------------------------- traffic family --
def _traffic_results() -> dict:
    """Transcribed from tests/test_traffic_flows_html_exporter.py::_results."""
    df = pd.DataFrame([{"Port": 443, "Protocol": "TCP", "Flow Count": 10}])
    return {
        "findings": [],
        "mod01": {"total_flows": 10, "total_connections": 100,
                  "unique_src_ips": 2, "unique_dst_ips": 3,
                  "allowed_flows": 4, "blocked_flows": 1,
                  "potentially_blocked_flows": 5, "unknown_flows": 0,
                  "total_bytes": 0, "total_mb": 1.0,
                  "policy_coverage_pct": 40.0,
                  "src_managed_pct": 100.0, "dst_managed_pct": 50.0,
                  "date_range": "2026-04-27 ~ 2026-05-04",
                  "top_ports": df, "top_protocols": df},
        "mod02": {"summary": df, "chart_spec": dict(_CHART_SPEC)},
        "mod08": {"unmanaged_flow_count": 3, "unmanaged_pct": 30.0,
                  "unique_unmanaged_src": 1, "unique_unmanaged_dst": 1,
                  "top_unmanaged_src": df},
        "mod09": {"label_distribution": {"src_app": df, "dst_app": df,
                                         "src_env": df, "dst_env": df,
                                         "src_role": df, "dst_role": df},
                  "port_distribution": df, "proto_distribution": df},
        "mod11": {"bytes_data_available": True, "total_mb": 1.0,
                  "top_by_bytes": df, "top_bandwidth": df,
                  "byte_ratio_anomalies": df, "anomaly_threshold": 1.0},
        "mod12": {"generated_at": "2026-07-02 12:00:00", "kpis": [],
                  "findings_summary": {}, "total_findings": 0,
                  "key_findings": [], "findings": [],
                  "boundary_breaches": [], "suspicious_pivot_behavior": [],
                  "blast_radius": [], "blind_spots": [], "action_matrix": []},
    }


def _security_risk_results() -> dict:
    """Transcribed from tests/test_e2e_report_html_redesign.py::_make_traffic."""
    return {
        "mod01": {"total_flows": 100, "total_mb": 6062},
        "mod12": {
            "kpis": [{"label": "Total Data Volume", "value": "5.92 GB"}],
            "maturity_score": 52, "maturity_grade": "D",
            "maturity_dimensions": {}, "key_findings": [],
            "generated_at": "2026-05-15 09:00",
        },
        "findings": [],
    }


def _network_inventory_results() -> dict:
    """Based on tests/test_report_print_layout.py::_minimal_results, with the
    traffic module data layered on top.

    ``_minimal_results`` is all-empty dicts, so every section renders an
    empty-state panel and the document contains no real table — see
    ``_build_audit`` for why that makes a baseline worthless."""
    results = {k: {} for k in [
        "mod01", "mod02", "mod03", "mod04", "mod05", "mod06",
        "mod07", "mod08", "mod09", "mod11", "mod12",
        "mod13", "mod14", "mod15",
    ]}
    results.update(_traffic_results())
    return results


def _build_traffic() -> str:
    from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
    return TrafficFlowsHtmlExporter(_traffic_results(), data_source="api",
                                    lang=_LANG).build()


def _build_security_risk() -> str:
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
    return SecurityRiskHtmlExporter(_security_risk_results(), lang=_LANG).build()


def _build_network_inventory() -> str:
    from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter
    return NetworkInventoryHtmlExporter(_network_inventory_results(),
                                        pce_url="pce.test", org_name="TestOrg",
                                        date_range=("2026-01-01", "2026-05-01"),
                                        lang=_LANG).build()


# ------------------------------------------------------------------ audit --
def _build_audit() -> str:
    """Based on tests/test_print_button_all_exporters.py, extended so the
    document actually contains tables and a chart.

    That test passes ``{}``, which renders every table as an empty-state panel
    (``.report-table-panel--empty``, no ``.report-table``) and no chart at all —
    a baseline captured from it would record ``table_count: 0, chart_count: 0``
    and a migration that dropped every table and chart would still match it.
    """
    from src.report.exporters.audit_html_exporter import AuditHtmlExporter
    events = pd.DataFrame([
        {"event_type": "sec_policy.create", "severity": "info",
         "count": 3, "last_seen": "2026-07-23T09:14:23Z"},
        {"event_type": "user.login_failed", "severity": "warning",
         "count": 1, "last_seen": "2026-07-23T10:02:00Z"},
    ])
    results = {
        "mod00": {"generated_at": "2026-07-23 12:00:00", "attention_items": [],
                  "chart_spec": dict(_CHART_SPEC), "top_events_overall": events},
        "mod01": {"summary": events, "severity_breakdown": events,
                  "recent": events},
        "mod02": {"summary": events},
    }
    return AuditHtmlExporter(results, date_range=("2026-07-16", "2026-07-23"),
                             lang=_LANG)._build()


# ------------------------------------------------------------- ven status --
def _build_ven_status() -> str:
    """Exporter-level minimal construction, per
    tests/test_print_button_all_exporters.py. tests/test_ven_report_compact.py
    drives ``VenStatusGenerator`` rather than the exporter, so its fixture is a
    workload dict, not the ``{status: DataFrame}`` shape the exporter takes; the
    column names below are the generator's display columns."""
    from src.report.exporters.ven_html_exporter import VenHtmlExporter
    rows = pd.DataFrame([{
        "Hostname": "k8s-node01", "IP": "192.168.10.20, 10.0.0.5",
        "VEN Version": "21.5.35", "Status": "active",
        "Last Heartbeat": "0.2h", "policy_sync": "synced",
        "Paired At": "2024-07-03",
    }])
    return VenHtmlExporter({"online": rows, "sync_issues": rows,
                            "offline": rows}, lang=_LANG)._build()


# ----------------------------------------------------------- policy usage --
def _build_policy_usage() -> str:
    """Transcribed from tests/test_print_button_all_exporters.py.
    tests/test_policy_usage_report.py exercises the generator and the executive
    summary, not the exporter's own construction."""
    from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
    summary_df = pd.DataFrame([{"Category": "Hit", "Rules": 5, "Share %": 41.7},
                               {"Category": "Unused", "Rules": 7, "Share %": 58.3}])
    rules_df = pd.DataFrame([{"ruleset": "RS-A", "rule_id": "1",
                              "consumers": "c", "providers": "p",
                              "services": "s", "hit_count": 5,
                              "last_hit_at": "2026-06-28T09:14:23Z"}])
    results = {
        "mod00": {"generated_at": "2026-07-02 12:00:00", "kpis": []},
        "mod01": {"total_rules": 12, "hit_count": 5, "unused_count": 7,
                  "hit_rate_pct": 41.7, "summary_df": summary_df},
        "mod02": {"hit_df": rules_df},
        "mod03": {"unused_df": rules_df},
    }
    return PolicyUsageHtmlExporter(results, lang=_LANG)._build()


# ------------------------------------------------------------ policy diff --
def _build_policy_diff() -> str:
    """Transcribed from tests/test_policy_diff_html_exporter.py::_diff."""
    from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
    rs = pd.DataFrame([{
        "change_type": "modified", "ruleset_name": "RS-A", "ruleset_id": "1",
        "field": "enabled", "draft_value": "False", "active_value": "True",
        "last_actor": "bob", "last_changed": "2026-06-05T12:00:00Z",
        "last_event": "rule_set.update",
    }])
    rule = pd.DataFrame(columns=["change_type", "ruleset_name", "rule_id", "field",
                                 "draft_value", "active_value",
                                 "last_actor", "last_changed", "last_event"])
    results = {"ruleset_changes": rs, "rule_changes": rule,
               "summary": {"rulesets_added": 0, "rulesets_removed": 0,
                           "rulesets_modified": 1, "rules_added": 0,
                           "rules_removed": 0, "rules_modified": 0,
                           "total_changes": 1}}
    return PolicyDiffHtmlExporter(results, lang=_LANG)._render_html()


# ------------------------------------------------------------ app summary --
def _build_app_summary() -> str:
    """Transcribed from tests/test_print_button_all_exporters.py.
    tests/test_app_summary_report.py drives the facade (fetch → scope → export)
    with mocked API clients, so it has no exporter-level results dict."""
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    flows = pd.DataFrame([{"src_app": "web", "dst_app": "DB", "port": 3306,
                           "proto": "TCP", "policy_decision": "allowed",
                           "num_connections": 12,
                           "last_detected": "2026-01-02T08:30:00Z"}])
    # ``empty: True`` (the print-button test's fixture) short-circuits the whole
    # body to a single note and renders no table at all.
    results = {"app": "DB", "env": "Prod", "empty": False,
               "baseline": {"inbound": flows, "outbound": flows,
                            "inbound_count": 1, "outbound_count": 1},
               "mod03": {}, "policy_impact": {}, "enforcement": {}, "findings": []}
    return AppSummaryHtmlExporter(results, lang=_LANG)._render_html()


# --------------------------------------------------------- rule hit count --
def _build_rule_hit_count() -> str:
    """Transcribed from tests/test_rule_hit_count_html_exporter.py::_row/_result."""
    from src.report.rule_hit_count_generator import RuleHitCountResult
    from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter
    rows = [{"rule_href": "/r/1", "ruleset": "RS-A", "rule_no": 1, "rule_id": "1",
             "rule_type": "Allow", "description": "d", "consumers": "c",
             "providers": "p", "services": "s", "enabled": True,
             "hit_count": 5, "days_since_last_hit": "3",
             "last_hit_at": "2026-06-28T09:14:23Z",
             "last_updated_by": "admin@lab.local",
             "last_updated_at": "2026-05-01T00:00:00Z"}]
    df = pd.DataFrame(rows)
    hit_df = df[df["hit_count"] > 0]
    unused_df = df[df["hit_count"] == 0]
    result = RuleHitCountResult(
        record_count=len(rows),
        date_range=("2026-06-01", "2026-07-01"),
        source="native",
        module_results={
            "kpis": {"total_rules": len(rows), "hit_rules": len(hit_df),
                     "unused_rules": len(unused_df), "hit_rate_pct": 50.0,
                     "total_hits": int(df["hit_count"].sum())},
            "hit_df": hit_df, "unused_df": unused_df, "cleanup_df": unused_df,
            "enrich_failed": False,
        },
        dataframe=df,
    )
    return RuleHitCountHtmlExporter(result, lang=_LANG)._render_html()


# --------------------------------------------------------------- readiness --
def _build_readiness() -> str:
    """Transcribed from tests/test_readiness_html_exporter.py::_result."""
    from src.report.readiness_report import ReadinessResult
    from src.report.exporters.readiness_html_exporter import ReadinessHtmlExporter
    queue_df = pd.DataFrame([{
        "app_display": "appA (prod)", "app_env_key": "appa|prod",
        "readiness_score": 91.0, "grade": "A", "current_mode": "full×2",
        "blocking_factor": "Ringfence Maturity",
        "blocking_factor_key": "ringfence_maturity",
        "recommended_action": "act", "flow_count": 6, "pb_uncovered_count": 0,
    }])
    factor_table = pd.DataFrame([{"Factor": "Policy Coverage", "Weight": 35,
                                  "Score": 30.0, "Ratio %": 85.0}])
    recs = pd.DataFrame([{"Priority": "P2", "App (Env)": "appB (prod)",
                          "App Env Key": "appb|prod", "Issue": "Enforcement Gap",
                          "Action": "Move to enforcement",
                          "Action Code": "MOVE_TO_ENFORCEMENT",
                          "Severity": "HIGH"}])
    readiness = {"total_score": 78.5, "grade": "B",
                 "factor_table": factor_table, "recommendations": recs,
                 "enforcement_mode_distribution": {"full": 2}}
    result = ReadinessResult(
        record_count=12,
        module_results={"readiness": readiness, "queue_df": queue_df,
                        "kpis": [{"i18n_key": "rpt_readiness_kpi_score",
                                  "label": "Readiness Score", "value": 78.5}],
                        "_trend_deltas": []},
        date_range=("2026-07-01", "2026-07-08"))
    return ReadinessHtmlExporter(result, lang=_LANG)._render_html()


BUILDERS: dict[str, Callable[[], str]] = {
    "traffic": _build_traffic,
    "security_risk": _build_security_risk,
    "network_inventory": _build_network_inventory,
    "audit": _build_audit,
    "ven_status": _build_ven_status,
    "policy_usage": _build_policy_usage,
    "policy_diff": _build_policy_diff,
    "app_summary": _build_app_summary,
    "rule_hit_count": _build_rule_hit_count,
    "readiness": _build_readiness,
}

REPORT_TYPES = tuple(BUILDERS)
