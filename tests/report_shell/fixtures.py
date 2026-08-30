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

HOW THE SAMPLE VALUES ARE CHOSEN — this is load-bearing, not cosmetic
=====================================================================
``conservation_diff``'s protection strength is set by this file, not by the
harness. It asks whether each old text node is findable *anywhere* in the new
document, so a value that is duplicated elsewhere, or shorter than
``MIN_LEAF_CHARS`` (4), is invisible to it. Measured on the first version of
these fixtures: deleting a column's cell values went unreported for **116 of
137 columns (85%)** — the guard was running and seeing almost nothing.

Two rules follow, and every value here obeys them:

1. **Every cell value is at least 4 characters.** ``443``, ``TCP``, ``5``,
   ``d``, ``act``, ``A`` do not exist as far as the guard is concerned. Numeric
   columns therefore use four- and five-digit values.
2. **No value repeats inside one document.** Reusing one DataFrame across
   several tables (the first version fed the same ``df`` to thirteen traffic
   tables and the same row to three VEN tables) makes each copy a hiding place
   for the others.

A third, weaker hazard is unavoidable and merely minimised: ``flat`` strips all
whitespace before matching, so adjacent cells concatenate and a short value can
be found inside that concatenation. Values here are kept long and dissimilar to
keep that unlikely.

Determinism matters too, because T3 captures a baseline from one call and
compares a later call against it. Never derive fixture values from a counter,
clock, or hash iteration order.

The output is NOT byte-stable, and does not need to be: matplotlib mints a
fresh random ``clip-path`` id on every SVG render, so ``ven_status`` differs by
about 165 bytes between two calls of the same builder. What the baselines
record — the leaf set and the table/chart counts — is stable, because ``svg``
subtrees are removed before the text is collected. That distinction is pinned
by ``test_builders_are_deterministic_in_everything_the_baselines_record``; do
not "fix" it by comparing whole documents.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

__all__ = ["BUILDERS", "REPORT_TYPES"]

_LANG = "en"

# A minimal but real chart_spec. The baselines record ``chart_count`` as a
# conservation signal, so a fixture that renders no chart would let a migration
# drop every chart and still match a baseline of zero.
# ``test_builders_render_enough_tables_and_charts_for_the_count_baselines``
# pins the exact SET of chart-bearing types (not a total, which one type's
# charts could prop up while another's vanished), so adding or removing a
# chart_spec here must be a deliberate edit to that test as well.
_CHART_SPEC = {
    "type": "pie",
    "title": "Policy Decision Breakdown",
    "title_key": "rpt_chart_policy_decision_breakdown",
    "data": {"labels": ["Allowed", "Blocked"], "values": [4, 1]},
}


def _flow_df(tag: str, base: int) -> pd.DataFrame:
    """Two flow rows unique to ``tag``/``base``, every cell >= 4 characters.

    ``tag`` must be unique per table within a document and ``base`` must be
    spaced far enough apart that no port or count is a substring of another.
    """
    return pd.DataFrame([
        {"Port": base + 11, "Protocol": f"tcp-{tag}-alfa",
         "Flow Count": base * 7 + 1234},
        {"Port": base + 23, "Protocol": f"udp-{tag}-bravo",
         "Flow Count": base * 9 + 5678},
    ])


# --------------------------------------------------------- traffic family --
def _traffic_results() -> dict:
    """Based on tests/test_traffic_flows_html_exporter.py::_results.

    That fixture feeds ONE ``df`` to every module slot, so the same three cells
    appear in thirteen rendered tables and the conservation check can never see
    any of them go missing. Each slot gets its own table here — see the module
    docstring.
    """
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
                  "top_ports": _flow_df("prts", 1100),
                  "top_protocols": _flow_df("prot", 1300)},
        "mod02": {"summary": _flow_df("summ", 1500),
                  "chart_spec": dict(_CHART_SPEC)},
        "mod08": {"unmanaged_flow_count": 3, "unmanaged_pct": 30.0,
                  "unique_unmanaged_src": 1, "unique_unmanaged_dst": 1,
                  "top_unmanaged_src": _flow_df("unmg", 1700)},
        "mod09": {"label_distribution": {
                      "src_app": _flow_df("sapp", 1900),
                      "dst_app": _flow_df("dapp", 2100),
                      "src_env": _flow_df("senv", 2300),
                      "dst_env": _flow_df("denv", 2500),
                      "src_role": _flow_df("srol", 2700),
                      "dst_role": _flow_df("drol", 2900)},
                  "port_distribution": _flow_df("pdis", 3100),
                  "proto_distribution": _flow_df("qdis", 3300)},
        "mod11": {"bytes_data_available": True, "total_mb": 1.0,
                  "top_by_bytes": _flow_df("byts", 3500),
                  "top_bandwidth": _flow_df("bwid", 3700),
                  "byte_ratio_anomalies": _flow_df("anom", 3900),
                  "anomaly_threshold": 1.0},
        "mod12": {"generated_at": "2026-07-02 12:00:00", "kpis": [],
                  "findings_summary": {}, "total_findings": 0,
                  "key_findings": [], "findings": [],
                  "boundary_breaches": [], "suspicious_pivot_behavior": [],
                  "blast_radius": [], "blind_spots": [], "action_matrix": []},
    }


def _security_risk_results() -> dict:
    """Transcribed from tests/test_e2e_report_html_redesign.py::_make_traffic.

    The KPI list deliberately exceeds ``_exec_summary.KPI_LIMIT`` (8). It used
    to hold exactly one, and EVERY fixture in this file was likewise under the
    cap — traffic's is an empty list, audit has none, policy usage's is empty —
    so the executive summary's elision branch was never executed by any test
    while the real producers go well past it (counted from their literal lists:
    10 for traffic, 16 plus conditionals for security risk / network inventory,
    10 plus up to 4 for audit). That is precisely how the silent truncation
    survived two rounds of migration review. One fixture now sits over the line
    so the branch is exercised by every parametrised guard here.
    """
    return {
        "mod01": {"total_flows": 100, "total_mb": 6062},
        "mod12": {
            # 11 > KPI_LIMIT. Labels and values obey this module's rules: at
            # least four characters, and no value repeated in the document.
            "kpis": [{"label": "Total Data Volume", "value": "5.92 GB"}] + [
                {"label": f"Exec KPI {name}", "value": f"{20000 + index * 137} {name}"}
                for index, name in enumerate(
                    ["alfa", "bravo", "charlie", "delta", "echo",
                     "foxtrot", "golf", "hotel", "india", "juliett"])
            ],
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

    def _events(tag: str, base: int, day: int) -> pd.DataFrame:
        # Each COLUMN gets its own token, not just each table: the exporter
        # splits event_type on ``_``/``.`` with <wbr/>, so ``...create.zulu``
        # becomes four separate leaves, and a bare ``zulu`` would still be
        # found in this row's severity cell after event_type was deleted.
        return pd.DataFrame([
            {"event_type": f"sec_policy.create.evt{tag}",
             "severity": f"informational-sev{tag}",
             "count": base + 1234, "last_seen": f"2026-07-{day:02d}T09:14:23Z"},
            {"event_type": f"user.login_failed.evt{tag}",
             "severity": f"warning-high-sev{tag}",
             "count": base + 5678, "last_seen": f"2026-07-{day:02d}T21:02:47Z"},
        ])

    results = {
        # Four execution notes, over _exec_summary.NOTE_LIMIT (2). The traffic
        # family cannot exercise that branch at all — its exporter passes only
        # ``{"kpis": …}`` into render_exec_summary_html — so audit is where the
        # note cap has to be covered. See _security_risk_results for the KPI
        # half of the same gap.
        "mod00": {"generated_at": "2026-07-23 12:00:00", "attention_items": [],
                  "chart_spec": dict(_CHART_SPEC),
                  "execution_notes": [f"execution note {name} for the audit run"
                                      for name in ("uniform", "tango", "sierra",
                                                   "romeo")],
                  "top_events_overall": _events("zulu", 10000, 11)},
        "mod01": {"summary": _events("yankee", 20000, 13),
                  "severity_breakdown": _events("xray", 30000, 15),
                  "recent": _events("whiskey", 40000, 17)},
        "mod02": {"summary": _events("victor", 50000, 19)},
    }
    # ``data_source`` was unset, so the data-source pill branch in
    # audit_html_exporter._build() had never been executed by a test — which is
    # how a nesting defect identical to the traffic exporter's went unseen there.
    return AuditHtmlExporter(results, date_range=("2026-07-16", "2026-07-23"),
                             data_source="api", lang=_LANG)._build()


# ------------------------------------------------------------- ven status --
def _build_ven_status() -> str:
    """Exporter-level minimal construction, per
    tests/test_print_button_all_exporters.py. tests/test_ven_report_compact.py
    drives ``VenStatusGenerator`` rather than the exporter, so its fixture is a
    workload dict, not the ``{status: DataFrame}`` shape the exporter takes; the
    column names below are the generator's display columns."""
    from src.report.exporters.ven_html_exporter import VenHtmlExporter

    def _vens(tag: str, octet: int, ver: str, hours: str) -> pd.DataFrame:
        return pd.DataFrame([{
            "Hostname": f"k8s-node-{tag}-01", "IP": f"192.168.{octet}.20",
            "VEN Version": ver, "Status": f"active-paired-{tag}",
            "Last Heartbeat": hours, "policy_sync": f"synced-{tag}",
            "Paired At": f"2024-0{octet % 9 + 1}-03",
        }])

    return VenHtmlExporter({
        "online": _vens("online", 11, "21.5.35-1042", "0.21 hours"),
        "sync_issues": _vens("syncissue", 22, "22.3.17-2053", "1.34 hours"),
        "offline": _vens("offline", 33, "23.1.09-3064", "9.87 hours"),
    }, lang=_LANG)._build()


# ----------------------------------------------------------- policy usage --
def _build_policy_usage() -> str:
    """Transcribed from tests/test_print_button_all_exporters.py.
    tests/test_policy_usage_report.py exercises the generator and the executive
    summary, not the exporter's own construction."""
    from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter
    summary_df = pd.DataFrame([
        {"Category": "Category-tango", "Rules": 5041, "Share %": 41.73},
        {"Category": "Category-sierra", "Rules": 7062, "Share %": 58.27},
    ])

    def _rules(tag: str, base: int, day: int) -> pd.DataFrame:
        return pd.DataFrame([{
            "ruleset": f"RS-{tag}-alfa", "rule_id": f"{base + 11}",
            "consumers": f"consumer-{tag}", "providers": f"provider-{tag}",
            "services": f"service-{tag}", "hit_count": base + 1234,
            "last_hit_at": f"2026-06-{day:02d}T09:14:23Z",
        }])

    results = {
        "mod00": {"generated_at": "2026-07-02 12:00:00", "kpis": []},
        "mod01": {"total_rules": 12103, "hit_count": 5041, "unused_count": 7062,
                  "hit_rate_pct": 41.73, "summary_df": summary_df},
        "mod02": {"hit_df": _rules("hit", 60000, 11)},
        "mod03": {"unused_df": _rules("unused", 70000, 13)},
    }
    return PolicyUsageHtmlExporter(results, lang=_LANG)._build()


# ------------------------------------------------------------ policy diff --
def _build_policy_diff() -> str:
    """Transcribed from tests/test_policy_diff_html_exporter.py::_diff."""
    from src.report.exporters.policy_diff_html_exporter import PolicyDiffHtmlExporter
    rs = pd.DataFrame([{
        "change_type": "modified", "ruleset_name": "RS-alfa-1042",
        "ruleset_id": "10471", "field": "enabled",
        "draft_value": "False", "active_value": "True",
        "last_actor": "bob.chen@lab.local",
        "last_changed": "2026-06-05T12:00:00Z",
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
    def _flows(tag: str, port: int, base: int, day: int, decision: str) -> pd.DataFrame:
        # inbound and outbound carry DIFFERENT decisions: with the same enum in
        # both, deleting either column leaves the value sitting in the other.
        return pd.DataFrame([{
            "src_app": f"web-tier-{tag}", "dst_app": f"data-tier-{tag}",
            "port": port, "proto": f"tcp-{tag}",
            "policy_decision": decision, "num_connections": base + 1234,
            "last_detected": f"2026-01-{day:02d}T08:30:00Z",
        }])

    # ``empty: True`` (the print-button test's fixture) short-circuits the whole
    # body to a single note and renders no table at all. Inbound and outbound
    # must also be DIFFERENT tables — one shared frame hides both from the check.
    results = {"app": "DB", "env": "Prod", "empty": False,
               "baseline": {"inbound": _flows("inbound", 33061, 80000, 11,
                                              "allowed"),
                            "outbound": _flows("outbound", 54321, 90000, 13,
                                               "potentially_blocked"),
                            "inbound_count": 1, "outbound_count": 1},
               "mod03": {}, "policy_impact": {}, "enforcement": {}, "findings": []}
    return AppSummaryHtmlExporter(results, lang=_LANG)._render_html()


# --------------------------------------------------------- rule hit count --
def _build_rule_hit_count() -> str:
    """Transcribed from tests/test_rule_hit_count_html_exporter.py::_row/_result."""
    from src.report.rule_hit_count_generator import RuleHitCountResult
    from src.report.exporters.rule_hit_count_html_exporter import RuleHitCountHtmlExporter
    rows = [{"rule_href": "/rules/10471", "ruleset": "RS-alfa-1042",
             "rule_no": 2085, "rule_id": "10471",
             "rule_type": "Allow", "description": "web tier to database tier",
             "consumers": "consumer-alfa", "providers": "provider-bravo",
             "services": "service-charlie", "enabled": True,
             "hit_count": 5063, "days_since_last_hit": "3074",
             "last_hit_at": "2026-06-28T09:14:23Z",
             "last_updated_by": "admin@lab.local",
             "last_updated_at": "2026-05-01T21:47:09Z"},
            # Second row so the KPI total (the sum) differs from either cell —
            # with one row the sum IS the cell, and deleting the Hit Count
            # column leaves the same digits sitting in the KPI block.
            {"rule_href": "/rules/20583", "ruleset": "RS-bravo-2096",
             "rule_no": 4176, "rule_id": "20583",
             "rule_type": "Deny", "description": "cache tier to queue tier",
             "consumers": "consumer-delta", "providers": "provider-echo",
             "services": "service-foxtrot", "enabled": False,
             "hit_count": 7094, "days_since_last_hit": "6108",
             "last_hit_at": "2026-06-14T17:38:52Z",
             "last_updated_by": "operator@lab.local",
             "last_updated_at": "2026-04-19T06:25:31Z"}]
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
        "app_display": "app-alfa (production)", "app_env_key": "appalfa|production",
        "readiness_score": 91.42, "grade": "A", "current_mode": "full enforcement ×2",
        "blocking_factor": "Ringfence Maturity romeo",
        "blocking_factor_key": "ringfence_maturity",
        "recommended_action": "tighten ringfence rules first",
        "flow_count": 6083, "pb_uncovered_count": 1094,
    }])
    factor_table = pd.DataFrame([{"Factor": "Policy Coverage quebec", "Weight": 3521,
                                  "Score": 3067.0, "Ratio %": 85.31}])
    recs = pd.DataFrame([{"Priority": "P2-medium", "App (Env)": "app-bravo (production)",
                          "App Env Key": "appbravo|production",
                          "Issue": "Enforcement Gap",
                          "Action": "Move to enforcement papa",
                          "Action Code": "MOVE_TO_ENFORCEMENT",
                          # not bare "HIGH": the narrative below this table
                          # contains "higher", and the match is a substring
                          # match over whitespace-stripped text.
                          "Severity": "HIGH-oscar"}])
    readiness = {"total_score": 78.54, "grade": "B",
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
