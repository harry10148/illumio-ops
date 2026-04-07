"""
Self-contained HTML report for the Policy Usage Report.
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

_CSS = build_css("policy_usage")


def _df_to_html(df, no_data_key: str = "rpt_no_data") -> str:
    if df is None or (hasattr(df, "empty") and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">No data</p>'

    def _render_cell(col, val, _row):
        val_str = str(val) if val is not None else ""
        if col == "Enabled":
            if val_str.lower() in ("true", "1", "yes"):
                return '<span class="badge-hit" data-i18n="rpt_yes">Yes</span>'
            return '<span class="badge-unused" data-i18n="rpt_no">No</span>'
        return val_str

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
    )


class PolicyUsageHtmlExporter:
    def __init__(
        self,
        results: dict,
        df: pd.DataFrame = None,
        date_range: tuple = ("", ""),
        lookback_days: int = 30,
    ):
        self._r = results
        self._df = df
        self._date_range = date_range
        self._lookback_days = lookback_days

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_policy_usage_report_{ts}.html"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._build())
        logger.info("[PolicyUsageHtmlExporter] Saved: %s", filepath)
        return filepath

    def _build(self) -> str:
        mod00 = self._r.get("mod00", {})
        date_str = " ~ ".join(self._date_range) if any(self._date_range) else ""
        period_part = (
            ' &nbsp;|&nbsp; <span data-i18n="rpt_period">Period:</span> ' + date_str
            if date_str
            else ""
        )
        today_str = str(datetime.date.today())

        nav_html = (
            "<nav>"
            '<div class="nav-brand">Illumio PCE Ops</div>'
            '<a href="#summary"><span data-i18n="rpt_pu_nav_summary">Executive Summary</span></a>'
            '<a href="#overview"><span data-i18n="rpt_pu_nav_overview">1 Usage Overview</span></a>'
            '<a href="#hit-rules"><span data-i18n="rpt_pu_nav_hit">2 Hit Rules</span></a>'
            '<a href="#unused-rules"><span data-i18n="rpt_pu_nav_unused">3 Unused Rules</span></a>'
            "</nav>"
        )

        body = (
            '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            '<div class="report-kicker" data-i18n="rpt_kicker_policy">Policy Usage Report</div>'
            '<h1 data-i18n="rpt_pu_title">Illumio Policy Usage Report</h1>'
            '<p class="report-subtitle"><span data-i18n="rpt_generated">Generated:</span> '
            + mod00.get("generated_at", "")
            + period_part
            + "</p></div>"
            + self._summary_pills(mod00)
            + self._kpi_html(mod00.get("kpis", []))
            + self._attention_html(mod00.get("attention_items", []))
            + "</section>\n"
            + self._section(
                "overview",
                "rpt_pu_sec_overview",
                "1 · Policy Usage Overview",
                self._mod01_html(),
                "顯示回溯期間內各規則集的整體使用狀態。",
            )
            + "\n"
            + self._section(
                "hit-rules",
                "rpt_pu_sec_hit",
                "2 · Hit Rules Detail",
                self._mod02_html(),
                "列出分析期間內實際被流量命中的規則。",
            )
            + "\n"
            + self._section(
                "unused-rules",
                "rpt_pu_sec_unused",
                "3 · Unused Rules Detail",
                self._mod03_html(),
                "列出本次資料中未被命中的規則，刪除前請先確認是否僅受保留期間限制。",
            )
            + "\n"
            + '<footer><span data-i18n="rpt_pu_footer">Illumio PCE Ops — Policy Usage Report</span>'
            + " &middot; "
            + today_str
            + "</footer>"
        )
        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>Illumio Policy Usage Report</title>"
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

    def _section(self, id_: str, i18n_key: str, title: str, content: str, intro: str = "") -> str:
        intro_html = f'<p class="section-intro">{intro}</p>' if intro else ""
        return (
            f'<section id="{id_}" class="card">'
            f'<h2 data-i18n="{i18n_key}">{title}</h2>'
            f"{intro_html}{content}</section>"
        )

    def _summary_pills(self, mod00: dict) -> str:
        top_ruleset = ""
        items = mod00.get("attention_items", []) or []
        if items:
            top_ruleset = str(items[0].get("ruleset", ""))
        pills = [
            (STRINGS["rpt_pill_lookback"]["en"], f"{self._lookback_days} days"),
            (STRINGS["rpt_pill_period"]["en"], " ~ ".join(self._date_range) if any(self._date_range) else "N/A"),
            (STRINGS["rpt_pill_focus"]["en"], top_ruleset or STRINGS["rpt_focus_usage"]["en"]),
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

    def _kpi_html(self, kpis: list) -> str:
        if not kpis:
            return ""
        cards = "".join(
            '<div class="kpi-card">'
            f'<div class="kpi-label">{k["label"]}</div>'
            f'<div class="kpi-value">{k["value"]}</div>'
            "</div>"
            for k in kpis
        )
        return f'<div class="kpi-grid">{cards}</div>'

    def _attention_html(self, attention_items: list) -> str:
        if not attention_items:
            return ""
        rows = "".join(
            '<div class="attention-row">'
            f'<span>{item.get("ruleset", "")}</span>'
            f'<span class="badge-unused">{item.get("unused_count", 0)}</span>'
            "</div>"
            for item in attention_items
        )
        return (
            '<div class="attention-box">'
            '<h4 data-i18n="rpt_pu_attention">Top Rulesets by Unused Rules</h4>'
            + rows
            + "</div>"
        )

    def _mod01_html(self) -> str:
        mod01 = self._r.get("mod01", {})
        total = mod01.get("total_rules", 0)
        hit = mod01.get("hit_count", 0)
        unused = mod01.get("unused_count", 0)
        rate = mod01.get("hit_rate_pct", 0.0)
        summary_df = mod01.get("summary_df")

        stats = (
            '<p class="section-intro">先用這組數字確認目前啟用規則中，有多少在回溯期間內實際被命中，這能幫助你快速掌握 Policy 的活躍程度。</p>'
            "<p>"
            f'<span data-i18n="rpt_pu_total_rules">Total Active Rules</span>: <strong>{total}</strong> &nbsp;|&nbsp; '
            f'<span class="badge-hit" data-i18n="rpt_pu_hit_rules">Hit Rules</span> {hit} &nbsp;|&nbsp; '
            f'<span class="badge-unused" data-i18n="rpt_pu_unused_rules">Unused Rules</span> {unused} &nbsp;|&nbsp; '
            f'<span data-i18n="rpt_pu_hit_rate">Hit Rate</span>: <strong>{rate}%</strong>'
            "</p>"
        )
        return stats + _df_to_html(summary_df)

    def _mod02_html(self) -> str:
        mod02 = self._r.get("mod02", {})
        hit_df = mod02.get("hit_df")
        count = mod02.get("record_count", 0)
        note = f'<p style="color:#718096;font-size:12px;">{count} 筆規則</p>' if count else ""
        if hit_df is None or (hasattr(hit_df, "empty") and hit_df.empty):
            return '<p class="note" data-i18n="rpt_pu_no_hit_rules">No rules were hit during this period.</p>'
        return note + '<p class="section-intro">這張表列出有實際流量命中的規則，適合用來辨識真正承載業務流量的核心 Policy。</p>' + _df_to_html(hit_df)

    def _mod03_html(self) -> str:
        mod03 = self._r.get("mod03", {})
        unused_df = mod03.get("unused_df")
        count = mod03.get("record_count", 0)
        caveat = mod03.get("caveat", "")

        caveat_html = ""
        if caveat:
            caveat_html = (
                '<div class="caveat-box">'
                '<strong data-i18n="rpt_pu_caveat_title">Retention Period Caveat</strong><br>'
                f'<span data-i18n="rpt_pu_caveat_body">{caveat}</span>'
                "</div>"
            )

        if unused_df is None or (hasattr(unused_df, "empty") and unused_df.empty):
            return (
                caveat_html
                + '<p class="note" data-i18n="rpt_pu_no_unused_rules">All rules had traffic hits; no unused rules found.</p>'
            )

        note = f'<p style="color:#718096;font-size:12px;">{count} 筆規則</p>' if count else ""
        return caveat_html + note + '<p class="section-intro">這張表列出本次回溯期間內沒有命中的規則，適合做為精簡 Policy 前的候選清單，但不應直接視為可刪除項目。</p>' + _df_to_html(unused_df)
