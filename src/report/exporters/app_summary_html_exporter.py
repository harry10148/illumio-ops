"""App Summary HTML exporter — standalone single-app report.

Uses the SHARED report styling (report_css.build_css + cover_page) so it matches
the other standalone reports (audit/ven/policy_usage): shared fonts, cover page,
and the .report-shell / .report-main / .card layout.

Six sections: cover, KPI row, inbound baseline, outbound dependencies, policy
coverage (this app), findings. Empty App Labels render a valid single-page
report carrying the rpt_app_empty note rather than raising.

Contract: __init__(results, lang) + export(output_dir) -> path.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.app_summary_report import _safe_filename_token
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.report_css import TABLE_JS, build_css
from src.report.exporters.table_renderer import render_df_table

_CSS = build_css("app_summary")


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{_esc(label)}</div>'
        f'<div class="kpi-value">{_esc(value)}</div></div>'
    )


class AppSummaryHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _section(self, id_: str, title: str, content: str) -> str:
        return f'<section id="{id_}" class="card"><h2>{title}</h2>{content}</section>'

    def _kpi_row(self) -> str:
        base = self._r.get("baseline", {})
        mod03 = self._r.get("mod03", {})
        coverage = mod03.get("enforced_coverage_pct", 0.0)
        return (
            _kpi(base.get("flow_count", 0), t("rpt_flow_count", lang=self._lang))
            + _kpi(base.get("inbound_count", 0), t("rpt_app_inbound", lang=self._lang))
            + _kpi(base.get("outbound_count", 0), t("rpt_app_outbound", lang=self._lang))
            + _kpi(f"{coverage}%", t("rpt_app_coverage", lang=self._lang))
        )

    def _coverage_section(self) -> str:
        mod03 = self._r.get("mod03", {})
        cards = (
            _kpi(mod03.get("n_allowed", 0), t("rpt_enforced", default="Enforced", lang=self._lang))
            + _kpi(mod03.get("pb_uncovered_count", 0), t("rpt_staged", default="Staged", lang=self._lang))
            + _kpi(mod03.get("n_blocked", 0) + mod03.get("n_unknown", 0),
                   t("rpt_gap", default="Gap", lang=self._lang))
        )
        top = render_df_table(mod03.get("top_flows"), col_i18n={}, lang=self._lang)
        return f'<div class="kpi-grid">{cards}</div>{top}'

    def _policy_impact_section(self) -> str:
        pi = self._r.get("policy_impact") or {}
        if not pi.get("available"):
            return f'<p class="note">{_esc(t("rpt_app_no_policy_impact", lang=self._lang))}</p>'
        cards = (
            _kpi(f'{pi["coverage_pct"]}%', t("rpt_app_pi_coverage", lang=self._lang))
            + _kpi(str(pi["would_be_blocked"]), t("rpt_app_pi_would_block", lang=self._lang))
            + _kpi(str(pi["allowed"]), t("rpt_app_pi_allowed", lang=self._lang))
            + _kpi(str(pi["blocked"]), t("rpt_app_pi_blocked", lang=self._lang))
        )
        note = _esc(t("rpt_app_pi_note", lang=self._lang)).replace("{n}", str(pi["would_be_blocked"]))
        return f'<div class="kpi-grid">{cards}</div><p class="note">{note}</p>'

    def _enforcement_section(self) -> str:
        en = self._r.get("enforcement") or {}
        if not en.get("available"):
            return f'<p class="note">{_esc(t("rpt_app_enf_unavailable", lang=self._lang))}</p>'
        summary = _esc(t("rpt_app_enf_summary", lang=self._lang)) \
            .replace("{enforced}", str(en["enforced"])).replace("{total}", str(en["total"]))
        table = render_df_table(en.get("table"), col_i18n={}, lang=self._lang)
        return f'<p class="note">{summary}</p>{table}'

    def _findings_section(self) -> str:
        findings = self._r.get("findings", []) or []
        if not findings:
            return render_df_table(None, col_i18n={}, lang=self._lang)
        rows = []
        for f in findings:
            sev = _esc(getattr(f, "severity", ""))
            badge = f'<span class="badge badge-{sev}">{sev}</span>' if sev else ""
            rows.append(
                f"<tr><td>{badge}</td>"
                f"<td>{_esc(getattr(f, 'rule_id', ''))}</td>"
                f"<td>{_esc(getattr(f, 'description', ''))}</td></tr>"
            )
        return (
            "<table class='report-table'><thead><tr>"
            f"<th>{_esc(t('rpt_col_severity', lang=self._lang))}</th>"
            f"<th>{_esc(t('rpt_col_rule_name', lang=self._lang))}</th>"
            f"<th>{_esc(t('rpt_col_description', lang=self._lang))}</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )

    def _render_html(self) -> str:
        lang = self._lang
        title = t("rpt_app_title", lang=lang)
        app = self._r.get("app", "")
        env = self._r.get("env", "")
        # Pass raw app/env — build_cover_page escapes its args (avoid double-escape).
        sub = app + (f" / {env}" if env else "")

        cover_html = _build_cover_page(
            title=title,
            report_type=sub or title,
            lang=lang,
        )

        if self._r.get("empty"):
            sections = self._section(
                "findings", _esc(t("rpt_app_findings", lang=lang)),
                f'<p class="note">{_esc(t("rpt_app_empty", lang=lang))}</p>',
            )
        else:
            base = self._r.get("baseline", {})
            inbound = render_df_table(base.get("inbound"), col_i18n={}, lang=lang)
            outbound = render_df_table(base.get("outbound"), col_i18n={}, lang=lang)
            sections = (
                f'<section class="card"><div class="kpi-grid">{self._kpi_row()}</div></section>'
                + self._section("inbound", _esc(t("rpt_app_inbound", lang=lang)), inbound)
                + self._section("outbound", _esc(t("rpt_app_outbound", lang=lang)), outbound)
                + self._section("coverage", _esc(t("rpt_app_coverage", lang=lang)), self._coverage_section())
                + self._section("policy-impact", _esc(t("rpt_app_policy_impact", lang=lang)), self._policy_impact_section())
                + self._section("enforcement", _esc(t("rpt_app_enforcement", lang=lang)), self._enforcement_section())
                + self._section("findings", _esc(t("rpt_app_findings", lang=lang)), self._findings_section())
            )

        lang_attr = "zh-TW" if lang == "zh_TW" else "en"
        return (
            f'<!DOCTYPE html><html lang="{lang_attr}"><head>\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n'
            f"<title>{_esc(title)}</title>"
            + _CSS
            + "</head>\n"
            + f'<body data-report-title="{_esc(title)}">'
            + cover_html
            + '<div class="report-shell"><main class="report-main">'
            + sections
            + "</main></div>"
            + TABLE_JS
            + "</body></html>"
        )

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        html = self._render_html()
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        token = _safe_filename_token(self._r.get("app", "app"))
        path = os.path.join(output_dir, f"Illumio_App_Summary_{token}_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return path
