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

logger = logging.getLogger(__name__)

_CSS = build_css('audit')

_SORT_JS = """
<script>
document.querySelectorAll('th').forEach((th, i) => {
  th.addEventListener('click', () => {
    var table = th.closest('table');
    var rows = Array.from(table.rows).slice(1);
    var asc = table.dataset.sortCol === String(i) && table.dataset.sortDir === 'asc';
    rows.sort((a, b) => {
      var av = a.cells[i]?.innerText || '', bv = b.cells[i]?.innerText || '';
      var an = parseFloat(av.replace(/,/g,'')), bn = parseFloat(bv.replace(/,/g,''));
      if (!isNaN(an) && !isNaN(bn)) return asc ? bn - an : an - bn;
      return asc ? bv.localeCompare(av) : av.localeCompare(bv);
    });
    rows.forEach(r => table.tBodies[0].appendChild(r));
    table.dataset.sortCol = i; table.dataset.sortDir = asc ? 'desc' : 'asc';
  });
});
</script>
"""


def _df_to_html(df, no_data_key: str = "rpt_no_data") -> str:
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
    for _, row in df.iterrows():
        html += '<tr>' + ''.join(f'<td>{str(v)}</td>' for v in row.values) + '</tr>'
    html += '</tbody></table>'
    return html


class AuditHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None,
                 date_range: tuple = ('', '')):
        self._r = results
        self._df = df
        self._date_range = date_range

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
            + _SORT_JS + make_i18n_js() + '</body></html>'
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
                + _df_to_html(sec_df)
            )

        # Agent connectivity
        conn_df = m.get('connectivity_events')
        if conn_df is not None and not conn_df.empty:
            html += (
                '<h3 data-i18n="rpt_au_connectivity_title">Agent Connectivity Events</h3>'
                + _df_to_html(conn_df)
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
            + _df_to_html(m.get('recent'))
        )

        return html

    def _mod02_html(self):
        m = self._r.get('mod02', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        failed = m.get('failed_logins', 0)

        html = (
            '<p><span data-i18n="rpt_au_total_user">Total User Events:</span>'
            ' <b>' + str(m.get('total_user_events', 0)) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_failed_logins">Failed Logins:</span>'
            ' <b style="color:' + ('#c0392b' if failed > 0 else '#313638') + '">' + str(failed) + '</b></p>'
        )

        # Best practice note
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_users">'
            '<b>Illumio Best Practice:</b> Monitor login failures for patterns indicating '
            'brute-force or credential stuffing attacks. Investigate repeated failures from '
            'the same user or sudden spikes in authentication events.'
            '</div>'
        )

        # Per-user breakdown
        per_user = m.get('per_user')
        if per_user is not None and not per_user.empty:
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
            + _df_to_html(m.get('recent'))
        )

        return html

    def _mod03_html(self):
        m = self._r.get('mod03', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        prov_count = m.get('provision_count', 0)
        rule_count = m.get('rule_change_count', 0)

        html = (
            '<p><span data-i18n="rpt_au_total_policy">Total Policy Events:</span>'
            ' <b>' + str(m.get('total_policy_events', 0)) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_provisions">Provisions:</span>'
            ' <b>' + str(prov_count) + '</b>'
            ' &nbsp;|&nbsp; '
            '<span data-i18n="rpt_au_rule_changes">Rule Changes:</span>'
            ' <b>' + str(rule_count) + '</b></p>'
        )

        # Best practice note
        html += (
            '<div class="bp-box" data-i18n-html="rpt_au_bp_policy">'
            '<b>Illumio Best Practice:</b> Review rule_set and sec_rule changes for overly broad scopes '
            '(null HREF = All Applications/Environments/Locations). When sec_policy.create (provision) '
            'events occur, check workloads_affected — a high number may indicate unintended policy impact. '
            'Monitor sec_rule.delete events to detect unauthorized policy weakening.'
            '</div>'
        )

        # Provision events
        provisions = m.get('provisions')
        if provisions is not None and not provisions.empty:
            html += (
                '<h3 data-i18n="rpt_au_provision_title">Policy Provision Events</h3>'
                '<p class="note note-warn" data-i18n="rpt_au_provision_desc">'
                'Policy provisions push draft changes to active enforcement. '
                'Review for unintended scope or excessive workload impact.</p>'
                + _df_to_html(provisions)
            )

        # Per-user breakdown
        per_user = m.get('per_user')
        if per_user is not None and not per_user.empty:
            html += (
                '<h3 data-i18n="rpt_au_per_user_policy">Changes by User</h3>'
                + _df_to_html(per_user)
            )

        html += (
            '<h3 data-i18n="rpt_au_summary_type">Summary by Event Type</h3>'
            + _df_to_html(m.get('summary'))
        )

        html += (
            '<h3 data-i18n="rpt_au_recent">Recent Events (up to 50)</h3>'
            + _df_to_html(m.get('recent'))
        )

        return html
