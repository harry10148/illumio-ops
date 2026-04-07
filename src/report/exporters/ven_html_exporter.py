"""
Self-contained HTML report for the VEN Status Inventory Report.
"""
from __future__ import annotations

import datetime
import logging
import os

import pandas as pd

from .report_css import TABLE_JS, build_css
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS, lang_btn_html, make_i18n_js
from .table_renderer import render_df_table

logger = logging.getLogger(__name__)

_CSS = build_css("ven")


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
    if df is None or (hasattr(df, "empty") and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">No records</p>'

    def _render_cell(col, val, _row):
        val_str = "" if val is None or str(val) in ("None", "nan") else str(val)
        if col == "Policy Sync":
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
        logger.info("[VenHtmlExporter] Saved: %s", filepath)
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

        kpi_cards = "".join(
            '<div class="kpi-card">'
            f'<div class="kpi-label">{k["label"]}</div>'
            f'<div class="kpi-value">{k["value"]}</div>'
            "</div>"
            for k in kpis
        )

        df_online = self._r.get("online")
        df_offline = self._r.get("offline")
        df_today = self._r.get("lost_today")
        df_yest = self._r.get("lost_yesterday")
        online_count = len(df_online) if df_online is not None and not df_online.empty else 0
        offline_count = len(df_offline) if df_offline is not None and not df_offline.empty else 0
        today_count = len(df_today) if df_today is not None and not df_today.empty else 0
        yest_count = len(df_yest) if df_yest is not None and not df_yest.empty else 0

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
            + "</section>\n"
            + self._section("online", "rpt_ven_sec_online", f"Online VENs ({online_count})", _df_to_html(df_online), "目前持續回報心跳且可正常套用策略的工作負載。這張表適合拿來確認健康資產清單與版本狀態。", "online")
            + "\n"
            + self._section("offline", "rpt_ven_sec_offline", f"Offline VENs ({offline_count})", _df_to_html(df_offline), "目前未正常回報的工作負載，請檢查連線、Agent 狀態或是否已除役。這張表通常是排查資產可視性問題的起點。", "offline")
            + "\n"
            + self._section("lost-today", "rpt_ven_sec_lost_today", f"Lost Connection in Last 24h ({today_count})", _df_to_html(df_today), "近 24 小時內失聯，建議優先排查。這些通常最有機會對應到新發生的網路、Agent 或主機異常。", "offline")
            + "\n"
            + self._section("lost-yest", "rpt_ven_sec_lost_yest", f"Lost Connection 24-48h Ago ({yest_count})", _df_to_html(df_yest), "已失聯超過一天，但仍屬近期事件，建議在成為陳舊資產前完成確認。這張表可用來追蹤持續未恢復的中短期異常。", "warn")
            + "\n"
            + '<footer><span data-i18n="rpt_ven_footer">Illumio PCE Ops — VEN Status Report</span> &middot; '
            + today_str
            + "</footer>"
        )

        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>Illumio VEN Status Report</title>"
            + _CSS
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
            (STRINGS["rpt_pill_online"]["en"], str(online_count)),
            (STRINGS["rpt_pill_offline"]["en"], str(offline_count)),
            (STRINGS["rpt_pill_lost_24h"]["en"], str(today_count)),
            (STRINGS["rpt_pill_lost_48h"]["en"], str(yest_count)),
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
        i18n_key: str,
        title: str,
        content: str,
        intro: str = "",
        extra_class: str = "",
    ) -> str:
        intro_html = f'<p class="section-intro">{intro}</p>' if intro else ""
        cls = f"card {extra_class}".strip()
        return (
            f'<section id="{id_}" class="{cls}">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f"{intro_html}{content}</section>"
        )
