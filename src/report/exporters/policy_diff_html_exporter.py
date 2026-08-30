"""Policy Diff HTML exporter — renders DRAFT-vs-ACTIVE diff + attribution.

Renders into the design/v2 report shell (``report_shell.build_shell_document``)
like every other HTML report: the shell owns the cover, the table of contents,
the chapter frames and the appendix.

Self-contained (no chart deps): a KPI strip that becomes the executive chapter,
a Ruleset-changes chapter, a Rule-changes chapter and one chapter per changed
object kind, each table row colour-coded by change_type and showing the
attributed operator. Mirrors the facade exporter contract: __init__(results,
lang) + export(output_dir) -> path.

The diff table is hand-written rather than rendered through
``render_df_table``: the row background encodes the change type, the risk cell
carries its own class, and blank attribution renders an em dash whose ``title``
explains why. ``render_df_table``'s ``render_cell`` hook only supplies a cell's
INNER html, so none of those three can be expressed through it. What the panel
gives — the wide-table print treatment — is added with
``table_renderer.wrap_table_panel`` instead, so this table gets the same verdict
as the seven that do go through the renderer.
"""
from __future__ import annotations

import datetime
import html as _html
import os

import pandas as pd

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
from src.report.report_metadata import write_metadata_sidecar

# Ported from report_css.py:470-483, which Task 6 deletes. These are this one
# report type's own components, so they travel in the document's extra_head
# rather than in the shared SHELL_CSS (the same call Task 4 made for policy
# usage's rule cards). Every colour is re-expressed as a shell tone token: the
# old palette variables (--green-10 / --red-10 / --gold-110 / --slate-50) do not
# exist once build_css() is gone, and a declaration referring to an undefined
# variable drops out silently — the row would simply stop being coloured.
_COMPONENT_CSS = """<style>
.report-table tbody tr.pd-added td    { background: var(--tone-ok-bg); }
.report-table tbody tr.pd-removed td  { background: var(--tone-crit-bg); }
.report-table tbody tr.pd-modified td { background: var(--tone-warn-bg); }
/* Hover keeps report_css.py:473-475's literals: they are self-contained hex
   values that never depended on a build_css() variable, so porting them is a
   copy, and inventing a replacement would change a shipped colour for no
   reason. Screen-only by nature — nothing hovers on paper. */
.report-table tbody tr.pd-added:hover td    { background: #cdf3df; }
.report-table tbody tr.pd-removed:hover td  { background: #fbd5d5; }
.report-table tbody tr.pd-modified:hover td { background: #FBF1C7; }
.pd-risk-critical, .pd-risk-high { color: var(--tone-crit-fg); font-weight: 700; }
.pd-risk-medium { color: var(--tone-warn-fg); font-weight: 600; }
.pd-risk-low    { color: var(--tone-ok-fg); font-weight: 600; }
.pd-risk-info   { color: var(--text-3); font-weight: 600; }
</style>"""

_ROW_CLASS = {"added": "pd-added", "removed": "pd-removed", "modified": "pd-modified"}


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _kpi(value, label) -> str:
    # .kpi / .kpi-strip is the v2 shell's KPI vocabulary; .kpi-card / .kpi-grid
    # were report_css.py's and have no rule in SHELL_CSS, so keeping them would
    # leave the numbers as unstyled stacked divs.
    return (
        '<div class="kpi">'
        f'<span class="kpi-label">{_esc(label)}</span>'
        f'<span class="kpi-value">{_esc(value)}</span></div>'
    )


class PolicyDiffHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _section(self, id_: str, title: str, content: str) -> ShellSection:
        """One chapter for the v2 shell.

        The heading is printed by ``build_shell_document`` now, so this returns
        the body plus the metadata the shell needs. No ``marks``: this report
        has no findings list, and the risk column is table data, which B10/C6
        keep out of the mark tally.
        """
        return ShellSection(id=id_, title=title, html=content)

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
        "name": "rpt_policy_diff_col_name",
        "object_id": "rpt_policy_diff_col_object_id",
    }

    def _header(self, col: str) -> str:
        key = self._COL_I18N.get(col)
        return _esc(t(key, lang=self._lang)) if key else _esc(col)

    _RISK_RANK = {"HIGH": 0, "MEDIUM": 1}

    def _table(self, df: pd.DataFrame, id_col: str, name_col: str = "ruleset_name") -> str:
        if df is None or df.empty:
            return f'<p class="note">{_esc(t("rpt_policy_diff_no_changes", lang=self._lang))}</p>'
        if "risk" in df.columns:
            df = df.copy()
            df["_rank"] = df["risk"].map(self._RISK_RANK).fillna(9)
            df = df.sort_values("_rank", kind="stable").drop(columns="_rank")
        cols = ["risk", "change_type", name_col, id_col, "field",
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
        table_html = (
            '<div class="report-table-wrap"><table class="report-table"><thead><tr>'
            f"{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
        )
        # The panel is what carries the wide-table print treatment in SHELL_CSS
        # (reduced font, tighter padding, the column-width floors). Without it a
        # nine-column diff prints at full body size and the release rules are all
        # that stand between it and the page edge.
        return wrap_table_panel(table_html, df, cols, self._lang)

    def _kpi_row(self) -> str:
        s = self._r.get("summary", {})
        _rs = t("rpt_pd_unit_rs", lang=self._lang)
        _rule = t("rpt_pd_unit_rule", lang=self._lang)
        return '<div class="kpi-strip">' + (
            _kpi(s.get("rulesets_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " " + _rs)
            + _kpi(s.get("rulesets_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " " + _rs)
            + _kpi(s.get("rulesets_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " " + _rs)
            + _kpi(s.get("rules_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " " + _rule)
            + _kpi(s.get("rules_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " " + _rule)
            + _kpi(s.get("rules_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " " + _rule)
        ) + "</div>"

    def _render_html(self) -> str:
        lang = self._lang
        title = t("rpt_policy_diff_report_title", lang=lang)
        report_type = t("rpt_cover_type_diff", lang=lang)

        sections: list[ShellSection] = [
            # The KPI row had no heading of its own before (a bare
            # <section class="card"> holding a .kpi-grid), so naming it here
            # takes nothing away, and it is the heading the other nine types
            # print above their own headline numbers.
            ShellSection(
                id="exec-summary",
                title=(f'{t("rpt_exec_summary_label", lang=lang)} '
                       f'— {report_type}'),
                html=self._kpi_row(),
                kind="exec"),
            self._section(
                "ruleset-changes",
                t("rpt_policy_diff_ruleset_changes", lang=lang),
                self._table(self._r.get("ruleset_changes"), "ruleset_id"),
            ),
            self._section(
                "rule-changes",
                t("rpt_policy_diff_rule_changes", lang=lang),
                self._table(self._r.get("rule_changes"), "rule_id"),
            ),
        ]
        for section_id, title_key, df_key in (
            ("ip-list-changes", "rpt_policy_diff_ip_list_changes", "ip_list_changes"),
            ("service-changes", "rpt_policy_diff_service_changes", "service_changes"),
            ("label-group-changes", "rpt_policy_diff_label_group_changes",
             "label_group_changes"),
        ):
            sections.append(self._section(
                section_id, t(title_key, lang=lang),
                self._table(self._r.get(df_key), "object_id", name_col="name")))

        # Raw strings: build_shell_document escapes every ShellCover scalar
        # itself, so escaping here would double-escape. The eyebrow carries the
        # type label because ``type_label`` alone only reaches an attribute
        # (body[data-report-title]) and would leave the text layer.
        cover = ShellCover(
            title=title,
            doc_title=title,
            type_label=report_type,
            eyebrow=report_type,
        )
        return build_shell_document(
            lang=lang,
            cover=cover,
            sections=sections,
            # The attribution caveat used to sit as a <p class="note"> after the
            # last section. It qualifies the whole document rather than any one
            # chapter, so it goes to the appendix colophon instead of into a
            # chapter that would appear to own it.
            appendix_html=(
                '<p class="note">'
                + _esc(t("rpt_policy_diff_attribution_note", lang=lang))
                + "</p>"),
            extra_head=_COMPONENT_CSS,
        )

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        html = self._render_html()
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        # 以 O_EXCL 搶下唯一檔名（同分鐘併發產出會撞名）＋暫存檔 os.replace，
        # 避免兩張同型報表互相截斷、或半寫檔被 GUI 列出。
        path = reserve_unique_path(
            os.path.join(output_dir, f"Illumio_Policy_Diff_Report_{ts}.html"))
        try:
            write_text_atomic(path, html)
        except BaseException:
            discard_reserved(path)
            raise
        self._write_report_metadata(path)
        return path

    def _write_report_metadata(self, report_path: str) -> None:
        """Sidecar for /api/reports (report_type / summary). Merges — see
        write_metadata_sidecar; the scheduler owns schedule_id in the same file."""
        s = self._r.get("summary") or {}
        # Language-neutral, like the audit/traffic sidecars ("audit events N").
        summary = (
            f"rulesets +{s.get('rulesets_added', 0)} "
            f"-{s.get('rulesets_removed', 0)} ~{s.get('rulesets_modified', 0)} | "
            f"rules +{s.get('rules_added', 0)} "
            f"-{s.get('rules_removed', 0)} ~{s.get('rules_modified', 0)}"
        )
        write_metadata_sidecar(report_path, {
            "report_type": "policy_diff",
            "file_format": "html",
            "generated_at": datetime.datetime.now().isoformat(),
            "record_count": int(s.get("total_changes", 0) or 0),
            "execution_stats": dict(s),
            "summary": summary,
        })
