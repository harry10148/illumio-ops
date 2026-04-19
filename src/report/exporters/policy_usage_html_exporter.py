"""
Self-contained HTML report for the Policy Usage Report.
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
from .code_highlighter import get_highlight_css
from src.humanize_ext import human_number

_CSS = build_css("policy_usage")
_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'

def _df_to_html(df, no_data_key: str = "rpt_no_data") -> str:
    # Empty case is rendered by the shared renderer for consistent panel chrome.

    def _render_cell(col, val, _row):
        val_str = str(val) if val is not None else ""
        if str(col).strip().lower() == "enabled":
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
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(self._build())
        logger.info("[PolicyUsageHtmlExporter] Saved: {}", filepath)
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
            '<a href="#deny-rules"><span data-i18n="rpt_pu_nav_deny">4 Deny Effectiveness</span></a>'
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
            + self._execution_html(mod00)
            + self._attention_html(mod00.get("attention_items", []))
            + self._attack_summary_html(mod00)
            + "</section>\n"
            + self._section(
                "overview",
                "rpt_pu_sec_overview",
                "1. Policy Usage Overview",
                self._mod01_html(),
                "Baseline coverage and usage rate for the selected lookback window.",
            )
            + "\n"
            + self._section(
                "hit-rules",
                "rpt_pu_sec_hit",
                "2. Hit Rules Detail",
                self._mod02_html(),
                "Rules that observed traffic during the lookback window, including their dominant hit ports.",
            )
            + "\n"
            + self._section(
                "unused-rules",
                "rpt_pu_sec_unused",
                "3. Unused Rules Detail",
                self._mod03_html(),
                "Rules without observed hits in the selected window, shown with expected services for review.",
            )
            + "\n"
            + self._section(
                "deny-rules",
                "rpt_pu_sec_deny",
                "4. Deny Rule Effectiveness",
                self._mod04_html(),
                "Deny rule coverage and hit analysis — are deny rules actively blocking unwanted traffic?",
            )
            + "\n"
            + '<footer><span data-i18n="rpt_pu_footer">Illumio PCE Ops - Policy Usage Report</span>'
            + " &middot; "
            + today_str
            + "</footer>"
        )
        return (
            '<!DOCTYPE html><html lang="en"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>Illumio Policy Usage Report</title>"
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

    def _execution_html(self, mod00: dict) -> str:
        stats = mod00.get("execution_stats", {}) or {}
        notes = mod00.get("execution_notes", []) or []
        if not stats and not notes:
            return ""

        rows = [
            ("Cached summaries", stats.get("cached_rules", 0)),
            ("New queries", stats.get("submitted_rules", 0)),
            ("Completed jobs", stats.get("completed_jobs", 0)),
            ("Pending jobs", stats.get("pending_jobs", 0)),
            ("Failed jobs", stats.get("failed_jobs", 0)),
        ]
        metrics_html = "".join(
            '<div class="attention-row">'
            f'<span>{label}</span><span class="badge-hit">{value}</span>'
            "</div>"
            for label, value in rows
        )
        notes_html = "".join(f"<li>{note}</li>" for note in notes)
        if notes_html:
            notes_html = f'<ul style="margin:10px 0 0 18px;">{notes_html}</ul>'
        return (
            '<div class="attention-box">'
            '<h4>Query Execution</h4>'
            + metrics_html
            + notes_html
            + "</div>"
        )

    def _attack_summary_html(self, mod00: dict) -> str:
        def _rows(section_items):
            if not section_items:
                return '<p class="note">No data</p>'
            return "".join(
                "<p style='margin-bottom:8px'><span class='badge badge-"
                + str(item.get("severity", "INFO"))
                + "'>"
                + str(item.get("severity", "INFO"))
                + "</span>&nbsp;"
                + str(item.get("finding", ""))
                + (("<br><span style='color:#718096;font-size:12px;'>"
                    + str(item.get("finding_zh", ""))
                    + "</span>") if item.get("finding_zh") else "")
                + " <em style='color:#718096'>&rarr; "
                + str(item.get("action", ""))
                + "</em>"
                + (("<br><span style='color:#718096;font-size:12px;'><em>&rarr; "
                    + str(item.get("action_zh", ""))
                    + "</em></span>") if item.get("action_zh") else "")
                + "</p>"
                for item in section_items[:3]
            )

        action_matrix = mod00.get("action_matrix", []) or []
        action_html = "".join(
            "<p style='margin-bottom:8px'><b>"
            + str(item.get("action_code", ""))
            + "</b>: "
            + str(item.get("action", ""))
            + (("<br><span style='color:#718096;font-size:12px;'>"
                + str(item.get("action_zh", ""))
                + "</span>") if item.get("action_zh") else "")
            + "</p>"
            for item in action_matrix[:3]
        ) or '<p class="note">No data</p>'

        return (
            '<h2 data-i18n="rpt_tr_attack_summary">Attack Summary</h2>'
            '<h3 data-i18n="rpt_tr_boundary_breaches">Boundary Breaches</h3>' + _rows(mod00.get("boundary_breaches", []))
            + '<h3 data-i18n="rpt_tr_suspicious_pivot_behavior">Suspicious Pivot Behavior</h3>' + _rows(mod00.get("suspicious_pivot_behavior", []))
            + '<h3 data-i18n="rpt_tr_blast_radius">Blast Radius</h3>' + _rows(mod00.get("blast_radius", []))
            + '<h3 data-i18n="rpt_tr_blind_spots">Blind Spots</h3>' + _rows(mod00.get("blind_spots", []))
            + '<h3 data-i18n="rpt_tr_action_matrix">Action Matrix</h3>' + action_html
        )

    def _mod01_html(self) -> str:
        mod01 = self._r.get("mod01", {})
        total = mod01.get("total_rules", 0)
        hit = mod01.get("hit_count", 0)
        unused = mod01.get("unused_count", 0)
        rate = mod01.get("hit_rate_pct", 0.0)
        summary_df = mod01.get("summary_df")

        stats = (
            "<p>"
            f'<span data-i18n="rpt_pu_total_rules">Total Active Rules</span>: <strong>{human_number(total)}</strong> &nbsp;|&nbsp; '
            f'<span class="badge-hit" data-i18n="rpt_pu_hit_rules">Hit Rules</span> {human_number(hit)} &nbsp;|&nbsp; '
            f'<span class="badge-unused" data-i18n="rpt_pu_unused_rules">Unused Rules</span> {human_number(unused)} &nbsp;|&nbsp; '
            f'<span data-i18n="rpt_pu_hit_rate">Hit Rate</span>: <strong>{rate}%</strong>'
            "</p>"
        )
        return stats + _df_to_html(summary_df)

    def _mod02_html(self) -> str:
        mod02 = self._r.get("mod02", {})
        hit_df = mod02.get("hit_df")
        top_ports_df = mod02.get("top_ports_df")
        count = mod02.get("record_count", 0)
        note = f'<p style="color:#718096;font-size:12px;">{count} rows</p>' if count else ""
        top_ports_html = ""
        if top_ports_df is not None and not getattr(top_ports_df, "empty", True):
            top_ports_html = (
                '<div class="attention-box">'
                '<h4>Top Hit Ports</h4>'
                + _df_to_html(top_ports_df)
                + "</div>"
            )
        if hit_df is None or (hasattr(hit_df, "empty") and hit_df.empty):
            return top_ports_html + '<p class="note" data-i18n="rpt_pu_no_hit_rules">No rules were hit during this period.</p>'
        return top_ports_html + note + _df_to_html(hit_df)

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

        note = f'<p style="color:#718096;font-size:12px;">{count} rows</p>' if count else ""
        return caveat_html + note + _df_to_html(unused_df)

    def _mod04_html(self) -> str:
        mod04 = self._r.get("mod04", {})
        total_deny = mod04.get("total_deny", 0)
        if total_deny == 0:
            return '<p class="note" data-i18n="rpt_pu_no_deny">No deny rules found in the active policy.</p>'

        deny_hit = mod04.get("deny_hit_count", 0)
        deny_unused = mod04.get("deny_unused_count", 0)
        deny_hit_rate = mod04.get("deny_hit_rate_pct", 0.0)
        deny_ratio = mod04.get("deny_ratio_pct", 0.0)
        override_count = mod04.get("override_deny_count", 0)

        stats = (
            "<p>"
            f'<span data-i18n="rpt_pu_deny_total">Total Deny Rules</span>: <strong>{total_deny}</strong> '
            f'({deny_ratio}% of all rules) &nbsp;|&nbsp; '
            f'<span class="badge-hit" data-i18n="rpt_pu_deny_hit">Hit</span> {deny_hit} &nbsp;|&nbsp; '
            f'<span class="badge-unused" data-i18n="rpt_pu_deny_unused">Unused</span> {deny_unused} &nbsp;|&nbsp; '
            f'<span data-i18n="rpt_pu_deny_hit_rate">Hit Rate</span>: <strong>{deny_hit_rate}%</strong>'
            "</p>"
        )

        if override_count > 0:
            stats += (
                '<p class="note note-warn">'
                f'<strong data-i18n="rpt_pu_override_deny">Override Deny Rules:</strong> {override_count} '
                '— these take highest priority and bypass all other rules. Review for correctness.</p>'
            )

        summary_df = mod04.get("deny_summary_df")
        summary_html = _df_to_html(summary_df) if summary_df is not None else ""

        detail_df = mod04.get("deny_detail_df")
        detail_html = ""
        if detail_df is not None and not detail_df.empty:
            detail_html = (
                '<h3 data-i18n="rpt_pu_deny_detail">Deny Rule Details</h3>'
                + _df_to_html(detail_df)
            )

        return stats + summary_html + detail_html
