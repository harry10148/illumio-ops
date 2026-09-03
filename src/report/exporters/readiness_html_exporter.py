"""Enforcement Readiness HTML exporter.

Renders into the design/v2 report shell (``report_shell.build_shell_document``);
facade contract: __init__(result, lang, pce_url, org_name) + export(output_dir).

Long-cell policy (CLAUDE.md): cells in _TRUNC_COLS longer than _CELL_MAX chars
are truncated to _CELL_MAX-1 chars + ellipsis; the FULL value is preserved in
the cell's title attribute and in the CSV export. Never silent. The ``title``
half is a screen affordance: a printed PDF shows the ellipsis but not the hover
text, so on paper the CSV export is the recoverable copy. Unchanged by the v2
shell; recorded rather than quietly altered.

The tables are hand-written rather than rendered through ``render_df_table``:
each carries its own column order, its own header lookup and the truncated
cell's full value in ``<td title="...">``, which ``render_df_table``'s
``render_cell`` hook cannot express (it supplies a cell's INNER html only).
What the panel gives — the wide-table print treatment — is added with
``table_renderer.wrap_table_panel`` instead, so these tables get the same wide
verdict as the seven that do go through the renderer.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.exporters._output_paths import (
    discard_reserved,
    reserve_unique_path,
    write_text_atomic,
)
from src.report.exporters.report_shell import (
    ShellCover,
    ShellSection,
    build_shell_document,
)
from src.report.exporters.table_renderer import wrap_table_panel

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
_REC_COL_I18N = {
    "Priority": "rpt_col_priority",
    "App (Env)": "rpt_col_app_env",
    "Issue": "rpt_col_issue",
    "Action": "rpt_col_action",
    "Severity": "rpt_col_severity",
}
_FACTOR_COL_I18N = {
    "Factor": "rpt_col_factor",
    "Weight": "rpt_col_weight",
    "Score": "rpt_col_score",
    "Ratio %": "rpt_col_ratio_pct",
}
_TRUNC_COLS = {"app_display", "current_mode", "recommended_action", "Action"}
_DIR_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label, kpi: dict | None = None) -> str:
    # .kpi / .kpi-strip is the v2 shell's KPI vocabulary; .kpi-card / .kpi-row
    # were report_css.py's and have no rule in SHELL_CSS, so keeping them would
    # leave the numbers as unstyled stacked divs.
    #
    # This report renders its own KPI strip rather than going through
    # _exec_summary, so it has to ask for the tone itself — the shared helper is
    # the single rule for which KPI earns one.
    from src.report.exporters._exec_summary import kpi_tone_attr
    tone = kpi_tone_attr(kpi or {}, str(value))
    return (f'<div class="kpi"{tone}>'
            f'<span class="kpi-label">{_esc(label)}</span>'
            f'<span class="kpi-value">{_esc(value)}</span></div>')


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
        # No `sortable` class: nothing has ever styled or read one. TABLE_JS
        # keys interactive sorting off `report-table--interactive` plus
        # `data-interactive`, both emitted by table_renderer.py, and this table
        # is hand-built. Carrying the word implied an affordance this report has
        # never had (removed in Task 6 with the old shell it came from).
        table_html = ('<div class="report-table-wrap">'
                      '<table class="report-table">'
                      f'<thead><tr>{head}</tr></thead>'
                      f'<tbody>{body}</tbody></table></div>')
        # The panel is what carries the wide-table print treatment in SHELL_CSS
        # (reduced font, tighter padding, the column-width floors); the queue
        # table is eight columns wide.
        return wrap_table_panel(table_html, df, use, self._lang)

    # ── sections ──────────────────────────────────────────────────────
    def _summary(self, readiness, kpis) -> str:
        lang = self._lang
        kpi_row = '<div class="kpi-strip">' + "".join(
            _kpi(k.get("value", ""), k.get("label", k.get("i18n_key", "")), k)
            for k in kpis
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
        detail_html = self._table(recs, detail_cols,
                                  lambda c: t(_REC_COL_I18N.get(c, c), lang=lang))
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
        table_html = ('<div class="report-table-wrap"><table class="report-table">'
                      f'<thead><tr>{head}</tr></thead>'
                      f'<tbody>{body}</tbody></table></div>')
        return wrap_table_panel(table_html, None,
                                ["metric", "current", "previous", "delta"], lang)

    # ── document ──────────────────────────────────────────────────────
    def _render_html(self) -> str:
        lang = self._lang
        mr = self._result.module_results or {}
        readiness = mr.get("readiness", {})
        report_type = t("rpt_readiness_cover_type", lang=lang)
        factor_table = readiness.get("factor_table")
        sections: list[ShellSection] = [
            # readiness-summary becomes the exec chapter: it is already titled
            # rpt_readiness_sec_summary ("Executive Summary"), so the shared
            # "Executive Summary — <type>" heading only adds the qualifier and
            # the old string survives inside the new one. Its id becomes the
            # shared exec-summary so the whole family anchors the same way.
            ShellSection(
                id="exec-summary",
                title=(f'{t("rpt_readiness_sec_summary", lang=lang)} '
                       f'— {report_type}'),
                html=self._summary(readiness, mr.get("kpis", [])),
                kind="exec"),
            ShellSection(
                id="readiness-queue", title=t("rpt_readiness_sec_queue", lang=lang),
                html=self._table(mr.get("queue_df"), _QUEUE_COLS,
                                 lambda c: t(_QUEUE_COL_I18N.get(c, c), lang=lang))),
            ShellSection(
                id="readiness-factors",
                title=t("rpt_readiness_sec_factors", lang=lang),
                html=self._factor_legend()
                + self._table(factor_table,
                              list(getattr(factor_table, "columns", [])),
                              lambda c: t(_FACTOR_COL_I18N.get(c, c), lang=lang))),
            ShellSection(
                id="readiness-recommendations",
                title=t("rpt_readiness_sec_recommendations", lang=lang),
                html=self._recommendations(readiness.get("recommendations"))),
            ShellSection(
                id="readiness-trend", title=t("rpt_readiness_sec_trend", lang=lang),
                html=self._trend(mr.get("_trend_deltas", []))),
        ]

        # Raw strings: build_shell_document escapes every ShellCover scalar. The
        # eyebrow carries the type label because type_label alone only reaches
        # body[data-report-title] — which this report did not have at all before
        # (nor a lang attribute); the shell supplies both.
        meta: dict[str, str] = {}
        if self._pce_url:
            meta[t("rpt_cover_pce", lang=lang)] = self._pce_url
        if self._org_name:
            meta[t("rpt_cover_org", lang=lang)] = self._org_name
        date_range = " – ".join(d for d in (self._result.date_range or ()) if d)
        if date_range:
            meta[t("rpt_cover_date_range", lang=lang)] = date_range
        # The legacy cover suppressed the grade block for a missing or "?"
        # grade; the same guard, or the cover would print an empty chip whose
        # tone says "neutral" as if that were a measured result.
        grade = str(readiness.get("grade") or "")
        cover = ShellCover(
            title=t("rpt_readiness_report_title", lang=lang),
            doc_title=t("rpt_readiness_report_title", lang=lang),
            type_label=report_type,
            eyebrow=report_type,
            grade="" if grade in ("", "?") else grade,
            meta=meta,
        )
        return build_shell_document(lang=lang, cover=cover, sections=sections)

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        # 先把文件建置完成再碰檔案系統：舊寫法是 open(...,'w') 之後才呼叫
        # _render_html()，建置中途拋錯就留下 0-byte 報表（GUI 照樣列出並可下載）。
        # 再以 O_EXCL 搶下唯一檔名（同分鐘併發產出會撞名）＋暫存檔 os.replace。
        body = self._render_html()
        path = reserve_unique_path(
            os.path.join(output_dir, f"Illumio_Readiness_Report_{ts}.html"))
        try:
            write_text_atomic(path, body)
        except BaseException:
            discard_reserved(path)
            raise
        return path
