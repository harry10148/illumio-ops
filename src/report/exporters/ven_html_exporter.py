"""
Self-contained HTML report for the VEN Status Inventory Report.
"""
from __future__ import annotations

import datetime
from loguru import logger
import os

import pandas as pd

from .report_css import TABLE_JS, build_css
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS, lang_btn_html, make_i18n_js
from .table_renderer import render_df_table
from .chart_renderer import render_plotly_html
from .code_highlighter import get_highlight_css
from src.humanize_ext import human_number

_CSS = build_css("ven")
_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'

def _policy_sync_badge(val: str) -> str:
    v = str(val).lower().strip()
    if v == "synced":
        return f'<span class="badge-synced">{val}</span>'
    if v == "staged":
        return f'<span class="badge-staged">{val}</span>'
    if v and v not in ("none", "nan"):
        return f'<span class="badge-unsynced">{val}</span>'
    return ""

def _df_to_html(df, no_data_key: str = "rpt_no_records") -> str:
    # Empty case is rendered by the shared renderer for consistent panel chrome.

    def _render_cell(col, val, _row):
        val_str = "" if val is None or str(val) in ("None", "nan") else str(val)
        if str(col).strip().lower().replace(" ", "_") == "policy_sync":
            return _policy_sync_badge(val_str)
        return val_str

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
    )

class VenHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None):
        self._r = results
        self._df = df

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_ven_status_{ts}.html"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._build())
        logger.info("[VenHtmlExporter] Saved: {}", filepath)
        return filepath

    def _build(self) -> str:
        kpis = self._r.get("kpis", [])
        gen_at = self._r.get("generated_at", "")
        today_str = str(datetime.date.today())

        nav_html = (
            "<nav>"
            '<div class="nav-brand">Illumio PCE Ops</div>'
            '<a href="#summary"><span data-i18n="rpt_ven_nav_summary">Executive Summary</span></a>'
            '<a href="#online"><span data-i18n="rpt_ven_nav_online">Online VENs</span></a>'
            '<a href="#offline"><span data-i18n="rpt_ven_nav_offline">Offline VENs</span></a>'
            '<a href="#lost-today"><span data-i18n="rpt_ven_nav_lost_today">Lost Today (&lt;24h)</span></a>'
            '<a href="#lost-yest"><span data-i18n="rpt_ven_nav_lost_yest">Lost Yesterday</span></a>'
            "</nav>"
        )

        # KPI labels are i18n keys resolved against STRINGS; applyI18n() swaps
        # textContent on lang toggle. Render EN initially so the pre-JS view
        # reads correctly.
        def _kpi_label(k: dict) -> tuple[str, str]:
            key = k.get("i18n_key") or ""
            entry = STRINGS.get(key, {}) if key else {}
            en = entry.get("en", key) if isinstance(entry, dict) else key
            return key, en

        kpi_cards_parts = []
        for k in kpis:
            key, label_en = _kpi_label(k)
            i18n_attr = f' data-i18n="{key}"' if key else ""
            kpi_cards_parts.append(
                '<div class="kpi-card">'
                f'<div class="kpi-label"{i18n_attr}>{label_en}</div>'
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
                    "type": "pie",
                    "title": "VEN Status Distribution",
                    "data": {
                        "labels": ["Online", "Offline", "Lost <24h", "Lost 24-48h"],
                        "values": [online_count, offline_count, today_count, yest_count],
                    },
                }
                div = render_plotly_html(spec)
                if div:
                    status_chart_html = f'<div class="chart-container">{div}</div>'
            except Exception:
                pass

        body = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            '<div class="report-kicker" data-i18n="rpt_kicker_ven">VEN Inventory Report</div>'
            '<h1 data-i18n="rpt_ven_title">Illumio VEN Status Inventory Report</h1>'
            '<p class="report-subtitle"><span data-i18n="rpt_generated">Generated:</span> '
            + gen_at
            + "</p></div>"
            + self._summary_pills(online_count, offline_count, today_count, yest_count)
            + f'<div class="kpi-grid">{kpi_cards}</div>'
            + status_chart_html
            + "</section>\n"
            + self._section("online", "rpt_ven_sec_online_title", "Online VENs", online_count, _df_to_html(df_online), "rpt_ven_sec_online_intro", "online")
            + "\n"
            + self._section("offline", "rpt_ven_sec_offline_title", "Offline VENs", offline_count, _df_to_html(df_offline), "rpt_ven_sec_offline_intro", "offline")
            + "\n"
            + self._section("lost-today", "rpt_ven_sec_lost_today_title", "Lost Connection in Last 24h", today_count, _df_to_html(df_today), "rpt_ven_sec_lost_today_intro", "offline")
            + "\n"
            + self._section("lost-yest", "rpt_ven_sec_lost_yest_title", "Lost Connection 24-48h Ago", yest_count, _df_to_html(df_yest), "rpt_ven_sec_lost_yest_intro", "warn")
            + "\n"
            + '<footer><span data-i18n="rpt_ven_footer">Illumio PCE Ops — VEN Status Report</span> &middot; '
            + today_str
            + "</footer>"
        )

        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>Illumio VEN Status Report</title>"
            + _CSS + _HIGHLIGHT_CSS
            + "</head>\n<body>"
            + lang_btn_html()
            + nav_html
            + "<main>"
            + body
            + "</main>"
            + TABLE_JS
            + make_i18n_js()
            + "</body></html>"
        )

    def _summary_pills(self, online_count: int, offline_count: int, today_count: int, yest_count: int) -> str:
        pills = [
            (STRINGS["rpt_pill_online"]["en"], human_number(online_count)),
            (STRINGS["rpt_pill_offline"]["en"], human_number(offline_count)),
            (STRINGS["rpt_pill_lost_24h"]["en"], human_number(today_count)),
            (STRINGS["rpt_pill_lost_48h"]["en"], human_number(yest_count)),
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

    def _section(
        self,
        id_: str,
        title_key: str,
        title_en: str,
        count: int,
        content: str,
        intro_key: str = "",
        extra_class: str = "",
    ) -> str:
        # Section heading renders "Title (count)"; applyI18n swaps the title
        # text on lang toggle, count is appended as a static span alongside.
        intro_html = ""
        if intro_key:
            entry = STRINGS.get(intro_key, {})
            intro_en = entry.get("en", "") if isinstance(entry, dict) else ""
            intro_html = (
                f'<p class="section-intro" data-i18n="{intro_key}">{intro_en}</p>'
            )
        cls = f"card {extra_class}".strip()
        return (
            f'<section id="{id_}" class="{cls}">'
            f'<h2><span data-i18n="{title_key}">{title_en}</span> ({count})</h2>'
            f"{intro_html}{content}</section>"
        )
