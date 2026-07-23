"""Rule Hit Count HTML exporter — VEN-measured native data, one row per rule.

Shared report styling (report_css.build_css + cover_page); facade exporter
contract: __init__(result, lang) + export(output_dir) -> path.

Long-cell policy (CLAUDE.md 報表規則): cells in _TRUNC_COLS longer than
_CELL_MAX chars are truncated to _CELL_MAX-1 chars + an ellipsis; the FULL
value is preserved in the cell's title attribute (hover) and in the CSV
export. Truncation is explicit and recoverable, never silent.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.report_css import TABLE_JS, build_css
from src.report.rule_hit_count_generator import CLEANUP_DAYS_THRESHOLD

_CSS = build_css("rule_hit_count")   # unknown type → base styling only

_CELL_MAX = 160
_TRUNC_COLS = {"consumers", "providers", "services", "description"}

# 命中量測欄前移：報表主指標（hit_count/days_since/last_hit）曾排在長文字
# 欄之後，1440px 下被推出可視範圍（2026-07-23 視覺實檢）
_COLS = ["ruleset", "rule_no", "hit_count", "days_since_last_hit", "last_hit_at",
         "rule_type", "description", "consumers", "providers", "services",
         "enabled"]

_COL_I18N = {
    "ruleset": "rpt_rhc_col_ruleset",
    "rule_no": "rpt_rhc_col_rule_no",
    "rule_id": "rpt_rhc_col_rule_id",
    "rule_type": "rpt_rhc_col_rule_type",
    "description": "rpt_rhc_col_description",
    "consumers": "rpt_rhc_col_consumers",
    "providers": "rpt_rhc_col_providers",
    "services": "rpt_rhc_col_services",
    "enabled": "rpt_rhc_col_enabled",
    "hit_count": "rpt_rhc_col_hit_count",
    "days_since_last_hit": "rpt_rhc_col_days_since",
    "last_hit_at": "rpt_rhc_col_last_hit_at",
}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{_esc(label)}</div>'
        f'<div class="kpi-value">{_esc(value)}</div></div>'
    )


class RuleHitCountHtmlExporter:
    def __init__(self, result, lang: str = "en", pce_url: str = "", org_name: str = ""):
        self._result = result
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    def _cell(self, col: str, value) -> str:
        text = "" if value is None else str(value)
        if col in _TRUNC_COLS and len(text) > _CELL_MAX:
            shown = text[:_CELL_MAX - 1] + "…"
            return f'<td title="{_esc(text)}">{_esc(shown)}</td>'
        return f"<td>{_esc(text)}</td>"

    def _table(self, df) -> str:
        if df is None or df.empty:
            return f'<p class="note">{_esc(t("rpt_rhc_no_rows", lang=self._lang))}</p>'
        cols = [c for c in _COLS if c in df.columns]
        head = "".join(
            f"<th>{_esc(t(_COL_I18N.get(c, c), lang=self._lang))}</th>" for c in cols)
        body = []
        for _, row in df.iterrows():
            cells = "".join(self._cell(c, row.get(c, "")) for c in cols)
            body.append(f"<tr>{cells}</tr>")
        return (
            '<div class="report-table-wrap"><table class="report-table sortable">'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
        )

    def _notes(self) -> str:
        lang = self._lang
        notes = [
            t("rpt_rhc_note_semantics", lang=lang),
            t("rpt_rhc_note_optimization", lang=lang),
            t("rpt_rhc_note_retention", lang=lang),
        ]
        if self._result.source == "csv":
            notes.append(t("rpt_rhc_note_csv_window", lang=lang))
        if (self._result.module_results or {}).get("enrich_failed"):
            notes.append(t("rpt_rhc_note_enrich_failed", lang=lang))
        _unparsed = (self._result.module_results or {}).get("unparsed_rows") or 0
        if _unparsed:
            notes.append(t("rpt_rhc_note_unparsed", lang=lang, n=_unparsed))
        items = "".join(f"<li>{_esc(n)}</li>" for n in notes)
        return f'<section class="card"><ul class="note">{items}</ul></section>'

    def _render_html(self) -> str:
        mr = self._result.module_results or {}
        kpis = mr.get("kpis", {})
        lang = self._lang
        cover = _build_cover_page(
            t("rpt_rhc_report_title", lang=lang),
            t("rpt_rhc_cover_type", lang=lang),
            date_range=self._result.date_range,
            pce_url=self._pce_url, org_name=self._org_name, lang=lang)
        kpi_row = '<div class="kpi-row">' + "".join([
            _kpi(kpis.get("total_rules", 0), t("rpt_rhc_kpi_total", lang=lang)),
            _kpi(kpis.get("hit_rules", 0), t("rpt_rhc_kpi_hit", lang=lang)),
            _kpi(kpis.get("unused_rules", 0), t("rpt_rhc_kpi_unused", lang=lang)),
            _kpi(f'{kpis.get("hit_rate_pct", 0)}%', t("rpt_rhc_kpi_hit_rate", lang=lang)),
            _kpi(kpis.get("total_hits", 0), t("rpt_rhc_kpi_total_hits", lang=lang)),
        ]) + "</div>"
        sections = [
            ("rhc-hit", t("rpt_rhc_sec_hit", lang=lang), mr.get("hit_df")),
            ("rhc-unused", t("rpt_rhc_sec_unused", lang=lang), mr.get("unused_df")),
            ("rhc-cleanup",
             t("rpt_rhc_sec_cleanup", days=CLEANUP_DAYS_THRESHOLD, lang=lang),
             mr.get("cleanup_df")),
        ]
        body_sections = "".join(
            f'<section id="{sid}" class="card"><h2>{_esc(title)}</h2>{self._table(df)}</section>'
            for sid, title, df in sections)
        nav_html = (
            '<aside class="report-toc screen-only">'
            f'<button class="print-btn" onclick="window.print()">{t("rpt_nav_print_pdf", lang=lang)}</button>'
            '</aside>'
        )
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{_esc(t('rpt_rhc_report_title', lang=lang))}</title>{_CSS}</head>"
            f"<body>{cover}<div class='report-shell'>{nav_html}<main class='report-main'>"
            f"{kpi_row}{self._notes()}{body_sections}</main></div>{TABLE_JS}</body></html>"
        )

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Rule_Hit_Count_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._render_html())
        return path
