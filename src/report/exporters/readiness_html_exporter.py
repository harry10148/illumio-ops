"""Enforcement Readiness HTML exporter.

Facade contract: __init__(result, lang, pce_url, org_name) + export(output_dir).
Long-cell policy (CLAUDE.md): cells in _TRUNC_COLS longer than _CELL_MAX chars
are truncated to _CELL_MAX-1 chars + ellipsis; the FULL value is preserved in
the cell's title attribute and in the CSV export. Never silent.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.report_css import TABLE_JS, build_css

_CSS = build_css("readiness")  # unknown type -> base styling (incl. @media print)
_CELL_MAX = 160

_QUEUE_COLS = ["app_display", "readiness_score", "grade", "current_mode",
               "blocking_factor", "recommended_action", "flow_count",
               "pb_uncovered_count"]
_QUEUE_COL_I18N = {
    "app_display": "rpt_readiness_col_app",
    "readiness_score": "rpt_readiness_col_score",
    "grade": "rpt_readiness_col_grade",
    "current_mode": "rpt_readiness_col_mode",
    "blocking_factor": "rpt_readiness_col_blocking",
    "recommended_action": "rpt_readiness_col_action",
    "flow_count": "rpt_readiness_col_flows",
    "pb_uncovered_count": "rpt_readiness_col_pb",
}
_TRUNC_COLS = {"app_display", "current_mode", "recommended_action", "Action"}
_DIR_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    return ('<div class="kpi-card">'
            f'<div class="kpi-label">{_esc(label)}</div>'
            f'<div class="kpi-value">{_esc(value)}</div></div>')


class ReadinessHtmlExporter:
    def __init__(self, result, lang: str = "en", pce_url: str = "", org_name: str = ""):
        self._result = result
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    # ── cells / tables ────────────────────────────────────────────────
    def _cell(self, col: str, value) -> str:
        text = "" if value is None else str(value)
        if col in _TRUNC_COLS and len(text) > _CELL_MAX:
            shown = text[:_CELL_MAX - 1] + "…"
            return f'<td title="{_esc(text)}">{_esc(shown)}</td>'
        return f"<td>{_esc(text)}</td>"

    def _table(self, df, cols: list[str], header_of) -> str:
        if df is None or df.empty:
            return f'<p class="note">{_esc(t("rpt_readiness_no_rows", lang=self._lang))}</p>'
        use = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{_esc(header_of(c))}</th>" for c in use)
        body = "".join(
            "<tr>" + "".join(self._cell(c, row.get(c, "")) for c in use) + "</tr>"
            for _, row in df.iterrows())
        return ('<div class="report-table-wrap"><table class="report-table sortable">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    # ── sections ──────────────────────────────────────────────────────
    def _summary(self, readiness, kpis) -> str:
        lang = self._lang
        kpi_row = '<div class="kpi-row">' + "".join(
            _kpi(k.get("value", ""), k.get("label", k.get("i18n_key", ""))) for k in kpis
        ) + "</div>"
        return (f'<p class="note">{_esc(t("rpt_readiness_subnote", lang=lang))}</p>'
                + kpi_row)

    def _factor_legend(self) -> str:
        lang = self._lang
        rows = "".join(
            f'<li><b>{_esc(t(f"rpt_factor_{name}", lang=lang))}</b> — '
            f'{t(f"rpt_mod13_col_guide_{guide}", lang=lang)}</li>'
            for name, guide in [("policy_coverage", "policy"),
                                ("ringfence_maturity", "ringfence"),
                                ("enforcement_mode", "enforcement"),
                                ("staged_readiness", "staged"),
                                ("remote_app_coverage", "remote")])
        return f'<ul class="note">{rows}</ul>'

    def _recommendations(self, recs) -> str:
        lang = self._lang
        if recs is None or recs.empty:
            return f'<p class="note">{_esc(t("rpt_readiness_no_rows", lang=lang))}</p>'
        rollup = (recs.groupby("Action")["App Env Key"].nunique()
                  .sort_values(ascending=False).reset_index())
        rollup.columns = [t("rpt_readiness_rollup_action", lang=lang),
                          t("rpt_readiness_rollup_apps", lang=lang)]
        rollup_html = self._table(rollup, list(rollup.columns), lambda c: c)
        detail_cols = ["Priority", "App (Env)", "Issue", "Action", "Severity"]
        detail_html = self._table(recs, detail_cols, lambda c: c)
        return rollup_html + detail_html

    def _trend(self, deltas) -> str:
        lang = self._lang
        if not deltas:
            return f'<p class="note">{_esc(t("rpt_readiness_trend_first_run", lang=lang))}</p>'
        head = "".join(f"<th>{_esc(t(k, lang=lang))}</th>" for k in
                       ("rpt_readiness_trend_col_metric", "rpt_readiness_trend_col_current",
                        "rpt_readiness_trend_col_previous", "rpt_readiness_trend_col_delta"))
        body = "".join(
            "<tr>"
            f"<td>{_esc(t(d.get('metric', ''), lang=lang))}</td>"
            f"<td>{_esc(d.get('current', ''))}</td>"
            f"<td>{_esc(d.get('previous', ''))}</td>"
            f"<td>{_DIR_ARROW.get(d.get('direction', 'flat'), '→')} {_esc(d.get('delta', ''))}</td>"
            "</tr>" for d in deltas)
        return ('<div class="report-table-wrap"><table class="report-table">'
                f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    # ── document ──────────────────────────────────────────────────────
    def _render_html(self) -> str:
        lang = self._lang
        mr = self._result.module_results or {}
        readiness = mr.get("readiness", {})
        cover = _build_cover_page(
            t("rpt_readiness_report_title", lang=lang),
            t("rpt_readiness_cover_type", lang=lang),
            date_range=self._result.date_range,
            pce_url=self._pce_url, org_name=self._org_name, lang=lang,
            maturity_grade=readiness.get("grade"))
        sections = [
            ("readiness-summary", t("rpt_readiness_sec_summary", lang=lang),
             self._summary(readiness, mr.get("kpis", []))),
            ("readiness-queue", t("rpt_readiness_sec_queue", lang=lang),
             self._table(mr.get("queue_df"), _QUEUE_COLS,
                         lambda c: t(_QUEUE_COL_I18N.get(c, c), lang=lang))),
            ("readiness-factors", t("rpt_readiness_sec_factors", lang=lang),
             self._factor_legend()
             + self._table(readiness.get("factor_table"),
                           list(getattr(readiness.get("factor_table"), "columns", [])),
                           lambda c: c)),
            ("readiness-recommendations", t("rpt_readiness_sec_recommendations", lang=lang),
             self._recommendations(readiness.get("recommendations"))),
            ("readiness-trend", t("rpt_readiness_sec_trend", lang=lang),
             self._trend(mr.get("_trend_deltas", []))),
        ]
        toc = ("<aside class=\"report-toc screen-only\">"
               f"<h3>{_esc(t('rpt_nav_contents', lang=lang))}</h3><ol>"
               + "".join(f'<li><a href="#{sid}">{_esc(title)}</a></li>'
                         for sid, title, _ in sections)
               + "</ol>"
               f"<button class=\"print-btn\" onclick=\"window.print()\">"
               f"{_esc(t('rpt_nav_print_pdf', lang=lang))}</button></aside>")
        body = "".join(
            f'<section id="{sid}" class="card"><h2>{_esc(title)}</h2>{content}</section>'
            for sid, title, content in sections)
        return ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                f"<title>{_esc(t('rpt_readiness_report_title', lang=lang))}</title>{_CSS}</head>"
                f"<body>{cover}<div class='report-shell'>{toc}"
                f"<main class='report-main'>{body}</main></div>{TABLE_JS}</body></html>")

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Readiness_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._render_html())
        return path
