"""
src/report/exporters/html_exporter.py
Exports a report results dict to a single self-contained HTML file.

Features:
- Embedded CSS (no external dependencies)
- Navigation sidebar linking to all 15 sections + Findings
- Tables with alternating row colours and severity colour coding
- Inline JavaScript for basic table sorting
- Embedded EN ↔ 繁體中文 language toggle (via report_i18n)
- Suitable for direct email attachment or browser viewing
"""
from __future__ import annotations

import datetime
import os
import logging
import pandas as pd

from .report_i18n import make_i18n_js, lang_btn_html, COL_I18N as _COL_I18N
from .report_css import build_css, TABLE_JS

logger = logging.getLogger(__name__)

_CSS = build_css('traffic')


def _fmt_bytes(b) -> str:
    """Convert raw byte count to human-readable string (B / KB / MB / GB / TB)."""
    try:
        b = float(b)
    except (TypeError, ValueError):
        return str(b) if b is not None else '—'
    if b < 0:
        return '—'
    if b >= 1024 ** 4:
        return f'{b / 1024 ** 4:.2f} TB'
    if b >= 1024 ** 3:
        return f'{b / 1024 ** 3:.2f} GB'
    if b >= 1024 ** 2:
        return f'{b / 1024 ** 2:.1f} MB'
    if b >= 1024:
        return f'{b / 1024:.1f} KB'
    return f'{int(b)} B'


def _fmt_bw(mbps) -> str:
    """Convert Mbps value to auto-scaled human-readable string (Mbps / Gbps / Tbps), 2 decimal places."""
    try:
        mbps = float(mbps)
    except (TypeError, ValueError):
        return str(mbps) if mbps is not None else '—'
    if mbps < 0:
        return '—'
    if mbps >= 1_000_000:
        return f'{mbps / 1_000_000:.2f} Tbps'
    if mbps >= 1_000:
        return f'{mbps / 1_000:.2f} Gbps'
    return f'{mbps:.2f} Mbps'


# Column name fragments that contain raw byte values and should be auto-formatted
_BYTE_COL_KEYWORDS = {'byte', 'bytes', 'total bytes', 'bytes total', 'bytes/conn'}

# Column name fragments that contain Mbps bandwidth values and should be auto-scaled
_BW_COL_KEYWORDS = {'bandwidth (mbps)', 'bandwidth(mbps)', 'bw (mbps)'}


def _cov_stat(label: str, value: str) -> str:
    return (
        '<div class="cov-stat">'
        f'<div class="cov-label">{label}</div>'
        f'<div class="cov-value">{value}</div>'
        '</div>'
    )


def _progress_bar(pct: float) -> str:
    pct = max(0.0, min(100.0, float(pct or 0)))
    color = 'var(--green-80)' if pct >= 80 else ('var(--gold-110)' if pct >= 50 else 'var(--red-80)')
    return (
        f'<div class="progress-bar">'
        f'<div class="progress-fill" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
    )


def _format_evidence(evidence: dict) -> str:
    """Convert evidence dict to readable pills, parsing Python literal strings where possible."""
    if not evidence:
        return ''
    import ast
    pills = []
    for k, v in evidence.items():
        label = k.replace('_', ' ').title()
        v_str = str(v)
        # Try to parse Python-literal dicts/lists for nicer display
        try:
            parsed = ast.literal_eval(v_str)
            if isinstance(parsed, dict):
                v_display = ', '.join(f'{pk}:{pv}' for pk, pv in list(parsed.items())[:5])
            elif isinstance(parsed, list):
                v_display = ', '.join(str(x)[:40] for x in parsed[:3])
                if len(parsed) > 3:
                    v_display += f' …+{len(parsed)-3}'
            else:
                v_display = v_str
        except (ValueError, SyntaxError):
            v_display = v_str
        pills.append(
            f'<div class="ev-pill">'
            f'<span class="ev-label">{label}</span>'
            f'<b>{v_display}</b>'
            f'</div>'
        )
    return '<div class="finding-evidence">' + ''.join(pills) + '</div>'


# Rule descriptions: human-readable explanation of what each built-in rule checks
_RULE_DESCRIPTIONS = {
    # ── Ransomware exposure ────────────────────────────────────────────────────
    'B001': ('Ransomware Critical Ports Not Blocked',
             'Checks for traffic on ransomware\'s primary attack ports (SMB 445, RPC 135, RDP 3389, WinRM 5985/5986) that is NOT blocked. These are the exact ports used in EternalBlue, NotPetya, and WannaCry-class attacks for network-wide lateral spread.'),
    'B002': ('Ransomware High-Risk Remote Access Allowed',
             'Detects allowed flows on secondary remote-access ports (TeamViewer 5938, VNC 5900, NetBIOS 137-139). Ransomware operators and APT groups use these for C2 persistence and remote control after initial compromise.'),
    'B003': ('Ransomware Ports in Test Mode — Block Not Active',
             'Detects medium-risk ports (SSH 22, NFS 2049, FTP 20/21, HTTP 80) showing as potentially_blocked. This means the segmentation rule exists but the workload is in visibility/test mode — the block is NOT enforced and traffic flows freely.'),
    # ── Policy & coverage gaps ─────────────────────────────────────────────────
    'B004': ('Unmanaged Source High Activity',
             'Counts flows from hosts not enrolled in the PCE. Unmanaged hosts have no VEN and therefore no micro-segmentation enforcement — they are outside the zero-trust boundary and represent uncontrolled attack surface.'),
    'B005': ('Low Policy Coverage',
             'Measures the percentage of observed flows with an active allow policy. Coverage below 30% means most traffic is uncontrolled — a sign that segmentation is in early stages and large attack surface remains exposed.'),
    'B009': ('Cross-Environment Flow Volume',
             'Tracks the number of flows crossing environment boundaries (e.g. Production → Development). Excessive cross-env traffic may indicate lateral movement from a compromised lower-security zone into production.'),
    # ── Anomalous behaviour ────────────────────────────────────────────────────
    'B006': ('Lateral Movement Fan-Out',
             'Detects source IPs that connect to an abnormally high number of distinct destinations on lateral movement ports. This fan-out pattern (one source → many destinations) is the hallmark of worm propagation and attacker pivoting after initial compromise.'),
    'B007': ('User Account Reaching Many Destinations',
             'Detects individual user accounts connecting to unusually many unique destination IPs. This may indicate a compromised account being used for automated reconnaissance, credential stuffing, or data staging before exfiltration.'),
    'B008': ('High Bandwidth Anomaly',
             'Flags individual flows exceeding the 95th percentile of byte volume in the dataset. Sudden high-volume transfers from unexpected sources are a key indicator of data staging, exfiltration, or unsanctioned large-scale backups.'),
    # ── Lateral movement — cleartext & legacy protocols ────────────────────────
    'L001': ('Cleartext Protocol in Use (Telnet / FTP)',
             'Detects any traffic on Telnet (23) or FTP (20/21). These protocols transmit credentials and data without encryption. Any attacker with network access can perform a man-in-the-middle or ARP poisoning attack to harvest passwords in plaintext — enabling instant credential reuse for lateral movement.'),
    'L002': ('Network Discovery Protocol Exposure',
             'Detects unblocked flows on broadcast/discovery protocols: NetBIOS (137/138), mDNS (5353), LLMNR (5355), SSDP (1900). Tools like Responder and Inveigh exploit these to perform hostname poisoning and capture NTLMv2 hashes without any authentication — then crack or relay those hashes for lateral movement.'),
    # ── Lateral movement — database exposure ───────────────────────────────────
    'L003': ('Database Port Accessible from Many App Tiers',
             'Checks whether database ports (MSSQL 1433, MySQL 3306, PostgreSQL 5432, Oracle 1521, MongoDB 27017, Redis 6379, Elasticsearch 9200) are reachable from many distinct application labels. Databases should only be reachable from their direct app tier. Wide exposure provides direct data access after a single lateral move.'),
    'L004': ('Cross-Environment Database Access',
             'Detects allowed database flows crossing environment boundaries (e.g. Dev app → Production database). Environment boundaries are the macro-segmentation layer. Breaching them allows an attacker in a low-security Dev environment to directly access Production data stores.'),
    # ── Lateral movement — identity infrastructure ──────────────────────────────
    'L005': ('Identity Infrastructure Wide Exposure',
             'Detects Kerberos (88), LDAP (389/636), and Global Catalog (3268/3269) traffic from many source applications. Active Directory is the domain\'s authentication authority. Excessive access enables domain enumeration (BloodHound), Kerberoasting, Golden/Silver Ticket attacks, and full domain takeover.'),
    # ── Lateral movement — graph-based blast radius ─────────────────────────────
    'L006': ('High Blast-Radius Lateral Path (Graph BFS)',
             'Uses BFS graph traversal on allowed lateral-port connections to find apps that can reach many others through a chain of pivots. High reachability = high blast radius. An attacker who compromises a top-ranked app can traverse the entire reachable subgraph — this is the MCP detect-lateral-movement-paths methodology.'),
    # ── Lateral movement — unmanaged pivot ──────────────────────────────────────
    'L007': ('Unmanaged Host Accessing Critical Services',
             'Detects unmanaged (non-PCE) hosts communicating on database, identity (Kerberos/LDAP), or Windows management ports to managed workloads. Unmanaged hosts have no VEN enforcement — they are outside zero-trust. If they can reach critical services, they represent uncontrolled lateral movement entry points.'),
    # ── Lateral movement — enforcement gap ──────────────────────────────────────
    'L008': ('Lateral Ports in Test Mode — Policy Not Enforced',
             'Identifies \'potentially_blocked\' flows on lateral movement ports. This means the policy rule exists but the destination workload is in visibility/test mode — the block is not active. These are live, traversable attack paths right now. The most common cause of "we had policies but still got breached" incidents.'),
    # ── Lateral movement — exfiltration pattern ─────────────────────────────────
    'L009': ('Data Exfiltration Pattern — Outbound to Unmanaged',
             'Detects managed workloads transferring significant data volume to unmanaged (external/unknown) destinations. This is the post-lateral-movement exfiltration phase: attacker has pivoted to a high-value host and is now staging or exfiltrating data to an external C2 or drop server outside PCE visibility.'),
    # ── Lateral movement — cross-env boundary break ──────────────────────────────
    'L010': ('Cross-Environment Lateral Port Access — Boundary Break',
             'CRITICAL: Detects lateral movement ports (SMB 445, RDP 3389, WinRM 5985/5986, RPC 135) allowed between different environments. Environment segmentation is the macro-security boundary. If lateral ports cross it, an attacker who compromises Dev/Test can directly pivot into Production using exactly the same techniques, bypassing all environment-level controls.'),
}


def _df_to_html(df: pd.DataFrame | None, severity_col: str | None = None,
                no_data_key: str = "rpt_no_data") -> str:
    if df is None or (hasattr(df, 'empty') and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">— No data —</p>'

    # Determine which columns contain raw byte values (auto-format them)
    byte_cols = {col for col in df.columns
                 if any(kw in col.lower() for kw in _BYTE_COL_KEYWORDS)}
    # Determine which columns contain Mbps bandwidth values (auto-scale units)
    bw_cols = {col for col in df.columns
               if any(kw in col.lower() for kw in _BW_COL_KEYWORDS)}

    html = '<table><thead><tr>'
    for col in df.columns:
        i18n_key = _COL_I18N.get(col)
        if i18n_key:
            html += f'<th data-i18n="{i18n_key}">{col}</th>'
        else:
            html += f'<th>{col}</th>'
    html += '</tr></thead><tbody>'
    for _, row in df.iterrows():
        html += '<tr>'
        for col, val in zip(df.columns, row.values):
            if severity_col and col == severity_col and str(val).upper() in (
                    'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'):
                html += f'<td><span class="badge badge-{str(val).upper()}">{val}</span></td>'
            elif col in byte_cols:
                html += f'<td>{_fmt_bytes(val)}</td>'
            elif col in bw_cols:
                html += f'<td>{_fmt_bw(val)}</td>'
            else:
                html += f'<td>{val}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html


class HtmlExporter:
    """Export report results to a single self-contained HTML file."""

    def __init__(self, results: dict):
        self._r = results

    def export(self, output_dir: str = 'reports') -> str:
        """Write HTML file and return full path."""
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        filename = f'Illumio_Traffic_Report_{ts}.html'
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self._build())
        logger.info(f"[HtmlExporter] Saved: {filepath}")
        return filepath

    def _build(self) -> str:
        mod12 = self._r.get('mod12', {})
        findings = self._r.get('findings', [])
        n_findings = str(len(findings))

        nav_html = (
            '<nav>'
            '<a href="#summary"><span data-i18n="rpt_tr_nav_summary">📊 Executive Summary</span></a>'
            '<a href="#overview"><span data-i18n="rpt_tr_nav_overview">1 Traffic Overview</span></a>'
            '<a href="#policy"><span data-i18n="rpt_tr_nav_policy">2 Policy Decisions</span></a>'
            '<a href="#uncovered"><span data-i18n="rpt_tr_nav_uncovered">3 Uncovered Flows</span></a>'
            '<a href="#ransomware"><span data-i18n="rpt_tr_nav_ransomware">4 Ransomware Exposure</span></a>'
            '<a href="#remote"><span data-i18n="rpt_tr_nav_remote">5 Remote Access</span></a>'
            '<a href="#user"><span data-i18n="rpt_tr_nav_user">6 User &amp; Process</span></a>'
            '<a href="#matrix"><span data-i18n="rpt_tr_nav_matrix">7 Cross-Label Matrix</span></a>'
            '<a href="#unmanaged"><span data-i18n="rpt_tr_nav_unmanaged">8 Unmanaged Hosts</span></a>'
            '<a href="#distribution"><span data-i18n="rpt_tr_nav_distribution">9 Traffic Distribution</span></a>'
            '<a href="#allowed"><span data-i18n="rpt_tr_nav_allowed">10 Allowed Traffic</span></a>'
            '<a href="#bandwidth"><span data-i18n="rpt_tr_nav_bandwidth">11 Bandwidth &amp; Volume</span></a>'
            '<a href="#readiness"><span data-i18n="rpt_tr_nav_readiness">13 Enforcement Readiness</span></a>'
            '<a href="#infrastructure"><span data-i18n="rpt_tr_nav_infrastructure">14 Infrastructure Scoring</span></a>'
            '<a href="#lateral"><span data-i18n="rpt_tr_nav_lateral">15 Lateral Movement</span></a>'
            '<a href="#findings"><span data-i18n="rpt_tr_nav_findings">🔍 Findings</span> (' + n_findings + ')</a>'
            '</nav>'
        )

        # Pre-compute nested blocks to avoid f-string quote conflicts
        kpi_cards = ''.join(
            '<div class="kpi-card"><div class="kpi-label">' + str(k['label']) + '</div>'
            '<div class="kpi-value">' + str(k['value']) + '</div></div>'
            for k in mod12.get('kpis', [])
        )
        key_findings_html = ''.join(
            '<p style="margin-bottom:8px"><span class="badge badge-' +
            kf.get('severity', 'INFO') + '">' + kf.get('severity', '') + '</span>&nbsp;' +
            kf.get('finding', '') + ' <em style="color:#718096">&rarr; ' +
            kf.get('action', '') + '</em></p>'
            for kf in mod12.get('key_findings', [])
        ) or '<p class="note" data-i18n="rpt_no_findings">No key findings.</p>'

        generated_at = mod12.get('generated_at', '')
        today_str = str(datetime.date.today())

        body = (
            '<section id="summary" class="card">'
            '<h1 data-i18n="rpt_tr_title">Illumio Traffic Flow Report</h1>'
            '<p style="color:#718096; margin-top:4px">'
            '<span data-i18n="rpt_generated">Generated:</span> ' + generated_at + '</p>'
            '<h2 data-i18n="rpt_key_metrics">Key Metrics</h2>'
            '<div class="kpi-grid">' + kpi_cards + '</div>'
            '<h2 data-i18n="rpt_key_findings">Key Findings</h2>' + key_findings_html +
            '</section>\n' +
            self._section('overview',     'rpt_tr_sec_overview',    '1 \u00b7 Traffic Overview',     self._mod01_html()) + '\n' +
            self._section('policy',       'rpt_tr_sec_policy',      '2 \u00b7 Policy Decisions',     self._mod02_html()) + '\n' +
            self._section('uncovered',    'rpt_tr_sec_uncovered',   '3 \u00b7 Uncovered Flows',      self._mod03_html()) + '\n' +
            self._section('ransomware',   'rpt_tr_sec_ransomware',  '4 \u00b7 Ransomware Exposure',  self._mod04_html()) + '\n' +
            self._section('remote',       'rpt_tr_sec_remote',      '5 \u00b7 Remote Access',        self._mod05_html()) + '\n' +
            self._section('user',         'rpt_tr_sec_user',        '6 \u00b7 User &amp; Process',   self._mod06_html()) + '\n' +
            self._section('matrix',       'rpt_tr_sec_matrix',      '7 \u00b7 Cross-Label Matrix',   self._mod07_html()) + '\n' +
            self._section('unmanaged',    'rpt_tr_sec_unmanaged',   '8 \u00b7 Unmanaged Hosts',      self._mod08_html()) + '\n' +
            self._section('distribution', 'rpt_tr_sec_distribution','9 \u00b7 Traffic Distribution', self._mod09_html()) + '\n' +
            self._section('allowed',      'rpt_tr_sec_allowed',     '10 \u00b7 Allowed Traffic',     self._mod10_html()) + '\n' +
            self._section('bandwidth',    'rpt_tr_sec_bandwidth',   '11 \u00b7 Bandwidth &amp; Volume', self._mod11_html()) + '\n' +
            self._section('readiness',    'rpt_tr_sec_readiness',   '13 \u00b7 Enforcement Readiness', self._mod13_html()) + '\n' +
            self._section('infrastructure','rpt_tr_sec_infrastructure','14 \u00b7 Infrastructure Scoring', self._mod14_html()) + '\n' +
            self._section('lateral',      'rpt_tr_sec_lateral',     '15 \u00b7 Lateral Movement',     self._mod15_html()) + '\n' +
            '<section id="findings" class="card">'
            '<h2><span data-i18n="rpt_tr_sec_findings">🔍 Security Findings</span> (' + n_findings + ')</h2>'
            + self._findings_html() +
            '</section>\n' +
            '<footer><span data-i18n="rpt_tr_footer">Illumio PCE Ops — Traffic Flow Report</span>'
            ' &middot; ' + today_str + '</footer>'
        )
        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>Illumio Traffic Report</title>' + _CSS + '</head>\n'
            '<body>' + lang_btn_html() + nav_html + '<main>' + body + '</main>'
            + TABLE_JS + make_i18n_js() + '</body></html>'
        )

    def _section(self, id_: str, i18n_key: str, title: str, content: str) -> str:
        return (
            f'<section id="{id_}" class="card">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f'{content}</section>'
        )

    def _mod01_html(self):
        m = self._r.get('mod01', {})
        kv_html = (
            '<tr><td><b><span data-i18n="rpt_tr_policy_coverage">Policy Coverage</span></b></td>'
            '<td>' + str(m.get('policy_coverage_pct', 0)) + '%</td></tr>'
            '<tr><td><b><span data-i18n="rpt_tr_flow_breakdown">Allowed / Blocked / Potential</span></b></td>'
            '<td>' + str(m.get('allowed_flows', 0)) + ' / ' + str(m.get('blocked_flows', 0)) + ' / ' +
            str(m.get('potentially_blocked_flows', 0)) + '</td></tr>'
            '<tr><td><b><span data-i18n="rpt_tr_total_data">Total Data</span></b></td>'
            '<td>' + _fmt_bytes(m.get('total_mb', 0) * 1024 * 1024) + '</td></tr>'
            '<tr><td><b><span data-i18n="rpt_tr_date_range">Date Range</span></b></td>'
            '<td>' + str(m.get('date_range', '')) + '</td></tr>'
        )
        return (
            '<table><tbody>' + kv_html + '</tbody></table>'
            '<h3 data-i18n="rpt_tr_top_ports">Top Ports</h3>'
            + _df_to_html(m.get('top_ports'))
        )

    def _mod02_html(self):
        m = self._r.get('mod02', {})
        out = _df_to_html(m.get('summary'))
        # Per-port coverage table
        pc = m.get('port_coverage')
        if pc is not None and hasattr(pc, 'empty') and not pc.empty:
            out += '<h3 data-i18n="rpt_tr_port_coverage">Per-Port Coverage</h3>' + _df_to_html(pc)
        for d in ('allowed', 'blocked', 'potentially_blocked'):
            dm = m.get(d, {})
            if not isinstance(dm, dict) or dm.get('count', 0) == 0:
                continue
            inb = dm.get('inbound_count', 0)
            outb = dm.get('outbound_count', 0)
            pct = dm.get('pct_of_total', 0)
            out += (
                '<h3>' + d.replace('_', ' ').upper() + f' ({pct}% of total)'
                f' &nbsp;·&nbsp; ↓ Inbound: {inb} &nbsp;·&nbsp; ↑ Outbound: {outb}</h3>'
                '<h4 data-i18n="rpt_tr_top_app_flows">Top App Flows</h4>'
                + _df_to_html(dm.get('top_app_flows'))
            )
            if inb > 0:
                out += '<h4 data-i18n="rpt_tr_top_inbound_ports">Top Inbound Ports</h4>' + _df_to_html(dm.get('top_inbound_ports'))
            if outb > 0:
                out += '<h4 data-i18n="rpt_tr_top_outbound_ports">Top Outbound Ports</h4>' + _df_to_html(dm.get('top_outbound_ports'))
        return out

    def _mod03_html(self):
        m = self._r.get('mod03', {})
        cov = m.get('coverage_pct', 0)
        inb_cov = m.get('inbound_coverage_pct')
        outb_cov = m.get('outbound_coverage_pct')
        stats = (
            '<div class="coverage-grid">'
            + _cov_stat('<span data-i18n="rpt_tr_overall_coverage">Overall Coverage</span>', str(cov) + '%')
            + (_cov_stat('<span data-i18n="rpt_tr_inbound_coverage">Inbound Coverage</span>', str(inb_cov) + '%') if inb_cov is not None else '')
            + (_cov_stat('<span data-i18n="rpt_tr_outbound_coverage">Outbound Coverage</span>', str(outb_cov) + '%') if outb_cov is not None else '')
            + _cov_stat('<span data-i18n="rpt_col_uncovered_flows">Uncovered Flows</span>', str(m.get('total_uncovered', 0)))
            + '</div>'
            + _progress_bar(cov)
        )
        out = (
            stats
            + '<h3 data-i18n="rpt_tr_top_uncovered">Top Uncovered Flows</h3>'
            + _df_to_html(m.get('top_flows'))
        )
        up = m.get('uncovered_ports')
        if up is not None and hasattr(up, 'empty') and not up.empty:
            out += '<h3 data-i18n="rpt_tr_port_gaps">Port Gap Ranking</h3>' + _df_to_html(up)
        us = m.get('uncovered_services')
        if us is not None and hasattr(us, 'empty') and not us.empty:
            out += '<h3 data-i18n="rpt_tr_service_gaps">Uncovered Services (App + Port)</h3>' + _df_to_html(us)
        out += '<h3 data-i18n="rpt_tr_by_rec">By Recommendation Category</h3>' + _df_to_html(m.get('by_recommendation'))
        return out

    def _mod04_html(self):
        m = self._r.get('mod04', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        out = ('<p><span data-i18n="rpt_tr_risk_flows">Total risk flows:</span> <b>'
               + str(m.get('risk_flows_total', 0)) + '</b></p>')

        # Part E — Investigation targets (allowed traffic on critical/high ports)
        part_e = m.get('part_e_investigation')
        if part_e is not None and hasattr(part_e, 'empty') and not part_e.empty:
            out += (
                '<div style="background:#fff3cd;border-left:4px solid var(--gold);'
                'padding:12px 16px;margin:12px 0;border-radius:4px">'
                '<b><span data-i18n="rpt_tr_investigation_title">⚠ 需要調查的目標主機</span></b><br>'
                '<span style="font-size:12px" data-i18n="rpt_tr_investigation_desc">'
                '以下目標主機在重大或高風險通訊埠上有被允許的流量，應進行驗證或考慮封鎖。'
                '</span>'
                '</div>'
                + _df_to_html(part_e, 'Risk Level')
            )
        else:
            out += (
                '<div style="background:#d4edda;border-left:4px solid var(--green-80);'
                'padding:12px 16px;margin:12px 0;border-radius:4px">'
                '<b data-i18n="rpt_tr_no_investigation">✅ 未發現重大/高風險通訊埠上的允許流量。</b>'
                '</div>'
            )

        out += (
            '<h3 data-i18n="rpt_tr_risk_summary">Risk Level Summary</h3>'
            + _df_to_html(m.get('part_a_summary'), 'Risk Level') +
            '<h3 data-i18n="rpt_tr_per_port">Per-Port Detail</h3>'
            + _df_to_html(m.get('part_b_per_port'), 'Risk Level') +
            '<h3 data-i18n="rpt_tr_host_exposure">Host Exposure Ranking</h3>'
            + '<p class="note" style="font-size:11px" data-i18n="rpt_tr_host_exposure_note">'
            '依接觸風險通訊埠數量排序的目標主機，包含所有決策（含阻斷）。</p>'
            + _df_to_html(m.get('part_d_host_exposure'))
        )
        return out

    def _mod05_html(self):
        m = self._r.get('mod05', {})
        if not isinstance(m, dict) or m.get('total_lateral_flows', 0) == 0:
            return '<p class="note" data-i18n="rpt_no_lateral">No lateral movement traffic found.</p>'
        return (
            _df_to_html(m.get('by_service')) +
            '<h3 data-i18n="rpt_tr_top_talkers">Top Talkers</h3>'
            + _df_to_html(m.get('top_talkers'))
        )

    def _mod06_html(self):
        m = self._r.get('mod06', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        out = ''
        if m.get('user_data_available'):
            out += '<h3 data-i18n="rpt_tr_top_users">Top Users</h3>' + _df_to_html(m.get('top_users'))
        if m.get('process_data_available'):
            out += '<h3 data-i18n="rpt_tr_top_processes">Top Processes</h3>' + _df_to_html(m.get('top_processes'))
        return out or '<p class="note" data-i18n="rpt_no_user_proc">No user/process data.</p>'

    def _mod07_html(self):
        m = self._r.get('mod07', {})
        out = ''
        for key, data in m.get('matrices', {}).items():
            out += '<h3><span data-i18n="rpt_tr_label_key">Label Key:</span> ' + key.upper() + '</h3>'
            if 'note' in data:
                out += f'<p class="note">{data["note"]}</p>'
            else:
                kv = (f'<span data-i18n="rpt_tr_same_value">Same-value:</span> {data.get("same_value_flows",0)} · '
                      f'<span data-i18n="rpt_tr_cross_value">Cross-value:</span> {data.get("cross_value_flows",0)}')
                out += f'<p>{kv}</p>{_df_to_html(data.get("top_cross_pairs"))}'
        return out or '<p class="note" data-i18n="rpt_no_matrix">No label matrix data.</p>'

    def _mod08_html(self):
        m = self._r.get('mod08', {})
        out = (
            '<div class="coverage-grid">'
            + _cov_stat('<span data-i18n="rpt_tr_unmanaged_flow_stat">Unmanaged Flows</span>', str(m.get('unmanaged_flow_count', 0)) + ' (' + str(m.get('unmanaged_pct', 0)) + '%)')
            + _cov_stat('<span data-i18n="rpt_tr_unique_unmanaged_src">Unique Unmanaged Src</span>', str(m.get('unique_unmanaged_src', 0)))
            + _cov_stat('<span data-i18n="rpt_tr_unique_unmanaged_dst">Unique Unmanaged Dst</span>', str(m.get('unique_unmanaged_dst', 0)))
            + '</div>'
            '<h3 data-i18n="rpt_tr_top_unmanaged">Top Unmanaged Sources</h3>'
            + _df_to_html(m.get('top_unmanaged_src'))
        )
        pa = m.get('per_dst_app')
        if pa is not None and hasattr(pa, 'empty') and not pa.empty:
            out += '<h3 data-i18n="rpt_tr_managed_apps_unmanaged">Managed Apps Receiving Unmanaged Traffic</h3>' + _df_to_html(pa)
        pp = m.get('per_port_proto')
        if pp is not None and hasattr(pp, 'empty') and not pp.empty:
            out += '<h3 data-i18n="rpt_tr_exposed_ports_proto">Exposed Ports / Protocols</h3>' + _df_to_html(pp)
        sp = m.get('src_port_detail')
        if sp is not None and hasattr(sp, 'empty') and not sp.empty:
            out += '<h3 data-i18n="rpt_tr_unmanaged_src_port">Unmanaged Source × Port Detail</h3>' + _df_to_html(sp)
        mh = m.get('managed_hosts_targeted_by_unmanaged')
        if mh is not None and hasattr(mh, 'empty') and not mh.empty:
            out += '<h3 data-i18n="rpt_tr_managed_targeted">Managed Hosts Targeted by Unmanaged Sources</h3>' + _df_to_html(mh)
        return out

    def _mod09_html(self):
        m = self._r.get('mod09', {})
        return (
            '<h3 data-i18n="rpt_tr_port_dist">Port Distribution</h3>'
            + _df_to_html(m.get('port_distribution')) +
            '<h3 data-i18n="rpt_tr_proto_dist">Protocol Distribution</h3>'
            + _df_to_html(m.get('proto_distribution'))
        )

    def _mod10_html(self):
        m = self._r.get('mod10', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        return (
            _df_to_html(m.get('top_app_flows')) +
            '<h3><span data-i18n="rpt_tr_audit_flags">Audit Flags</span> (' +
            str(m.get('audit_flag_count', 0)) + ')</h3>'
            + _df_to_html(m.get('audit_flags'))
        )

    def _mod11_html(self):
        m = self._r.get('mod11', {})
        if not m.get('bytes_data_available', False):
            return f'<p class="note">{m.get("note","No byte data.")}</p>'

        max_bw = m.get('max_bandwidth_mbps')
        avg_bw = m.get('avg_bandwidth_mbps')
        p95_bw = m.get('p95_bandwidth_mbps')

        out = '<div class="coverage-grid">'
        out += _cov_stat('<span data-i18n="rpt_tr_total_volume">Total Volume</span>',
                         _fmt_bytes(m.get('total_bytes', 0)))
        if max_bw is not None:
            out += _cov_stat('<span data-i18n="rpt_tr_max_bw">Max Bandwidth</span>',
                             _fmt_bw(max_bw))
        if avg_bw is not None:
            out += _cov_stat('<span data-i18n="rpt_tr_avg_bw">Avg Bandwidth</span>',
                             _fmt_bw(avg_bw))
        if p95_bw is not None:
            out += _cov_stat('<span data-i18n="rpt_tr_p95_bw">P95 Bandwidth</span>',
                             _fmt_bw(p95_bw))
        out += '</div>'

        out += ('<h3 data-i18n="rpt_tr_top_by_bytes">Top by Total Bytes</h3>'
                + _df_to_html(m.get('top_by_bytes')))

        tb = m.get('top_bandwidth')
        if tb is not None and hasattr(tb, 'empty') and not tb.empty:
            out += ('<h3 data-i18n="rpt_tr_top_by_bw">Top by Bandwidth (Mbps)</h3>'
                    + _df_to_html(tb))

        anom = m.get('byte_ratio_anomalies')
        if anom is not None and hasattr(anom, 'empty') and not anom.empty:
            threshold = m.get('anomaly_threshold_bytes_per_conn')
            thresh_str = (f' &nbsp;<span style="font-weight:400;font-size:11px;color:var(--slate-50)">'
                          f'P95 ≥ {_fmt_bytes(threshold)}/conn</span>'
                          if threshold else '')
            out += (
                f'<h3><span data-i18n="rpt_tr_anomalies">Anomalies (High Bytes/Conn)</span>'
                f'{thresh_str}</h3>'
                '<p class="note" style="font-size:11px" data-i18n="rpt_tr_anomalies_note">'
                '每連線傳輸量高於 P95 的流量（僅計算連線數 &gt; 1），可能為大量傳輸或資料外洩候選項目。'
                '</p>'
                + _df_to_html(anom)
            )

        return out

    def _findings_html(self):
        from src.report.exporters.report_i18n import STRINGS as _S
        findings = self._r.get('findings', [])
        if not findings:
            en_msg = _S.get('rpt_no_findings_detail', {}).get('en', '')
            return f'<p class="note" data-i18n="rpt_no_findings_detail">{en_msg}</p>'

        from collections import Counter, defaultdict
        counts = Counter(f.severity for f in findings)
        sev_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

        # ── Severity summary bar ──────────────────────────────────────────────
        sev_html = '<div class="sev-summary">'
        for sev in sev_order:
            n = counts.get(sev, 0)
            sev_html += (
                f'<div class="sev-box">'
                f'<div><span class="badge badge-{sev}">{sev}</span></div>'
                f'<div class="sev-count">{n}</div>'
                f'</div>'
            )
        sev_html += '</div>'

        # ── Group by category ─────────────────────────────────────────────────
        by_cat: dict[str, list] = defaultdict(list)
        for f in sorted(findings, key=lambda x: (x.severity_rank, x.rule_id)):
            by_cat[f.category].append(f)

        cards_html = ''
        for cat, cat_findings in by_cat.items():
            # Look up bilingual category strings from report_i18n.STRINGS
            cat_key = cat.lower()
            name_key = f'rpt_cat_{cat_key}_name'
            desc_key = f'rpt_cat_{cat_key}_desc'
            cat_name_en = _S.get(name_key, {}).get('en', cat)
            cat_desc_en = _S.get(desc_key, {}).get('en', '')
            cards_html += (
                f'<div class="cat-group">'
                f'<h3 style="margin-bottom:6px;" data-i18n="{name_key}">{cat_name_en}</h3>'
                f'<p style="font-size:12px;color:var(--slate-50);margin-bottom:14px;"'
                f' data-i18n="{desc_key}">{cat_desc_en}</p>'
            )
            for f in cat_findings:
                _rule_title, rule_how = _RULE_DESCRIPTIONS.get(f.rule_id, (f.rule_name, ''))
                evidence_html = _format_evidence(f.evidence)
                cards_html += (
                    f'<div class="finding-card sev-{f.severity}">'
                    f'<div class="finding-header">'
                    f'<span class="badge badge-{f.severity}">{f.severity}</span>'
                    f'<span class="finding-rule-id">{f.rule_id}</span>'
                    f'<span class="finding-title">{f.rule_name}</span>'
                    f'</div>'
                )
                if rule_how:
                    how_key = f'rpt_rule_{f.rule_id}_how'
                    how_en = _S.get(how_key, {}).get('en', rule_how)
                    check_label_en = _S.get('rpt_rule_check_label', {}).get('en', 'What this rule checks:')
                    cards_html += (
                        f'<p style="font-size:11px;color:var(--slate-50);margin-bottom:8px;">'
                        f'<b data-i18n="rpt_rule_check_label">{check_label_en}</b>'
                        f' <span data-i18n="{how_key}">{how_en}</span></p>'
                    )
                rec_label_en = _S.get('rpt_recommendation_label', {}).get('en', 'Recommendation:')
                cards_html += (
                    f'<p class="finding-desc">{f.description}</p>'
                    + evidence_html
                    + f'<div class="finding-rec">'
                    f'<b data-i18n="rpt_recommendation_label">{rec_label_en}</b> '
                    f'{f.recommendation}</div>'
                    f'</div>'
                )
            cards_html += '</div>'

        return sev_html + cards_html

    def _mod13_html(self):
        m = self._r.get('mod13', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'
        score = m.get('total_score', 0)
        grade = m.get('grade', '?')
        grade_color = {'A': '#22C55E', 'B': '#84CC16', 'C': '#EAB308',
                       'D': '#F97316', 'F': '#EF4444'}.get(grade, '#6B7280')
        factor_table = m.get('factor_table')
        recommendations = m.get('recommendations')
        score_bar = _progress_bar(score)
        html = (
            f'<div style="display:flex;align-items:center;gap:24px;margin-bottom:16px;">'
            f'<div style="font-size:48px;font-weight:700;color:{grade_color};">{grade}</div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:13px;color:var(--slate-50);margin-bottom:4px;"><span data-i18n="rpt_tr_readiness_score">Enforcement Readiness Score:</span> <b>{score}/100</b></div>'
            f'{score_bar}'
            f'</div></div>'
            + '<h4 data-i18n="rpt_tr_score_breakdown">Score Breakdown by Factor</h4>'
            + _df_to_html(factor_table)
        )
        if recommendations is not None and not recommendations.empty:
            html += '<h4 data-i18n="rpt_tr_remediation_rec">Remediation Recommendations</h4>' + _df_to_html(recommendations)
        return html

    def _mod14_html(self):
        m = self._r.get('mod14', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'
        html = (
            f'<p><span data-i18n="rpt_tr_apps_analysed">Applications analysed:</span> <b>{m.get("total_apps", 0)}</b> · '
            f'<span data-i18n="rpt_tr_comm_edges">Communication edges:</span> <b>{m.get("total_edges", 0)}</b></p>'
        )
        role_summary = m.get('role_summary')
        if role_summary is not None and not role_summary.empty:
            html += '<h4 data-i18n="rpt_tr_role_distribution">Role Distribution</h4>' + _df_to_html(role_summary)
        hub_apps = m.get('hub_apps')
        if hub_apps is not None and not hub_apps.empty:
            html += '<h4 data-i18n="rpt_tr_hub_apps">Hub Applications (High Blast Radius)</h4>' + _df_to_html(hub_apps)
        top_apps = m.get('top_apps')
        if top_apps is not None and not top_apps.empty:
            html += '<h4 data-i18n="rpt_tr_top_apps_infra">Top Applications by Infrastructure Score</h4>' + _df_to_html(top_apps)
        top_edges = m.get('top_edges')
        if top_edges is not None and not top_edges.empty:
            html += '<h4 data-i18n="rpt_tr_top_comm_paths">Top Communication Paths (by Volume)</h4>' + _df_to_html(top_edges)
        return html

    def _mod15_html(self):
        m = self._r.get('mod15', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'
        total = m.get('total_lateral_flows', 0)
        pct = m.get('lateral_pct', 0)
        html = (f'<p><span data-i18n="rpt_tr_lateral_flows">Lateral movement port flows:</span> '
                f'<b>{total:,}</b> ({pct}% <span data-i18n="rpt_tr_lateral_pct">of all flows</span>)</p>')
        service_summary = m.get('service_summary')
        if service_summary is not None and not service_summary.empty:
            html += '<h4 data-i18n="rpt_tr_lateral_by_service">Lateral Port Activity by Service</h4>' + _df_to_html(service_summary)
        fan_out = m.get('fan_out_sources')
        if fan_out is not None and not fan_out.empty:
            html += '<h4 data-i18n="rpt_tr_fan_out">Fan-out Sources (Potential Scanner / Worm)</h4>' + _df_to_html(fan_out)
        allowed_lateral = m.get('allowed_lateral_flows')
        if allowed_lateral is not None and not allowed_lateral.empty:
            html += '<h4 data-i18n="rpt_tr_allowed_lateral">Explicitly Allowed Lateral Flows (Highest Risk)</h4>' + _df_to_html(allowed_lateral)
        source_risk = m.get('source_risk_scores')
        if source_risk is not None and not source_risk.empty:
            html += '<h4 data-i18n="rpt_tr_top_risk_sources">Top High-Risk Sources</h4>' + _df_to_html(source_risk)
        app_chains = m.get('app_chains')
        if app_chains is not None and not app_chains.empty:
            html += '<h4 data-i18n="rpt_tr_app_chains">Lateral Movement App Chains (BFS Paths)</h4>' + _df_to_html(app_chains)
        return html
