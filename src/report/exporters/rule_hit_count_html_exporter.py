"""Rule Hit Count HTML exporter — VEN-measured native data, one row per rule.

Renders into the design/v2 report shell (``report_shell.build_shell_document``);
facade exporter contract: __init__(result, lang) + export(output_dir) -> path.

Long-cell policy (CLAUDE.md 報表規則): cells in _TRUNC_COLS longer than
_CELL_MAX chars are truncated to _CELL_MAX-1 chars + an ellipsis; the FULL
value is preserved in the cell's title attribute (hover) and in the CSV
export. Truncation is explicit and recoverable, never silent. Note the limit
of the ``title`` half on paper: a printed PDF shows the ellipsis but not the
hover text, so the CSV export is the recoverable copy there. That is unchanged
by the v2 shell and is recorded here rather than quietly altered.

The rule table is hand-written rather than rendered through
``render_df_table``: it renders ``enabled`` as a localized word, formats the
count columns with thousands separators, and carries the truncated cell's full
value in the ``<td title="...">`` attribute. ``render_df_table``'s
``render_cell`` hook only supplies a cell's INNER html, so the title attribute
cannot be expressed through it, and its timestamp handling would insert a
``<wbr/>`` into ``last_hit_at``. What the panel gives — the wide-table print
treatment — is added with ``table_renderer.wrap_table_panel`` instead, so this
table gets the same wide verdict as the seven that do go through the renderer.
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
from src.report.rule_hit_count_generator import CLEANUP_DAYS_THRESHOLD

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


# 計數欄千分位、天數欄整數（1.0/28.0 浮點與無分位是 2026-07-23 視覺殘項）
_THOUSANDS_COLS = {"hit_count"}
_INT_COLS = {"days_since_last_hit"}


def _fmt_cell_value(col: str, value) -> str:
    text = "" if value is None else str(value)
    if col in _THOUSANDS_COLS or col in _INT_COLS:
        if text.strip() == "":
            return text
        try:
            num = float(text)
        except ValueError:
            return text
        if num.is_integer():
            return f"{int(num):,}" if col in _THOUSANDS_COLS else str(int(num))
        return f"{num:,.1f}" if col in _THOUSANDS_COLS else f"{num:.1f}"
    return text


def _kpi(value, label) -> str:
    # .kpi / .kpi-strip is the v2 shell's KPI vocabulary; .kpi-card / .kpi-row
    # were report_css.py's and have no rule in SHELL_CSS, so keeping them would
    # leave the numbers as unstyled stacked divs.
    return (
        '<div class="kpi">'
        f'<span class="kpi-label">{_esc(label)}</span>'
        f'<span class="kpi-value">{_esc(value)}</span></div>'
    )


class RuleHitCountHtmlExporter:
    def __init__(self, result, lang: str = "en", pce_url: str = "", org_name: str = ""):
        self._result = result
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    def _fmt_enabled(self, value) -> str:
        s = str(value).strip().lower()
        if s in ("true", "1"):
            return t("rpt_rhc_enabled_true", lang=self._lang)
        if s in ("false", "0"):
            return t("rpt_rhc_enabled_false", lang=self._lang)
        return "—" if s in ("", "none", "nan") else str(value)

    def _cell(self, col: str, value) -> str:
        if col == "enabled":
            return f"<td>{_esc(self._fmt_enabled(value))}</td>"
        text = _fmt_cell_value(col, value)
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
        # No `sortable` class: nothing has ever styled or read one. TABLE_JS
        # keys interactive sorting off `report-table--interactive` plus
        # `data-interactive`, both emitted by table_renderer.py, and this table
        # is hand-built. Carrying the word implied an affordance this report has
        # never had (removed in Task 6 with the old shell it came from).
        table_html = (
            '<div class="report-table-wrap"><table class="report-table">'
            f'<thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
        )
        # The panel carries the wide-table treatment in SHELL_CSS (reduced print
        # font, tighter padding, the four column-width floors). This is the
        # widest table in the product — eleven columns from _COLS, more in a real
        # PCE — so it is the one that most needs it.
        return wrap_table_panel(table_html, df, cols, self._lang)

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
        # The <section class="card"> wrapper goes with the old shell; the shell
        # supplies the chapter frame now.
        return f'<ul class="note">{items}</ul>'

    def _render_html(self) -> str:
        mr = self._result.module_results or {}
        kpis = mr.get("kpis", {})
        lang = self._lang
        report_type = t("rpt_rhc_cover_type", lang=lang)
        kpi_row = '<div class="kpi-strip">' + "".join([
            _kpi(kpis.get("total_rules", 0), t("rpt_rhc_kpi_total", lang=lang)),
            _kpi(kpis.get("hit_rules", 0), t("rpt_rhc_kpi_hit", lang=lang)),
            _kpi(kpis.get("unused_rules", 0), t("rpt_rhc_kpi_unused", lang=lang)),
            _kpi(f'{kpis.get("hit_rate_pct", 0)}%', t("rpt_rhc_kpi_hit_rate", lang=lang)),
            _kpi(f'{int(kpis.get("total_hits", 0) or 0):,}', t("rpt_rhc_kpi_total_hits", lang=lang)),
        ]) + "</div>"
        chapters = [
            ("rhc-hit", t("rpt_rhc_sec_hit", lang=lang), mr.get("hit_df")),
            ("rhc-unused", t("rpt_rhc_sec_unused", lang=lang), mr.get("unused_df")),
            ("rhc-cleanup",
             t("rpt_rhc_sec_cleanup", days=CLEANUP_DAYS_THRESHOLD, lang=lang),
             mr.get("cleanup_df")),
        ]
        sections: list[ShellSection] = [
            # The KPI row and the notes list both had no heading of their own
            # (a bare .kpi-row and a bare <section class="card">), so naming the
            # pair here takes nothing away. The notes stay ABOVE the tables, in
            # their original document order: they say what "hit count" measures,
            # how far back retention goes and when enrichment failed, and moving
            # a caveat away from the data it qualifies is a downgrade. The brief
            # said "detail chapter"; making them one would have meant minting a
            # heading for a block that never had one.
            ShellSection(
                id="exec-summary",
                title=(f'{t("rpt_exec_summary_label", lang=lang)} '
                       f'— {report_type}'),
                html=kpi_row + self._notes(),
                kind="exec"),
        ]
        sections += [ShellSection(id=sid, title=title, html=self._table(df))
                     for sid, title, df in chapters]

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
        cover = ShellCover(
            title=t("rpt_rhc_report_title", lang=lang),
            doc_title=t("rpt_rhc_report_title", lang=lang),
            type_label=report_type,
            eyebrow=report_type,
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
            os.path.join(output_dir, f"Illumio_Rule_Hit_Count_Report_{ts}.html"))
        try:
            write_text_atomic(path, body)
        except BaseException:
            discard_reserved(path)
            raise
        return path
