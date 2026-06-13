"""Policy Diff HTML exporter — renders DRAFT-vs-ACTIVE diff + attribution.

Uses the SHARED report styling (report_css.build_css + cover_page) so it matches
the other standalone reports (audit/ven/policy_usage/app_summary): shared fonts,
cover page, and the .report-shell / .report-main / .card layout.

Self-contained (no chart deps): KPI cards + a Ruleset-changes table + a
Rule-changes table, each row colour-coded by change_type and showing the
attributed operator. Mirrors the facade exporter contract: __init__(results,
lang) + export(output_dir) -> path.
"""
from __future__ import annotations

import datetime
import html as _html
import os

import pandas as pd

from src.i18n import t
from src.report.exporters.cover_page import build_cover_page as _build_cover_page
from src.report.exporters.report_css import TABLE_JS, build_css

_CSS = build_css("policy_diff")

_ROW_CLASS = {"added": "pd-added", "removed": "pd-removed", "modified": "pd-modified"}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    return (
        '<div class="kpi-card">'
        f'<div class="kpi-label">{_esc(label)}</div>'
        f'<div class="kpi-value">{_esc(value)}</div></div>'
    )


class PolicyDiffHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _section(self, id_: str, title: str, content: str) -> str:
        return f'<section id="{id_}" class="card"><h2>{title}</h2>{content}</section>'

    # DataFrame column name -> i18n key for the localized <th> header.
    _COL_I18N = {
        "risk": "rpt_policy_diff_col_risk",
        "change_type": "rpt_policy_diff_col_change_type",
        "ruleset_name": "rpt_policy_diff_col_ruleset",
        "ruleset_id": "rpt_policy_diff_col_ruleset_id",
        "rule_id": "rpt_policy_diff_col_rule_id",
        "field": "rpt_policy_diff_col_field",
        "draft_value": "rpt_policy_diff_col_draft",
        "active_value": "rpt_policy_diff_col_active",
        "last_actor": "rpt_policy_diff_col_actor",
        "last_changed": "rpt_policy_diff_col_changed",
    }

    def _header(self, col: str) -> str:
        key = self._COL_I18N.get(col)
        return _esc(t(key, lang=self._lang)) if key else _esc(col)

    _RISK_RANK = {"HIGH": 0, "MEDIUM": 1}

    def _table(self, df: pd.DataFrame, id_col: str) -> str:
        if df is None or df.empty:
            return f'<p class="note">{_esc(t("rpt_policy_diff_no_changes", lang=self._lang))}</p>'
        if "risk" in df.columns:
            df = df.copy()
            df["_rank"] = df["risk"].map(self._RISK_RANK).fillna(9)
            df = df.sort_values("_rank", kind="stable").drop(columns="_rank")
        cols = ["risk", "change_type", "ruleset_name", id_col, "field",
                "draft_value", "active_value", "last_actor", "last_changed"]
        cols = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{self._header(c)}</th>" for c in cols)
        body = []
        for _, row in df.iterrows():
            cls = _ROW_CLASS.get(str(row.get("change_type", "")), "")
            cells = []
            for c in cols:
                v = row.get(c, "")
                if c == "risk" and v:
                    cells.append(f'<td class="pd-risk-{str(v).lower()}">{_esc(v)}</td>')
                elif c in ("last_actor", "last_changed") and str(v).strip() in ("", "nan"):
                    cells.append(f'<td title="{_esc(t("rpt_policy_diff_attribution_note", lang=self._lang))}">—</td>')
                else:
                    cells.append(f"<td>{_esc(v)}</td>")
            body.append(f'<tr class="{cls}">{"".join(cells)}</tr>')
        return (
            '<div class="report-table-wrap"><table class="report-table"><thead><tr>'
            f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )

    def _kpi_row(self) -> str:
        s = self._r.get("summary", {})
        return (
            _kpi(s.get("rulesets_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " RS")
            + _kpi(s.get("rulesets_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " RS")
            + _kpi(s.get("rulesets_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " RS")
            + _kpi(s.get("rules_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " Rule")
            + _kpi(s.get("rules_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " Rule")
            + _kpi(s.get("rules_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " Rule")
        )

    def _render_html(self) -> str:
        lang = self._lang
        title = t("rpt_policy_diff_report_title", lang=lang)
        # Pass raw title — build_cover_page escapes its args (avoid double-escape).
        cover_html = _build_cover_page(
            title=title,
            report_type=title,
            lang=lang,
        )

        sections = (
            f'<section class="card"><div class="kpi-grid">{self._kpi_row()}</div></section>'
            + self._section(
                "ruleset-changes",
                _esc(t("rpt_policy_diff_ruleset_changes", lang=lang)),
                self._table(self._r.get("ruleset_changes"), "ruleset_id"),
            )
            + self._section(
                "rule-changes",
                _esc(t("rpt_policy_diff_rule_changes", lang=lang)),
                self._table(self._r.get("rule_changes"), "rule_id"),
            )
            + f'<p class="note">{_esc(t("rpt_policy_diff_attribution_note", lang=lang))}</p>'
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
        path = os.path.join(output_dir, f"Illumio_Policy_Diff_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return path
