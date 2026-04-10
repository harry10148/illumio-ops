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

from .report_i18n import STRINGS, make_i18n_js, lang_btn_html, COL_I18N as _COL_I18N
from .report_css import build_css, TABLE_JS
from .table_renderer import render_df_table

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
        return f'<p class="note" data-i18n="{no_data_key}">No data</p>'

    # Determine which columns contain raw byte values (auto-format them)
    byte_cols = {col for col in df.columns
                 if any(kw in col.lower() for kw in _BYTE_COL_KEYWORDS)}
    # Determine which columns contain Mbps bandwidth values (auto-scale units)
    bw_cols = {col for col in df.columns
               if any(kw in col.lower() for kw in _BW_COL_KEYWORDS)}

    def _render_cell(col, val, _row):
        if severity_col and col == severity_col and str(val).upper() in (
                'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'):
            return f'<span class="badge badge-{str(val).upper()}">{val}</span>'
        if col in byte_cols:
            return _fmt_bytes(val)
        if col in bw_cols:
            return _fmt_bw(val)
        return '' if val is None else str(val)

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
    )


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
            '<a href="#findings"><span data-i18n="rpt_tr_nav_findings">Findings</span> (' + n_findings + ')</a>'
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
        attack_summary_html = self._attack_summary_html(mod12)

        generated_at = mod12.get('generated_at', '')
        today_str = str(datetime.date.today())
        total_flows = self._r.get('mod01', {}).get('total_flows', 0)
        summary_pills = (
            '<div class="summary-pill-row">'
            f'<div class="summary-pill"><span class="summary-pill-label">{STRINGS["rpt_pill_flows"]["en"]}</span><span class="summary-pill-value">{total_flows}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{STRINGS["rpt_pill_findings"]["en"]}</span><span class="summary-pill-value">{n_findings}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{STRINGS["rpt_pill_focus"]["en"]}</span><span class="summary-pill-value">{STRINGS["rpt_focus_traffic"]["en"]}</span></div>'
            '</div>'
        )

        body = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top"><div class="report-kicker" data-i18n="rpt_kicker_traffic">Traffic Analytics Report</div>'
            '<h1 data-i18n="rpt_tr_title">Illumio Traffic Flow Report</h1>'
            '<p class="report-subtitle">'
            '<span data-i18n="rpt_generated">Generated:</span> ' + generated_at + '</p></div>'
            + summary_pills +
            '<h2 data-i18n="rpt_key_metrics">Key Metrics</h2>'
            '<div class="kpi-grid">' + kpi_cards + '</div>'
            '<h2 data-i18n="rpt_key_findings">Key Findings</h2>' + key_findings_html +
            attack_summary_html +
            '</section>\n' +
            self._section('overview', 'rpt_tr_sec_overview', '1 \u00b7 Traffic Overview', self._mod01_html(), '先從整體流量規模、Policy 覆蓋率與熱門通訊埠建立基準視角，方便後續判讀各模組結果。') + '\n' +
            self._section('policy', 'rpt_tr_sec_policy', '2 \u00b7 Policy Decisions', self._mod02_html(), '拆解 Allow、Blocked 與 Potentially Blocked 的比例與細節，用來判斷目前 Policy 的實際落地程度。') + '\n' +
            self._section('uncovered', 'rpt_tr_sec_uncovered', '3 \u00b7 Uncovered Flows', self._mod03_html(), '聚焦尚未被有效 Policy 覆蓋的流量，協助找出應優先補強的服務與通訊方向。') + '\n' +
            self._section('ransomware', 'rpt_tr_sec_ransomware', '4 \u00b7 Ransomware Exposure', self._mod04_html(), '檢查與勒索軟體常見攻擊鏈相關的高風險通訊埠、允許流量與主機曝露情況。') + '\n' +
            self._section('remote', 'rpt_tr_sec_remote', '5 \u00b7 Remote Access', self._mod05_html(), '整理與遠端管理或橫向擴散相關的服務活動，協助區分日常維運流量與敏感連線。') + '\n' +
            self._section('user', 'rpt_tr_sec_user', '6 \u00b7 User &amp; Process', self._mod06_html(), '從使用者與程序視角補充流量背景，協助判斷這些連線是否符合既有操作模式。') + '\n' +
            self._section('matrix', 'rpt_tr_sec_matrix', '7 \u00b7 Cross-Label Matrix', self._mod07_html(), '以 Label 維度觀察跨群組互通情況，適合用來找出原本不應頻繁互動的區段。') + '\n' +
            self._section('unmanaged', 'rpt_tr_sec_unmanaged', '8 \u00b7 Unmanaged Hosts', self._mod08_html(), '盤點未受 VEN 管理的主機流量，這些主機通常位於可視性與控管邊界之外。') + '\n' +
            self._section('distribution', 'rpt_tr_sec_distribution','9 \u00b7 Traffic Distribution', self._mod09_html(), '觀察整體流量在通訊埠與協定上的分佈，快速辨識高集中度或異常偏高的類型。') + '\n' +
            self._section('allowed', 'rpt_tr_sec_allowed', '10 \u00b7 Allowed Traffic', self._mod10_html(), '聚焦目前被明確允許的流量，確認哪些是業務必要路徑，哪些則應再做稽核。') + '\n' +
            self._section('bandwidth', 'rpt_tr_sec_bandwidth', '11 \u00b7 Bandwidth &amp; Volume', self._mod11_html(), '從頻寬與資料量角度檢視高傳輸流量，用來辨識大型備份、批次作業或疑似資料外流。') + '\n' +
            self._section('readiness', 'rpt_tr_sec_readiness', '13 \u00b7 Enforcement Readiness', self._mod13_html(), '將多個訊號彙整成 readiness 分數，協助評估是否適合提高 enforcement 強度。') + '\n' +
            self._section('infrastructure','rpt_tr_sec_infrastructure','14 \u00b7 Infrastructure Scoring', self._mod14_html(), '從應用通訊關係辨識關鍵節點與高影響範圍的基礎架構角色。') + '\n' +
            self._section('lateral', 'rpt_tr_sec_lateral', '15 \u00b7 Lateral Movement', self._mod15_html(), '專門觀察與橫向移動有關的路徑、服務與來源，協助辨識擴散風險。') + '\n' +
            '<section id="findings" class="card">'
            '<h2><span data-i18n="rpt_tr_sec_findings">Security Findings</span> (' + n_findings + ')</h2>'
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

    def _section(self, id_: str, i18n_key: str, title: str, content: str, intro: str = '') -> str:
        intro_html = f'<p class="section-intro">{intro}</p>' if intro else ''
        return (
            f'<section id="{id_}" class="card">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f'{intro_html}{content}</section>'
        )

    def _subnote(self, text: str) -> str:
        return f'<p class="note" style="font-size:12px;">{text}</p>'

    def _attack_summary_html(self, mod12: dict) -> str:
        def _rows(section_items):
            if not section_items:
                return '<p class="note">No data</p>'
            return ''.join(
                '<p style="margin-bottom:8px"><span class="badge badge-' +
                str(item.get('severity', 'INFO')) + '">' + str(item.get('severity', 'INFO')) +
                '</span>&nbsp;' + str(item.get('finding', '')) +
                (('<br><span style="color:#718096;font-size:12px;">' + str(item.get('finding_zh', '')) + '</span>') if item.get('finding_zh') else '') +
                ' <em style="color:#718096">&rarr; ' + str(item.get('action', '')) + '</em>' +
                (('<br><span style="color:#718096;font-size:12px;"><em>&rarr; ' + str(item.get('action_zh', '')) + '</em></span>') if item.get('action_zh') else '') +
                '</p>'
                for item in section_items[:3]
            )

        action_matrix = mod12.get('action_matrix', []) or []
        action_html = ''.join(
            '<p style="margin-bottom:8px"><b>' + str(item.get('action_code', '')) + '</b>: ' +
            str(item.get('action', '')) +
            (('<br><span style="color:#718096;font-size:12px;">' + str(item.get('action_zh', '')) + '</span>') if item.get('action_zh') else '') +
            '</p>'
            for item in action_matrix[:3]
        ) or '<p class="note">No data</p>'

        return (
            '<h2 data-i18n="rpt_tr_attack_summary">Attack Summary</h2>'
            '<h3 data-i18n="rpt_tr_boundary_breaches">Boundary Breaches</h3>' + _rows(mod12.get('boundary_breaches', [])) +
            '<h3 data-i18n="rpt_tr_suspicious_pivot_behavior">Suspicious Pivot Behavior</h3>' + _rows(mod12.get('suspicious_pivot_behavior', [])) +
            '<h3 data-i18n="rpt_tr_blast_radius">Blast Radius</h3>' + _rows(mod12.get('blast_radius', [])) +
            '<h3 data-i18n="rpt_tr_blind_spots">Blind Spots</h3>' + _rows(mod12.get('blind_spots', [])) +
            '<h3 data-i18n="rpt_tr_action_matrix">Action Matrix</h3>' + action_html
        )

    def _mod01_summary_table(self, mod01: dict) -> str:
        df = pd.DataFrame(
            [
                {"Metric": "Policy Coverage", "Value": f"{mod01.get('policy_coverage_pct', 0)}%"},
                {
                    "Metric": "Allowed / Blocked / Potential",
                    "Value": (
                        f"{mod01.get('allowed_flows', 0)} / "
                        f"{mod01.get('blocked_flows', 0)} / "
                        f"{mod01.get('potentially_blocked_flows', 0)}"
                    ),
                },
                {"Metric": "Total Data", "Value": _fmt_bytes(mod01.get('total_mb', 0) * 1024 * 1024)},
                {"Metric": "Date Range", "Value": str(mod01.get('date_range', ''))},
            ]
        )
        return render_df_table(
            df,
            col_i18n={},
        )

    def _side_by_side_tables(self, left_title: str, left_html: str, right_title: str, right_html: str) -> str:
        return (
            '<div class="dual-grid">'
            f'<div>{left_title}{left_html}</div>'
            f'<div>{right_title}{right_html}</div>'
            '</div>'
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
            self._subnote('這張摘要表先交代流量規模、Policy 覆蓋率與觀測期間，方便你建立本次報表的整體背景。')
            + self._mod01_summary_table(m)
            + self._subnote('熱門通訊埠表可快速看出目前環境最常出現的服務，並判斷是否有不符合預期的活動。')
            + '<h3 data-i18n="rpt_tr_top_ports">Top Ports</h3>'
            + _df_to_html(m.get('top_ports'))
        )

    def _mod02_html(self):
        m = self._r.get('mod02', {})
        out = self._subnote('先看整體決策分佈，理解目前流量有多少被 Allow、Blocked 或仍停留在 Potentially Blocked。') + _df_to_html(m.get('summary'))
        # Per-port coverage table
        pc = m.get('port_coverage')
        if pc is not None and hasattr(pc, 'empty') and not pc.empty:
            out += self._subnote('各通訊埠覆蓋率可用來找出哪些服務已具備較完整的 Policy，哪些仍有明顯缺口。') + '<h3 data-i18n="rpt_tr_port_coverage">Per-Port Coverage</h3>' + _df_to_html(pc)
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
            status = {
                'allowed': 'ALLOWED',
                'blocked': 'BLOCKED',
                'potentially_blocked': 'POTENTIAL',
            }.get(d, d.upper())
            out += self._side_by_side_tables(
                f'<h4>Top Inbound Ports ({status})</h4>',
                _df_to_html(dm.get('top_inbound_ports')),
                f'<h4>Top Outbound Ports ({status})</h4>',
                _df_to_html(dm.get('top_outbound_ports')),
            )
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
            + self._subnote('未覆蓋流量排行用來指出目前最需要補 Policy 的流向，通常應優先處理量大或敏感度高的服務。')
            + '<h3 data-i18n="rpt_tr_top_uncovered">Top Uncovered Flows</h3>'
            + _df_to_html(m.get('top_flows'))
        )
        up = m.get('uncovered_ports')
        if up is not None and hasattr(up, 'empty') and not up.empty:
            out += self._subnote('通訊埠缺口排行有助於從服務面向盤點缺口，適合直接轉成補強清單。') + '<h3 data-i18n="rpt_tr_port_gaps">Port Gap Ranking</h3>' + _df_to_html(up)
        us = m.get('uncovered_services')
        if us is not None and hasattr(us, 'empty') and not us.empty:
            out += self._subnote('未覆蓋服務把應用與通訊埠綁在一起看，更適合做為後續 Policy 設計的輸入。') + '<h3 data-i18n="rpt_tr_service_gaps">Uncovered Services (App + Port)</h3>' + _df_to_html(us)
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
            self._subnote('先看各服務在遠端管理情境下的活動量，判斷哪些協定最常被拿來做維運或遠端連線。')
            + _df_to_html(m.get('by_service'))
            + self._subnote('Top Talkers 用來找出最常參與這些連線的來源或目的端，適合核對是否為已知管理節點。')
            + '<h3 data-i18n="rpt_tr_top_talkers">Top Talkers</h3>'
            + _df_to_html(m.get('top_talkers'))
        )

    def _mod06_html(self):
        m = self._r.get('mod06', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        out = ''
        if m.get('user_data_available'):
            out += self._subnote('使用者排行用來辨識哪些帳號最常出現在這批流量中，可協助判斷是否符合既有操作模式。') + '<h3 data-i18n="rpt_tr_top_users">Top Users</h3>' + _df_to_html(m.get('top_users'))
        if m.get('process_data_available'):
            out += self._subnote('程序排行可協助釐清實際發起連線的程式，方便區分正常服務與值得追查的背景程序。') + '<h3 data-i18n="rpt_tr_top_processes">Top Processes</h3>' + _df_to_html(m.get('top_processes'))
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
            + self._subnote('先看非受管流量的整體規模，再往下確認哪些來源最活躍，以及它們主要打到哪些受管服務。')
            + '<h3 data-i18n="rpt_tr_top_unmanaged">Top Unmanaged Sources</h3>'
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
            self._subnote('流量分佈表主要用來看整體結構，適合確認是否存在過度集中的服務或突然升高的協定活動。')
            + '<h3 data-i18n="rpt_tr_port_dist">Port Distribution</h3>'
            + _df_to_html(m.get('port_distribution')) +
            '<h3 data-i18n="rpt_tr_proto_dist">Protocol Distribution</h3>'
            + _df_to_html(m.get('proto_distribution'))
        )

    def _mod10_html(self):
        m = self._r.get('mod10', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        return (
            self._subnote('先看目前被明確允許的主要應用流向，確認哪些是業務必要路徑。')
            + _df_to_html(m.get('top_app_flows'))
            + self._subnote('Audit Flags 會列出雖然已被允許，但仍值得再人工檢視的流量。')
            + '<h3><span data-i18n="rpt_tr_audit_flags">Audit Flags</span> (' +
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

        out += self._subnote('先從總傳輸量與峰值頻寬掌握整體資料移動規模，再往下看哪些流量最值得優先檢查。')
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
        app_env_scores = m.get('app_env_scores')
        score_bar = _progress_bar(score)
        html = (
            self._subnote('readiness 分數用來評估目前環境是否適合進一步提高 enforcement 強度，分數越高通常代表收斂程度越好。') +
            f'<div style="display:flex;align-items:center;gap:24px;margin-bottom:16px;">'
            f'<div style="font-size:48px;font-weight:700;color:{grade_color};">{grade}</div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:13px;color:var(--slate-50);margin-bottom:4px;"><span data-i18n="rpt_tr_readiness_score">Enforcement Readiness Score:</span> <b>{score}/100</b></div>'
            f'{score_bar}'
            f'</div></div>'
            + '<h4 data-i18n="rpt_tr_score_breakdown">Score Breakdown by Factor</h4>'
            + _df_to_html(factor_table)
        )
        if app_env_scores is not None and not app_env_scores.empty:
            html += '<h4>App(env) Readiness Ranking</h4>' + _df_to_html(app_env_scores)
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
        html = (self._subnote('本區專注在與橫向移動有關的風險路徑，協助你確認哪些來源、服務與可達鏈最值得優先收斂。') + f'<p><span data-i18n="rpt_tr_lateral_flows">Lateral movement port flows:</span> '
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
        bridge_nodes = m.get('bridge_nodes')
        if bridge_nodes is not None and not bridge_nodes.empty:
            html += '<h4>Bridge Nodes (Articulation)</h4>' + _df_to_html(bridge_nodes)
        reachable_nodes = m.get('top_reachable_nodes')
        if reachable_nodes is not None and not reachable_nodes.empty:
            html += '<h4>Top Reachable Nodes</h4>' + _df_to_html(reachable_nodes)
        attack_paths = m.get('attack_paths')
        if attack_paths is not None and not attack_paths.empty:
            html += '<h4>Attack Paths (Depth-Bounded)</h4>' + _df_to_html(attack_paths)
        app_chains = m.get('app_chains')
        if app_chains is not None and not app_chains.empty:
            html += '<h4 data-i18n="rpt_tr_app_chains">Lateral Movement App Chains (BFS Paths)</h4>' + _df_to_html(app_chains)
        return html
