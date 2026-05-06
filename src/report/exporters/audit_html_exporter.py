"""Self-contained HTML report for the Audit & System Events Report."""

from __future__ import annotations

import datetime
from loguru import logger
import os

import pandas as pd

from .html_exporter import _trend_deltas_section, render_section_guidance
from src.report.section_guidance import visible_in
from .report_css import TABLE_JS, build_css
from src.humanize_ext import human_number
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS
from .table_renderer import render_df_table
from .chart_renderer import render_plotly_html, FirstChartTracker
from .code_highlighter import get_highlight_css
from src.report.analysis.audit.audit_risk import RISK_BG, RISK_COLOR, get_risk
from src.report.exporters._exec_summary import render_exec_summary_html

_CSS = build_css("audit")
_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'
_REPORT_DETAIL_LEVEL = "full"


def _chart_html(spec: dict | None, include_js: bool = True) -> str:
    """Render a chart_spec as a styled chart-container div, or '' on failure."""
    if not spec:
        return ""
    try:
        div = render_plotly_html(spec, include_js=include_js)
        return f'<div class="chart-container">{div}</div>' if div else ""
    except Exception as exc:
        logger.warning("audit chart render failed: {}", exc)
        return ""


def _norm_col(name) -> str:
    """Tolerant column-name match: case-insensitive, whitespace/dash collapsed."""
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")

def _df_to_html(df, no_data_key: str = "rpt_no_data", show_risk: bool = False, lang: str = "en") -> str:
    event_type_col = None
    if show_risk and df is not None and not (hasattr(df, "empty") and df.empty):
        for c in df.columns:
            if _norm_col(c) == "event_type":
                event_type_col = c
                break

    def _row_attrs(row):
        if not event_type_col:
            return ""
        risk_level = get_risk(str(row[event_type_col]))[0]
        if risk_level == "CRITICAL":
            return " style='background:#FEF2F2;'"
        if risk_level == "HIGH":
            return " style='background:#FFF7ED;'"
        return ""

    def _render_cell(col, val, row):
        if event_type_col and col == event_type_col:
            risk_level = get_risk(str(row[event_type_col]))[0]
            color = RISK_COLOR.get(risk_level, "#989A9B")
            bg = RISK_BG.get(risk_level, "#F9FAFB")
            badge = (
                f"<span class='risk-badge' style='background:{bg};color:{color};border-color:{color}'>"
                f"{risk_level}</span>"
            )
            return f"{badge}{row[col]}"
        return "" if row[col] is None else str(row[col])

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
        row_attrs=_row_attrs,
        lang=lang,
    )

class AuditHtmlExporter:
    def __init__(self, results: dict, df: pd.DataFrame = None, date_range: tuple = ("", ""), data_source: str = "",
                 profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en"):
        self._r = results
        self._df = df
        self._date_range = date_range
        self._data_source = data_source
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang

    @staticmethod
    def _risk_badge(risk_level: str) -> str:
        color = RISK_COLOR.get(risk_level, "#989A9B")
        bg = RISK_BG.get(risk_level, "#F9FAFB")
        return (
            f"<span class='risk-badge' style='background:{bg};color:{color};border-color:{color}'>"
            f"{risk_level}</span>"
        )

    def _attention_section(self, attention_items: list) -> str:
        if not attention_items:
            return ""
        _s = self._s
        items_html = ""
        for item in attention_items:
            risk = item.get("risk", "INFO")
            badge = self._risk_badge(risk)
            event_type = item.get("event_type", "")
            count = item.get("count", 0)
            summary = item.get("summary", "")
            rec = item.get("recommendation", "")
            actors_str = ", ".join(str(a) for a in item.get("actors", [])[:3]) or "N/A"
            targets_str = ", ".join(str(a) for a in item.get("targets", [])[:3])
            resources_str = ", ".join(str(a) for a in item.get("resources", [])[:3])
            src_ips_str = ", ".join(str(ip) for ip in item.get("src_ips", [])[:3])
            items_html += (
                f'<div class="audit-attn-item risk-{risk}">'
                f'<div class="audit-attn-header">'
                f'{badge}'
                f'<code class="audit-attn-event-code">{event_type}</code>'
                f'<span class="audit-attn-count">x{count}</span>'
                f'</div>'
                f'<div class="audit-attn-summary">{summary}</div>'
                f'<div class="audit-attn-meta">'
                f'<strong>{_s("rpt_au_actor")}</strong> {actors_str}'
                + (f' &nbsp;|&nbsp; <strong>IP:</strong> {src_ips_str}' if src_ips_str else '')
                + '</div>'
                + (
                    f'<div class="audit-attn-meta">'
                    f'<strong>Target:</strong> {targets_str}'
                    + (f' &nbsp;|&nbsp; <strong>Resource:</strong> {resources_str}' if resources_str else '')
                    + '</div>'
                    if targets_str or resources_str else ''
                )
                + f'<div class="audit-attn-rec"><strong>{_s("rpt_au_rec")}</strong> {rec}</div>'
                f'</div>'
            )
        return (
            '<div style="margin-bottom:20px">'
            f'<h2 style="color:var(--red)">{_s("rpt_au_attention_title")}</h2>'
            + items_html
            + '</div>'
        )

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_audit_report_{ts}.html"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self._build())
        logger.info("[AuditHtmlExporter] Saved: {}", filepath)
        return filepath

    def _build(self, profile: str = "", detail_level: str = "") -> str:
        profile = profile or self._profile
        detail_level = _REPORT_DETAIL_LEVEL
        self._chart_tracker = FirstChartTracker()
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s

        mod00 = self._r.get("mod00", {})
        nav_html = (
            "<nav>"
            '<div class="nav-brand">Illumio PCE Ops</div>'
            f'<a href="#summary">{_s("rpt_au_nav_summary")}</a>'
            f'<a href="#health">{_s("rpt_au_nav_health")}</a>'
            f'<a href="#users">{_s("rpt_au_nav_users")}</a>'
            f'<a href="#policy">{_s("rpt_au_nav_policy")}</a>'
            f'<a href="#correlation">{_s("rpt_au_nav_correlation")}</a>'
            "</nav>"
        )
        kpi_cards = "".join(
            '<div class="kpi-card"><div class="kpi-label">' + k["label"] + "</div>"
            '<div class="kpi-value">' + k["value"] + "</div></div>"
            for k in mod00.get("kpis", [])
        )
        date_str = " ~ ".join(self._date_range) if any(self._date_range) else ""
        today_str = str(datetime.date.today())
        period_part = (
            ' &nbsp;|&nbsp; ' + _s("rpt_period") + ' ' + date_str if date_str else ""
        )
        summary_pills = (
            '<div class="summary-pill-row">'
            f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pill_period")}</span><span class="summary-pill-value">{date_str or "N/A"}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pill_attention")}</span><span class="summary-pill-value">{human_number(len(mod00.get("attention_items", [])))}</span></div>'
            f'<div class="summary-pill"><span class="summary-pill-label">{_s("rpt_pill_focus")}</span><span class="summary-pill-value">{_s("rpt_focus_audit")}</span></div>'
            "</div>"
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
            summary_pills = summary_pills.replace("</div>", data_source_pill + "</div>", 1)

        exec_html = render_exec_summary_html(mod00, report_name='Audit Report')
        body = (
            exec_html
            + render_section_guidance("audit_mod00_executive", profile="security_risk", detail_level="full")
            + '<section id="summary" class="card report-hero">'
            '<div class="report-hero-top">'
            f'<div class="report-kicker">{_s("rpt_kicker_audit")}</div>'
            f'<h1>{_s("rpt_au_title")}</h1>'
            f'<p class="report-subtitle">{_s("rpt_generated")} '
            + mod00.get("generated_at", "") + period_part + "</p></div>"
            + summary_pills
            + self._attention_section(mod00.get("attention_items", []))
            + f'<h2>{_s("rpt_key_metrics")}</h2>'
            + '<div class="kpi-grid">' + kpi_cards + "</div>"
            + self._trend_deltas_html()
            + self._severity_dist_html(mod00)
            + f'<h2>{_s("rpt_au_top_events")}</h2>'
            + _chart_html(mod00.get("chart_spec"), include_js=self._chart_tracker.consume())
            + _df_to_html(mod00.get("top_events_overall"), lang=_sl)
            + "</section>\n"
            + self._section("health", "rpt_au_sec_health", self._mod01_html())
            + "\n"
            + self._section("users", "rpt_au_sec_users", self._mod02_html())
            + "\n"
            + (self._section("policy", "rpt_au_sec_policy", self._mod03_html())
               + "\n"
               if visible_in('audit_mod03_policy', profile, detail_level) else '')
            + (self._section("correlation", "rpt_au_sec_correlation", self._mod04_html())
               + "\n"
               if visible_in('audit_mod04_correlation', profile, detail_level) else '')
            + f'<footer>{_s("rpt_au_footer")} &middot; {today_str}</footer>'
        )
        return (
            f'<!DOCTYPE html><html lang="{"zh-TW" if self._lang == "zh_TW" else "en"}"><head>\n'
            "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>Illumio Audit Report</title>"
            + _CSS + _HIGHLIGHT_CSS
            + "</head>\n"
            + "<body>"
            + nav_html
            + "<main>"
            + body
            + "</main>"
            + TABLE_JS
            + "</body></html>"
        )

    def _section(self, id_: str, i18n_key: str, content: str) -> str:
        return f'<section id="{id_}" class="card"><h2>{self._s(i18n_key)}</h2>{content}</section>'

    def _trend_deltas_html(self) -> str:
        return _trend_deltas_section(self._r.get("_trend_deltas"))

    def _subnote(self, i18n_key: str, en_text: str = "") -> str:
        text = self._s(i18n_key) if i18n_key else en_text
        return f'<p class="note" style="font-size:12px;">{text}</p>'

    def _severity_dist_html(self, mod00: dict) -> str:
        sev_df = mod00.get("severity_distribution")
        if sev_df is None or (hasattr(sev_df, "empty") and sev_df.empty):
            return ""
        chart_html = ""
        try:
            labels = sev_df["Severity"].tolist()
            values = sev_df["Count"].tolist()
            if labels and any(v > 0 for v in values):
                spec = {
                    "type": "pie",
                    "title": "Event Severity Distribution",
                    "data": {"labels": labels, "values": values},
                }
                chart_html = _chart_html(spec, include_js=self._chart_tracker.consume())
        except Exception:
            pass
        return (
            f'<h2>{self._s("rpt_au_severity_dist")}</h2>'
            + chart_html
            + _df_to_html(sev_df, lang=self._lang)
        )

    def _high_impact_provisions_html(self, items: list, threshold: int) -> str:
        if not items:
            return ""
        _s = self._s
        html = (
            f"<div style='margin-bottom:14px; padding:12px 16px; background:#FEF2F2; border:1px solid #FCA5A5; border-radius:8px;'>"
            f"<div style='font-weight:700; font-size:13px; color:#991B1B; margin-bottom:6px;'>{_s('rpt_au_high_impact_title')}</div>"
            f"<p style='font-size:12px; color:#7F1D1D; margin:0 0 10px 0;'>{_s('rpt_au_high_impact_desc')} (threshold: {threshold}+)</p>"
        )
        for item in items:
            wa = item.get("workloads_affected", 0)
            ts = item.get("timestamp", "")
            et = item.get("event_type", "")
            actor = item.get("actor", "N/A")
            src_ip = item.get("src_ip", "")
            resource_name = item.get("resource_name", "")
            status = item.get("status", "")
            html += (
                f"<div style='display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:8px 10px; background:#FFF5F5; "
                f"border-radius:6px; margin-bottom:6px; border-left:4px solid #EF4444;'>"
                f"<span style='font-size:20px; font-weight:900; color:#DC2626;'>{wa:,}</span>"
                f"<span style='font-size:11px; color:#991B1B;'>{_s('rpt_au_workloads_affected')}</span>"
                f"<code style='font-size:11px; background:#FEE2E2; padding:2px 6px; border-radius:3px; color:#7F1D1D;'>{et}</code>"
                f"<span style='font-size:11px; color:#6B7280;'>{ts}</span>"
                f"<span style='font-size:11px; color:#6B7280;'>by <b>{actor}</b></span>"
                + (f"<span style='font-size:11px; color:#6B7280;'>resource <b>{resource_name}</b></span>" if resource_name else "")
                + (f"<span style='font-size:11px; color:#6B7280;'>from <code>{src_ip}</code></span>" if src_ip else "")
                + (f"<span style='font-size:11px; color:#6B7280;'>| {status}</span>" if status else "")
                + "</div>"
            )
        html += "</div>"
        return html

    def _mod01_html(self) -> str:
        m = self._r.get("mod01", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod01_health", profile="security_risk", detail_level="full")]

        sec_count = m.get("security_concern_count", 0)
        conn_count = m.get("connectivity_event_count", 0)
        html = (
            self._subnote("rpt_au_mod01_intro")
            + f'<p>{_s("rpt_au_total_health")} <b>{m.get("total_health_events", 0)}</b>'
            + ' &nbsp;|&nbsp; '
            + f'{_s("rpt_au_security_concerns")} <b style="color:{"#c0392b" if sec_count > 0 else "#313638"}">{sec_count}</b>'
            + ' &nbsp;|&nbsp; '
            + f'{_s("rpt_au_connectivity_issues")} <b>{conn_count}</b></p>'
        )
        html += f'<div class="bp-box">{_s("rpt_au_bp_health")}</div>'

        sec_df = m.get("security_concerns")
        if sec_df is not None and not sec_df.empty:
            html += (
                f'<h3>{_s("rpt_au_sec_concern_title")}</h3>'
                f'<p class="note note-warn">{_s("rpt_au_sec_concern_desc")}</p>'
                + _df_to_html(sec_df, show_risk=True, lang=_lang)
            )

        conn_df = m.get("connectivity_events")
        if conn_df is not None and not conn_df.empty:
            html += (
                self._subnote("rpt_au_connectivity_subnote")
                + f'<h3>{_s("rpt_au_connectivity_title")}</h3>'
                + _df_to_html(conn_df, show_risk=True, lang=_lang)
            )

        html += f'<h3>{_s("rpt_au_severity_breakdown")}</h3>' + _df_to_html(m.get("severity_breakdown"), lang=_lang)
        html += f'<h3>{_s("rpt_au_summary_type")}</h3>' + _df_to_html(m.get("summary"), lang=_lang)
        html += f'<h3>{_s("rpt_au_recent")}</h3>' + _df_to_html(m.get("recent"), show_risk=True, lang=_lang)
        return "".join(html_parts) + html

    def _mod02_html(self) -> str:
        m = self._r.get("mod02", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod02_users", profile="security_risk", detail_level="full")]

        failed = m.get("failed_logins", 0)
        unique_ips = m.get("unique_src_ips", 0)
        html = (
            self._subnote("rpt_au_mod02_intro")
            + f'<p>{_s("rpt_au_total_user")} <b>{m.get("total_user_events", 0)}</b>'
            + ' &nbsp;|&nbsp; '
            + f'{_s("rpt_au_failed_logins")} <b style="color:{"#c0392b" if failed > 0 else "#313638"}">{failed}</b>'
        )
        if unique_ips > 0:
            html += f' &nbsp;|&nbsp; {_s("rpt_au_unique_src_ips")} <b>{unique_ips}</b>'
        html += "</p>"
        html += f'<div class="bp-box">{_s("rpt_au_bp_users")}</div>'

        failed_detail = m.get("failed_login_detail")
        if failed_detail is not None and not (hasattr(failed_detail, "empty") and failed_detail.empty):
            html += (
                self._subnote("rpt_au_failed_detail_subnote")
                + f'<h3>{_s("rpt_au_failed_detail")}</h3>'
                + f'<p class="note note-warn">{_s("rpt_au_failed_detail_desc")}</p>'
                + _df_to_html(failed_detail, show_risk=True, lang=_lang)
            )

        per_user = m.get("per_user")
        if per_user is not None and not (hasattr(per_user, "empty") and per_user.empty):
            html += (
                f'<h3>{_s("rpt_au_per_user")}</h3>'
                + _chart_html(m.get("chart_spec"), include_js=self._chart_tracker.consume())
                + _df_to_html(per_user, lang=_lang)
            )

        html += f'<h3>{_s("rpt_au_summary_type")}</h3>' + _df_to_html(m.get("summary"), lang=_lang)
        html += f'<h3>{_s("rpt_au_recent")}</h3>' + _df_to_html(m.get("recent"), show_risk=True, lang=_lang)
        return "".join(html_parts) + html

    def _mod03_html(self) -> str:
        m = self._r.get("mod03", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod03_policy", profile="security_risk", detail_level="full")]

        prov_count = m.get("provision_count", 0)
        rule_count = m.get("rule_change_count", 0)
        total_wa = m.get("total_workloads_affected", 0)
        threshold = m.get("high_impact_threshold", 50)
        high_impact = m.get("high_impact_provisions", [])

        html = (
            self._subnote("rpt_au_mod03_intro")
            + f'<p>{_s("rpt_au_total_policy")} <b>{m.get("total_policy_events", 0)}</b>'
            + ' &nbsp;|&nbsp; '
            + f'{_s("rpt_au_provisions")} <b>{prov_count}</b>'
            + ' &nbsp;|&nbsp; '
            + f'{_s("rpt_au_rule_changes")} <b>{rule_count}</b>'
            + ' &nbsp;|&nbsp; '
            + f'{_s("rpt_au_provision_impact_stat")} <b style="color:{"#c0392b" if total_wa > threshold else "#313638"}">{f"{total_wa:,}" if total_wa else "0"}</b></p>'
        )
        html += f'<div class="bp-box">{_s("rpt_au_bp_policy")}</div>'
        html += f'<div class="bp-box">{_s("rpt_au_change_detail_note")}</div>'
        html += self._high_impact_provisions_html(high_impact, threshold)

        provisions = m.get("provisions")
        if provisions is not None and not (hasattr(provisions, "empty") and provisions.empty):
            html += (
                self._subnote("rpt_au_provision_subnote")
                + f'<h3>{_s("rpt_au_provision_title")}</h3>'
                + f'<p class="note note-warn">{_s("rpt_au_provision_desc")}</p>'
                + f'<p class="note" style="font-size:.82rem">{_s("rpt_au_provision_change_detail_note")}</p>'
                + _df_to_html(provisions, show_risk=True, lang=_lang)
            )

        draft_events = m.get("draft_events")
        if draft_events is not None and not (hasattr(draft_events, "empty") and draft_events.empty):
            html += (
                self._subnote("rpt_au_draft_subnote")
                + f'<h3>{_s("rpt_au_draft_section")}</h3>'
                + f'<p class="note">{_s("rpt_au_draft_desc")}</p>'
                + f'<p class="note" style="font-size:.82rem">{_s("rpt_au_draft_change_detail_note")}</p>'
                + _df_to_html(draft_events, show_risk=True, lang=_lang)
            )

        per_user = m.get("per_user")
        if per_user is not None and not (hasattr(per_user, "empty") and per_user.empty):
            html += (
                self._subnote("rpt_au_per_user_policy_subnote")
                + f'<h3>{_s("rpt_au_per_user_policy")}</h3>'
                + _chart_html(m.get("chart_spec"), include_js=self._chart_tracker.consume())
                + _df_to_html(per_user, lang=_lang)
            )

        html += f'<h3>{_s("rpt_au_summary_type")}</h3>' + _df_to_html(m.get("summary"), lang=_lang)
        html += f'<h3>{_s("rpt_au_recent")}</h3>' + _df_to_html(m.get("recent"), show_risk=True, lang=_lang)
        return "".join(html_parts) + html

    def _mod04_html(self) -> str:
        m = self._r.get("mod04", {})
        if "error" in m:
            return f'<p class="note">{m["error"]}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod04_correlation", profile="security_risk", detail_level="full")]

        total_corr = m.get("total_correlations", 0)
        total_bf = m.get("total_brute_force", 0)
        total_oh = m.get("total_off_hours", 0)
        window = m.get("window_minutes", 30)

        html = (
            self._subnote("rpt_au_mod04_intro")
            + (
                f'<p class="note" style="font-size:12px;">'
                f'{_s("rpt_au_mod04_window_prefix")} <b>{window}</b> {_s("rpt_au_mod04_window_suffix")}'
                f'</p>'
            )
            + f'<p>{_s("rpt_au_corr_summary")} <b>{total_corr}</b>'
            + f' &nbsp;|&nbsp; {_s("rpt_au_brute_force")} <b>{total_bf}</b>'
            + f' &nbsp;|&nbsp; {_s("rpt_au_off_hours")} <b>{total_oh}</b></p>'
        )

        corr_df = m.get("correlated_sequences")
        if corr_df is not None and hasattr(corr_df, "empty") and not corr_df.empty:
            html += (
                f'<h3>{_s("rpt_au_corr_sequences")}</h3>'
                f'<p class="note note-warn">{_s("rpt_au_corr_desc")}</p>'
                + _df_to_html(corr_df, lang=_lang)
            )

        bf_df = m.get("brute_force_detections")
        if bf_df is not None and hasattr(bf_df, "empty") and not bf_df.empty:
            html += (
                f'<h3>{_s("rpt_au_brute_section")}</h3>'
                f'<p class="note">{_s("rpt_au_brute_desc")}</p>'
                + _df_to_html(bf_df, lang=_lang)
            )

        oh_df = m.get("off_hours_operations")
        if oh_df is not None and hasattr(oh_df, "empty") and not oh_df.empty:
            html += (
                f'<h3>{_s("rpt_au_offhours_section")}</h3>'
                f'<p class="note">{_s("rpt_au_offhours_desc")}</p>'
                + _df_to_html(oh_df, lang=_lang)
            )

        if total_corr == 0 and total_bf == 0 and total_oh == 0:
            html += f'<p class="note">{_s("rpt_au_no_correlation")}</p>'

        return "".join(html_parts) + html
