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
from src.report.exporters._exec_summary import render_exec_summary_html
from .table_renderer import render_df_table
from .chart_renderer import render_plotly_html, FirstChartTracker
from .code_highlighter import get_highlight_css
from src.humanize_ext import human_number
from src.report.section_guidance import get_guidance, visible_in
from src.i18n import t, get_language

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
    _sl = get_language()
    for k, v in evidence.items():
        label = STRINGS.get(f"rpt_col_{k}", {}).get(_sl) or k.replace('_', ' ').title()
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

def _trend_deltas_section(deltas: list | None, lang: str = "en") -> str:
    """Heading + chip-bearing table; or a friendly first-run note when empty."""
    _s = lambda k: STRINGS[k].get(lang) or STRINGS[k]["en"]
    heading = f'<h3>{_s("rpt_tr_trend_heading")}</h3>'
    if not deltas:
        return (
            heading
            + '<div class="trend-empty-note" data-trend-empty="true">'
            '<span class="trend-empty-dot" aria-hidden="true"></span>'
            f'<span>{_s("rpt_tr_trend_empty")}</span>'
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
        lang=lang,
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
                no_data_key: str = "rpt_no_data", lang: str = "en") -> str:
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
        lang=lang,
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
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s
        mod12 = self._r.get('mod12', {})
        findings = self._r.get('findings', [])
        n_findings = str(len(findings))

        # nav_html is built after block flags are known (see below)

        # Pre-compute nested blocks to avoid f-string quote conflicts
        _raw_kpis = mod12.get('kpis', [])
        if isinstance(_raw_kpis, dict):
            # New-style: dict of kpi_name -> numeric value (from _security_risk_kpis)
            _kpi_items = [{"label": t(f"mod12_kpi_{k}", default=k.replace("_", " ").title()), "value": v}
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
        ) or f'<p class="note">{_s("rpt_no_findings")}</p>'
        attack_summary_html = self._attack_summary_html(mod12) if profile == 'security_risk' else ''

        generated_at = mod12.get('generated_at', '')
        today_str = str(datetime.date.today())
        _traffic_mod00 = {"kpis": _kpi_items}
        total_flows = self._r.get('mod01', {}).get('total_flows', 0)
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
            ds_label = _s(ds_key)
            ds_color = {"cache": "#22C55E", "api": "#60A5FA"}.get(self._data_source, "#EAB308")
            data_source_pill = (
                f'<div class="summary-pill" style="border-left: 3px solid {ds_color};">'
                f'<span class="summary-pill-label">{ds_label}</span>'
                f'</div>'
            )
            summary_pills = summary_pills.replace('</div>', data_source_pill + '</div>', 1)

        if self._compute_draft:
            draft_pill = f'<span class="report-draft-pill">{t("rpt_hdr_draft_enabled")}</span>'
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
            f'<div style="font-size:14px;color:var(--slate-50);margin-top:4px">'
            f'{_s("rpt_tr_maturity_score")}: {m_score}/100</div></div>'
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
            label = _s(i18n_key) if i18n_key in STRINGS else fallback
            return (f'<a href="#{anchor}">{label}'
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
                (_nav_link('ringfence', 'rpt_tr_nav_ringfence', 'Application Ringfence')
                 if visible_in('mod_ringfence', profile, detail_level) else ''),
                (_nav_link('change_impact', 'rpt_tr_nav_change_impact', 'Change Impact')
                 if visible_in('mod_change_impact', profile, detail_level) else ''),
            ]
        nav_html = '<nav>' + ''.join(_nav_links) + '</nav>'

        exec_html = render_exec_summary_html(_traffic_mod00, report_name='Traffic Report')
        body = (
            exec_html
            + '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_traffic")}</div>'
            + (
                f'<div class="report-profile-badge report-profile-badge--security">{_s("rpt_kicker_security_risk")}</div>'
                if profile == 'security_risk' else
                f'<div class="report-profile-badge report-profile-badge--inventory">{_s("rpt_kicker_network_inventory")}</div>'
            ) +
            f'<h1>{_s("rpt_tr_title")}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} ' + generated_at + '</p></div>'
            + summary_pills +
            f'<h2>{_s("rpt_tr_maturity_heading")}</h2>'
            + maturity_html +
            f'<h2>{_s("rpt_key_metrics")}</h2>'
            '<div class="kpi-grid">' + kpi_cards + '</div>'
            + trend_html +
            f'<h2>{_s("rpt_key_findings")}</h2>' + key_findings_html +
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
            (self._section('ringfence', 'rpt_mod_ringfence_title', 'Application Ringfence',
                           render_section_guidance('mod_ringfence', profile, detail_level) + self._mod_ringfence_html(),
                           '', '') + '\n'
             if visible_in('mod_ringfence', profile, detail_level) else '') +
            (self._section('change_impact', 'rpt_mod_change_impact_title', 'Change Impact',
                           render_section_guidance('mod_change_impact', profile, detail_level) + self._mod_change_impact_html(),
                           '', '') + '\n'
             if visible_in('mod_change_impact', profile, detail_level) else '') +
            ((
            '<section id="findings" class="card">'
            f'<h2>{_s("rpt_tr_sec_findings")} ({n_findings})</h2>'
            + self._findings_html() +
            '</section>\n'
            ) if profile == 'security_risk' else '') +
            f'<footer>{_s("rpt_tr_footer")} &middot; {today_str}</footer>'
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
        h2_text = self._s(i18n_key)
        if h2_text == i18n_key:
            h2_text = title
        intro_html = ''
        if intro_key:
            intro_text = self._s(intro_key)
            if intro_text == intro_key:
                intro_text = intro_en
            intro_html = f'<p class="section-intro">{intro_text}</p>'
        return (
            f'<section id="{id_}" class="card">'
            f'<h2>{h2_text}</h2>'
            f'{intro_html}{content}</section>'
        )

    def _trend_deltas_html(self) -> str:
        return _trend_deltas_section(self._r.get("_trend_deltas"), lang=self._lang)

    def _subnote(self, i18n_key: str, en_text: str = "") -> str:
        text = self._s(i18n_key)
        if text == i18n_key:
            text = en_text
        return f'<p class="note" style="font-size:12px;">{text}</p>'

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

        _s = self._s
        return (
            f'<h2>{_s("rpt_tr_attack_summary")}</h2>'
            f'<h3>{_s("rpt_tr_boundary_breaches")}</h3>' + _rows(mod12.get('boundary_breaches', [])) +
            f'<h3>{_s("rpt_tr_suspicious_pivot_behavior")}</h3>' + _rows(mod12.get('suspicious_pivot_behavior', [])) +
            f'<h3>{_s("rpt_tr_blast_radius")}</h3>' + _rows(mod12.get('blast_radius', [])) +
            f'<h3>{_s("rpt_tr_blind_spots")}</h3>' + _rows(mod12.get('blind_spots', [])) +
            f'<h3>{_s("rpt_tr_action_matrix")}</h3>' + action_html
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
        _s = self._s
        m = self._r.get('mod01', {})
        return (
            self._subnote('rpt_tr_mod01_intro')
            + self._mod01_summary_table(m)
            + self._subnote('rpt_tr_top_ports_subnote')
            + f'<h3>{_s("rpt_tr_top_ports")}</h3>'
            + _df_to_html(m.get('top_ports'), lang=self._lang)
        )

    def _mod02_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod02', {})
        out = self._subnote('rpt_tr_mod02_intro') + _df_to_html(m.get('summary'), lang=_lang) + _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume())
        pc = m.get('port_coverage')
        if pc is not None and hasattr(pc, 'empty') and not pc.empty:
            out += self._subnote('rpt_tr_port_coverage_subnote') + f'<h3>{_s("rpt_tr_port_coverage")}</h3>' + _df_to_html(pc, lang=_lang)
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
                f'<h4>{_s("rpt_tr_top_app_flows")}</h4>',
                _df_to_html(dm.get('top_app_flows'), lang=_lang),
                f'<h4>{_s("rpt_mod02_top_inbound_ports")} ({status})</h4>',
                _df_to_html(dm.get('top_inbound_ports'), lang=_lang),
                f'<h4>{_s("rpt_mod02_top_outbound_ports")} ({status})</h4>',
                _df_to_html(dm.get('top_outbound_ports'), lang=_lang),
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

        _s = self._s
        _lang = self._lang
        stats = (
            '<div class="coverage-grid">'
            + _cov_stat(_s('rpt_tr_enforced_coverage'), str(enforced_cov) + '%')
            + _cov_stat(t('rpt_pb_label'), str(staged_cov) + '%')
            + _cov_stat(_s('rpt_tr_true_gap'), str(true_gap) + '%')
            + (_cov_stat(_s('rpt_tr_inbound_coverage'), str(inb_cov) + '%') if inb_cov is not None else '')
            + (_cov_stat(_s('rpt_tr_outbound_coverage'), str(outb_cov) + '%') if outb_cov is not None else '')
            + _cov_stat(_s('rpt_col_uncovered_flows'), str(m.get('total_uncovered', 0)))
            + '</div>'
            + bar_html
            + (f'<p class="note">{t("rpt_pb_explainer")}</p>' if staged_cov > 0 else '')
        )
        out = (
            stats
            + self._subnote('rpt_tr_top_uncovered_subnote')
            + f'<h3>{_s("rpt_tr_top_uncovered")}</h3>'
            + _df_to_html(m.get('top_flows'), lang=_lang)
        )
        up = m.get('uncovered_ports')
        if up is not None and hasattr(up, 'empty') and not up.empty:
            out += self._subnote('rpt_tr_port_gaps_subnote') + f'<h3>{_s("rpt_tr_port_gaps")}</h3>' + _df_to_html(up, lang=_lang)
        us = m.get('uncovered_services')
        if us is not None and hasattr(us, 'empty') and not us.empty:
            out += self._subnote('rpt_tr_service_gaps_subnote') + f'<h3>{_s("rpt_tr_service_gaps")}</h3>' + _df_to_html(us, lang=_lang)
        out += f'<h3>{_s("rpt_tr_by_rec")}</h3>' + _df_to_html(m.get('by_recommendation'), lang=_lang)
        return out

    def _mod04_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod04', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'

        out = f'<p>{_s("rpt_tr_risk_flows")} <b>{m.get("risk_flows_total", 0)}</b></p>'

        part_e = m.get('part_e_investigation')
        if part_e is not None and hasattr(part_e, 'empty') and not part_e.empty:
            out += (
                '<div style="background:#fff3cd;border-left:4px solid var(--gold);'
                'padding:12px 16px;margin:12px 0;border-radius:4px">'
                f'<b>{_s("rpt_tr_investigation_title")}</b><br>'
                f'<span style="font-size:12px">{_s("rpt_tr_investigation_desc")}</span>'
                '</div>'
                + _df_to_html(part_e, 'Risk Level', lang=_lang)
            )
        else:
            out += (
                '<div style="background:#d4edda;border-left:4px solid var(--green-80);'
                'padding:12px 16px;margin:12px 0;border-radius:4px">'
                f'<b>{_s("rpt_tr_no_investigation")}</b>'
                '</div>'
            )

        out += (
            f'<h3>{_s("rpt_tr_risk_summary")}</h3>'
            + _df_to_html(m.get('part_a_summary'), 'Risk Level', lang=_lang) +
            f'<h3>{_s("rpt_tr_per_port")}</h3>'
            + _df_to_html(m.get('part_b_per_port'), 'Risk Level', lang=_lang) +
            f'<h3>{_s("rpt_tr_host_exposure")}</h3>'
            + f'<p class="note" style="font-size:11px">{_s("rpt_tr_host_exposure_note")}</p>'
            + _df_to_html(m.get('part_d_host_exposure'), lang=_lang)
        )
        return out

    def _mod05_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod05', {})
        if not isinstance(m, dict) or m.get('total_lateral_flows', 0) == 0:
            return f'<p class="note">{_s("rpt_no_lateral")}</p>'
        return (
            self._subnote('rpt_tr_remote_services_subnote')
            + _df_to_html(m.get('by_service'), lang=_lang)
            + self._subnote('rpt_tr_remote_talkers_subnote')
            + f'<h3>{_s("rpt_tr_top_talkers")}</h3>'
            + _df_to_html(m.get('top_talkers'), lang=_lang)
        )

    def _mod06_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod06', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        out = ''
        if m.get('user_data_available'):
            out += self._subnote('rpt_tr_top_users_subnote') + f'<h3>{_s("rpt_tr_top_users")}</h3>' + _df_to_html(m.get('top_users'), lang=_lang)
        if m.get('process_data_available'):
            out += self._subnote('rpt_tr_top_processes_subnote') + f'<h3>{_s("rpt_tr_top_processes")}</h3>' + _df_to_html(m.get('top_processes'), lang=_lang)
        return out or f'<p class="note">{_s("rpt_no_user_proc")}</p>'

    def _mod07_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod07', {})
        out = ''
        for key, data in m.get('matrices', {}).items():
            out += f'<h3>{_s("rpt_tr_label_key")} {key.upper()}</h3>'
            if 'note' in data:
                out += f'<p class="note">{data["note"]}</p>'
            else:
                kv = (f'{_s("rpt_tr_same_value")} {data.get("same_value_flows",0)} · '
                      f'{_s("rpt_tr_cross_value")} {data.get("cross_value_flows",0)}')
                out += f'<p>{kv}</p>{_df_to_html(data.get("top_cross_pairs"), lang=_lang)}'
        out += _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume())
        return out or f'<p class="note">{_s("rpt_no_matrix")}</p>'

    def _mod08_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod08', {})
        out = (
            '<div class="coverage-grid">'
            + _cov_stat(_s('rpt_tr_unmanaged_flow_stat'), str(m.get('unmanaged_flow_count', 0)) + ' (' + str(m.get('unmanaged_pct', 0)) + '%)')
            + _cov_stat(_s('rpt_tr_unique_unmanaged_src'), str(m.get('unique_unmanaged_src', 0)))
            + _cov_stat(_s('rpt_tr_unique_unmanaged_dst'), str(m.get('unique_unmanaged_dst', 0)))
            + '</div>'
            + self._subnote('rpt_tr_unmanaged_subnote')
            + f'<h3>{_s("rpt_tr_top_unmanaged")}</h3>'
            + _df_to_html(m.get('top_unmanaged_src'), lang=_lang)
        )
        pa = m.get('per_dst_app')
        if pa is not None and hasattr(pa, 'empty') and not pa.empty:
            out += f'<h3>{_s("rpt_tr_managed_apps_unmanaged")}</h3>' + _df_to_html(pa, lang=_lang)
        pp = m.get('per_port_proto')
        if pp is not None and hasattr(pp, 'empty') and not pp.empty:
            out += f'<h3>{_s("rpt_tr_exposed_ports_proto")}</h3>' + _df_to_html(pp, lang=_lang)
        sp = m.get('src_port_detail')
        if sp is not None and hasattr(sp, 'empty') and not sp.empty:
            out += f'<h3>{_s("rpt_tr_unmanaged_src_port")}</h3>' + _df_to_html(sp, lang=_lang)
        mh = m.get('managed_hosts_targeted_by_unmanaged')
        if mh is not None and hasattr(mh, 'empty') and not mh.empty:
            out += f'<h3>{_s("rpt_tr_managed_targeted")}</h3>' + _df_to_html(mh, lang=_lang)
        return out

    def _mod09_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod09', {})
        return (
            self._subnote('rpt_tr_distribution_subnote')
            + f'<h3>{_s("rpt_tr_port_dist")}</h3>'
            + _df_to_html(m.get('port_distribution'), lang=_lang) +
            f'<h3>{_s("rpt_tr_proto_dist")}</h3>'
            + _df_to_html(m.get('proto_distribution'), lang=_lang)
        )

    def _mod10_html(self):
        _s = self._s
        _lang = self._lang
        m = self._r.get('mod10', {})
        if m.get('note'):
            return f'<p class="note">{m["note"]}</p>'
        return (
            self._subnote('rpt_tr_allowed_flows_subnote')
            + _df_to_html(m.get('top_app_flows'), lang=_lang)
            + _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume())
            + self._subnote('rpt_tr_audit_flags_subnote')
            + f'<h3>{_s("rpt_tr_audit_flags")} ({m.get("audit_flag_count", 0)})</h3>'
            + _df_to_html(m.get('audit_flags'), lang=_lang)
        )

    def _mod11_html(self):
        m = self._r.get('mod11', {})
        if not m.get('bytes_data_available', False):
            return f'<p class="note">{m.get("note","No byte data.")}</p>'

        max_bw = m.get('max_bandwidth_mbps')
        avg_bw = m.get('avg_bandwidth_mbps')
        p95_bw = m.get('p95_bandwidth_mbps')

        _s = self._s
        _lang = self._lang
        out = '<div class="coverage-grid">'
        out += _cov_stat(_s('rpt_tr_total_volume'), _fmt_bytes(m.get('total_bytes', 0)))
        if max_bw is not None:
            out += _cov_stat(_s('rpt_tr_max_bw'), _fmt_bw(max_bw))
        if avg_bw is not None:
            out += _cov_stat(_s('rpt_tr_avg_bw'), _fmt_bw(avg_bw))
        if p95_bw is not None:
            out += _cov_stat(_s('rpt_tr_p95_bw'), _fmt_bw(p95_bw))
        out += '</div>'

        out += self._subnote('rpt_tr_bandwidth_subnote')
        out += f'<h3>{_s("rpt_tr_top_by_bytes")}</h3>' + _df_to_html(m.get('top_by_bytes'), lang=_lang)

        tb = m.get('top_bandwidth')
        if tb is not None and hasattr(tb, 'empty') and not tb.empty:
            out += f'<h3>{_s("rpt_tr_top_by_bw")}</h3>' + _df_to_html(tb, lang=_lang)

        anom = m.get('byte_ratio_anomalies')
        if anom is not None and hasattr(anom, 'empty') and not anom.empty:
            threshold = m.get('anomaly_threshold_bytes_per_conn')
            thresh_str = (f' &nbsp;<span style="font-weight:400;font-size:11px;color:var(--slate-50)">'
                          f'P95 ≥ {_fmt_bytes(threshold)}/conn</span>'
                          if threshold else '')
            out += (
                f'<h3>{_s("rpt_tr_anomalies")}{thresh_str}</h3>'
                f'<p class="note" style="font-size:11px">{_s("rpt_tr_anomalies_note")}</p>'
                + _df_to_html(anom, lang=_lang)
            )

        return out

    def _findings_html(self):
        from src.report.exporters.report_i18n import STRINGS as _S
        _s = self._s
        findings = self._r.get('findings', [])
        if not findings:
            return f'<p class="note">{_s("rpt_no_findings_detail")}</p>'

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
            cat_name = _s(name_key) if name_key in _S else cat_name_en
            cat_desc = _s(desc_key) if desc_key in _S else cat_desc_en
            cards_html += (
                f'<div class="cat-group">'
                f'<h3 style="margin-bottom:6px;">{cat_name}</h3>'
                f'<p style="font-size:12px;color:var(--slate-50);margin-bottom:14px;">{cat_desc}</p>'
            )
            for f in cat_findings:
                _rule_title, rule_how = _RULE_DESCRIPTIONS.get(f.rule_id, (f.rule_name, ''))
                evidence_html = _format_evidence(f.evidence)
                rule_name_key = f'rpt_rule_{f.rule_id}_name'
                rule_name = _s(rule_name_key) if rule_name_key in _S else f.rule_name
                cards_html += (
                    f'<div class="finding-card sev-{f.severity}">'
                    f'<div class="finding-header">'
                    f'<span class="badge badge-{f.severity}">{f.severity}</span>'
                    f'<span class="finding-rule-id">{f.rule_id}</span>'
                    f'<span class="finding-title">{rule_name}</span>'
                    f'</div>'
                )
                if rule_how:
                    how_key = f'rpt_rule_{f.rule_id}_how'
                    how_text = _s(how_key) if how_key in _S else rule_how
                    cards_html += (
                        f'<p style="font-size:11px;color:var(--slate-50);margin-bottom:8px;">'
                        f'<b>{_s("rpt_rule_check_label")}</b>'
                        f' <span>{how_text}</span></p>'
                    )
                cards_html += (
                    f'<p class="finding-desc">{f.description}</p>'
                    + evidence_html
                    + f'<div class="finding-rec">'
                    f'<b>{_s("rpt_recommendation_label")}</b> '
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
                label = STRINGS.get(f"rpt_enforce_mode_{mode}", {}).get(self._lang) or mode.replace('_', ' ').title()
                bars.append(
                    f'<div style="width:{pct}%;background:{color};min-width:40px" title="{label}: {count}">{count}</div>'
                )
            _s_local = self._s
            dist_html = (
                f'<h4>{_s_local("rpt_tr_enforcement_dist")}</h4>'
                '<div style="display:flex;height:32px;border-radius:6px;overflow:hidden;margin:8px 0 16px 0;'
                'font-size:12px;font-weight:600;color:#fff;text-align:center;line-height:32px">'
                + ''.join(bars)
                + '</div>'
                '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px;font-size:13px">'
                + ''.join(
                    f'<span><span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
                    f'background:{mode_colors.get(md, "#6B7280")};margin-right:4px"></span>'
                    f'{STRINGS.get(f"rpt_enforce_mode_{md}", {{}}).get(self._lang) or md.replace("_", " ").title()}: {ct}</span>'
                    for md, ct in sorted(enforcement_dist.items(), key=lambda x: {'full': 0, 'selective': 1, 'visibility_only': 2}.get(x[0], 9))
                )
                + '</div>'
            )

        _s_local = self._s
        _factor_legend = (
            '<div style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;'
            'padding:12px 16px;margin-bottom:12px;font-size:13px;line-height:1.6">'
            f'<b>{_s_local("rpt_mod13_col_guide_title")}</b>'
            '<ul style="margin:6px 0 0 0;padding-left:18px">'
            f'<li>{_s_local("rpt_mod13_col_guide_factor")}</li>'
            f'<li>{_s_local("rpt_mod13_col_guide_weight")}</li>'
            f'<li>{_s_local("rpt_mod13_col_guide_ratio")}</li>'
            f'<li>{_s_local("rpt_mod13_col_guide_score")}</li>'
            '</ul>'
            '<table style="margin-top:10px;font-size:12px;border-collapse:collapse;width:100%">'
            '<tr style="border-bottom:1px solid var(--border)">'
            f'<th style="text-align:left;padding:4px 8px">{_s_local("rpt_col_factor")}</th>'
            f'<th style="text-align:left;padding:4px 8px">{_s_local("rpt_tr_what_it_measures")}</th>'
            '</tr>'
            f'<tr><td style="padding:4px 8px">{_s_local("rpt_factor_policy_coverage")}</td>'
            f'<td style="padding:4px 8px">{_s_local("rpt_mod13_col_guide_policy")}</td></tr>'
            f'<tr style="background:var(--row-alt)"><td style="padding:4px 8px">{_s_local("rpt_factor_ringfence_maturity")}</td>'
            f'<td style="padding:4px 8px">{_s_local("rpt_mod13_col_guide_ringfence")}</td></tr>'
            f'<tr><td style="padding:4px 8px">{_s_local("rpt_factor_enforcement_mode")}</td>'
            f'<td style="padding:4px 8px">{_s_local("rpt_mod13_col_guide_enforcement")}</td></tr>'
            f'<tr style="background:var(--row-alt)"><td style="padding:4px 8px">{_s_local("rpt_factor_staged_readiness")}</td>'
            f'<td style="padding:4px 8px">{_s_local("rpt_mod13_col_guide_staged")}</td></tr>'
            f'<tr><td style="padding:4px 8px">{_s_local("rpt_factor_remote_app_coverage")}</td>'
            f'<td style="padding:4px 8px">{_s_local("rpt_mod13_col_guide_remote")}</td></tr>'
            '</table>'
            '</div>'
        )
        _s = self._s
        _lang = self._lang
        html = (
            self._subnote('rpt_tr_readiness_subnote') +
            f'<div style="display:flex;align-items:center;gap:24px;margin-bottom:16px;">'
            f'<div style="font-size:48px;font-weight:700;color:{grade_color};">{grade}</div>'
            f'<div style="flex:1;">'
            f'<div style="font-size:13px;color:var(--slate-50);margin-bottom:4px;">{_s("rpt_tr_readiness_score")} <b>{score}/100</b></div>'
            f'{score_bar}'
            f'</div></div>'
            + dist_html
            + f'<h4>{_s("rpt_tr_score_breakdown")}</h4>'
            + _factor_legend
            + _df_to_html(
                factor_table.rename(columns={"Factor": "Factor", "Weight": "Weight", "Score": "Score", "Ratio %": "Ratio %"}) if factor_table is not None else factor_table,
                lang=_lang,
            )
        )
        if app_env_scores is not None and not app_env_scores.empty:
            _aes = app_env_scores.rename(columns={
                "app_env_key": "App (Env)",
                "readiness_score": "Readiness Score",
                "policy_coverage_ratio": "Policy Coverage %",
                "ringfence_maturity_ratio": "Ringfence Maturity %",
                "enforcement_mode_ratio": "Enforcement Mode %",
                "staged_readiness_ratio": "Staged Readiness %",
                "remote_app_coverage_ratio": "Remote-App Coverage %",
                "flow_count": "Flows",
                "connection_count": "Connections",
                "grade": "Grade",
            })
            html += f'<h4>{_s("rpt_tr_app_env_readiness")}</h4>' + _df_to_html(_aes, lang=_lang)
        if recommendations is not None and not recommendations.empty:
            _rec = recommendations.rename(columns={
                "Priority": "Priority",
                "App (Env)": "App (Env)",
                "Issue": "Issue",
                "Action": "Action",
                "Action Code": "Action Code",
            })
            html += f'<h4>{_s("rpt_tr_remediation_rec")}</h4>' + _df_to_html(_rec, lang=_lang)
        return html

    def _mod14_html(self):
        m = self._r.get('mod14', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'
        _s = self._s
        _lang = self._lang
        html = (
            f'<p>{_s("rpt_tr_apps_analysed")} <b>{m.get("total_apps", 0)}</b> · '
            f'{_s("rpt_tr_comm_edges")} <b>{m.get("total_edges", 0)}</b></p>'
        )
        role_summary = m.get('role_summary')
        if role_summary is not None and not role_summary.empty:
            html += f'<h4>{_s("rpt_tr_role_distribution")}</h4>' + _df_to_html(role_summary, lang=_lang)
        hub_apps = m.get('hub_apps')
        if hub_apps is not None and not hub_apps.empty:
            html += f'<h4>{_s("rpt_tr_hub_apps")}</h4>' + _df_to_html(hub_apps, lang=_lang)
        top_apps = m.get('top_apps')
        if top_apps is not None and not top_apps.empty:
            html += f'<h4>{_s("rpt_tr_top_apps_infra")}</h4>' + _df_to_html(top_apps, lang=_lang)
        top_edges = m.get('top_edges')
        if top_edges is not None and not top_edges.empty:
            html += f'<h4>{_s("rpt_tr_top_comm_paths")}</h4>' + _df_to_html(top_edges, lang=_lang)
        return html

    def _mod15_html(self):
        m = self._r.get('mod15', {})
        if 'error' in m:
            return f'<p class="note">{m["error"]}</p>'
        _s = self._s
        _lang = self._lang
        total = m.get('total_lateral_flows', 0)
        pct = m.get('lateral_pct', 0)
        html = (self._subnote('rpt_tr_lateral_intro', 'Covers all lateral-movement analysis including IP-level host connection patterns and App(Env)-level graph risk scoring.') + _render_chart_for_html(m.get('chart_spec'), include_js=self._chart_tracker.consume()) + f'<p>{_s("rpt_tr_lateral_flows")} '
                f'<b>{total:,}</b> ({pct}% {_s("rpt_tr_lateral_pct")})</p>')
        service_summary = m.get('service_summary')
        if service_summary is not None and not service_summary.empty:
            html += f'<h4>{_s("rpt_tr_lateral_by_service")}</h4>' + _df_to_html(service_summary, lang=_lang)

        # IP-level analysis (consolidated from former mod05)
        ip_talkers = m.get('ip_top_talkers')
        if ip_talkers is not None and not ip_talkers.empty:
            html += (
                self._subnote('rpt_tr_lateral_talkers_subnote', 'IP Top Talkers finds the hosts most active in lateral traffic, handy for checking whether they match known admin nodes.')
                + f'<h4>{_s("rpt_tr_ip_top_talkers")}</h4>'
                + _df_to_html(ip_talkers, lang=_lang)
            )
        ip_pairs = m.get('ip_top_pairs')
        if ip_pairs is not None and not ip_pairs.empty:
            html += f'<h4>{_s("rpt_tr_ip_top_pairs")}</h4>' + _df_to_html(ip_pairs, lang=_lang)

        # App(Env)-level graph analysis
        fan_out = m.get('fan_out_sources')
        if fan_out is not None and not fan_out.empty:
            html += f'<h4>{_s("rpt_tr_fan_out")}</h4>' + _df_to_html(fan_out, lang=_lang)
        allowed_lateral = m.get('allowed_lateral_flows')
        if allowed_lateral is not None and not allowed_lateral.empty:
            html += f'<h4>{_s("rpt_tr_allowed_lateral")}</h4>' + _df_to_html(allowed_lateral, lang=_lang)
        source_risk = m.get('source_risk_scores')
        if source_risk is not None and not source_risk.empty:
            html += f'<h4>{_s("rpt_tr_top_risk_sources")}</h4>' + _df_to_html(source_risk, lang=_lang)
        bridge_nodes = m.get('bridge_nodes')
        if bridge_nodes is not None and not bridge_nodes.empty:
            html += f'<h4>{_s("rpt_mod15_bridge_nodes")}</h4>' + _df_to_html(bridge_nodes, lang=_lang)
        reachable_nodes = m.get('top_reachable_nodes')
        if reachable_nodes is not None and not reachable_nodes.empty:
            html += f'<h4>{_s("rpt_mod15_top_reachable")}</h4>' + _df_to_html(reachable_nodes, lang=_lang)
        attack_paths = m.get('attack_paths')
        if attack_paths is not None and not attack_paths.empty:
            html += f'<h4>{_s("rpt_mod15_attack_paths")}</h4>' + _df_to_html(attack_paths, lang=_lang)
        app_chains = m.get('app_chains')
        if app_chains is not None and not app_chains.empty:
            html += f'<h4>{_s("rpt_tr_app_chains")}</h4>' + _df_to_html(app_chains, lang=_lang)
        return html

    def _mod_ringfence_html(self) -> str:
        _s = self._s
        m = self._r.get('mod_ringfence', {})
        if m.get('skipped'):
            return f'<p class="note">{_s("rpt_mod_ringfence_no_labels")}</p>'
        top_apps = m.get('top_apps', [])
        if not top_apps:
            return f'<p class="note">{_s("rpt_mod_ringfence_no_apps")}</p>'
        html = (f'<h4>{_s("rpt_mod_ringfence_top_apps_h4")}</h4>'
                f'<table><tr><th>{_s("rpt_col_app")}</th><th>{_s("rpt_col_flows")}</th></tr>')
        for a in top_apps[:10]:
            app_name = a.get('app', a.get('index', ''))
            flows = a.get('flows', a.get(0, ''))
            html += f'<tr><td>{app_name}</td><td>{flows}</td></tr>'
        html += '</table>'
        return html

    def _mod_change_impact_html(self) -> str:
        _s = self._s
        from src.report.snapshot_store import read_latest
        from src.report.analysis.mod_change_impact import compare
        mod12 = self._r.get('mod12', {})
        current_kpis = mod12.get('kpis', {})
        if not isinstance(current_kpis, dict) or not current_kpis:
            return f'<p class="note">{_s("rpt_mod_change_impact_no_kpi")}</p>'
        previous = read_latest('traffic', profile=self._profile)
        impact = compare(current_kpis=current_kpis, previous=previous)
        if impact.get('skipped'):
            return f'<p class="note">{t("rpt_change_impact_no_previous", default="No previous snapshot — change impact will appear on the next report run.")}</p>'
        verdict = impact.get('overall_verdict', 'unchanged')
        verdict_color = {'improved': '#22C55E', 'regressed': '#EF4444', 'mixed': '#EAB308'}.get(verdict, '#6B7280')
        dir_label = {
            'improved': _s('rpt_change_direction_improved'),
            'regressed': _s('rpt_change_direction_regressed'),
            'unchanged': _s('rpt_change_direction_unchanged'),
            'neutral': _s('rpt_change_direction_neutral'),
        }
        html = (f'<p><b>{_s("rpt_mod_change_impact_overall_label")}:</b>'
                f' <span style="color:{verdict_color};font-weight:700">{dir_label.get(verdict, verdict).upper()}</span>'
                f' (vs {(impact.get("previous_snapshot_at") or "")[:10]})</p>')
        deltas = impact.get('deltas', {})
        if deltas:
            html += (f'<table><tr>'
                     f'<th>{_s("rpt_col_kpi")}</th><th>{_s("rpt_col_previous")}</th>'
                     f'<th>{_s("rpt_col_current")}</th><th>{_s("rpt_col_delta")}</th>'
                     f'<th>{_s("rpt_col_direction")}</th></tr>')
            dir_color = {'improved': '#22C55E', 'regressed': '#EF4444', 'unchanged': '#6B7280', 'neutral': '#6B7280'}
            for kpi, d in deltas.items():
                col = dir_color.get(d['direction'], '#6B7280')
                html += (f'<tr><td>{kpi}</td><td>{d["previous"]}</td><td>{d["current"]}</td>'
                         f'<td>{d["delta"]:+}</td>'
                         f'<td style="color:{col};font-weight:600">{dir_label.get(d["direction"], d["direction"])}</td></tr>')
            html += '</table>'
        return html

