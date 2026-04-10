"""Self-contained HTML report for the Audit & System Events Report."""

from __future__ import annotations

import datetime
import logging
import os

import pandas as pd

from .report_css import TABLE_JS, build_css
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS, lang_btn_html, make_i18n_js
from .table_renderer import render_df_table
from src.report.analysis.audit.audit_risk import RISK_BG, RISK_COLOR, get_risk

logger = logging.getLogger(__name__)

_CSS = build_css("audit")


def _df_to_html(df, no_data_key: str = "rpt_no_data", show_risk: bool = False) -> str:
    if df is None or (hasattr(df, "empty") and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">No data</p>'

    has_event_type = show_risk and "event_type" in df.columns

    def _row_attrs(row):
        risk_level = "INFO"
        if has_event_type:
            risk_level = get_risk(str(row["event_type"]))[0]
        if risk_level == "CRITICAL":
            return " style='background:#FEF2F2;'"
        if risk_level == "HIGH":
            return " style='background:#FFF7ED;'"
        return ""

    def _render_cell(col, val, row):
        if has_event_type and col == "event_type":
            risk_level = get_risk(str(row["event_type"]))[0]
            color = RISK_COLOR.get(risk_level, "#989A9B")
            bg = RISK_BG.get(risk_level, "#F9FAFB")
            badge = (
                f"<span style='display:inline-block; background:{bg}; color:{color}; "
                f"border:1px solid {color}; padding:1px 5px; border-radius:3px; "
                f"font-size:10px; font-weight:700; white-space:nowrap; margin-right:5px;'>"
                f"{risk_level}</span>"
            )
            return f"{badge}{row[col]}"
        return "" if row[col] is None else str(row[col])

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
        row_attrs=_row_attrs,
    )


class AuditHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None, date_range: tuple = ("", "")):
        self._r = results
        self._df = df
        self._date_range = date_range

    @staticmethod
    def _risk_badge(risk_level: str) -> str:
        color = RISK_COLOR.get(risk_level, "#989A9B")
        bg = RISK_BG.get(risk_level, "#F9FAFB")
        return (
            f"<span style='display:inline-block; background:{bg}; color:{color}; "
            f"border:1px solid {color}; padding:1px 6px; border-radius:4px; "
            f"font-size:10px; font-weight:700; white-space:nowrap;'>{risk_level}</span>"
        )

    def _attention_section(self, attention_items: list) -> str:
        if not attention_items:
            return ""
        html = "<div style='margin-bottom:20px;'>"
        html += (
            "<h2 style='font-family:\"Montserrat\",Arial,sans-serif; font-size:15px; "
            "font-weight:700; margin:0 0 10px 0; color:#BE122F;' "
            "data-i18n='rpt_au_attention_title'>Attention Required</h2>"
        )
        for item in attention_items:
            risk = item.get("risk", "INFO")
            color = RISK_COLOR.get(risk, "#989A9B")
            bg = RISK_BG.get(risk, "#F9FAFB")
            badge = self._risk_badge(risk)
            event_type = item.get("event_type", "")
            count = item.get("count", 0)
            summary = item.get("summary", "")
            rec = item.get("recommendation", "")
            actors = item.get("actors", [])
            actors_str = ", ".join(str(a) for a in actors[:3]) if actors else "N/A"
            targets = item.get("targets", [])
            targets_str = ", ".join(str(a) for a in targets[:3]) if targets else ""
            resources = item.get("resources", [])
            resources_str = ", ".join(str(a) for a in resources[:3]) if resources else ""
            src_ips = item.get("src_ips", [])
            src_ips_str = ", ".join(str(ip) for ip in src_ips[:3]) if src_ips else ""

            html += (
                f"<div style='border-left:4px solid {color}; background:{bg}; "
                f"padding:10px 14px; margin-bottom:8px; border-radius:0 6px 6px 0;'>"
                f"<div style='display:flex; align-items:center; gap:8px; margin-bottom:4px; flex-wrap:wrap;'>"
                f"{badge}"
                f"<code style='font-size:11px; color:#8B407A;'>{event_type}</code>"
                f"<span style='font-size:11px; font-weight:700; color:{color};'>x{count}</span>"
                f"</div>"
                f"<div style='font-size:12px; color:#313638; margin-bottom:3px;'>{summary}</div>"
                f"<div style='font-size:11px; color:#989A9B;'>"
                f"<strong style='color:#313638;' data-i18n='rpt_au_actor'>Actor:</strong> {actors_str}"
                + (f" &nbsp;|&nbsp; <strong style='color:#313638;'>IP:</strong> {src_ips_str}" if src_ips_str else "")
                + "</div>"
                + (
                    f"<div style='font-size:11px; color:#989A9B; margin-top:3px;'>"
                    f"<strong style='color:#313638;'>Target:</strong> {targets_str}"
                    + (f" &nbsp;|&nbsp; <strong style='color:#313638;'>Resource:</strong> {resources_str}" if resources_str else "")
                    + "</div>"
                    if targets_str or resources_str else ""
                )
                + f"<div style='font-size:11px; color:#325158; margin-top:3px;'>"
                f"<strong data-i18n='rpt_au_rec'>Recommendation:</strong> {rec}"
                f"</div>"
                f"</div>"
            )
        html += "</div>"
        return html

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_audit_report_{ts}.html"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._build())
        logger.info("[AuditHtmlExporter] Saved: %s", filepath)
        return filepath

    def _build(self) -> str:
        mod00 = self._r.get("mod00", {})
        nav_html = (
            "<nav>"
            '<div class="nav-brand">Illumio PCE Ops</div>'
            '<a href="#summary"><span data-i18n="rpt_au_nav_summary">Executive Summary</span></a>'
            '<a href="#health"><span data-i18n="rpt_au_nav_health">1 System Health</span></a>'
            '<a href="#users"><span data-i18n="rpt_au_nav_users">2 User Activity</span></a>'
            '<a href="#policy"><span data-i18n="rpt_au_nav_policy">3 Policy Changes</span></a>'
            "</nav>"
        )
        kpi_cards = "".join(
            '<div class="kpi-card"><div class="kpi-label">' + k["label"] + "</div>"
            '<div class="kpi-value">' + k["value"] + "</div></div>"
            for k in mod00.get("kpis", [])
        )
        date_str = " ~ ".join(self._date_range) if any(self._date_range) else ""
        today_str = str(datetime.date.today())
        period_part = (
            ' &nbsp;|&nbsp; <span data-i18n="rpt_period">Period:</span> ' + date_str if date_str else ""
        )
        summary_pills = (
            '<div class="summary-pill-row">'
            f'<div class="summary-pill"><span class="summary-pill-label">{STRINGS["rpt_pill_period"]["en"]}</span><span class="summary-pill-value">{date_str or "N/A"}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{STRINGS["rpt_pill_attention"]["en"]}</span><span class="summary-pill-value">{len(mod00.get("attention_items", []))}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{STRINGS["rpt_pill_focus"]["en"]}</span><span class="summary-pill-value">{STRINGS["rpt_focus_audit"]["en"]}</span></div>'
            "</div>"
        )

        body = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top"><div class="report-kicker" data-i18n="rpt_kicker_audit">Audit & Event Report</div>'
            '<h1 data-i18n="rpt_au_title">Illumio Audit &amp; System Events Report</h1>'
            '<p class="report-subtitle">'
            '<span data-i18n="rpt_generated">Generated:</span> ' + mod00.get("generated_at", "") + period_part + "</p></div>"
            + summary_pills
            + self._attention_section(mod00.get("attention_items", []))
            + self._attack_summary_html(mod00)
            + '<h2 data-i18n="rpt_key_metrics">Key Metrics</h2>'
            + '<div class="kpi-grid">' + kpi_cards + "</div>"
            + self._severity_dist_html(mod00)
            + '<h2 data-i18n="rpt_au_top_events">Top Event Types</h2>'
            + _df_to_html(mod00.get("top_events_overall"))
            + "</section>\n"
            + self._section("health", "rpt_au_sec_health", "1 System Health &amp; Agent", self._mod01_html())
            + "\n"
            + self._section("users", "rpt_au_sec_users", "2 User Activity &amp; Authentication", self._mod02_html())
            + "\n"
            + self._section("policy", "rpt_au_sec_policy", "3 Policy Modifications", self._mod03_html())
            + "\n"
            + '<footer><span data-i18n="rpt_au_footer">Illumio PCE Ops Audit Report</span>'
            + " &middot; "
            + today_str
            + "</footer>"
        )
        return (
            "<!DOCTYPE html><html lang=\"en\"><head>\n"
            "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>Illumio Audit Report</title>"
            + _CSS
            + "</head>\n"
            + "<body>"
            + lang_btn_html()
            + nav_html
            + "<main>"
            + body
            + "</main>"
            + TABLE_JS
            + make_i18n_js()
            + "</body></html>"
        )

    def _section(self, id_: str, i18n_key: str, title: str, content: str, intro: str = "") -> str:
        intro_html = f'<p class="section-intro">{intro}</p>' if intro else ""
        return f'<section id="{id_}" class="card"><h2 data-i18n="{i18n_key}">{title}</h2>{intro_html}{content}</section>'

    def _subnote(self, text: str) -> str:
        return f'<p class="note" style="font-size:12px;">{text}</p>'

    def _attack_summary_html(self, mod00: dict) -> str:
        def _rows(section_items):
            if not section_items:
                return '<p class="note">No data</p>'
            return "".join(
                "<p style='margin-bottom:8px'><span class='badge badge-"
                + str(item.get("severity", "INFO"))
                + "'>"
                + str(item.get("severity", "INFO"))
                + "</span>&nbsp;"
                + str(item.get("finding", ""))
                + (("<br><span style='color:#718096;font-size:12px;'>"
                    + str(item.get("finding_zh", ""))
                    + "</span>") if item.get("finding_zh") else "")
                + " <em style='color:#718096'>&rarr; "
                + str(item.get("action", ""))
                + "</em>"
                + (("<br><span style='color:#718096;font-size:12px;'><em>&rarr; "
                    + str(item.get("action_zh", ""))
                    + "</em></span>") if item.get("action_zh") else "")
                + "</p>"
                for item in section_items[:3]
            )

        action_matrix = mod00.get("action_matrix", []) or []
        action_html = "".join(
            "<p style='margin-bottom:8px'><b>"
            + str(item.get("action_code", ""))
            + "</b>: "
            + str(item.get("action", ""))
            + (("<br><span style='color:#718096;font-size:12px;'>"
                + str(item.get("action_zh", ""))
                + "</span>") if item.get("action_zh") else "")
            + "</p>"
            for item in action_matrix[:3]
        ) or '<p class="note">No data</p>'

        return (
            '<h2 data-i18n="rpt_tr_attack_summary">Attack Summary</h2>'
            '<h3 data-i18n="rpt_tr_boundary_breaches">Boundary Breaches</h3>' + _rows(mod00.get("boundary_breaches", []))
            + '<h3 data-i18n="rpt_tr_suspicious_pivot_behavior">Suspicious Pivot Behavior</h3>' + _rows(mod00.get("suspicious_pivot_behavior", []))
            + '<h3 data-i18n="rpt_tr_blast_radius">Blast Radius</h3>' + _rows(mod00.get("blast_radius", []))
            + '<h3 data-i18n="rpt_tr_blind_spots">Blind Spots</h3>' + _rows(mod00.get("blind_spots", []))
            + '<h3 data-i18n="rpt_tr_action_matrix">Action Matrix</h3>' + action_html
        )

    def _severity_dist_html(self, mod00: dict) -> str:
        sev_df = mod00.get("severity_distribution")
        if sev_df is None or (hasattr(sev_df, "empty") and sev_df.empty):
            return ""
        return '<h2 data-i18n="rpt_au_severity_dist">Severity Distribution</h2>' + _df_to_html(sev_df)

    def _mod01_html(self) -> str:
        m = self._r.get("mod01", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        sec_count = m.get("security_concern_count", 0)
        conn_count = m.get("connectivity_event_count", 0)
        html = (
            self._subnote("This section focuses on platform health, agent connectivity, and host-level security events. Use actor, target, source IP, and parser notes together when validating whether an event needs investigation.")
            + '<p><span data-i18n="rpt_au_total_health">Total Health Events:</span> <b>'
            + str(m.get("total_health_events", 0))
            + "</b> &nbsp;|&nbsp; "
            + '<span data-i18n="rpt_au_security_concerns">Security Concerns:</span> <b style="color:'
            + ("#c0392b" if sec_count > 0 else "#313638")
            + '">'
            + str(sec_count)
            + "</b> &nbsp;|&nbsp; "
            + '<span data-i18n="rpt_au_connectivity_issues">Agent Connectivity:</span> <b>'
            + str(conn_count)
            + "</b></p>"
        )
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_health">'
            "<b>Illumio Best Practice:</b> Monitor system_health events for severity changes "
            "(Warning / Error / Fatal). Investigate agent.tampering and agent.suspend events immediately. "
            "Track missed heartbeats and offline checks to catch workloads that silently fall out of policy."
            "</div>"
        )

        sec_df = m.get("security_concerns")
        if sec_df is not None and not sec_df.empty:
            html += (
                '<h3 data-i18n="rpt_au_sec_concern_title">Security Concern Events</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_sec_concern_desc">'
                "agent.tampering, agent.suspend, and agent.clone_detected events may indicate "
                "compromised workloads or unauthorized changes. Investigate immediately.</p>"
                + _df_to_html(sec_df, show_risk=True)
            )

        conn_df = m.get("connectivity_events")
        if conn_df is not None and not conn_df.empty:
            html += (
                self._subnote("Connectivity events highlight agents that stopped checking in, were removed from policy, or require re-pairing. The parsed target and resource columns help identify the affected workload quickly.")
                + '<h3 data-i18n="rpt_au_connectivity_title">Agent Connectivity Events</h3>'
                + _df_to_html(conn_df, show_risk=True)
            )

        html += '<h3 data-i18n="rpt_au_severity_breakdown">Severity Breakdown</h3>' + _df_to_html(m.get("severity_breakdown"))
        html += '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>' + _df_to_html(m.get("summary"))
        html += '<h3 data-i18n="rpt_au_recent">Recent Events (up to 50)</h3>' + _df_to_html(m.get("recent"), show_risk=True)
        return html

    def _mod02_html(self) -> str:
        m = self._r.get("mod02", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        failed = m.get("failed_logins", 0)
        unique_ips = m.get("unique_src_ips", 0)
        html = (
            self._subnote("User activity now relies on parsed principals and actions. The report prefers the affected user account as the main identity, then falls back to the actor when the target is unavailable.")
            + '<p><span data-i18n="rpt_au_total_user">Total User Events:</span> <b>'
            + str(m.get("total_user_events", 0))
            + "</b> &nbsp;|&nbsp; "
            + '<span data-i18n="rpt_au_failed_logins">Failed Logins:</span> <b style="color:'
            + ("#c0392b" if failed > 0 else "#313638")
            + '">'
            + str(failed)
            + "</b>"
        )
        if unique_ips > 0:
            html += (
                ' &nbsp;|&nbsp; <span data-i18n="rpt_au_unique_src_ips">Unique Admin IPs:</span> <b>'
                + str(unique_ips)
                + "</b>"
            )
        html += "</p>"
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_users">'
            "<b>Illumio Best Practice:</b> Monitor login failures for patterns indicating "
            "brute-force or credential stuffing attacks. Investigate repeated failures from "
            "the same user or sudden spikes in authentication events."
            "</div>"
        )

        failed_detail = m.get("failed_login_detail")
        if failed_detail is not None and not (hasattr(failed_detail, "empty") and failed_detail.empty):
            html += (
                self._subnote("Failed authentication rows are enriched with the parsed target user, source IP, supplied username, and action path. Review repeated failures by user or by source IP.")
                + '<h3 data-i18n="rpt_au_failed_detail">Failed Login Details</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_failed_detail_desc">'
                "Enriched with source IP and notification context. "
                "Check for brute-force patterns or suspicious source IPs.</p>"
                + _df_to_html(failed_detail, show_risk=True)
            )

        per_user = m.get("per_user")
        if per_user is not None and not (hasattr(per_user, "empty") and per_user.empty):
            html += '<h3 data-i18n="rpt_au_per_user">Activity by User</h3>' + _df_to_html(per_user)

        html += '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>' + _df_to_html(m.get("summary"))
        html += '<h3 data-i18n="rpt_au_recent">Recent Events (up to 50)</h3>' + _df_to_html(m.get("recent"), show_risk=True)
        return html

    @staticmethod
    def _lifecycle_concept_box() -> str:
        return (
            "<details style='margin-bottom:16px; border:1px solid #CBD5E0; border-radius:8px; overflow:hidden;' open>"
            "<summary style='padding:10px 14px; background:#EBF4FF; cursor:pointer; font-weight:700; "
            "font-size:13px; color:#2B6CB0; list-style:none; display:flex; align-items:center; gap:6px;' "
            "data-i18n='rpt_au_lifecycle_title'>Illumio Policy Lifecycle: Draft vs Provision</summary>"
            "<div style='display:grid; grid-template-columns:1fr 1fr; gap:0; border-top:1px solid #CBD5E0;'>"
            "<div style='padding:14px 16px; border-right:1px solid #CBD5E0; background:#FEFCE8;'>"
            "<div style='font-weight:700; font-size:12px; color:#92400E; margin-bottom:8px;' "
            "data-i18n='rpt_au_lifecycle_draft_title'>1 Draft Changes (Not Yet Enforced)</div>"
            "<div style='font-size:12px; color:#374151; line-height:1.7;' data-i18n-html='rpt_au_lifecycle_draft_body'>"
            "Draft events such as <code>rule_set.*</code> and <code>sec_rule.*</code> only represent policy edits. "
            "<b>No firewall rules are pushed yet.</b> Review broad scopes carefully before the next provision."
            "</div></div>"
            "<div style='padding:14px 16px; background:#F0FDF4;'>"
            "<div style='font-weight:700; font-size:12px; color:#065F46; margin-bottom:8px;' "
            "data-i18n='rpt_au_lifecycle_prov_title'>2 Provision (Policy Goes Live)</div>"
            "<div style='font-size:12px; color:#374151; line-height:1.7;' data-i18n-html='rpt_au_lifecycle_prov_body'>"
            "A <code>sec_policy.create</code> event means draft changes were packaged into a new policy version and pushed to workloads. "
            "Use <code>workloads_affected</code> to verify rollout impact."
            "</div></div></div></details>"
        )

    @staticmethod
    def _high_impact_provisions_html(items: list, threshold: int) -> str:
        if not items:
            return ""
        html = (
            f"<div style='margin-bottom:14px; padding:12px 16px; background:#FEF2F2; border:1px solid #FCA5A5; border-radius:8px;'>"
            f"<div style='font-weight:700; font-size:13px; color:#991B1B; margin-bottom:6px;' data-i18n='rpt_au_high_impact_title'>High-Impact Provisions</div>"
            f"<p style='font-size:12px; color:#7F1D1D; margin:0 0 10px 0;' data-i18n='rpt_au_high_impact_desc'>"
            f"The following provision events affected an unusually large number of workloads (threshold: {threshold}+). "
            f"Verify these were intended large-scale policy changes.</p>"
        )
        for item in items:
            wa = item.get("workloads_affected", 0)
            ts = item.get("timestamp", "")
            et = item.get("event_type", "")
            actor = item.get("actor", "N/A")
            src_ip = item.get("src_ip", "")
            resource_name = item.get("resource_name", "")
            status = item.get("status", "")
            html += (
                f"<div style='display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 10px; background:#FFF5F5; "
                f"border-radius:6px; margin-bottom:6px; border-left:4px solid #EF4444;'>"
                f"<span style='font-size:20px; font-weight:900; color:#DC2626;'>{wa:,}</span>"
                f"<span style='font-size:11px; color:#991B1B;' data-i18n='rpt_au_workloads_affected'>Workloads Affected</span>"
                f"<code style='font-size:11px; background:#FEE2E2; padding:2px 6px; border-radius:3px; color:#7F1D1D;'>{et}</code>"
                f"<span style='font-size:11px; color:#6B7280;'>{ts}</span>"
                f"<span style='font-size:11px; color:#6B7280;'>by <b>{actor}</b></span>"
                + (f"<span style='font-size:11px; color:#6B7280;'>resource <b>{resource_name}</b></span>" if resource_name else "")
                + (f"<span style='font-size:11px; color:#6B7280;'>from <code>{src_ip}</code></span>" if src_ip else "")
                + (f"<span style='font-size:11px; color:#6B7280;'>| {status}</span>" if status else "")
                + "</div>"
            )
        html += "</div>"
        return html

    def _mod03_html(self) -> str:
        m = self._r.get("mod03", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        prov_count = m.get("provision_count", 0)
        rule_count = m.get("rule_change_count", 0)
        total_wa = m.get("total_workloads_affected", 0)
        threshold = m.get("high_impact_threshold", 50)
        high_impact = m.get("high_impact_provisions", [])

        html = (
            self._subnote("Policy events now surface the parsed actor, target, resource, action, and change summary together. This makes it easier to separate draft edits from provisions that actually impacted workloads.")
            + '<p><span data-i18n="rpt_au_total_policy">Total Policy Events:</span> <b>'
            + str(m.get("total_policy_events", 0))
            + "</b> &nbsp;|&nbsp; "
            + '<span data-i18n="rpt_au_provisions">Provisions:</span> <b>'
            + str(prov_count)
            + "</b> &nbsp;|&nbsp; "
            + '<span data-i18n="rpt_au_rule_changes">Rule Changes (Draft):</span> <b>'
            + str(rule_count)
            + "</b> &nbsp;|&nbsp; "
            + '<span data-i18n="rpt_au_provision_impact_stat">Total Workloads Affected (all provisions):</span> <b style="color:'
            + ("#c0392b" if total_wa > threshold else "#313638")
            + '">'
            + (f"{total_wa:,}" if total_wa else "0")
            + "</b></p>"
        )
        html += self._lifecycle_concept_box()
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_policy">'
            "<b>Illumio Best Practice:</b> Review rule_set and sec_rule changes for overly broad scopes. "
            "When sec_policy.create events occur, check workloads_affected and change_detail to confirm rollout impact."
            "</div>"
        )
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_change_detail_note">'
            "<b>Change Tracking:</b> The <code>change_detail</code> column summarizes parsed before/after values, commit metadata, and impacted objects."
            "</div>"
        )
        html += self._high_impact_provisions_html(high_impact, threshold)

        provisions = m.get("provisions")
        if provisions is not None and not (hasattr(provisions, "empty") and provisions.empty):
            html += (
                self._subnote("Provision rows show rollout impact directly. Use workloads affected, actor, source IP, resource name, and change detail together to validate whether a large policy change was expected.")
                + '<h3 data-i18n="rpt_au_provision_title">Policy Provision Events</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_provision_desc">'
                "Policy provisions push draft changes to active enforcement. "
                "Review for unintended scope or excessive workload impact.</p>"
                '<p class="note" style="font-size:.82rem">'
                "<b>change_detail</b> summarizes commit message, version, modified object counts, and impacted resources for provision events."
                "</p>"
                + _df_to_html(provisions, show_risk=True)
            )

        draft_events = m.get("draft_events")
        if draft_events is not None and not (hasattr(draft_events, "empty") and draft_events.empty):
            html += (
                self._subnote("Draft changes represent edits that have not been provisioned yet. Use target, resource, action, and change detail to review scope before the next provision.")
                + '<h3 data-i18n="rpt_au_draft_section">Draft Rule Changes</h3>'
                '<p class="note" data-i18n="rpt_au_draft_desc">'
                "These events represent policy edits in draft state. No enforcement changes have "
                "occurred yet; they only take effect after Provision.</p>"
                '<p class="note" style="font-size:.82rem">'
                "<b>change_detail</b> summarizes field-level before/after values for draft edits so policy reviewers can inspect scope and intent without opening raw JSON."
                "</p>"
                + _df_to_html(draft_events, show_risk=True)
            )

        per_user = m.get("per_user")
        if per_user is not None and not (hasattr(per_user, "empty") and per_user.empty):
            html += (
                self._subnote("This breakdown groups policy activity by parsed actor so admin-driven changes, system tasks, and agent-originated operations are easier to distinguish.")
                + '<h3 data-i18n="rpt_au_per_user_policy">Changes by User</h3>'
                + _df_to_html(per_user)
            )

        html += '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>' + _df_to_html(m.get("summary"))
        html += '<h3 data-i18n="rpt_au_recent">All Policy Events (up to 50)</h3>' + _df_to_html(m.get("recent"), show_risk=True)
        return html
