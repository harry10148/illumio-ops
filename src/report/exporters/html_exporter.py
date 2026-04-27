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
from loguru import logger
import pandas as pd

from .report_i18n import STRINGS, lang_btn_html, COL_I18N as _COL_I18N
from .report_css import build_css, TABLE_JS
from .table_renderer import render_df_table
from .chart_renderer import render_plotly_html, FirstChartTracker
from .code_highlighter import get_highlight_css
from src.humanize_ext import human_number
from src.report.section_guidance import get_guidance, visible_in
from src.i18n import t

_CSS = build_css('traffic')
_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'


_REPORT_DETAIL_LEVEL = "full"


def render_section_guidance(module_id: str, profile: str, detail_level: str) -> str:
    """Return a small HTML card with the section's reader-guide.
    Empty string if module has no guidance, or section not visible at this
    (profile, detail_level)."""
    g = get_guidance(module_id)
    if g is None:
        return ""
    if not visible_in(module_id, profile, detail_level):
        return ""
    purpose = t(g.purpose_key)
    actions = t(g.recommended_actions_key)
    signals = t(g.watch_signals_key)
    how = t(g.how_to_read_key)
    return (
        '<div class="section-guidance standard">'
        f'<div><b>{t("rpt_guidance_purpose_label")}</b>: {purpose}</div>'
        f'<div><b>{t("rpt_guidance_watch_signals_label")}</b>: {signals}</div>'
        f'<div><b>{t("rpt_guidance_how_to_read_label")}</b>: {how}</div>'
        f'<div><b>{t("rpt_guidance_recommended_actions_label")}</b>: {actions}</div>'
        "</div>"
    )


def render_appendix(title: str, body_html: str, *, detail_level: str) -> str:
    """Wrap body_html in an expanded appendix block."""
    return (
        f'<details open class="report-appendix">'
        f'<summary><b>{t("rpt_appendix_label")}: {title}</b></summary>'
        f'{body_html}'
        f'</details>'
    )


def _render_chart_for_html(chart_spec: dict | None, include_js: bool = True) -> str:
    """Emit plotly interactive div. Matplotlib PNG is PDF-only; never shown in HTML."""
    if not chart_spec:
        return ''
    try:
        plotly_div = render_plotly_html(chart_spec, include_js=include_js)
        if plotly_div:
            return f'<div class="chart-container">{plotly_div}</div>'
    except Exception as exc:
        logger.warning('plotly render failed: {}', exc)
    return ''

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

# Metrics whose direction polarity is inverted (up = good).
_GOOD_UP_KEYWORDS = ('coverage', 'readiness', 'maturity')

def _trend_chip(direction: str, delta: float, delta_pct: float | None, metric: str) -> str:
    """Render a tabular trend chip with arrow + signed delta + percentage."""
    arrow = {"up": "\u2191", "down": "\u2193", "flat": "\u2192"}.get(direction, "")
    metric_lower = (metric or '').lower()
    inverted = any(k in metric_lower for k in _GOOD_UP_KEYWORDS)

    if direction == 'flat':
        chip_cls = 'trend-chip trend-chip--flat'
    elif inverted:
        chip_cls = f'trend-chip trend-chip--good-{direction}'
    else:
        chip_cls = f'trend-chip trend-chip--{direction}'

    pct_str = f' ({delta_pct:+.1f}%)' if delta_pct is not None else ''
    return (
        f'<span class="{chip_cls}">'
        f'<span class="trend-arrow">{arrow}</span>{delta:+,.1f}{pct_str}'
        f'</span>'
    )

def _trend_deltas_section(deltas: list | None) -> str:
    """Heading + chip-bearing table; or a friendly first-run note when empty."""
    heading = '<h3 data-i18n="rpt_tr_trend_heading">Trend vs Previous Report</h3>'
    if not deltas:
        return (
            heading
            + '<div class="trend-empty-note" data-trend-empty="true">'
            '<span class="trend-empty-dot" aria-hidden="true"></span>'
            '<span data-i18n="rpt_tr_trend_empty">'
            'No previous snapshot — trend will appear from the next report onward.'
            '</span>'
            '</div>'
        )

    rows = []
    for d in deltas:
        rows.append({
            'Metric': d.get('metric', ''),
            'Previous': d.get('previous', 0),
            'Current': d.get('current', 0),
            'Delta': d,  # carry the raw entry through; renderer formats as chip
        })
    df = pd.DataFrame(rows)

    def _render_cell(col, val, _row):
        if col == 'Delta':
            return _trend_chip(
                direction=val.get('direction', ''),
                delta=float(val.get('delta', 0) or 0),
                delta_pct=val.get('delta_pct'),
                metric=val.get('metric', ''),
            )
        if col in ('Previous', 'Current'):
            try:
                return f'{float(val):,.1f}'
            except (TypeError, ValueError):
                return str(val) if val is not None else ''
        return str(val) if val is not None else ''

    return heading + render_df_table(
        df,
        col_i18n=_COL_I18N,
        render_cell=_render_cell,
    )

# Rule descriptions: human-readable explanation of what each built-in rule checks
_RULE_DESCRIPTIONS = {
    # ── Ransomware exposure ────────────────────────────────────────────────────
    'B001': ('Ransomware Critical Ports Not Blocked',
             'Checks for traffic on ransomware\'s primary attack ports (SMB 445, RPC 135, RDP 3389, WinRM 5985/5986) that is NOT blocked. These are the exact ports used in EternalBlue, NotPetya, and WannaCry-class attacks for network-wide lateral spread.'),
    'B002': ('Ransomware High-Risk Remote Access Allowed',
             'Detects allowed flows on secondary remote-access ports (TeamViewer 5938, VNC 5900, NetBIOS 137-139). Ransomware operators and APT groups use these for C2 persistence and remote control after initial compromise.'),
    'B003': ('Ransomware Risk Port (Medium) — Uncovered',
             t('rpt_rule_b003_desc')),
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
    'L008': ('Lateral Ports in Test Mode (PB)',
             t('rpt_rule_l008_desc')),
    # ── Lateral movement — exfiltration pattern ─────────────────────────────────
    'L009': ('Data Exfiltration Pattern — Outbound to Unmanaged',
             'Detects managed workloads transferring significant data volume to unmanaged (external/unknown) destinations. This is the post-lateral-movement exfiltration phase: attacker has pivoted to a high-value host and is now staging or exfiltrating data to an external C2 or drop server outside PCE visibility.'),
    # ── Lateral movement — cross-env boundary break ──────────────────────────────
    'L010': ('Cross-Environment Lateral Port Access — Boundary Break',
             'CRITICAL: Detects lateral movement ports (SMB 445, RDP 3389, WinRM 5985/5986, RPC 135) allowed between different environments. Environment segmentation is the macro-security boundary. If lateral ports cross it, an attacker who compromises Dev/Test can directly pivot into Production using exactly the same techniques, bypassing all environment-level controls.'),
}

_SEVERITY_TOKENS = {'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'}

# Column-name fragments that should render as integers (strip trailing ".0"
# when dtype was promoted to float by pandas groupby/unstack).
_INT_COL_KEYWORDS = ('port', '連接埠', 'flow count', 'connections', 'flows',
                     'allowed', 'blocked', 'count')

def _norm_col(name) -> str:
    """Normalize a column name for tolerant matching (case-insensitive, trimmed)."""
    return str(name).strip().lower().replace(' ', '_')

def _fmt_int_cell(val) -> str:
    """Format an integer-valued cell with thousands separators; bare floats like
    53.0 render as '53', not '53.0'. Falls back to str(val) on non-numerics."""
    if val is None:
        return ''
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    if f != f:  # NaN
        return ''
    if f.is_integer():
        return f'{int(f):,}'
    return f'{f:,.1f}'

def _df_to_html(df: pd.DataFrame | None, severity_col: str | None = None,
                no_data_key: str = "rpt_no_data") -> str:
    # Empty-case rendering is handled inside render_df_table() so the panel
    # chrome stays consistent across data-bearing and empty sections.

    # Determine which columns contain raw byte / bandwidth / integer-count values
    if df is None or (hasattr(df, 'empty') and df.empty):
        byte_cols = bw_cols = int_cols = set()
    else:
        byte_cols = {col for col in df.columns
                     if any(kw in str(col).lower() for kw in _BYTE_COL_KEYWORDS)}
        bw_cols = {col for col in df.columns
                   if any(kw in str(col).lower() for kw in _BW_COL_KEYWORDS)}
        int_cols = {col for col in df.columns
                    if any(kw in str(col).lower() for kw in _INT_COL_KEYWORDS)
                    and col not in byte_cols and col not in bw_cols}

    sev_target = _norm_col(severity_col) if severity_col else None

    def _render_cell(col, val, _row):
        if sev_target and _norm_col(col) == sev_target and str(val).upper() in _SEVERITY_TOKENS:
            return f'<span class="badge badge-{str(val).upper()}">{val}</span>'
        if col in byte_cols:
            return _fmt_bytes(val)
        if col in bw_cols:
            return _fmt_bw(val)
        if col in int_cols:
            return _fmt_int_cell(val)
        return '' if val is None else str(val)

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
    )

class HtmlExporter:
    """Export report results to a single self-contained HTML file."""

    def __init__(self, results: dict, data_source: str = "",
                 profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL,
                 compute_draft: bool = False, lang: str = "en"):
        self._r = results
        self._data_source = data_source
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._compute_draft = compute_draft
        self._lang = lang

    def export(self, output_dir: str = 'reports') -> str:
        """Write HTML file and return full path."""
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime('%Y-%m-%d_%H%M')
        profile_label = "NetworkInventory" if self._profile == "network_inventory" else "SecurityRisk"
        filename = f'Illumio_Traffic_Report_{profile_label}_{ts}.html'
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self._build())
        logger.info(f"[HtmlExporter] Saved: {filepath}")
        return filepath

    def _build(self, profile: str = "", detail_level: str = "") -> str:
        profile = profile or self._profile
        detail_level = _REPORT_DETAIL_LEVEL
        self._chart_tracker = FirstChartTracker()
        mod12 = self._r.get('mod12', {})
        findings = self._r.get('findings', [])
        n_findings = str(len(findings))

        # nav_html is built after block flags are known (see below)

        # Pre-compute nested blocks to avoid f-string quote conflicts
        _raw_kpis = mod12.get('kpis', [])
        if isinstance(_raw_kpis, dict):
            # New-style: dict of kpi_name -> numeric value (from _security_risk_kpis)
            _kpi_items = [{"label": k.replace("_", " ").title(), "value": v}
                          for k, v in _raw_kpis.items() if not isinstance(v, dict)]
        else:
            _kpi_items = list(_raw_kpis)
        kpi_cards = ''.join(
            '<div class="kpi-card"><div class="kpi-label">' + str(k['label']) + '</div>'
            '<div class="kpi-value">' + str(k['value']) + '</div></div>'
            for k in _kpi_items
        )
        trend_html = self._trend_deltas_html()
        key_findings_html = ''.join(
            '<p style="margin-bottom:8px"><span class="badge badge-' +
            kf.get('severity', 'INFO') + '">' + kf.get('severity', '') + '</span>&nbsp;' +
            kf.get('finding', '') + ' <em style="color:#718096">&rarr; ' +
            kf.get('action', '') + '</em></p>'
            for kf in mod12.get('key_findings', [])
        ) or '<p class="note" data-i18n="rpt_no_findings">No key findings.</p>'
        attack_summary_html = self._attack_summary_html(mod12) if profile == 'security_risk' else ''

        generated_at = mod12.get('generated_at', '')
        today_str = str(datetime.date.today())
        total_flows = self._r.get('mod01', {}).get('total_flows', 0)
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        summary_pills = (
            '<div class="summary-pill-row">'
            f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pill_flows")}</span><span class="summary-pill-value">{human_number(total_flows)}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pill_findings")}</span><span class="summary-pill-value">{human_number(int(n_findings))}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pill_focus")}</span><span class="summary-pill-value">{_s("rpt_focus_traffic")}</span></div>'
            '</div>'
        )

        if self._data_source:
            ds_key = {
                "cache": "rpt_data_source_cache",
                "api": "rpt_data_source_api",
            }.get(self._data_source, "rpt_data_source_mixed")
            ds_label = STRINGS[ds_key]["en"]
            ds_color = {"cache": "#22C55E", "api": "#60A5FA"}.get(self._data_source, "#EAB308")
            data_source_pill = (
                f'<div class="summary-pill" style="border-left: 3px solid {ds_color};">'
                f'<span class="summary-pill-label" data-i18n="{ds_key}">{ds_label}</span>'
                f'</div>'
            )
            summary_pills = summary_pills.replace('</div>', data_source_pill + '</div>', 1)

        if self._compute_draft:
            draft_pill = (
                f'<span class="report-draft-pill" data-i18n="rpt_hdr_draft_enabled">'
                f'{t("rpt_hdr_draft_enabled")}</span>'
            )
            summary_pills = summary_pills.replace('</div>', draft_pill + '</div>', 1)

        # Maturity score gauge
        m_score = mod12.get('maturity_score', 0)
        m_grade = mod12.get('maturity_grade', '?')
        m_dims = mod12.get('maturity_dimensions', {})
        m_grade_color = {'A': '#22C55E', 'B': '#84CC16', 'C': '#EAB308', 'D': '#F97316', 'F': '#EF4444'}.get(m_grade, '#6B7280')
        m_dim_labels = {
            'enforcement_coverage': 'Enforcement Coverage',
            'policy_coverage': 'Policy Coverage',
            'lateral_movement_control': 'Lateral Movement Control',
            'managed_asset_ratio': 'Managed Asset Ratio',
            'risk_port_control': 'Risk Port Control',
        }
        maturity_bars = ''
        for dim_key, dim_label in m_dim_labels.items():
            dim = m_dims.get(dim_key, {})
            dim_score = dim.get('score', 0)
            dim_weight = dim.get('weight', 0)
            dim_pct = round(dim_score / max(dim_weight, 1) * 100, 0) if dim_weight else 0
            bar_color = '#22C55E' if dim_pct >= 70 else ('#EAB308' if dim_pct >= 40 else '#EF4444')
            maturity_bars += (
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px">'
                f'<div style="width:200px;flex-shrink:0">{dim_label}</div>'
                f'<div style="flex:1;height:16px;background:#2D3748;border-radius:4px;overflow:hidden">'
                f'<div style="width:{dim_pct}%;height:100%;background:{bar_color};border-radius:4px"></div></div>'
                f'<div style="width:60px;text-align:right;font-weight:600">{dim_score}/{dim_weight}</div>'
                f'</div>'
            )

        maturity_html = (
            '<div style="display:flex;align-items:center;gap:24px;margin:20px 0;padding:20px;'
            'background:var(--card-bg);border:1px solid var(--border);border-radius:12px">'
            f'<div style="text-align:center;min-width:100px">'
            f'<div style="font-size:48px;font-weight:700;color:{m_grade_color};line-height:1">{m_grade}</div>'
            f'<div style="font-size:14px;color:var(--slate-50);margin-top:4px" data-i18n="rpt_tr_maturity_score">'
            f'Maturity: {m_score}/100</div></div>'
            f'<div style="flex:1">{maturity_bars}</div></div>'
        )

        # T6: mod06 user/process — security_risk only, and only when data available
        _mod06 = self._r.get('mod06', {})
        _mod06_has_data = _mod06.get('user_data_available') or _mod06.get('process_data_available')
        _mod06_block = (self._section(
            'user', 'rpt_tr_sec_user', 'User & Process',
            render_section_guidance('mod06', profile=profile, detail_level=detail_level) + self._mod06_html(),
        ) if (_mod06_has_data and profile == 'security_risk') else '') + '\n'

        # T7: mod07 — profile-aware rendering
        if visible_in('mod07_cross_label_matrix', profile, detail_level):
            _mod07_body = (render_section_guidance('mod07', profile=profile, detail_level=detail_level) +
                           self._mod07_html())
            if profile == 'security_risk':
                _mod07_block = (
                    self._section('matrix', 'rpt_tr_sec_matrix', 'Cross-Label Matrix',
                                  _mod07_body,
                                  'rpt_tr_sec_matrix_intro', 'Observe cross-group communication by Label dimension, useful for surfacing segments that should not interact frequently.') + '\n'
                )
            else:  # network_inventory — full matrix in main
                _mod07_block = (
                    self._section('matrix', 'rpt_tr_sec_matrix', 'Cross-Label Matrix',
                                  _mod07_body,
                                  'rpt_tr_sec_matrix_intro', 'Observe cross-group communication by Label dimension, useful for surfacing segments that should not interact frequently.') + '\n'
                )
        else:
            _mod07_block = ''

        # Build profile-aware nav after all block flags are known
        def _nav_link(anchor: str, i18n_key: str, fallback: str, badge: str = '') -> str:
            return (f'<a href="#{anchor}"><span data-i18n="{i18n_key}">{fallback}</span>'
                    + (f'<span class="nav-badge">{badge}</span>' if badge else '') + '</a>')

        if profile == 'security_risk':
            _nav_links = [
                _nav_link('summary', 'rpt_tr_nav_summary', 'Executive Summary'),
                _nav_link('overview', 'rpt_tr_nav_overview', '1 Traffic Overview'),
                _nav_link('policy', 'rpt_tr_nav_policy', '2 Policy Decisions'),
                _nav_link('uncovered', 'rpt_tr_nav_uncovered', '3 Uncovered Flows'),
                _nav_link('ransomware', 'rpt_tr_nav_ransomware', '4 Ransomware Exposure'),
                (_nav_link('user', 'rpt_tr_nav_user', '6 User & Process') if _mod06_has_data else ''),
                _nav_link('allowed', 'rpt_tr_nav_allowed', '10 Allowed Traffic'),
                _nav_link('readiness', 'rpt_tr_nav_readiness', '13 Enforcement Readiness'),
                _nav_link('infrastructure', 'rpt_tr_nav_infrastructure', '14 Infrastructure Scoring'),
                _nav_link('lateral', 'rpt_tr_nav_lateral', '15 Lateral Movement'),
                (_nav_link('draft_actions', 'rpt_tr_nav_draft_actions', 'Draft Actions')
                 if visible_in('mod_draft_actions', profile, detail_level) else ''),
                (_nav_link('enforcement_rollout', 'rpt_tr_nav_enf_rollout', 'Enforcement Rollout')
                 if visible_in('mod_enforcement_rollout', profile, detail_level) else ''),
                (_nav_link('exfiltration', 'rpt_tr_nav_exfiltration', 'Exfiltration Intel')
                 if visible_in('mod_exfiltration_intel', profile, detail_level) else ''),
                _nav_link('findings', 'rpt_tr_nav_findings', 'Findings', badge=n_findings),
            ]
        else:  # network_inventory
            _nav_links = [
                _nav_link('summary', 'rpt_tr_nav_summary', 'Executive Summary'),
                _nav_link('overview', 'rpt_tr_nav_overview', '1 Traffic Overview'),
                _nav_link('policy', 'rpt_tr_nav_policy', '2 Policy Decisions'),
                (_nav_link('matrix', 'rpt_tr_nav_matrix', '7 Cross-Label Matrix')
                 if _mod07_block else ''),
                _nav_link('unmanaged', 'rpt_tr_nav_unmanaged', '8 Unmanaged Hosts'),
                _nav_link('distribution', 'rpt_tr_nav_distribution', '9 Traffic Distribution'),
                _nav_link('bandwidth', 'rpt_tr_nav_bandwidth', '11 Bandwidth & Volume'),
                _nav_link('readiness', 'rpt_tr_nav_readiness', '13 Enforcement Readiness'),
                (_nav_link('draft_actions', 'rpt_tr_nav_draft_actions', 'Draft Actions')
                 if visible_in('mod_draft_actions', profile, detail_level) else ''),
                (_nav_link('ringfence', 'rpt_tr_nav_ringfence', 'Application Ringfence')
                 if visible_in('mod_ringfence', profile, detail_level) else ''),
                (_nav_link('change_impact', 'rpt_tr_nav_change_impact', 'Change Impact')
                 if visible_in('mod_change_impact', profile, detail_level) else ''),
            ]
        nav_html = '<nav>' + ''.join(_nav_links) + '</nav>'

        body = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top"><div class="report-kicker" data-i18n="rpt_kicker_traffic">Traffic Analytics Report</div>'
            + (
                f'<div class="report-profile-badge report-profile-badge--security" '
                f'data-i18n="rpt_kicker_security_risk">{_s("rpt_kicker_security_risk")}</div>'
                if profile == 'security_risk' else
                f'<div class="report-profile-badge report-profile-badge--inventory" '
                f'data-i18n="rpt_kicker_network_inventory">{_s("rpt_kicker_network_inventory")}</div>'
            ) +
            '<h1 data-i18n="rpt_tr_title">Illumio Traffic Flow Report</h1>'
            '<p class="report-subtitle">'
            '<span data-i18n="rpt_generated">Generated:</span> ' + generated_at + '</p></div>'
            + summary_pills +
            '<h2 data-i18n="rpt_tr_maturity_heading">Microsegmentation Maturity</h2>'
            + maturity_html +
            '<h2 data-i18n="rpt_key_metrics">Key Metrics</h2>'
            '<div class="kpi-grid">' + kpi_cards + '</div>'
            + trend_html +
            '<h2 data-i18n="rpt_key_findings">Key Findings</h2>' + key_findings_html +
            attack_summary_html +
            '</section>\n' +
            self._section('overview', 'rpt_tr_sec_overview', 'Traffic Overview',
                          render_section_guidance('mod01', profile=profile, detail_level=detail_level) + self._mod01_html(),
                          'rpt_tr_sec_overview_intro', 'Start from overall traffic scale, Policy coverage, and top Ports to set a baseline for reading the rest of the report.') + '\n' +
            (self._section('policy', 'rpt_tr_sec_policy', 'Policy Decisions',
                           render_section_guidance('mod02', profile=profile, detail_level=detail_level) + self._mod02_html(),
                           'rpt_tr_sec_policy_intro', 'Break down the ratios and details of Allowed, Blocked, and Potentially Blocked to gauge how Policy is actually landing.') + '\n'
             if visible_in('mod02_policy_decisions', profile, detail_level) else '') +
            (self._section('uncovered', 'rpt_tr_sec_uncovered', 'Uncovered Flows',
                           render_section_guidance('mod03', profile=profile, detail_level=detail_level) + self._mod03_html(),
                           'rpt_tr_sec_uncovered_intro', 'Focus on traffic not yet covered by effective Policy, helping prioritise which Services and directions to tighten first.') + '\n'
             if visible_in('mod03_uncovered_flows', profile, detail_level) else '') +
            (self._section('ransomware', 'rpt_tr_sec_ransomware', 'Ransomware Exposure',
                           render_section_guidance('mod04', profile=profile, detail_level=detail_level) + self._mod04_html(),
                           'rpt_tr_sec_ransomware_intro', 'Check high-risk Ports, Allowed flows, and host exposure commonly tied to ransomware attack chains.') + '\n'
             if visible_in('mod04_ransomware_exposure', profile, detail_level) else '') +
            # mod05 (Remote Access) consolidated into mod15 (Lateral Movement)

            _mod06_block +
            _mod07_block +
            (self._section('unmanaged', 'rpt_tr_sec_unmanaged', 'Unmanaged Hosts',
                           render_section_guidance('mod08', profile=profile, detail_level=detail_level) + self._mod08_html(),
                           'rpt_tr_sec_unmanaged_intro', 'Inventory traffic involving hosts not managed by VEN; these typically sit outside the visibility and control boundary.') + '\n'
             if visible_in('mod08_unmanaged_hosts', profile, detail_level) else '') +
            (self._section('distribution', 'rpt_tr_sec_distribution', 'Traffic Distribution',
                           render_section_guidance('mod09', profile=profile, detail_level=detail_level) +
                           self._mod09_html()) + '\n'
             if profile == 'network_inventory' else '') +
            (self._section('allowed', 'rpt_tr_sec_allowed', 'Allowed Traffic',
                           render_section_guidance('mod10', profile=profile, detail_level=detail_level) + self._mod10_html(),
                           'rpt_tr_sec_allowed_intro', 'Focus on explicitly Allowed traffic to confirm which are required business paths and which still deserve an audit.') + '\n'
             if profile == 'security_risk' else '') +
            (self._section('bandwidth', 'rpt_tr_sec_bandwidth', 'Bandwidth &amp; Volume',
                           render_section_guidance('mod11', profile=profile, detail_level=detail_level) + self._mod11_html(),
                           'rpt_tr_sec_bandwidth_intro', 'Review high-volume flows by bandwidth and data volume to identify large backups, batch jobs, or suspected exfiltration.') + '\n'
             if profile == 'network_inventory' else '') +
            (self._section('readiness', 'rpt_tr_sec_readiness', 'Enforcement Readiness',
                           render_section_guidance('mod13', profile=profile, detail_level=detail_level) + self._mod13_html(),
                           'rpt_tr_sec_readiness_intro', 'Aggregate multiple signals into a readiness score to help assess whether it is safe to tighten Enforcement.') + '\n'
             if visible_in('mod13_readiness', profile, detail_level) else '') +
            (self._section('infrastructure', 'rpt_tr_sec_infrastructure', 'Infrastructure Scoring',
                           render_section_guidance('mod14', profile=profile, detail_level=detail_level) + self._mod14_html(),
                           'rpt_tr_sec_infrastructure_intro', 'Identify critical nodes and infrastructure roles with large blast radius from application communication patterns.') + '\n'
             if profile == 'security_risk' else '') +
            (self._section('lateral', 'rpt_tr_sec_lateral', 'Lateral Movement',
                           render_section_guidance('mod15', profile=profile, detail_level=detail_level) + self._mod15_html(),
                           'rpt_tr_sec_lateral_intro', 'Focus on paths, Services, and sources tied to lateral movement to surface spread risk.') + '\n'
             if visible_in('mod15_lateral_movement', profile, detail_level) else '') +
            (self._section('draft_actions', 'rpt_mod_draft_actions_title', 'Draft Actions',
                           render_section_guidance('mod_draft_actions', profile, detail_level) + self._mod_draft_actions_html(),
                           '', '') + '\n'
             if visible_in('mod_draft_actions', profile, detail_level) else '') +
            (self._section('enforcement_rollout', 'rpt_mod_enf_rollout_title', 'Enforcement Rollout Plan',
                           render_section_guidance('mod_enforcement_rollout', profile, detail_level) + self._mod_enforcement_rollout_html(),
                           '', '') + '\n'
             if visible_in('mod_enforcement_rollout', profile, detail_level) else '') +
            (self._section('ringfence', 'rpt_mod_ringfence_title', 'Application Ringfence',
                           render_section_guidance('mod_ringfence', profile, detail_level) + self._mod_ringfence_html(),
                           '', '') + '\n'
             if visible_in('mod_ringfence', profile, detail_level) else '') +
            (self._section('change_impact', 'rpt_mod_change_impact_title', 'Change Impact',
                           render_section_guidance('mod_change_impact', profile, detail_level) + self._mod_change_impact_html(),
                           '', '') + '\n'
             if visible_in('mod_change_impact', profile, detail_level) else '') +
            (self._section('exfiltration', 'rpt_mod_exfil_title', 'Exfiltration & Threat Intel',
                           render_section_guidance('mod_exfiltration_intel', profile, detail_level) + self._mod_exfil_html(),
                           '', '') + '\n'
             if visible_in('mod_exfiltration_intel', profile, detail_level) else '') +
            ((
            '<section id="findings" class="card">'
            '<h2><span data-i18n="rpt_tr_sec_findings">Security Findings</span> (' + n_findings + ')</h2>'
            + self._findings_html() +
            '</section>\n'
            ) if profile == 'security_risk' else '') +
            '<footer><span data-i18n="rpt_tr_footer">Illumio PCE Ops — Traffic Flow Report</span>'
            ' &middot; ' + today_str + '</footer>'
        )
        html_lang = "zh-TW" if self._lang == "zh_TW" else "en"
        return (
            f'<!DOCTYPE html><html lang="{html_lang}"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            '<title>Illumio Traffic Report</title>' + _CSS + _HIGHLIGHT_CSS + '</head>\n'
            '<body>' + nav_html + '<main>' + body + '</main>'
            + TABLE_JS + '</body></html>'
        )

    def _section(
        self,
        id_: str,
        i18n_key: str,
        title: str,
        content: str,
        intro_key: str = '',
        intro_en: str = '',
    ) -> str:
        """Emit a report section with translatable h2 title and intro.

        Both the title and intro paragraphs carry ``data-i18n``; applyI18n()
        swaps textContent on language toggle. Initial render uses English so
        the no-JS path reads correctly.
        """
        intro_html = (
            f'<p class="section-intro" data-i18n="{intro_key}">{intro_en}</p>'
            if intro_key else ''
        )
        return (
            f'<section id="{id_}" class="card">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f'{intro_html}{content}</section>'
        )

    def _trend_deltas_html(self) -> str:
        """Render trend deltas via the shared table renderer + chip cells.

        When no prior snapshot exists, emits a soft 'first-run' note instead
        of being silently empty (so the section feels intentional, not broken).
        """
        return _trend_deltas_section(self._r.get("_trend_deltas"))

    def _subnote(self, i18n_key: str, en_text: str) -> str:
        """Render a small annotation paragraph with i18n support.

        Emits ``data-i18n`` so applyI18n() swaps textContent on language toggle,
        and includes the English fallback as initial text for the no-JS path.
        """
        return (
            f'<p class="note" style="font-size:12px;" '
            f'data-i18n="{i18n_key}">{en_text}</p>'
        )

    def _attack_summary_html(self, mod12: dict) -> str:
        def _rows(section_items):
            if not section_items:
                return '<p class="note">No data</p>'
            return ''.join(
                '<p style="margin-bottom:8px"><span class="badge badge-' +
                str(item.get('severity', 'INFO')) + '">' + str(item.get('severity', 'INFO')) +
                '</span>&nbsp;' + str(item.get('finding', '')) +
                ' <em style="color:#718096">&rarr; ' + str(item.get('action', '')) + '</em>' +
                '</p>'
                for item in section_items[:3]
            )

        action_matrix = mod12.get('action_matrix', []) or []
        action_html = ''.join(
            '<p style="margin-bottom:8px"><b>' + str(item.get('action_code', '')) + '</b>: ' +
            str(item.get('action', '')) +
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

    def _three_col_tables(
        self,
        main_title: str, main_html: str,
        mid_title: str, mid_html: str,
        right_title: str, right_html: str,
    ) -> str:
        """Wide-left + two narrow-right columns in a single tri-grid row."""
        return (
            '<div class="tri-grid">'
            f'<div>{main_title}{main_html}</div>'
            f'<div>{mid_title}{mid_html}</div>'
            f'<div>{right_title}{right_html}</div>'
            '</div>'
        )

    def _mod01_html(self):
        m = self._r.get('mod01', {})
        return (
            self._subnote('rpt_tr_mod01_intro', 'This summary frames traffic scale, Policy coverage, and observation period so the rest of the report has context.')
            + self._mod01_summary_table(m)
            + self._subnote('rpt_tr_top_ports_subnote', 'Top Ports shows which Services dominate the environment and helps spot unexpected activity.')
            + '<h3 data-i18n="rpt_tr_top_ports">Top Ports</h3>'
            + _df_to_html(m.get('top_ports'))
        )

    def _mod02_html(self):
        m = self._r.get('mod02', {})
        out = self._subnote('rpt_tr_mod02_intro', 'Start with the decision breakdown to see how much traffic is Allowed vs Blocked vs Potentially Blocked.') + _df_to_html(m.get('summary')) + _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume())
        # Per-port coverage table
        pc = m.get('port_coverage')
        if pc is not None and hasattr(pc, 'empty') and not pc.empty:
            out += self._subnote('rpt_tr_port_coverage_subnote', 'Per-Port Coverage surfaces which Services already have solid Policy and which still have gaps.') + '<h3 data-i18n="rpt_tr_port_coverage">Per-Port Coverage</h3>' + _df_to_html(pc)
        for d in ('allowed', 'blocked', 'potentially_blocked'):
            dm = m.get(d, {})
            if not isinstance(dm, dict) or dm.get('count', 0) == 0:
                continue
            inb = dm.get('inbound_count', 0)
            outb = dm.get('outbound_count', 0)
            pct = dm.get('pct_of_total', 0)
            status = {
                'allowed': 'ALLOWED',
                'blocked': 'BLOCKED',
                'potentially_blocked': 'POTENTIAL',
            }.get(d, d.upper())
            out += (
                '<h3>' + d.replace('_', ' ').upper() + f' ({pct}% of total)'
                f' &nbsp;·&nbsp; ↓ Inbound: {inb} &nbsp;·&nbsp; ↑ Outbound: {outb}</h3>'
            )
            out += self._three_col_tables(
                '<h4 data-i18n="rpt_tr_top_app_flows">Top App Flows</h4>',
                _df_to_html(dm.get('top_app_flows')),
                f'<h4>Top Inbound Ports ({status})</h4>',
                _df_to_html(dm.get('top_inbound_ports')),
                f'<h4>Top Outbound Ports ({status})</h4>',
                _df_to_html(dm.get('top_outbound_ports')),
            )
        return out

    def _mod03_html(self):
        m = self._r.get('mod03', {})
        enforced_cov = m.get('enforced_coverage_pct', m.get('coverage_pct', 0))
        staged_cov = m.get('staged_coverage_pct', 0)
        true_gap = m.get('true_gap_pct', 0)
        inb_cov = m.get('inbound_coverage_pct')
        outb_cov = m.get('outbound_coverage_pct')

        # Three-tier coverage bar: enforced (green) + staged (amber) + gap (red)
        bar_html = (
            '<div style="display:flex;height:28px;border-radius:6px;overflow:hidden;margin:12px 0 16px 0;font-size:12px;font-weight:600;color:#fff;text-align:center;line-height:28px">'
            f'<div style="width:{enforced_cov}%;background:#38A169" title="Enforced">{enforced_cov}%</div>'
            + (f'<div style="width:{staged_cov}%;background:#D69E2E" title="Staged">{staged_cov}%</div>' if staged_cov > 0 else '')
            + (f'<div style="width:{true_gap}%;background:#E53E3E" title="True Gap">{true_gap}%</div>' if true_gap > 0 else '')
            + '</div>'
        )

        stats = (
            '<div class="coverage-grid">'
            + _cov_stat('<span data-i18n="rpt_tr_enforced_coverage">Enforced Coverage</span>', str(enforced_cov) + '%')
            + _cov_stat(f'<span data-i18n="rpt_pb_label">{t("rpt_pb_label")}</span>', str(staged_cov) + '%')
            + _cov_stat('<span data-i18n="rpt_tr_true_gap">True Gap</span>', str(true_gap) + '%')
            + (_cov_stat('<span data-i18n="rpt_tr_inbound_coverage">Inbound Coverage</span>', str(inb_cov) + '%') if inb_cov is not None else '')
            + (_cov_stat('<span data-i18n="rpt_tr_outbound_coverage">Outbound Coverage</span>', str(outb_cov) + '%') if outb_cov is not None else '')
            + _cov_stat('<span data-i18n="rpt_col_uncovered_flows">Uncovered Flows</span>', str(m.get('total_uncovered', 0)))
            + '</div>'
            + bar_html
            + (f'<p class="note" data-i18n-html="rpt_pb_explainer">{t("rpt_pb_explainer")}</p>' if staged_cov > 0 else '')
        )
        out = (
            stats
            + self._subnote('rpt_tr_top_uncovered_subnote', 'Top uncovered flows highlight where Policy most urgently needs filling, usually by volume or sensitivity.')
            + '<h3 data-i18n="rpt_tr_top_uncovered">Top Uncovered Flows</h3>'
            + _df_to_html(m.get('top_flows'))
        )
        up = m.get('uncovered_ports')
        if up is not None and hasattr(up, 'empty') and not up.empty:
            out += self._subnote('rpt_tr_port_gaps_subnote', 'The Port gap ranking helps you inventory gaps by Service and turn them directly into a remediation list.') + '<h3 data-i18n="rpt_tr_port_gaps">Port Gap Ranking</h3>' + _df_to_html(up)
        us = m.get('uncovered_services')
        if us is not None and hasattr(us, 'empty') and not us.empty:
            out += self._subnote('rpt_tr_service_gaps_subnote', 'Uncovered Services tie apps and Ports together, making a better input for future Policy design.') + '<h3 data-i18n="rpt_tr_service_gaps">Uncovered Services (App + Port)</h3>' + _df_to_html(us)
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
                '<b><span data-i18n="rpt_tr_investigation_title">⚠ Hosts Requiring Investigation</span></b><br>'
                '<span style="font-size:12px" data-i18n="rpt_tr_investigation_desc">'
                'The following destination hosts have Allowed traffic on critical or high-risk Ports. Verify whether this is expected, or block the traffic.'
                '</span>'
                '</div>'
                + _df_to_html(part_e, 'Risk Level')
            )
        else:
            out += (
                '<div style="background:#d4edda;border-left:4px solid var(--green-80);'
                'padding:12px 16px;margin:12px 0;border-radius:4px">'
                '<b data-i18n="rpt_tr_no_investigation">✅ No Allowed traffic on critical/high-risk Ports detected.</b>'
                '</div>'
            )

        out += (
            '<h3 data-i18n="rpt_tr_risk_summary">Risk Level Summary</h3>'
            + _df_to_html(m.get('part_a_summary'), 'Risk Level') +
            '<h3 data-i18n="rpt_tr_per_port">Per-Port Detail</h3>'
            + _df_to_html(m.get('part_b_per_port'), 'Risk Level') +
            '<h3 data-i18n="rpt_tr_host_exposure">Host Exposure Ranking</h3>'
            + '<p class="note" style="font-size:11px" data-i18n="rpt_tr_host_exposure_note">'
            'Destination hosts ranked by number of risk-Port touches, across all decisions including blocks.</p>'
            + _df_to_html(m.get('part_d_host_exposure'))
        )
        return out

    def _mod05_html(self):
        m = self._r.get('mod05', {})
        if not isinstance(m, dict) or m.get('total_lateral_flows', 0) == 0:
            return '<p class="note" data-i18n="rpt_no_lateral">No lateral movement traffic found.</p>'
        return (
            self._subnote('rpt_tr_remote_services_subnote', 'Service-level activity in remote-management scenarios shows which protocols are most used for ops or remote sessions.')
            + _df_to_html(m.get('by_service'))
            + self._subnote('rpt_tr_remote_talkers_subnote', 'Top Talkers surfaces the most active sources or destinations so you can cross-check against known admin nodes.')
            + '<h3 data-i18n="rpt_tr_top_talkers">Top Talkers</h3>'
            + _df_to_html(m.get('top_talkers'))
        )

    def _mod06_html(self):
        m = self._r.get('mod06', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        out = ''
        if m.get('user_data_available'):
            out += self._subnote('rpt_tr_top_users_subnote', 'Top Users identifies which accounts appear most often in this traffic, helping confirm whether behaviour matches existing patterns.') + '<h3 data-i18n="rpt_tr_top_users">Top Users</h3>' + _df_to_html(m.get('top_users'))
        if m.get('process_data_available'):
            out += self._subnote('rpt_tr_top_processes_subnote', 'Top Processes narrows down the binaries that initiated connections, separating normal services from background processes worth investigating.') + '<h3 data-i18n="rpt_tr_top_processes">Top Processes</h3>' + _df_to_html(m.get('top_processes'))
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
        out += _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume())
        return out or '<p class="note" data-i18n="rpt_no_matrix">No label matrix data.</p>'

    def _mod08_html(self):
        m = self._r.get('mod08', {})
        out = (
            '<div class="coverage-grid">'
            + _cov_stat('<span data-i18n="rpt_tr_unmanaged_flow_stat">Unmanaged Flows</span>', str(m.get('unmanaged_flow_count', 0)) + ' (' + str(m.get('unmanaged_pct', 0)) + '%)')
            + _cov_stat('<span data-i18n="rpt_tr_unique_unmanaged_src">Unique Unmanaged Src</span>', str(m.get('unique_unmanaged_src', 0)))
            + _cov_stat('<span data-i18n="rpt_tr_unique_unmanaged_dst">Unique Unmanaged Dst</span>', str(m.get('unique_unmanaged_dst', 0)))
            + '</div>'
            + self._subnote('rpt_tr_unmanaged_subnote', 'Start with the scale of unmanaged traffic, then drill into which sources are most active and which managed Services they target.')
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
            self._subnote('rpt_tr_distribution_subnote', 'Distribution tables are mainly for shape — good for spotting concentration around a single Service or sudden spikes in a protocol.')
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
            self._subnote('rpt_tr_allowed_flows_subnote', 'Focus on explicitly Allowed top flows and verify they are required business paths.')
            + _df_to_html(m.get('top_app_flows'))
            + _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume())
            + self._subnote('rpt_tr_audit_flags_subnote', 'Audit Flags lists traffic that is Allowed but still worth a human review.')
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

        out += self._subnote('rpt_tr_bandwidth_subnote', 'Start from total volume and peak bandwidth to size overall data movement, then drill into which flows to inspect first.')
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
                'Flows whose bytes-per-connection exceed P95 (only where connection count &gt; 1); candidates for large transfers or exfiltration.'
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
                    f'<span class="finding-title" data-i18n="rpt_rule_{f.rule_id}_name">{f.rule_name}</span>'
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
        # Enforcement mode distribution
        enforcement_dist = m.get('enforcement_mode_distribution', {})
        dist_html = ''
        if enforcement_dist:
            mode_colors = {
                'full': '#22C55E', 'selective': '#84CC16',
                'visibility_only': '#EAB308', 'idle': '#6B7280',
            }
            total_wl = sum(enforcement_dist.values())
            bars = []
            for mode, count in sorted(enforcement_dist.items(), key=lambda x: {'full': 0, 'selective': 1, 'visibility_only': 2}.get(x[0], 9)):
                pct = round(count / max(total_wl, 1) * 100, 1)
                color = mode_colors.get(mode, '#6B7280')
                label = mode.replace('_', ' ').title()
                bars.append(
                    f'<div style="width:{pct}%;background:{color};min-width:40px" title="{label}: {count}">{count}</div>'
                )
            dist_html = (
                '<h4 data-i18n="rpt_tr_enforcement_dist">Enforcement Mode Distribution</h4>'
                '<div style="display:flex;height:32px;border-radius:6px;overflow:hidden;margin:8px 0 16px 0;'
                'font-size:12px;font-weight:600;color:#fff;text-align:center;line-height:32px">'
                + ''.join(bars)
                + '</div>'
                '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;font-size:13px">'
                + ''.join(
                    f'<span><span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
                    f'background:{mode_colors.get(md, "#6B7280")};margin-right:4px"></span>'
                    f'{md.replace("_", " ").title()}: {ct}</span>'
                    for md, ct in sorted(enforcement_dist.items(), key=lambda x: {'full': 0, 'selective': 1, 'visibility_only': 2}.get(x[0], 9))
                )
                + '</div>'
            )

        _factor_legend = (
            '<div style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;'
            'padding:12px 16px;margin-bottom:12px;font-size:13px;line-height:1.6">'
            '<b data-i18n="rpt_tr_col_legend">Column guide</b>'
            '<ul style="margin:6px 0 0 0;padding-left:18px">'
            '<li><b data-i18n="rpt_tr_col_factor">Factor</b> — <span data-i18n="rpt_tr_col_factor_desc">the aspect of enforcement readiness being measured</span></li>'
            '<li><b data-i18n="rpt_tr_col_weight">Weight</b> — <span data-i18n="rpt_tr_col_weight_desc">how much this factor contributes to the 100-point total score (e.g. 35 = 35%)</span></li>'
            '<li><b data-i18n="rpt_tr_col_ratio">Ratio %</b> — <span data-i18n="rpt_tr_col_ratio_desc">the underlying measurement (e.g. 60% of flows are policy-covered)</span></li>'
            '<li><b data-i18n="rpt_tr_col_score">Score</b> — <span data-i18n="rpt_tr_col_score_desc">points earned for this factor (= Weight × Ratio ÷ 100); all factors sum to the total</span></li>'
            '</ul>'
            '<table style="margin-top:10px;font-size:12px;border-collapse:collapse;width:100%">'
            '<tr style="border-bottom:1px solid var(--border)">'
            '<th style="text-align:left;padding:4px 8px" data-i18n="rpt_tr_col_factor">Factor</th>'
            '<th style="text-align:left;padding:4px 8px" data-i18n="rpt_tr_col_factor_meaning">What it measures</th>'
            '</tr>'
            '<tr><td style="padding:4px 8px">Policy Coverage</td>'
            '<td style="padding:4px 8px" data-i18n="rpt_tr_mod13_factor_policy">% of flows matched by an allow policy (higher = fewer unprotected paths)</td></tr>'
            '<tr style="background:var(--row-alt)"><td style="padding:4px 8px">Ringfence Maturity</td>'
            '<td style="padding:4px 8px" data-i18n="rpt_tr_mod13_factor_ringfence">% of apps with app-boundary ringfence policies in place</td></tr>'
            '<tr><td style="padding:4px 8px">Enforcement Mode</td>'
            '<td style="padding:4px 8px" data-i18n="rpt_tr_mod13_factor_enforcement">% of workloads in selective or full enforcement (not visibility-only or idle)</td></tr>'
            '<tr style="background:var(--row-alt)"><td style="padding:4px 8px">Staged Readiness</td>'
            '<td style="padding:4px 8px" data-i18n="rpt_tr_mod13_factor_staged">% of staged flows (rules written, not yet enforced) that are already covered; shows how much of the backlog is resolved</td></tr>'
            '<tr><td style="padding:4px 8px">Remote-App Coverage</td>'
            '<td style="padding:4px 8px" data-i18n="rpt_tr_mod13_factor_remote">% of remote-access flows (RDP/SSH/VNC) that have a matching allow policy</td></tr>'
            '</table>'
            '</div>'
        )
        html = (
            self._subnote('rpt_tr_readiness_subnote', 'The readiness score estimates how ready the environment is to tighten Enforcement; a higher score usually means tighter convergence.') +
            f'<div style="display:flex;align-items:center;gap:24px;margin-bottom:16px;">'
            f'<div style="font-size:48px;font-weight:700;color:{grade_color};">{grade}</div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:13px;color:var(--slate-50);margin-bottom:4px;"><span data-i18n="rpt_tr_readiness_score">Enforcement Readiness Score:</span> <b>{score}/100</b></div>'
            f'{score_bar}'
            f'</div></div>'
            + dist_html
            + '<h4 data-i18n="rpt_tr_score_breakdown">Score Breakdown by Factor</h4>'
            + _factor_legend
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
        html = (self._subnote('rpt_tr_lateral_intro', 'Covers all lateral-movement analysis including IP-level host connection patterns and App(Env)-level graph risk scoring.') + _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume()) + f'<p><span data-i18n="rpt_tr_lateral_flows">Lateral movement port flows:</span> '
                f'<b>{total:,}</b> ({pct}% <span data-i18n="rpt_tr_lateral_pct">of all flows</span>)</p>')
        service_summary = m.get('service_summary')
        if service_summary is not None and not service_summary.empty:
            html += '<h4 data-i18n="rpt_tr_lateral_by_service">Lateral Port Activity by Service</h4>' + _df_to_html(service_summary)

        # IP-level analysis (consolidated from former mod05)
        ip_talkers = m.get('ip_top_talkers')
        if ip_talkers is not None and not ip_talkers.empty:
            html += (
                self._subnote('rpt_tr_lateral_talkers_subnote', 'IP Top Talkers finds the hosts most active in lateral traffic, handy for checking whether they match known admin nodes.')
                + '<h4 data-i18n="rpt_tr_ip_top_talkers">IP Top Talkers (Host-Level)</h4>'
                + _df_to_html(ip_talkers)
            )
        ip_pairs = m.get('ip_top_pairs')
        if ip_pairs is not None and not ip_pairs.empty:
            html += '<h4 data-i18n="rpt_tr_ip_top_pairs">Top Host Pairs</h4>' + _df_to_html(ip_pairs)

        # App(Env)-level graph analysis
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

    def _mod_draft_actions_html(self) -> str:
        m = self._r.get('mod_draft_actions', {})
        if m.get('skipped'):
            return f'<p class="note">{t("rpt_no_draft_data", default="No draft_policy_decision data available.")}</p>'
        parts = []
        od = m.get('override_deny', {})
        if od.get('count', 0):
            parts.append(f'<h4>Override Deny ({od["count"]} flows)</h4>')
            for rem in od.get('remediation', []):
                parts.append(f'<p>{t(rem["description_key"], default=rem.get("action_code",""))}</p>')
            pairs = od.get('top_pairs', [])
            if pairs:
                parts.append('<table><tr><th>Src</th><th>Dst</th><th>Port</th><th>Flows</th></tr>')
                for p in pairs[:10]:
                    parts.append(f'<tr><td>{p.get("src","")}</td><td>{p.get("dst","")}</td><td>{p.get("port","")}</td><td>{p.get("flows","")}</td></tr>')
                parts.append('</table>')
        pod = m.get('potentially_blocked_by_override_deny', {})
        if pod.get('count', 0):
            parts.append(f'<h4>Potentially Blocked by Override Deny ({pod["count"]} flows)</h4>')
        aab = m.get('allowed_across_boundary', {})
        if aab.get('count', 0):
            parts.append(f'<h4>Allowed Across Boundary ({aab["count"]} flows)</h4>')
        if not parts:
            parts.append('<p>No Override Deny or Allowed Across Boundary flows detected.</p>')
        return ''.join(parts)

    def _mod_enforcement_rollout_html(self) -> str:
        m = self._r.get('mod_enforcement_rollout', {})
        if m.get('skipped'):
            return '<p class="note">No app labels available for rollout ranking.</p>'
        rows = m.get('ranked', [])
        if not rows:
            return '<p class="note">No apps to rank.</p>'
        html = '<table><tr><th>#</th><th>App</th><th>Why Now</th><th>PB Impact</th><th>Allow Rules Needed</th><th>Risk Reduction</th></tr>'
        for r in rows:
            html += (f'<tr><td>{r.get("priority","")}</td><td>{r.get("app","")}</td>'
                     f'<td>{r.get("why_now","").replace("_"," ")}</td>'
                     f'<td>{r.get("expected_default_deny_impact","")}</td>'
                     f'<td>{r.get("required_allow_rules","")}</td>'
                     f'<td>{r.get("risk_reduction","")}</td></tr>')
        html += '</table>'
        return html

    def _mod_ringfence_html(self) -> str:
        m = self._r.get('mod_ringfence', {})
        if m.get('skipped'):
            return '<p class="note">No app labels available for ringfence analysis.</p>'
        top_apps = m.get('top_apps', [])
        if not top_apps:
            return '<p class="note">No apps found.</p>'
        html = '<h4>Top Apps by Flow Volume</h4><table><tr><th>App</th><th>Flows</th></tr>'
        for a in top_apps[:10]:
            app_name = a.get('app', a.get('index', ''))
            flows = a.get('flows', a.get(0, ''))
            html += f'<tr><td>{app_name}</td><td>{flows}</td></tr>'
        html += '</table>'
        return html

    def _mod_change_impact_html(self) -> str:
        from src.report.snapshot_store import read_latest
        from src.report.analysis.mod_change_impact import compare
        mod12 = self._r.get('mod12', {})
        current_kpis = mod12.get('kpis', {})
        if not isinstance(current_kpis, dict) or not current_kpis:
            return '<p class="note">No KPI data available for change comparison.</p>'
        previous = read_latest('traffic', profile=self._profile)
        impact = compare(current_kpis=current_kpis, previous=previous)
        if impact.get('skipped'):
            return f'<p class="note">{t("rpt_change_impact_no_previous", default="No previous snapshot — change impact will appear on the next report run.")}</p>'
        verdict = impact.get('overall_verdict', 'unchanged')
        verdict_color = {'improved': '#22C55E', 'regressed': '#EF4444', 'mixed': '#EAB308'}.get(verdict, '#6B7280')
        html = (f'<p><b>Overall:</b> <span style="color:{verdict_color};font-weight:700">{verdict.upper()}</span>'
                f' (vs {(impact.get("previous_snapshot_at") or "")[:10]})</p>')
        deltas = impact.get('deltas', {})
        if deltas:
            html += '<table><tr><th>KPI</th><th>Previous</th><th>Current</th><th>Delta</th><th>Direction</th></tr>'
            dir_color = {'improved': '#22C55E', 'regressed': '#EF4444', 'unchanged': '#6B7280', 'neutral': '#6B7280'}
            for kpi, d in deltas.items():
                col = dir_color.get(d['direction'], '#6B7280')
                html += (f'<tr><td>{kpi}</td><td>{d["previous"]}</td><td>{d["current"]}</td>'
                         f'<td>{d["delta"]:+}</td>'
                         f'<td style="color:{col};font-weight:600">{d["direction"]}</td></tr>')
            html += '</table>'
        return html

    def _mod_exfil_html(self) -> str:
        m = self._r.get('mod_exfiltration_intel', {})
        if m.get('skipped'):
            return '<p class="note">No managed/unmanaged labels available for exfiltration analysis.</p>'
        parts = [f'<p>Managed→Unmanaged flows: <b>{m.get("managed_to_unmanaged_count", 0)}</b></p>']
        high_vol = m.get('high_volume_exfil', [])
        if high_vol:
            parts.append('<h4>High-Volume Flows (≥1 GB)</h4>')
            parts.append('<table><tr><th>Src</th><th>Dst</th><th>Port</th><th>Bytes</th><th>Flows</th></tr>')
            for r in high_vol:
                parts.append(f'<tr><td>{r.get("src","")}</td><td>{r.get("dst","")}</td>'
                             f'<td>{r.get("port","")}</td><td>{r.get("bytes",""):,}</td>'
                             f'<td>{r.get("flows","")}</td></tr>')
            parts.append('</table>')
        matches = m.get('threat_intel_matches', [])
        if matches:
            parts.append('<h4>Threat Intel Matches</h4>')
            parts.append('<table><tr><th>Src</th><th>Dst</th><th>Port</th><th>Reason</th></tr>')
            for r in matches:
                parts.append(f'<tr><td>{r["src"]}</td><td>{r["dst"]}</td><td>{r["port"]}</td><td>{r["reason"]}</td></tr>')
            parts.append('</table>')
        return ''.join(parts)
