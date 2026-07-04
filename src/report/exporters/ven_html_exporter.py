"""
Self-contained HTML report for the VEN Status Inventory Report.
"""
from __future__ import annotations

import datetime
import html
from loguru import logger
import os

import pandas as pd

from .report_css import TABLE_JS, build_css
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS
from .table_renderer import render_df_table
from .chart_renderer import render_matplotlib_svg
from .code_highlighter import get_highlight_css
from .html_exporter import render_section_guidance
from src.i18n import t
from src.report.section_guidance import visible_in
from src.humanize_ext import human_number
from src.report.exporters._exec_summary import render_exec_summary_html
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.html_exporter import _trend_deltas_section

_CSS = build_css("ven")
_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'
_REPORT_DETAIL_LEVEL = "full"

def _policy_sync_badge(val: str) -> str:
    v = str(val).lower().strip()
    if v == "synced":
        return f'<span class="badge-synced">{val}</span>'
    if v == "staged":
        return f'<span class="badge-staged">{val}</span>'
    if v and v not in ("none", "nan"):
        return f'<span class="badge-unsynced">{val}</span>'
    return ""


# Ransomware-posture cell styling (reuse the report's shared badge palette).
_RWP_SEV_BADGE = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM",
                  "low": "LOW", "fully_protected": "LOW"}
_RWP_SEV_BORDER = {"critical": "var(--red)", "high": "var(--red-80)",
                   "medium": "var(--gold-110)", "low": "var(--green)",
                   "fully_protected": "var(--green)"}
_RWP_PROT_BADGE = {"unprotected": "badge-unsynced", "protected_open": "badge-staged",
                   "protected_closed": "badge-synced"}


def _rwp_severity_badge(sev: str) -> str:
    cls = _RWP_SEV_BADGE.get(str(sev).lower().strip())
    label = html.escape(str(sev) or "—")
    return f'<span class="badge badge-{cls}">{label}</span>' if cls else label


def _rwp_protection_badge(state: str) -> str:
    cls = _RWP_PROT_BADGE.get(str(state).lower().strip())
    label = html.escape(str(state) or "—")
    return f'<span class="{cls}">{label}</span>' if cls else label

class VenHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None,
                 profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en",
                 pce_url: str = "", org_name: str = ""):
        self._r = results
        self._df = df
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_ven_status_{ts}.html"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._build())
        logger.info("[VenHtmlExporter] Saved: {}", filepath)
        return filepath

    def _build(self, profile: str = "", detail_level: str = "") -> str:
        profile = profile or self._profile
        detail_level = _REPORT_DETAIL_LEVEL
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s

        kpis = self._r.get("kpis", [])
        gen_at = self._r.get("generated_at", "")
        _ven_mod00 = {"kpis": kpis}
        today_str = str(datetime.date.today())

        nav_html = (
            '<aside class="report-toc screen-only">'
            f'<h3>{_s("rpt_nav_contents")}</h3>'
            '<ol>'
            f'<li><a href="#summary">{_s("rpt_ven_nav_summary")}</a></li>'
            f'<li><a href="#online">{_s("rpt_ven_nav_online")}</a></li>'
            f'<li><a href="#offline">{_s("rpt_ven_nav_offline")}</a></li>'
            f'<li><a href="#lost-today">{_s("rpt_ven_nav_lost_today")}</a></li>'
            f'<li><a href="#lost-yest">{_s("rpt_ven_nav_lost_yest")}</a></li>'
            '</ol>'
            f'<button class="print-btn" onclick="window.print()">{_s("rpt_nav_print_pdf")}</button>'
            '</aside>'
        )

        kpi_cards_parts = []
        for k in kpis:
            key = k.get("i18n_key") or ""
            label = _s(key) if key and key in STRINGS else k.get("label", key)
            kpi_cards_parts.append(
                '<div class="kpi-card">'
                f'<div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{k["value"]}</div>'
                "</div>"
            )
        kpi_cards = "".join(kpi_cards_parts)

        df_online = self._r.get("online")
        df_offline = self._r.get("offline")
        df_today = self._r.get("lost_today")
        df_yest = self._r.get("lost_yesterday")
        online_count = len(df_online) if df_online is not None and not df_online.empty else 0
        offline_count = len(df_offline) if df_offline is not None and not df_offline.empty else 0
        today_count = len(df_today) if df_today is not None and not df_today.empty else 0
        yest_count = len(df_yest) if df_yest is not None and not df_yest.empty else 0

        status_chart_html = ""
        total_vens = online_count + offline_count + today_count + yest_count
        if total_vens > 0:
            try:
                spec = {
                    "type": "bar",
                    "title": "VEN Status Distribution",
                    "data": {
                        "labels": [t("chart_ven_online", lang=self._lang), t("chart_ven_offline", lang=self._lang), t("chart_ven_lost_24h", lang=self._lang), t("chart_ven_lost_48h", lang=self._lang)],
                        "values": [online_count, offline_count, today_count, yest_count],
                    },
                }
                svg = render_matplotlib_svg(spec, lang=self._lang)
                if svg:
                    status_chart_html = f'<figure class="chart-static">{svg}</figure>'
            except Exception:
                pass

        def _df_to_html(df, no_data_key: str = "rpt_no_records") -> str:
            def _render_cell(col, val, _row):
                val_str = "" if val is None or str(val) in ("None", "nan") else str(val)
                col_key = str(col).strip().lower().replace(" ", "_")
                if col_key == "policy_sync":
                    return _policy_sync_badge(val_str)
                if col_key == "ip" and ", " in val_str:
                    # Multi-homed hosts blow out the column width; show the first IP
                    # plus a +N chip, full list preserved in the title (and in CSV).
                    parts = val_str.split(", ")
                    first = html.escape(parts[0])
                    full = html.escape(val_str, quote=True)
                    return (f'<span title="{full}">{first} '
                            f'<span class="ip-more">+{len(parts) - 1}</span></span>')
                return html.escape(val_str)
            return render_df_table(df, col_i18n=_COL_I18N, no_data_key=no_data_key,
                                   render_cell=_render_cell, lang=_sl)

        def _online_summary_html(df) -> str:
            # spec K2：Online 章不再列逐台明細（明細留給 XLSX/CSV），改為版本
            # 分布小表（online 桶限定，與 Estate 段的全 estate by_version 不同語意）。
            if df is None or df.empty or "VEN Version" not in df.columns:
                version_table = f'<p>{_s("rpt_no_records")}</p>'
            else:
                counts = (df["VEN Version"].fillna("").astype(str)
                          .replace("", "(unknown)").value_counts())
                rows = "".join(
                    f"<tr><td>{html.escape(str(ver))}</td><td>{cnt}</td></tr>"
                    for ver, cnt in counts.items()
                )
                version_table = (
                    '<div class="report-table-panel report-table-panel--compact">'
                    f'<div class="report-table-wrap"><table class="report-table">'
                    f'<thead><tr><th>{_s("rpt_col_ven_version")}</th>'
                    f'<th>{_s("rpt_ei_count")}</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table></div></div>'
                )
            heading = f'{_s("rpt_ven_by_version")} — {_s("rpt_ven_sec_online_title")}'
            note_html = f'<p class="section-intro">{_s("rpt_ven_online_detail_note")}</p>'
            return f'<h3>{heading}</h3>{version_table}{note_html}'

        exec_html = render_exec_summary_html(_ven_mod00, report_name=t('gui_btn_ven_report', lang=self._lang), lang=self._lang)
        _deltas = (self._r or {}).get("_trend_deltas") or []
        if _deltas:
            exec_html += _trend_deltas_section(
                _deltas, self._lang, mismatch=(self._r or {}).get("_trend_mismatch"),
            )
        body = (
            exec_html
            + '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_ven")}</div>'
            f'<h1>{_s("rpt_ven_title")}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} '
            + gen_at
            + "</p></div>"
            + self._summary_pills(online_count, offline_count, today_count, yest_count)
            + status_chart_html
            + "</section>\n"
            + self._section("online", "rpt_ven_sec_online_title", online_count, _online_summary_html(df_online), "rpt_ven_sec_online_intro", "online", "ven_online_inventory")
            + "\n"
            + (self._section("offline", "rpt_ven_sec_offline_title", offline_count, _df_to_html(df_offline), "rpt_ven_sec_offline_intro", "offline", "ven_offline")
               + "\n"
               if visible_in('ven_offline', profile, detail_level) else '')
            + (self._section("lost-today", "rpt_ven_sec_lost_today_title", today_count, _df_to_html(df_today), "rpt_ven_sec_lost_today_intro", "offline", "ven_lost_heartbeat_24h")
               + "\n"
               if visible_in('ven_lost_heartbeat_24h', profile, detail_level) else '')
            + (self._section("lost-yest", "rpt_ven_sec_lost_yest_title", yest_count, _df_to_html(df_yest), "rpt_ven_sec_lost_yest_intro", "warn", "ven_lost_heartbeat_48h")
               + "\n"
               if visible_in('ven_lost_heartbeat_48h', profile, detail_level) else '')
            + self._estate_inventory_section()
            + self._ransomware_posture_section()
            + f'<footer>{_s("rpt_ven_footer")} &middot; '
            + today_str
            + "</footer>"
        )

        _cover_title = _s("rpt_cover_type_ven")
        cover_html = _build_cover_page(
            title=_cover_title,
            report_type=_cover_title,
            date_range=("", ""),
            pce_url=self._pce_url,
            org_name=self._org_name,
            lang=self._lang,
        )
        html_lang = "zh-TW" if self._lang == "zh_TW" else "en"
        return (
            f'<!DOCTYPE html><html lang="{html_lang}"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f"<title>{t('rpt_page_title_ven_status', lang=self._lang)}</title>"
            + _CSS + _HIGHLIGHT_CSS
            + "</head>\n"
            + f'<body data-report-title="{_cover_title}">'
            + cover_html
            + '<div class="report-shell">'
            + nav_html
            + '<main class="report-main">'
            + body
            + "</main></div>"
            + TABLE_JS
            + "</body></html>"
        )

    def _summary_pills(self, online_count: int, offline_count: int, today_count: int, yest_count: int) -> str:
        _s = self._s
        pills = [
            (_s("rpt_pill_online"), human_number(online_count)),
            (_s("rpt_pill_offline"), human_number(offline_count)),
            (_s("rpt_pill_lost_24h"), human_number(today_count)),
            (_s("rpt_pill_lost_48h"), human_number(yest_count)),
        ]
        html = '<div class="summary-pill-row">'
        for label, value in pills:
            html += (
                '<div class="summary-pill">'
                f'<span class="summary-pill-label">{label}</span>'
                f'<span class="summary-pill-value">{value}</span>'
                "</div>"
            )
        html += "</div>"
        return html

    def _estate_inventory_section(self) -> str:
        """Render the Estate Inventory & Posture section from module_results."""
        os_dist = self._r.get("os_distribution")
        enf_dist = self._r.get("enforcement_distribution")
        enf_net = self._r.get("enforcement_by_network")
        by_version = self._r.get("by_version")
        # Guard: older snapshots may not have these keys
        if not any([os_dist, enf_dist, enf_net, by_version]):
            return ""

        _s = self._s
        parts = [
            f'<section id="estate-inventory" class="card">'
            f'<h2>{t("rpt_ei_section", lang=self._lang)}</h2>'
        ]

        def _panel(tbl_html: str) -> str:
            # Wrap a <table class="report-table"> in the same styled container the
            # rest of the report uses (render_df_table), so these estate tables
            # render with proper borders/headers instead of looking like raw text.
            return (
                '<div class="report-table-panel report-table-panel--compact">'
                f'<div class="report-table-wrap">{tbl_html}</div></div>'
            )

        # -- OS Distribution sub-block --
        if os_dist:
            by_family = os_dist.get("by_family", {})
            total = os_dist.get("total", 0)
            parts.append(f'<h3>{t("rpt_ei_os_dist", lang=self._lang)}</h3>')
            if by_family:
                rows = "".join(
                    f"<tr><td>{html.escape(str(fam))}</td><td>{cnt}</td></tr>"
                    for fam, cnt in sorted(by_family.items(), key=lambda kv: kv[1], reverse=True)
                )
                parts.append(_panel(
                    f'<table class="report-table"><thead><tr>'
                    f'<th>{t("rpt_ei_family", lang=self._lang)}</th>'
                    f'<th>{t("rpt_ei_count", lang=self._lang)}</th>'
                    f'</tr></thead><tbody>{rows}</tbody>'
                    f'<tfoot><tr><td><strong>{t("rpt_ei_total", lang=self._lang)}</strong></td>'
                    f'<td><strong>{total}</strong></td></tr></tfoot></table>'
                ))
            else:
                parts.append(f'<p>{t("rpt_no_records", lang=self._lang)}</p>')

        # -- VEN Version Distribution sub-block (upgrade planning) --
        if by_version:
            parts.append(f'<h3>{t("rpt_ven_by_version", lang=self._lang)}</h3>')
            ver_total = sum(by_version.values())
            rows = "".join(
                f"<tr><td>{html.escape(str(ver))}</td><td>{cnt}</td></tr>"
                for ver, cnt in sorted(by_version.items(), key=lambda kv: kv[1], reverse=True)
            )
            parts.append(_panel(
                f'<table class="report-table"><thead><tr>'
                f'<th>{t("rpt_col_ven_version", lang=self._lang)}</th>'
                f'<th>{t("rpt_ei_count", lang=self._lang)}</th>'
                f'</tr></thead><tbody>{rows}</tbody>'
                f'<tfoot><tr><td><strong>{t("rpt_ei_total", lang=self._lang)}</strong></td>'
                f'<td><strong>{ver_total}</strong></td></tr></tfoot></table>'
            ))

        # -- Enforcement Posture sub-block --
        if enf_dist:
            by_mode = enf_dist.get("by_mode", {})
            total = enf_dist.get("total", 0)
            parts.append(f'<h3>{t("rpt_ei_enforcement", lang=self._lang)}</h3>')
            if by_mode:
                rows = "".join(
                    f"<tr><td>{html.escape(str(mode))}</td><td>{cnt}</td></tr>"
                    for mode, cnt in by_mode.items()
                )
                parts.append(_panel(
                    f'<table class="report-table"><thead><tr>'
                    f'<th>{t("rpt_ei_mode", lang=self._lang)}</th>'
                    f'<th>{t("rpt_ei_count", lang=self._lang)}</th>'
                    f'</tr></thead><tbody>{rows}</tbody>'
                    f'<tfoot><tr><td><strong>{t("rpt_ei_total", lang=self._lang)}</strong></td>'
                    f'<td><strong>{total}</strong></td></tr></tfoot></table>'
                ))
            else:
                parts.append(f'<p>{t("rpt_no_records", lang=self._lang)}</p>')

        # -- Enforcement by Network sub-block --
        if enf_net:
            parts.append(f'<h3>{t("rpt_ei_by_network", lang=self._lang)}</h3>')
            # Collect all modes seen across networks for column headers
            all_modes: list[str] = []
            seen_modes: set[str] = set()
            for entry in enf_net:
                for m in entry.get("by_mode", {}):
                    if m not in seen_modes:
                        seen_modes.add(m)
                        all_modes.append(m)
            mode_headers = "".join(
                f"<th>{html.escape(str(m))}</th>" for m in all_modes
            )
            header = (
                f'<tr><th>{t("rpt_ei_network", lang=self._lang)}</th>'
                f'<th>{t("rpt_ei_total", lang=self._lang)}</th>'
                f'{mode_headers}</tr>'
            )
            rows_html = ""
            for entry in enf_net:
                net_name = html.escape(str(entry.get("network", "")))
                total = entry.get("total", 0)
                mode_cells = "".join(
                    f"<td>{entry.get('by_mode', {}).get(m, 0)}</td>" for m in all_modes
                )
                rows_html += f"<tr><td>{net_name}</td><td>{total}</td>{mode_cells}</tr>"
            parts.append(_panel(
                f'<table class="report-table"><thead>{header}</thead>'
                f'<tbody>{rows_html}</tbody></table>'
            ))

        parts.append("</section>\n")
        return "".join(parts)

    def _ransomware_posture_section(self) -> str:
        """Render the Ransomware Exposure & High-Risk Open Ports section."""
        m = self._r.get("ransomware_posture")
        if not isinstance(m, dict):
            return ""
        per_ven = m.get("per_ven") or []
        if not per_ven:
            return ""
        import pandas as pd
        _l = self._lang
        kpi = m.get("kpi") or {}
        ports = m.get("ports") or []

        # ── KPI strip: exposure distribution (severity-coloured) + coverage + pending
        by_exp = kpi.get("by_exposure") or {}
        cards = "".join(
            f'<div class="kpi-card" style="border-top-color:{_RWP_SEV_BORDER[lvl]}">'
            f'<div class="kpi-label">{html.escape(lvl.replace("_", " "))}</div>'
            f'<div class="kpi-value">{by_exp.get(lvl, 0)}</div></div>'
            for lvl in ("critical", "high", "medium", "low", "fully_protected")
        )
        cards += (
            f'<div class="kpi-card"><div class="kpi-label">{t("rpt_rwp_avg_coverage", lang=_l)}</div>'
            f'<div class="kpi-value">{kpi.get("avg_protection_percent", 0)}%</div></div>'
            f'<div class="kpi-card"><div class="kpi-label">{t("rpt_rwp_pending", lang=_l)}</div>'
            f'<div class="kpi-value">{kpi.get("pending", 0)}</div></div>'
        )
        kpi_html = f'<div class="kpi-grid">{cards}</div>'

        # ── per-VEN risk ranking table
        ven_df = pd.DataFrame([{
            "Hostname": r["hostname"], "Severity": r["severity"],
            "Protection %": r["protection_percent"], "High-Risk Open Ports": r["open_risky_count"],
        } for r in per_ven])
        ven_col_i18n = {"Hostname": "rpt_rwp_host", "Severity": "rpt_rwp_severity",
                        "Protection %": "rpt_rwp_coverage", "High-Risk Open Ports": "rpt_rwp_open_ports"}

        def _ven_cell(col, val, _row):
            if col == "Severity":
                return _rwp_severity_badge(str(val))
            if col == "Protection %":
                return f"{html.escape(str(val))}%"
            return html.escape("" if val is None else str(val))

        ven_table = (
            f'<h3>{t("rpt_rwp_ven_title", lang=_l)}</h3>'
            + render_df_table(ven_df, col_i18n=ven_col_i18n, render_cell=_ven_cell, lang=_l)
        )

        # ── per-VEN high-risk open-port detail (severity + protection badges)
        port_table = ""
        if ports:
            port_df = pd.DataFrame([{
                "Hostname": p["hostname"], "Port/Proto": f'{p["port"]}/{p["proto"]}',
                "Service": p["service"], "Severity": p["severity"],
                "Protection": p["protection_state"], "Process": p["process"] or "—",
                "User": p["user"] or "—",
            } for p in ports])
            port_col_i18n = {"Hostname": "rpt_rwp_host", "Port/Proto": "rpt_rwp_portproto",
                             "Service": "rpt_rwp_service", "Severity": "rpt_rwp_severity",
                             "Protection": "rpt_rwp_protection", "Process": "rpt_rwp_process",
                             "User": "rpt_rwp_user"}

            def _port_cell(col, val, _row):
                if col == "Severity":
                    return _rwp_severity_badge(str(val))
                if col == "Protection":
                    return _rwp_protection_badge(str(val))
                return html.escape("" if val is None else str(val))

            port_table = (
                f'<h3>{t("rpt_rwp_ports_title", lang=_l)}</h3>'
                + render_df_table(port_df, col_i18n=port_col_i18n, render_cell=_port_cell, lang=_l)
            )

        return (
            f'<section id="ransomware-posture" class="card">'
            f'<h2>{t("rpt_rwp_section", lang=_l)}</h2>'
            f'<p class="section-intro">{t("rpt_rwp_intro", lang=_l)}</p>'
            f'{kpi_html}{ven_table}{port_table}</section>\n'
        )

    def _section(
        self,
        id_: str,
        title_key: str,
        count: int,
        content: str,
        intro_key: str = "",
        extra_class: str = "",
        guidance_module_id: str = "",
    ) -> str:
        _s = self._s
        title = _s(title_key)
        intro_html = f'<p class="section-intro">{_s(intro_key)}</p>' if intro_key else ""
        guidance_html = ""
        if guidance_module_id:
            guidance_html = render_section_guidance(guidance_module_id, profile="security_risk", detail_level=_REPORT_DETAIL_LEVEL, lang=self._lang)
        cls = f"card {extra_class}".strip()
        return (
            f'<section id="{id_}" class="{cls}">'
            f'<h2>{title} ({count})</h2>'
            f"{intro_html}{guidance_html}{content}</section>"
        )
