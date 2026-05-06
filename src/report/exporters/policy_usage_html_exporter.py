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
from .report_i18n import STRINGS
from .table_renderer import render_df_table
from .chart_renderer import render_plotly_html, FirstChartTracker
from .code_highlighter import get_highlight_css
from .html_exporter import render_section_guidance
from src.report.section_guidance import visible_in
from src.humanize_ext import human_number
from src.report.exporters._exec_summary import render_exec_summary_html

_CSS = build_css("policy_usage")
_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'
_REPORT_DETAIL_LEVEL = "full"

def _e(val) -> str:
    import html as _html
    return _html.escape(str(val)) if val is not None else ""

def _rule_cards_html(df, mode: str = "hit", lang: str = "en") -> str:
    """Render hit/unused rules as compact card rows instead of a wide flat table."""
    import html as _html
    _s = lambda k: STRINGS[k].get(lang) or STRINGS[k]["en"]
    if df is None or (hasattr(df, "empty") and df.empty):
        return f'<p class="note">{_s("rpt_no_data")}</p>'

    rows_html = []
    for _, row in df.iterrows():
        ruleset   = _e(row.get("Ruleset", ""))
        rule_no   = _e(row.get("No", ""))
        rule_id   = _e(row.get("Rule ID", ""))
        rtype     = str(row.get("Type", "Allow"))
        desc      = _e(row.get("Description", ""))
        src       = _e(row.get("Source", ""))
        dst       = _e(row.get("Destination", ""))
        services  = _e(row.get("Services", ""))
        enabled   = row.get("Enabled", True)
        created   = _e(row.get("Created At", ""))

        type_cls  = "pu-badge-deny" if "deny" in rtype.lower() else "pu-badge-allow"
        en_cls    = "pu-badge-enabled" if str(enabled).lower() in ("true","1","yes") else "pu-badge-disabled"
        en_label  = _s("rpt_pu_enabled") if str(enabled).lower() in ("true","1","yes") else _s("rpt_pu_disabled")

        meta_parts = []
        if rule_no: meta_parts.append(f"#{_e(str(rule_no))}")
        if rule_id: meta_parts.append(f"ID: {_e(str(rule_id))}")
        meta_str = " &middot; ".join(meta_parts)

        # stats column
        if mode == "hit":
            hit_count = row.get("Hit Count", 0)
            top_ports = _e(row.get("Top Hit Ports", ""))
            stat_html = (
                f'<div class="pu-hit-count">{_html.escape(str(hit_count))}</div>'
                f'<div class="pu-stat-label">{_s("rpt_pu_stat_hits")}</div>'
                + (f'<div class="pu-stat-ports">{top_ports}</div>' if top_ports else "")
            )
        else:
            obs_ports = _e(row.get("Observed Hit Ports", ""))
            stat_html = (
                f'<div class="pu-unused-label">{_s("rpt_pu_stat_unused")}</div>'
                + (f'<div class="pu-stat-ports">{obs_ports}</div>' if obs_ports else "")
                + (f'<div class="pu-stat-label" style="margin-top:6px">{_s("rpt_pu_rule_created")} {created}</div>' if created else "")
            )

        rows_html.append(
            '<div class="pu-card">'
            # col 1: identity
            f'<div class="pu-col">'
            f'<div class="pu-ruleset">{ruleset}</div>'
            + (f'<div class="pu-meta">{meta_str}</div>' if meta_str else "")
            + f'<div class="pu-badges">'
            f'<span class="pu-badge {type_cls}">{_e(rtype)}</span>'
            f'<span class="pu-badge {en_cls}">{en_label}</span>'
            f'</div></div>'
            # col 2: flow
            f'<div class="pu-col"><div class="pu-flow-block">'
            f'<div class="pu-flow-row"><span class="pu-flow-label">{_s("rpt_pu_flow_source")}</span><span class="pu-flow-val">{src}</span></div>'
            f'<div class="pu-flow-row"><span class="pu-flow-label">{_s("rpt_pu_flow_dest")}</span><span class="pu-flow-val">{dst}</span></div>'
            + (f'<div class="pu-services"><span class="pu-flow-label">{_s("rpt_pu_flow_service")}</span> {services}</div>' if services else "")
            + (f'<div class="pu-desc">{desc}</div>' if desc and desc != "No description" else "")
            + '</div></div>'
            # col 3: stats
            f'<div class="pu-col"><div class="pu-stat-block">{stat_html}</div></div>'
            '</div>'
        )

    return '<div class="pu-cards">' + "".join(rows_html) + "</div>"


def _df_to_html(df, no_data_key: str = "rpt_no_data", lang: str = "en") -> str:
    _s = lambda k: STRINGS[k].get(lang) or STRINGS[k]["en"]

    def _render_cell(col, val, _row):
        val_str = str(val) if val is not None else ""
        if str(col).strip().lower() == "enabled":
            if val_str.lower() in ("true", "1", "yes"):
                return f'<span class="badge-hit">{_s("rpt_yes")}</span>'
            return f'<span class="badge-unused">{_s("rpt_no")}</span>'
        return val_str

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
        lang=lang,
    )

class PolicyUsageHtmlExporter:
    def __init__(
        self,
        results: dict,
        df: pd.DataFrame = None,
        date_range: tuple = ("", ""),
        lookback_days: int = 30,
        profile: str = "security_risk",
        detail_level: str = _REPORT_DETAIL_LEVEL,
        lang: str = "en",
    ):
        self._r = results
        self._df = df
        self._date_range = date_range
        self._lookback_days = lookback_days
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_policy_usage_report_{ts}.html"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(self._build())
        logger.info("[PolicyUsageHtmlExporter] Saved: {}", filepath)
        return filepath

    def _build(self, profile: str = "", detail_level: str = "") -> str:
        profile = profile or self._profile
        detail_level = _REPORT_DETAIL_LEVEL
        self._chart_tracker = FirstChartTracker()
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s

        mod00 = self._r.get("mod00", {})
        date_str = " ~ ".join(self._date_range) if any(self._date_range) else ""
        period_part = (
            ' &nbsp;|&nbsp; ' + _s("rpt_period") + ' ' + date_str
            if date_str
            else ""
        )
        today_str = str(datetime.date.today())

        nav_html = (
            "<nav>"
            '<div class="nav-brand">Illumio PCE Ops</div>'
            f'<a href="#summary">{_s("rpt_pu_nav_summary")}</a>'
            f'<a href="#overview">{_s("rpt_pu_nav_overview")}</a>'
            f'<a href="#hit-rules">{_s("rpt_pu_nav_hit")}</a>'
            f'<a href="#unused-rules">{_s("rpt_pu_nav_unused")}</a>'
            f'<a href="#deny-rules">{_s("rpt_pu_nav_deny")}</a>'
            f'<a href="#draft-pd">{_s("rpt_pu_nav_draft_pd")}</a>'
            "</nav>"
        )

        exec_html = render_exec_summary_html(mod00, report_name='Policy Usage Report')
        body = (
            exec_html
            + '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_policy")}</div>'
            f'<h1>{_s("rpt_pu_title")}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} '
            + mod00.get("generated_at", "")
            + period_part
            + "</p></div>"
            + render_section_guidance("pu_mod00_executive",
                                      profile="security_risk",
                                      detail_level="full")
            + self._summary_pills(mod00)
            + self._kpi_html(mod00.get("kpis", []))
            + self._execution_html(mod00)
            + self._attention_html(mod00.get("attention_items", []))
            + "</section>\n"
            + self._section(
                "overview",
                "rpt_pu_sec_overview",
                self._mod01_html(),
            )
            + "\n"
            + self._section(
                "hit-rules",
                "rpt_pu_sec_hit",
                self._mod02_html(),
            )
            + "\n"
            + (self._section(
                "unused-rules",
                "rpt_pu_sec_unused",
                self._mod03_html(),
            )
            + "\n"
            if visible_in('pu_mod03_unused_detail', profile, detail_level) else '')
            + (self._section(
                "deny-rules",
                "rpt_pu_sec_deny",
                self._mod04_html(),
            )
            + "\n"
            if visible_in('pu_mod04_deny_effectiveness', profile, detail_level) else '')
            + self._section("draft-pd", "rpt_pu_sec_draft_pd", self._mod05_html())
            + "\n"
            + f'<footer>{_s("rpt_pu_footer")} &middot; {today_str}</footer>'
        )
        html_lang = "zh-TW" if self._lang == "zh_TW" else "en"
        return (
            f'<!DOCTYPE html><html lang="{html_lang}"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            "<title>Illumio Policy Usage Report</title>"
            + _CSS + _HIGHLIGHT_CSS
            + "</head>\n<body>"
            + nav_html
            + "<main>"
            + body
            + "</main>"
            + TABLE_JS
            + "</body></html>"
        )

    def _section(self, id_: str, i18n_key: str, content: str) -> str:
        return (
            f'<section id="{id_}" class="card">'
            f'<h2>{self._s(i18n_key)}</h2>'
            f"{content}</section>"
        )

    def _summary_pills(self, mod00: dict) -> str:
        _s = self._s
        hit_rate = mod00.get("hit_rate_pct", None)
        hit_rate_str = f"{hit_rate:.1f}%" if hit_rate is not None else "—"
        pills = [
            (_s("rpt_pill_lookback"), f"{self._lookback_days} days"),
            (_s("rpt_pill_period"), " ~ ".join(self._date_range) if any(self._date_range) else "N/A"),
            (_s("rpt_pill_hit_rate"), hit_rate_str),
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

    def _mod05_html(self) -> str:
        _s = self._s
        m = self._r.get("mod05", {})
        intro = f'<p class="section-intro">{_s("rpt_pu_draft_pd_intro")}</p>'
        if m.get("skipped") or m.get("total", 0) == 0:
            return intro + f'<p class="note">{_s("rpt_pu_draft_pd_empty")}</p>'

        html = intro

        vis = m.get("visibility_risk", {})
        if vis.get("total", 0):
            by_sub = vis["by_subtype"]
            html += (
                f'<h4>{_s("rpt_pu_draft_vis_heading")}</h4>'
                '<div class="summary-pill-row">'
                f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pu_draft_pd_by_boundary")}</span>'
                f'<span class="summary-pill-value">{by_sub.get("potentially_blocked_by_boundary", 0):,}</span></div>'
                f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pu_draft_pd_by_override")}</span>'
                f'<span class="summary-pill-value">{by_sub.get("potentially_blocked_by_override_deny", 0):,}</span></div>'
                '</div>'
            )
            tp = vis.get("top_pairs")
            if tp is not None and not tp.empty:
                html += (f'<h4>{_s("rpt_pu_draft_pd_top_pairs")}</h4>'
                         + _df_to_html(tp, no_data_key="rpt_no_records", lang=self._lang))

        conf = m.get("draft_conflicts", {})
        if conf.get("total", 0):
            by_sub = conf["by_subtype"]
            html += (
                f'<h4>{_s("rpt_pu_draft_conflict_heading")}</h4>'
                '<div class="summary-pill-row">'
                f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pu_draft_blocked_override")}</span>'
                f'<span class="summary-pill-value">{by_sub.get("blocked_by_override_deny", 0):,}</span></div>'
                f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pu_draft_allowed_boundary")}</span>'
                f'<span class="summary-pill-value">{by_sub.get("allowed_across_boundary", 0):,}</span></div>'
                '</div>'
            )
            tp = conf.get("top_pairs")
            if tp is not None and not tp.empty:
                html += (f'<h4>{_s("rpt_pu_draft_pd_top_pairs")}</h4>'
                         + _df_to_html(tp, no_data_key="rpt_no_records", lang=self._lang))

        cov = m.get("draft_coverage", {})
        if cov.get("total", 0):
            by_sub = cov["by_subtype"]
            html += (
                f'<h4>{_s("rpt_pu_draft_coverage_heading")}</h4>'
                '<div class="summary-pill-row">'
                f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pu_draft_new_allowed")}</span>'
                f'<span class="summary-pill-value">{by_sub.get("allowed", 0):,}</span></div>'
                f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pu_draft_blocked_boundary")}</span>'
                f'<span class="summary-pill-value">{by_sub.get("blocked_by_boundary", 0):,}</span></div>'
                '</div>'
            )
            tp = cov.get("top_pairs")
            if tp is not None and not tp.empty:
                html += (f'<h4>{_s("rpt_pu_draft_pd_top_pairs")}</h4>'
                         + _df_to_html(tp, no_data_key="rpt_no_records", lang=self._lang))

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
            f'<h4>{self._s("rpt_pu_attention")}</h4>'
            + rows
            + "</div>"
        )

    def _execution_html(self, mod00: dict) -> str:
        stats = mod00.get("execution_stats", {}) or {}
        notes = mod00.get("execution_notes", []) or []
        if not stats and not notes:
            return ""

        rows = [
            (self._s("rpt_pu_exec_cached_summaries"), stats.get("cached_rules", 0)),
            (self._s("rpt_pu_exec_new_queries"), stats.get("submitted_rules", 0)),
            (self._s("rpt_pu_exec_completed_jobs"), stats.get("completed_jobs", 0)),
            (self._s("rpt_pu_exec_pending_jobs"), stats.get("pending_jobs", 0)),
            (self._s("rpt_pu_exec_failed_jobs"), stats.get("failed_jobs", 0)),
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
            f'<h4>{self._s("rpt_pu_query_execution")}</h4>'
            + metrics_html
            + notes_html
            + "</div>"
        )

    def _mod01_html(self) -> str:
        html_parts = []
        html_parts.append(render_section_guidance("pu_mod01_overview",
                                                  profile="security_risk",
                                                  detail_level="full"))

        mod01 = self._r.get("mod01", {})
        total = mod01.get("total_rules", 0)
        hit = mod01.get("hit_count", 0)
        unused = mod01.get("unused_count", 0)
        rate = mod01.get("hit_rate_pct", 0.0)
        summary_df = mod01.get("summary_df")
        _s = self._s

        stats = (
            "<p>"
            f'{_s("rpt_pu_total_rules")}: <strong>{human_number(total)}</strong> &nbsp;|&nbsp; '
            f'<span class="badge-hit">{_s("rpt_pu_hit_rules")}</span> {human_number(hit)} &nbsp;|&nbsp; '
            f'<span class="badge-unused">{_s("rpt_pu_unused_rules")}</span> {human_number(unused)} &nbsp;|&nbsp; '
            f'{_s("rpt_pu_hit_rate")}: <strong>{rate}%</strong>'
            "</p>"
        )
        chart_html = ""
        if hit + unused > 0:
            try:
                spec = {
                    "type": "pie",
                    "title": self._s("rpt_pu_chart_hit_rate_title"),
                    "data": {
                        "labels": [self._s("rpt_pu_nav_hit"), self._s("rpt_pu_nav_unused")],
                        "values": [hit, unused],
                    },
                }
                div = render_plotly_html(spec, include_js=self._chart_tracker.consume())
                if div:
                    chart_html = f'<div class="chart-container">{div}</div>'
            except Exception:
                pass
        html_parts.append(stats + chart_html + _df_to_html(summary_df, lang=self._lang))
        return "".join(html_parts)

    def _mod02_html(self) -> str:
        html_parts = []
        html_parts.append(render_section_guidance("pu_mod02_hit_detail",
                                                  profile="security_risk",
                                                  detail_level="full"))

        mod02 = self._r.get("mod02", {})
        hit_df = mod02.get("hit_df")
        top_ports_df = mod02.get("top_ports_df")
        count = mod02.get("record_count", 0)
        note = f'<p style="color:#718096;font-size:12px;">{count} rows</p>' if count else ""
        top_ports_html = ""
        if top_ports_df is not None and not getattr(top_ports_df, "empty", True):
            top_ports_html = (
                '<div class="attention-box">'
                f'<h4>{self._s("rpt_pu_top_hit_ports")}</h4>'
                + _df_to_html(top_ports_df, lang=self._lang)
                + "</div>"
            )
        if hit_df is None or (hasattr(hit_df, "empty") and hit_df.empty):
            html_parts.append(top_ports_html + f'<p class="note">{self._s("rpt_pu_no_hit_rules")}</p>')
        else:
            html_parts.append(top_ports_html + note + _rule_cards_html(hit_df, mode="hit", lang=self._lang))
        return "".join(html_parts)

    def _mod03_html(self) -> str:
        html_parts = []
        html_parts.append(render_section_guidance("pu_mod03_unused_detail",
                                                  profile="security_risk",
                                                  detail_level="full"))

        mod03 = self._r.get("mod03", {})
        unused_df = mod03.get("unused_df")
        count = mod03.get("record_count", 0)
        caveat = mod03.get("caveat", "")

        caveat_html = ""
        if caveat:
            caveat_html = (
                '<div class="caveat-box">'
                f'<strong>{self._s("rpt_pu_caveat_title")}</strong><br>'
                f'<span>{caveat}</span>'
                "</div>"
            )

        if unused_df is None or (hasattr(unused_df, "empty") and unused_df.empty):
            html_parts.append(
                caveat_html
                + f'<p class="note">{self._s("rpt_pu_no_unused_rules")}</p>'
            )
        else:
            note = f'<p style="color:#718096;font-size:12px;">{count} rows</p>' if count else ""
            html_parts.append(caveat_html + note + _rule_cards_html(unused_df, mode="unused", lang=self._lang))
        return "".join(html_parts)

    def _mod04_html(self) -> str:
        html_parts = []
        html_parts.append(render_section_guidance("pu_mod04_deny_effectiveness",
                                                  profile="security_risk",
                                                  detail_level="full"))

        mod04 = self._r.get("mod04", {})
        total_deny = mod04.get("total_deny", 0)
        if total_deny == 0:
            html_parts.append(f'<p class="note">{self._s("rpt_pu_no_deny")}</p>')
            return "".join(html_parts)

        deny_hit = mod04.get("deny_hit_count", 0)
        deny_unused = mod04.get("deny_unused_count", 0)
        deny_hit_rate = mod04.get("deny_hit_rate_pct", 0.0)
        deny_ratio = mod04.get("deny_ratio_pct", 0.0)
        override_count = mod04.get("override_deny_count", 0)
        _s = self._s

        stats = (
            "<p>"
            f'{_s("rpt_pu_deny_total")}: <strong>{total_deny}</strong> '
            f'({deny_ratio}% of all rules) &nbsp;|&nbsp; '
            f'<span class="badge-hit">{_s("rpt_pu_deny_hit")}</span> {deny_hit} &nbsp;|&nbsp; '
            f'<span class="badge-unused">{_s("rpt_pu_deny_unused")}</span> {deny_unused} &nbsp;|&nbsp; '
            f'{_s("rpt_pu_deny_hit_rate")}: <strong>{deny_hit_rate}%</strong>'
            "</p>"
        )

        if override_count > 0:
            stats += (
                '<p class="note note-warn">'
                f'<strong>{_s("rpt_pu_override_deny")}</strong> {override_count} '
                '— these take highest priority and bypass all other rules. Review for correctness.</p>'
            )

        summary_df = mod04.get("deny_summary_df")
        summary_html = _df_to_html(summary_df, lang=self._lang) if summary_df is not None else ""

        detail_df = mod04.get("deny_detail_df")
        detail_html = ""
        if detail_df is not None and not detail_df.empty:
            detail_html = (
                f'<h3>{_s("rpt_pu_deny_detail")}</h3>'
                + _df_to_html(detail_df, lang=self._lang)
            )

        html_parts.append(stats + summary_html + detail_html)
        return "".join(html_parts)
