"""
src/report/exporters/audit_html_exporter.py
Self-contained HTML report for the Audit & System Events Report.
Includes embedded EN ↔ 繁體中文 language toggle (via report_i18n).
"""
from __future__ import annotations
import datetime
import os
import logging
import pandas as pd

from .report_i18n import make_i18n_js, lang_btn_html, COL_I18N as _COL_I18N
from .report_css import build_css
from src.report.analysis.audit.audit_risk import RISK_COLOR, RISK_BG, RISK_ORDER, get_risk
from .report_css import build_css, TABLE_JS

logger = logging.getLogger(__name__)

_CSS = build_css('audit')

def _df_to_html(df, no_data_key: str = "rpt_no_data", show_risk: bool = False) -> str:
    if df is None or (hasattr(df, 'empty') and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">— No data —</p>'
    html = '<table><thead><tr>'
    for col in df.columns:
        i18n_key = _COL_I18N.get(col)
        if i18n_key:
            html += f'<th data-i18n="{i18n_key}">{col}</th>'
        else:
            html += f'<th>{col}</th>'
    html += '</tr></thead><tbody>'
    has_event_type = show_risk and 'event_type' in df.columns
    for _, row in df.iterrows():
        risk_level = 'INFO'
        if has_event_type:
            risk_level = get_risk(str(row['event_type']))[0]
        row_bg = ''
        if risk_level == 'CRITICAL':
            row_bg = " style='background:#FEF2F2;'"
        elif risk_level == 'HIGH':
            row_bg = " style='background:#FFF7ED;'"
        html += f'<tr{row_bg}>'
        for col in df.columns:
            val = str(row[col])
            if has_event_type and col == 'event_type':
                color = RISK_COLOR.get(risk_level, '#989A9B')
                bg = RISK_BG.get(risk_level, '#F9FAFB')
                badge = (
                    f"<span style='display:inline-block; background:{bg}; color:{color}; "
                    f"border:1px solid {color}; padding:1px 5px; border-radius:3px; "
                    f"font-size:10px; font-weight:700; white-space:nowrap; margin-right:5px;'>"
                    f"{risk_level}</span>"
                )
                html += f'<td>{badge}{val}</td>'
            else:
                html += f'<td>{val}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


class AuditHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None,
                 date_range: tuple = ('', '')):
        self._r = results
        self._df = df
        self._date_range = date_range

    @staticmethod
    def _risk_badge(risk_level: str) -> str:
        color = RISK_COLOR.get(risk_level, '#989A9B')
        bg = RISK_BG.get(risk_level, '#F9FAFB')
        return (
            f"<span style='display:inline-block; background:{bg}; color:{color}; "
            f"border:1px solid {color}; padding:1px 6px; border-radius:4px; "
            f"font-size:10px; font-weight:700; white-space:nowrap;'>{risk_level}</span>"
        )

    def _attention_section(self, attention_items: list) -> str:
        if not attention_items:
            return ''
        html = "<div style='margin-bottom:20px;'>"
        html += (
            "<h2 style='font-family:\"Montserrat\",Arial,sans-serif; font-size:15px; "
            "font-weight:700; margin:0 0 10px 0; color:#BE122F;' "
            "data-i18n='rpt_au_attention_title'>⚠ Attention Required</h2>"
        )
        for item in attention_items:
            risk = item.get('risk', 'INFO')
            color = RISK_COLOR.get(risk, '#989A9B')
            bg = RISK_BG.get(risk, '#F9FAFB')
            badge = self._risk_badge(risk)
            event_type = item.get('event_type', '')
            count = item.get('count', 0)
            summary = item.get('summary', '')
            rec = item.get('recommendation', '')
            actors = item.get('actors', [])
            actors_str = ', '.join(str(a) for a in actors[:3]) if actors else '—'
            src_ips = item.get('src_ips', [])
            src_ips_str = ', '.join(str(ip) for ip in src_ips[:3]) if src_ips else ''
            html += (
                f"<div style='border-left:4px solid {color}; background:{bg}; "
                f"padding:10px 14px; margin-bottom:8px; border-radius:0 6px 6px 0;'>"
                f"<div style='display:flex; align-items:center; gap:8px; margin-bottom:4px; flex-wrap:wrap;'>"
                f"{badge}"
                f"<code style='font-size:11px; color:#8B407A;'>{event_type}</code>"
                f"<span style='font-size:11px; font-weight:700; color:{color};'>×{count}</span>"
                f"</div>"
                f"<div style='font-size:12px; color:#313638; margin-bottom:3px;'>{summary}</div>"
                f"<div style='font-size:11px; color:#989A9B;'>"
                f"<strong style='color:#313638;' data-i18n='rpt_au_actor'>Actor:</strong> {actors_str}"
                + (f" &nbsp;|&nbsp; <strong style='color:#313638;'>IP:</strong> {src_ips_str}" if src_ips_str else "")
                + f"</div>"
                f"<div style='font-size:11px; color:#325158; margin-top:3px;'>"
                f"<strong data-i18n='rpt_au_rec'>Recommendation:</strong> {rec}"
                f"</div>"
                f"</div>"
            )
        html += "</div>"
        return html

    def export(self, output_dir: str = 'reports') -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        filename = f'illumio_audit_report_{ts}.html'
        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self._build())
        logger.info(f"[AuditHtmlExporter] Saved: {filepath}")
        return filepath

    def _build(self) -> str:
        mod00 = self._r.get('mod00', {})
        nav_html = (
            '<nav>'
            '<div class="nav-brand">Illumio PCE Ops</div>'
            '<a href="#summary"><span data-i18n="rpt_au_nav_summary">Executive Summary</span></a>'
            '<a href="#health"><span data-i18n="rpt_au_nav_health">1 System Health</span></a>'
            '<a href="#users"><span data-i18n="rpt_au_nav_users">2 User Activity</span></a>'
            '<a href="#policy"><span data-i18n="rpt_au_nav_policy">3 Policy Changes</span></a>'
            '</nav>'
        )
        kpi_cards = ''.join(
            '<div class="kpi-card"><div class="kpi-label">' + k['label'] + '</div>'
            '<div class="kpi-value">' + k['value'] + '</div></div>'
            for k in mod00.get('kpis', [])
        )
        date_str = ' ~ '.join(self._date_range) if any(self._date_range) else ''
        today_str = str(datetime.date.today())

        period_part = (
            ' &nbsp;|&nbsp; <span data-i18n="rpt_period">Period:</span> ' + date_str
            if date_str else ''
        )

        body = (
            '<section id="summary" class="card">'
            '<h1 data-i18n="rpt_au_title">Illumio Audit &amp; System Events Report</h1>'
            '<p style="color:#718096;margin-top:4px">'
            '<span data-i18n="rpt_generated">Generated:</span> ' + mod00.get('generated_at', '') +
            period_part + '</p>'
            + self._attention_section(mod00.get('attention_items', [])) +
            '<h2 data-i18n="rpt_key_metrics">Key Metrics</h2>'
            '<div class="kpi-grid">' + kpi_cards + '</div>'
            + self._severity_dist_html(mod00) +
            '<h2 data-i18n="rpt_au_top_events">Top Event Types</h2>'
            + _df_to_html(mod00.get('top_events_overall')) +
            '</section>\n' +
            self._section('health', 'rpt_au_sec_health', '1 · System Health &amp; Agent', self._mod01_html()) + '\n' +
            self._section('users',  'rpt_au_sec_users',  '2 · User Activity &amp; Authentication', self._mod02_html()) + '\n' +
            self._section('policy', 'rpt_au_sec_policy', '3 · Policy Modifications', self._mod03_html()) + '\n' +
            '<footer><span data-i18n="rpt_au_footer">Illumio PCE Ops — Audit Report</span>'
            ' &middot; ' + today_str + '</footer>'
        )
        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>Illumio Audit Report</title>' + _CSS + '</head>\n'
            '<body>' + lang_btn_html() + nav_html + '<main>' + body + '</main>'
            + TABLE_JS + make_i18n_js() + '</body></html>'
        )

    def _section(self, id_: str, i18n_key: str, title: str, content: str) -> str:
        return (
            f'<section id="{id_}" class="card">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f'{content}</section>'
        )

    def _severity_dist_html(self, mod00: dict) -> str:
        sev_df = mod00.get('severity_distribution')
        if sev_df is None or (hasattr(sev_df, 'empty') and sev_df.empty):
            return ''
        return (
            '<h2 data-i18n="rpt_au_severity_dist">Severity Distribution</h2>'
            + _df_to_html(sev_df)
        )

    def _mod01_html(self):
        m = self._r.get('mod01', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        sec_count = m.get('security_concern_count', 0)
        conn_count = m.get('connectivity_event_count', 0)

        html = (
            '<p><span data-i18n="rpt_au_total_health">Total Health Events:</span>'
            ' <b>' + str(m.get('total_health_events', 0)) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_security_concerns">Security Concerns:</span>'
            ' <b style="color:' + ('#c0392b' if sec_count > 0 else '#313638') + '">' + str(sec_count) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_connectivity_issues">Agent Connectivity:</span>'
            ' <b>' + str(conn_count) + '</b></p>'
        )

        # Best practice note
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_health">'
            '<b>Illumio Best Practice:</b> Monitor system_health events for severity changes '
            '(Warning → Error → Fatal). Investigate agent.tampering and agent.suspend events '
            'immediately — unintended suspensions or firewall tampering may indicate workload compromise. '
            'Track agent_missed_heartbeats_check (3+ missed = 15 min) and agent_offline_check '
            '(12 missed = removed from policy).'
            '</div>'
        )

        # Security concerns (tampering, suspend, clone)
        sec_df = m.get('security_concerns')
        if sec_df is not None and not sec_df.empty:
            html += (
                '<h3 data-i18n="rpt_au_sec_concern_title">⚠ Security Concern Events</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_sec_concern_desc">'
                'agent.tampering, agent.suspend, and agent.clone_detected events may indicate '
                'compromised workloads or unauthorized changes. Investigate immediately.</p>'
                + _df_to_html(sec_df, show_risk=True)
            )

        # Agent connectivity
        conn_df = m.get('connectivity_events')
        if conn_df is not None and not conn_df.empty:
            html += (
                '<h3 data-i18n="rpt_au_connectivity_title">Agent Connectivity Events</h3>'
                + _df_to_html(conn_df, show_risk=True)
            )

        # Severity breakdown
        html += (
            '<h3 data-i18n="rpt_au_severity_breakdown">Severity Breakdown</h3>'
            + _df_to_html(m.get('severity_breakdown'))
        )

        html += (
            '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>'
            + _df_to_html(m.get('summary'))
        )

        html += (
            '<h3 data-i18n="rpt_au_recent">Recent Events (up to 50)</h3>'
            + _df_to_html(m.get('recent'), show_risk=True)
        )

        return html

    def _mod02_html(self):
        m = self._r.get('mod02', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        failed = m.get('failed_logins', 0)
        unique_ips = m.get('unique_src_ips', 0)

        # ── Stats bar ────────────────────────────────────────────────────────
        html = (
            '<p><span data-i18n="rpt_au_total_user">Total User Events:</span>'
            ' <b>' + str(m.get('total_user_events', 0)) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_failed_logins">Failed Logins:</span>'
            ' <b style="color:' + ('#c0392b' if failed > 0 else '#313638') + '">' + str(failed) + '</b>'
        )
        if unique_ips > 0:
            html += (
                ' &nbsp;|&nbsp; '
                '<span data-i18n="rpt_au_unique_src_ips">Unique Admin IPs:</span>'
                ' <b>' + str(unique_ips) + '</b>'
            )
        html += '</p>'

        # ── Best practice notes ──────────────────────────────────────────────
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_users">'
            '<b>Illumio Best Practice:</b> Monitor login failures for patterns indicating '
            'brute-force or credential stuffing attacks. Investigate repeated failures from '
            'the same user or sudden spikes in authentication events.'
            '</div>'
        )
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_src_ip_note">'
            '<b>Source IP Tracking:</b> The <code>src_ip</code> column shows where the admin/API '
            'connected from. Multiple logins or policy changes from unexpected IPs may indicate '
            'compromised credentials or insider threats.'
            '</div>'
        )

        # ── Failed login detail (enriched with src_ip & notifications) ───────
        failed_detail = m.get('failed_login_detail')
        if failed_detail is not None and not (hasattr(failed_detail, 'empty') and failed_detail.empty):
            html += (
                '<h3 data-i18n="rpt_au_failed_detail">Failed Login Details</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_failed_detail_desc">'
                'Enriched with source IP and notification context. '
                'Check for brute-force patterns or suspicious source IPs.</p>'
                + _df_to_html(failed_detail, show_risk=True)
            )

        # ── Per-user breakdown ────────────────────────────────────────────────
        per_user = m.get('per_user')
        if per_user is not None and not (hasattr(per_user, 'empty') and per_user.empty):
            html += (
                '<h3 data-i18n="rpt_au_per_user">Activity by User</h3>'
                + _df_to_html(per_user)
            )

        html += (
            '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>'
            + _df_to_html(m.get('summary'))
        )

        html += (
            '<h3 data-i18n="rpt_au_recent">Recent Events (up to 50)</h3>'
            + _df_to_html(m.get('recent'), show_risk=True)
        )

        return html

    @staticmethod
    def _lifecycle_concept_box() -> str:
        """Render the Draft vs Provision lifecycle explanation panel."""
        return (
            "<details style='margin-bottom:16px; border:1px solid #CBD5E0; border-radius:8px; overflow:hidden;' open>"
            "<summary style='padding:10px 14px; background:#EBF4FF; cursor:pointer; font-weight:700; "
            "font-size:13px; color:#2B6CB0; list-style:none; display:flex; align-items:center; gap:6px;' "
            "data-i18n='rpt_au_lifecycle_title'>📘 Illumio Policy Lifecycle: Draft vs Provision</summary>"
            "<div style='display:grid; grid-template-columns:1fr 1fr; gap:0; border-top:1px solid #CBD5E0;'>"

            # Left: Draft
            "<div style='padding:14px 16px; border-right:1px solid #CBD5E0; background:#FEFCE8;'>"
            "<div style='font-weight:700; font-size:12px; color:#92400E; margin-bottom:8px;' "
            "data-i18n='rpt_au_lifecycle_draft_title'>1️⃣ Draft Changes (Not Yet Enforced)</div>"
            "<div style='font-size:12px; color:#374151; line-height:1.7;' "
            "data-i18n-html='rpt_au_lifecycle_draft_body'>"
            "When an admin creates, edits, or deletes a rule in the PCE console <b>without clicking Provision</b>, "
            "the system logs <code>rule_set.*</code> and <code>sec_rule.*</code> events. "
            "These only represent changes to the policy <em>draft</em> — "
            "<b>no firewall rules have been pushed to any VEN yet.</b><br><br>"
            "⚠ <b>Watch for:</b> Broad scopes such as <em>All Applications / All Environments / All Locations</em> "
            "(displayed as <code>null</code> in the API). A draft with such scope, once provisioned, "
            "could affect a large number of workloads."
            "</div>"
            "<div style='margin-top:10px; padding:8px; background:#FEF3C7; border-radius:4px; font-size:11px; color:#78350F;'>"
            "<b>Event types:</b> <code>rule_set.create</code> · <code>rule_set.update</code> · "
            "<code>rule_set.delete</code> · <code>sec_rule.create</code> · <code>sec_rule.update</code> · "
            "<code>sec_rule.delete</code>"
            "</div>"
            "</div>"

            # Right: Provision
            "<div style='padding:14px 16px; background:#F0FDF4;'>"
            "<div style='font-weight:700; font-size:12px; color:#065F46; margin-bottom:8px;' "
            "data-i18n='rpt_au_lifecycle_prov_title'>2️⃣ Provision — Policy Goes Live</div>"
            "<div style='font-size:12px; color:#374151; line-height:1.7;' "
            "data-i18n-html='rpt_au_lifecycle_prov_body'>"
            "When an admin clicks <b>Provision</b>, all draft changes are packaged into a new versioned policy "
            "and pushed to workload VENs. The PCE logs a <code>sec_policy.create</code> event — "
            "not <code>update</code>, because each provision creates a <em>new policy version</em>.<br><br>"
            "🔑 <b>Key field:</b> <code>workloads_affected</code> — "
            "how many hosts received the new policy. A surprisingly large number signals unexpectedly broad scope. "
            "<b>If this was not a planned large-scale change, investigate immediately.</b>"
            "</div>"
            "<div style='margin-top:10px; padding:8px; background:#D1FAE5; border-radius:4px; font-size:11px; color:#065F46;'>"
            "<b>Event type:</b> <code>sec_policy.create</code> &nbsp;(each provision = new version number)"
            "</div>"
            "</div>"

            "</div>"
            "</details>"
        )

    @staticmethod
    def _high_impact_provisions_html(items: list, threshold: int) -> str:
        """Render high-impact provision alert cards."""
        if not items:
            return ''
        html = (
            f"<div style='margin-bottom:14px; padding:12px 16px; background:#FEF2F2; "
            f"border:1px solid #FCA5A5; border-radius:8px;'>"
            f"<div style='font-weight:700; font-size:13px; color:#991B1B; margin-bottom:6px;' "
            f"data-i18n='rpt_au_high_impact_title'>🚨 High-Impact Provisions</div>"
            f"<p style='font-size:12px; color:#7F1D1D; margin:0 0 10px 0;' "
            f"data-i18n='rpt_au_high_impact_desc'>"
            f"The following provision events affected an unusually large number of workloads "
            f"(threshold: {threshold}+). Verify these were intended large-scale policy changes.</p>"
        )
        for item in items:
            wa = item.get('workloads_affected', 0)
            ts = item.get('timestamp', '')
            et = item.get('event_type', '')
            actor = item.get('actor', '—')
            src_ip = item.get('src_ip', '')
            status = item.get('status', '')
            html += (
                f"<div style='display:flex; align-items:center; flex-wrap:wrap; gap:8px; "
                f"padding:8px 10px; background:#FFF5F5; border-radius:6px; margin-bottom:6px; "
                f"border-left:4px solid #EF4444;'>"
                f"<span style='font-size:20px; font-weight:900; color:#DC2626;'>{wa:,}</span>"
                f"<span style='font-size:11px; color:#991B1B;' data-i18n='rpt_au_workloads_affected'>Workloads Affected</span>"
                f"<code style='font-size:11px; background:#FEE2E2; padding:2px 6px; border-radius:3px; color:#7F1D1D;'>{et}</code>"
                f"<span style='font-size:11px; color:#6B7280;'>{ts}</span>"
                f"<span style='font-size:11px; color:#6B7280;'>by <b>{actor}</b></span>"
                + (f"<span style='font-size:11px; color:#6B7280;'>from <code>{src_ip}</code></span>" if src_ip else "")
                + (f"<span style='font-size:11px; color:#6B7280;'>· {status}</span>" if status else "")
                + "</div>"
            )
        html += "</div>"
        return html

    def _mod03_html(self):
        m = self._r.get('mod03', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        prov_count = m.get('provision_count', 0)
        rule_count = m.get('rule_change_count', 0)
        total_wa = m.get('total_workloads_affected', 0)
        threshold = m.get('high_impact_threshold', 50)
        high_impact = m.get('high_impact_provisions', [])

        # ── Stats bar ────────────────────────────────────────────────────────
        html = (
            '<p><span data-i18n="rpt_au_total_policy">Total Policy Events:</span>'
            ' <b>' + str(m.get('total_policy_events', 0)) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_provisions">Provisions:</span>'
            ' <b>' + str(prov_count) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_rule_changes">Rule Changes (Draft):</span>'
            ' <b>' + str(rule_count) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_provision_impact_stat">Total Workloads Affected (all provisions):</span>'
            ' <b style="color:' + ('#c0392b' if total_wa > threshold else '#313638') + '">'
            + (f'{total_wa:,}' if total_wa else '0') + '</b></p>'
        )

        # ── Lifecycle concept box ─────────────────────────────────────────────
        html += self._lifecycle_concept_box()

        # ── Best practice notes ──────────────────────────────────────────────
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_policy">'
            '<b>Illumio Best Practice:</b> Review rule_set and sec_rule changes for overly broad scopes '
            '(null HREF = All Applications/Environments/Locations). When sec_policy.create (provision) '
            'events occur, check workloads_affected — a high number may indicate unintended policy impact. '
            'Monitor sec_rule.delete events to detect unauthorized policy weakening.'
            '</div>'
        )
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_change_detail_note">'
            '<b>Change Tracking:</b> The <code>change_detail</code> column shows before → after values '
            'for modified resources. Look for changes to broad scopes (null = All) or sensitive labels '
            '(Production, PCI).'
            '</div>'
        )

        # ── High-impact provision alerts ──────────────────────────────────────
        html += self._high_impact_provisions_html(high_impact, threshold)

        # ── Provision events table ────────────────────────────────────────────
        provisions = m.get('provisions')
        if provisions is not None and not (hasattr(provisions, 'empty') and provisions.empty):
            html += (
                '<h3 data-i18n="rpt_au_provision_title">Policy Provision Events</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_provision_desc">'
                'Policy provisions push draft changes to active enforcement. '
                'Review for unintended scope or excessive workload impact.</p>'
                '<p class="note" style="font-size:.82rem">'
                '<b>change_detail</b> 欄位（如有）顯示的是管理員的部署備註（<code>commit_message</code>）'
                '及本次部署所包含的物件數量統計（<code>object_counts</code>：rule_sets / ip_lists / services 等）。'
                '此欄位<b>不會</b>顯示個別規則的 before/after 差異——那些細節請查看上方「草稿規則變更」表格。'
                '</p>'
                + _df_to_html(provisions, show_risk=True)
            )

        # ── Draft rule changes table ──────────────────────────────────────────
        draft_events = m.get('draft_events')
        if draft_events is not None and not (hasattr(draft_events, 'empty') and draft_events.empty):
            html += (
                '<h3 data-i18n="rpt_au_draft_section">Draft Rule Changes</h3>'
                '<p class="note" data-i18n="rpt_au_draft_desc">'
                'These events represent policy edits in draft state. No enforcement changes have '
                'occurred yet — they only take effect after Provision.</p>'
                '<p class="note" style="font-size:.82rem">'
                '<b>change_detail</b> 格式：<code>[ruleset 或規則名稱 / href]</code> &nbsp;欄位名稱: 修改前 → 修改後。'
                '若名稱欄位為空，顯示縮略 href（例如 <code>rule_sets/471/sec_rules/1234</code>）。'
                '</p>'
                + _df_to_html(draft_events, show_risk=True)
            )

        # ── Per-user breakdown ────────────────────────────────────────────────
        per_user = m.get('per_user')
        if per_user is not None and not (hasattr(per_user, 'empty') and per_user.empty):
            html += (
                '<h3 data-i18n="rpt_au_per_user_policy">Changes by User</h3>'
                + _df_to_html(per_user)
            )

        html += (
            '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>'
            + _df_to_html(m.get('summary'))
        )

        html += (
            '<h3 data-i18n="rpt_au_recent">All Policy Events (up to 50)</h3>'
            + _df_to_html(m.get('recent'), show_risk=True)
        )

        return html
