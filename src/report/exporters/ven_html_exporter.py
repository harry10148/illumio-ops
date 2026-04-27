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
from .report_i18n import STRINGS
from .table_renderer import render_df_table
from .chart_renderer import render_plotly_html, FirstChartTracker
from .code_highlighter import get_highlight_css
from .html_exporter import render_section_guidance
from src.report.section_guidance import visible_in
from src.humanize_ext import human_number

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

class VenHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None,
                 profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en"):
        self._r = results
        self._df = df
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang

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
        self._chart_tracker = FirstChartTracker()
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s

        kpis = self._r.get("kpis", [])
        gen_at = self._r.get("generated_at", "")
        today_str = str(datetime.date.today())

        nav_html = (
            "<nav>"
            '<div class="nav-brand">Illumio PCE Ops</div>'
            f'<a href="#summary">{_s("rpt_ven_nav_summary")}</a>'
            f'<a href="#online">{_s("rpt_ven_nav_online")}</a>'
            f'<a href="#offline">{_s("rpt_ven_nav_offline")}</a>'
            f'<a href="#lost-today">{_s("rpt_ven_nav_lost_today")}</a>'
            f'<a href="#lost-yest">{_s("rpt_ven_nav_lost_yest")}</a>'
            "</nav>"
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
                    "type": "pie",
                    "title": "VEN Status Distribution",
                    "data": {
                        "labels": ["Online", "Offline", "Lost <24h", "Lost 24-48h"],
                        "values": [online_count, offline_count, today_count, yest_count],
                    },
                }
                div = render_plotly_html(spec, include_js=self._chart_tracker.consume())
                if div:
                    status_chart_html = f'<div class="chart-container">{div}</div>'
            except Exception:
                pass

        def _df_to_html(df, no_data_key: str = "rpt_no_records") -> str:
            def _render_cell(col, val, _row):
                val_str = "" if val is None or str(val) in ("None", "nan") else str(val)
                if str(col).strip().lower().replace(" ", "_") == "policy_sync":
                    return _policy_sync_badge(val_str)
                return val_str
            return render_df_table(df, col_i18n=_COL_I18N, no_data_key=no_data_key,
                                   render_cell=_render_cell, lang=_sl)

        body = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_ven")}</div>'
            f'<h1>{_s("rpt_ven_title")}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} '
            + gen_at
            + "</p></div>"
            + self._summary_pills(online_count, offline_count, today_count, yest_count)
            + f'<div class="kpi-grid">{kpi_cards}</div>'
            + status_chart_html
            + "</section>\n"
            + self._section("online", "rpt_ven_sec_online_title", online_count, _df_to_html(df_online), "rpt_ven_sec_online_intro", "online", "ven_online_inventory")
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
            + f'<footer>{_s("rpt_ven_footer")} &middot; '
            + today_str
            + "</footer>"
        )

        html_lang = "zh-TW" if self._lang == "zh_TW" else "en"
        return (
            f'<!DOCTYPE html><html lang="{html_lang}"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>Illumio VEN Status Report</title>"
            + _CSS + _HIGHLIGHT_CSS
            + "</head>\n<body>"
            + nav_html
            + "<main>"
            + body
            + "</main>"
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
            guidance_html = render_section_guidance(guidance_module_id, profile="security_risk", detail_level=_REPORT_DETAIL_LEVEL)
        cls = f"card {extra_class}".strip()
        return (
            f'<section id="{id_}" class="{cls}">'
            f'<h2>{title} ({count})</h2>'
            f"{intro_html}{guidance_html}{content}</section>"
        )
