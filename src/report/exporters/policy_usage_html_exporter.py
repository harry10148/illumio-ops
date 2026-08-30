"""
Self-contained HTML report for the Policy Usage Report.
"""
from __future__ import annotations

import datetime
from loguru import logger
import os

import pandas as pd

from ._output_paths import discard_reserved, reserve_unique_path, write_text_atomic
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS
from .report_i18n import RISK_TYPE_VALUE_I18N
from .report_shell import ShellCover, ShellSection, build_shell_document
from .table_renderer import render_df_table
from .chart_renderer import render_matplotlib_svg
from .code_highlighter import get_highlight_css
from .html_exporter import render_section_guidance
from src.i18n import t
from src.report.analysis.policy_usage.pu_mod01_overview import build_summary_df
from src.report.section_guidance import visible_in
from src.humanize_ext import human_number
from src.report.exporters._exec_summary import render_exec_summary_html
# _body_tone is the v2 shell's tone helper, kept next to the traffic exporter
# that first needed it.
from src.report.exporters.html_exporter import _body_tone

_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'

# This report's own components, ported from report_css.py (the attention box at
# 242-246, the caveat box at 252 and POLICY_USAGE_CSS's .pu-* card layout) with
# the old build_css tokens remapped onto the v2 shell's. They are NOT in
# SHELL_CSS: they belong to this one report type, and the shared shell has to
# stay comparable against design/v2/reports/shell.css. Without them the rule
# cards collapse into unstyled stacked divs — a layout loss conservation cannot
# see, because every character of text survives.
# Token remap: --border -> --line, --slate -> --text-1, --slate-50 -> --text-3,
# --cyan-120 -> --text-1, --green/--green-10 -> --tone-ok-fg/bg,
# --red/--red-10 -> --tone-crit-fg/bg, --gold-110 -> --tone-warn-fg,
# --tan/--tan-120 -> --surface-2/--line, --slate-10 -> --tone-neutral-bg.
_COMPONENT_CSS = """<style>
.attention-box { background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--radius-m); padding: var(--space-6) var(--space-6); margin: var(--space-5) 0 var(--space-6); }
.attention-box h4 { margin: 0 0 var(--space-5); color: var(--text-1); }
.attention-row { display: flex; justify-content: space-between; align-items: center; gap: var(--space-5); padding: var(--space-3) 0; border-bottom: 1px solid var(--line-soft); font-size: var(--fs-body); }
.attention-row:last-child { border-bottom: none; }
.attention-row > span:first-child { color: var(--text-1); font-weight: 500; }
.caveat-box { background: var(--tone-warn-bg); border-left: 3px solid var(--tone-warn-border); padding: var(--space-5) var(--space-6); border-radius: var(--radius-s); margin: var(--space-5) 0; font-size: var(--fs-body); line-height: var(--lead); }

.pu-cards { display: flex; flex-direction: column; gap: var(--space-4); margin-top: var(--space-5); }
.pu-card { display: grid; grid-template-columns: minmax(180px,22%) 1fr minmax(140px,18%); border: 1px solid var(--line); border-radius: var(--radius-m); overflow: hidden; background: var(--surface-1); font-size: var(--fs-body); }
.pu-card:nth-child(even) { background: var(--surface-2); }
.pu-col { padding: var(--space-5) var(--space-6); border-right: 1px solid var(--line); }
.pu-col:last-child { border-right: none; }
.pu-ruleset { font-weight: 700; color: var(--text-1); line-height: 1.35; overflow-wrap: anywhere; }
.pu-meta { color: var(--text-3); font-size: var(--fs-mini); margin-top: var(--space-1); }
.pu-badges { margin-top: var(--space-3); display: flex; flex-wrap: wrap; gap: var(--space-2); }
.pu-badge { display: inline-block; padding: 1px var(--space-3); border-radius: 10px; font-size: var(--fs-mini); font-weight: 600; }
.pu-badge-allow { background: var(--tone-ok-bg); color: var(--tone-ok-fg); }
.pu-badge-deny { background: var(--tone-crit-bg); color: var(--tone-crit-fg); }
.pu-badge-enabled { background: var(--tone-info-bg); color: var(--tone-info-fg); }
.pu-badge-disabled { background: var(--tone-neutral-bg); color: var(--tone-neutral-fg); }
.pu-flow-block { display: flex; flex-direction: column; gap: var(--space-3); }
.pu-flow-row { display: flex; align-items: flex-start; gap: var(--space-3); line-height: 1.4; }
.pu-flow-label { color: var(--text-3); font-size: var(--fs-mini); min-width: 50px; flex-shrink: 0; padding-top: 1px; }
.pu-flow-val { color: var(--text-1); overflow-wrap: anywhere; flex: 1; }
.pu-services { margin-top: var(--space-3); padding-top: var(--space-3); border-top: 1px dashed var(--line); }
.pu-desc { margin-top: var(--space-3); color: var(--text-3); font-size: var(--fs-mini); font-style: italic; }
.pu-stat-block { display: flex; flex-direction: column; gap: var(--space-2); }
.pu-stat-label { color: var(--text-3); font-size: var(--fs-mini); }
.pu-stat-val { font-weight: 700; color: var(--text-1); }
.pu-stat-ports { margin-top: var(--space-2); color: var(--text-3); font-size: var(--fs-mini); overflow-wrap: anywhere; }
.pu-hit-count { font-family: var(--font-mono); font-size: var(--fs-num); font-weight: 700; color: var(--text-1); }
.pu-unused-label { font-weight: 700; color: var(--tone-warn-fg); }
@media (max-width: 700px) {
  .pu-card { grid-template-columns: 1fr; }
  .pu-col { border-right: none; border-bottom: 1px solid var(--line); }
  .pu-col:last-child { border-bottom: none; }
}
</style>"""

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


def _df_to_html(
    df,
    no_data_key: str = "rpt_no_data",
    lang: str = "en",
    value_i18n_maps: dict[str, dict[str, str]] | None = None,
) -> str:
    _s = lambda k: STRINGS[k].get(lang) or STRINGS[k]["en"]

    def _render_cell(col, val, _row):
        val_str = str(val) if val is not None else ""
        if str(col).strip().lower() == "enabled":
            if val_str.lower() in ("true", "1", "yes"):
                return f'<span class="badge badge-hit" data-tone="ok">{_s("rpt_yes")}</span>'
            return f'<span class="badge badge-unused" data-tone="crit">{_s("rpt_no")}</span>'
        return _e(val_str)

    return render_df_table(
        df,
        col_i18n=_COL_I18N,
        no_data_key=no_data_key,
        render_cell=_render_cell,
        value_i18n_maps=value_i18n_maps,
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
        pce_url: str = "",
        org_name: str = "",
    ):
        self._r = results
        self._df = df
        self._date_range = date_range
        self._lookback_days = lookback_days
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_policy_usage_report_{ts}.html"
        # 先把文件建置完成再碰檔案系統：舊寫法是 open(...,'w') 之後才呼叫
        # _build()，建置中途拋錯就留下 0-byte 報表（GUI 照樣列出並可下載）。
        # 再以 O_EXCL 搶下唯一檔名（同分鐘併發產出會撞名）＋暫存檔 os.replace。
        body = self._build()
        filepath = reserve_unique_path(os.path.join(output_dir, filename))
        try:
            write_text_atomic(filepath, body)
        except BaseException:
            discard_reserved(filepath)
            raise
        logger.info("[PolicyUsageHtmlExporter] Saved: {}", filepath)
        return filepath

    def _build(self, profile: str = "", detail_level: str = "") -> str:
        profile = profile or self._profile
        detail_level = _REPORT_DETAIL_LEVEL
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s

        mod00 = self._r.get("mod00", {})
        today_str = str(datetime.date.today())

        # The v2 shell builds the table of contents from the section list, so
        # the hard-coded aside.report-toc is gone. Chapter titles come from the
        # headings (rpt_pu_sec_*), not the sidebar abbreviations
        # (rpt_pu_nav_*): "Hit Rules" would drop the heading's "Detail".
        _exec_title = f'{t("rpt_exec_summary_label", lang=self._lang)} — ' \
                      f'{t("gui_btn_pu_report", lang=self._lang)}'
        _exec_body = (
            render_exec_summary_html(self._reconciled_mod00(mod00),
                                     report_name=t('gui_btn_pu_report', lang=self._lang),
                                     lang=self._lang, include_heading=False)
            + render_section_guidance("pu_mod00_executive",
                                      profile="security_risk",
                                      detail_level="full",
                                      lang=self._lang)
        )
        # The hero's title block becomes the shell cover; the pills, the query
        # execution box and the attention box open the first chapter in the
        # order they had inside the hero card.
        _summary_body = (
            self._summary_pills(mod00)
            + self._execution_html(mod00)
            + self._attention_html(mod00.get("attention_items", []))
        )

        sections: list[ShellSection] = []
        if _exec_body:
            sections.append(ShellSection(id="exec-summary", title=_exec_title,
                                         html=_exec_body, kind="exec"))
        # Not rpt_pu_nav_summary ("Executive Summary") — the table of contents
        # would then list two chapters under the same name.
        sections.append(self._section("summary", "rpt_shell_sec_key_metrics", _summary_body))
        sections.append(self._section("overview", "rpt_pu_sec_overview", self._mod01_html()))
        sections.append(self._section("hit-rules", "rpt_pu_sec_hit", self._mod02_html()))
        if visible_in('pu_mod03_unused_detail', profile, detail_level):
            sections.append(self._section("unused-rules", "rpt_pu_sec_unused",
                                          self._mod03_html()))
        if visible_in('pu_mod04_deny_effectiveness', profile, detail_level):
            sections.append(self._section("deny-rules", "rpt_pu_sec_deny",
                                          self._mod04_html()))
        sections.append(self._section("draft-pd", "rpt_pu_sec_draft_pd", self._mod05_html()))

        _report_type = _s("rpt_cover_type_policy")
        _meta: dict[str, str] = {}
        if self._pce_url:
            _meta[_s("rpt_cover_pce")] = self._pce_url
        if self._org_name:
            _meta[_s("rpt_cover_org")] = self._org_name
        _cover_range = " – ".join(d for d in self._date_range if d)
        if _cover_range:
            _meta[_s("rpt_cover_date_range")] = _cover_range
        if mod00.get("generated_at"):
            _meta[_s("rpt_cover_generated")] = str(mod00["generated_at"])

        # rpt_kicker_policy and rpt_cover_type_policy are the same string
        # ("Policy Usage Report"), so printing both would stack one line on top
        # of an identical one (T3/F6, different slot).
        _kicker = _s("rpt_kicker_policy")
        cover = ShellCover(
            title=_s("rpt_pu_title"),
            doc_title=t('rpt_page_title_policy_usage', lang=self._lang),
            type_label=_report_type,
            eyebrow=_report_type,
            kicker='' if _kicker == _report_type else _kicker,
            meta=_meta,
        )
        return build_shell_document(
            lang=self._lang,
            cover=cover,
            sections=sections,
            appendix_html=f'{_s("rpt_pu_footer")} &middot; {today_str}',
            extra_head=_HIGHLIGHT_CSS + _COMPONENT_CSS,
        )

    def _section(self, id_: str, i18n_key: str, content: str) -> ShellSection:
        """One chapter for the v2 shell.

        The heading is printed by ``build_shell_document`` now, so this returns
        the body plus the metadata the shell needs. The tone is read from the
        chapter's own rendered content; policy usage has no findings list, so no
        chapter carries marks and the cover stays neutral (G1).
        """
        return ShellSection(id=id_, title=self._s(i18n_key), html=content,
                            tone=_body_tone(content))

    def _unused_split(self) -> tuple[int, int]:
        """Return (confirmed_unused, indeterminate) for this run.

        查詢失敗／未完成的規則不是「未使用」。mod01 若是在沒有 execution_stats 的
        情況下算出來的（舊呼叫形狀），這些規則還混在 unused_count 裡；此時改用
        mod03 的分流數字，讓整份報表只有一種未使用口徑。
        """
        mod01 = self._r.get("mod01", {}) or {}
        unused = int(mod01.get("unused_count", 0) or 0)
        indeterminate = int(mod01.get("indeterminate_count") or 0)
        if not indeterminate:
            fallback = int((self._r.get("mod03", {}) or {}).get("indeterminate_count") or 0)
            if fallback:
                indeterminate = fallback
                unused = max(unused - fallback, 0)
        return unused, indeterminate

    def _reconciled_mod00(self, mod00: dict) -> dict:
        """mod00 的 Unused Rules KPI 若還含未判定規則，改成已確認未使用的數字。

        同一頁不可出現兩個「未使用」數字：執行摘要的 KPI 與 overview 區塊必須一致。
        """
        unused, indeterminate = self._unused_split()
        if not indeterminate or not mod00:
            return mod00
        kpis = mod00.get("kpis") or []
        patched = [
            dict(k, value=str(unused))
            if k.get("label_key") == "rpt_pu_unused_rules" else k
            for k in kpis
        ]
        return dict(mod00, kpis=patched)

    def _summary_pills(self, mod00: dict) -> str:
        _s = self._s
        # hit_rate_pct is produced by mod01 (overview), not mod00 (executive) —
        # reading it off mod00 always yielded None and rendered '—'.
        hit_rate = self._r.get("mod01", {}).get("hit_rate_pct", None)
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
        if m.get("failed"):
            # 查詢失敗和「真的沒有 draft 阻擋風險」同樣是「沒有結果」，但語意相反：
            # 渲染成 empty 會讓操作者把一次失敗的檢查讀成乾淨的結果。
            reason = str(m.get("reason") or "").strip()
            warn = t("rpt_pu_draft_pd_failed", lang=self._lang)
            if reason:
                warn += f" ({_e(reason)})"
            return intro + f'<p class="note note-warn" data-tone="warn">{warn}</p>'
        if m.get("skipped") or m.get("total", 0) == 0:
            return intro + f'<p class="note">{_s("rpt_pu_draft_pd_empty")}</p>'

        html = intro
        if m.get("truncated_at"):
            _cap = t("rpt_pu_draft_pd_truncated", lang=self._lang).replace(
                "{n}", str(m["truncated_at"]))
            html += f'<p class="note note-warn" data-tone="warn">{_cap}</p>'

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

        merged = m.get("merged_top_pairs")
        if merged is not None and not merged.empty:
            html += (f'<h4>{_s("rpt_pu_draft_pd_top_pairs")}</h4>'
                     + _df_to_html(
                         merged,
                         no_data_key="rpt_no_records",
                         lang=self._lang,
                         value_i18n_maps={"Risk Type": RISK_TYPE_VALUE_I18N},
                     ))

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
            f'<span>{_e(item.get("ruleset", ""))}</span>'
            f'<span class="badge badge-unused" data-tone="crit">{item.get("unused_count", 0)}</span>'
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
            f'<span>{label}</span><span class="badge badge-hit" data-tone="ok">{value}</span>'
            "</div>"
            for label, value in rows
        )
        notes_html = "".join(f"<li>{_e(note)}</li>" for note in notes)
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
                                                  detail_level="full",
                                                  lang=self._lang))

        mod01 = self._r.get("mod01", {})
        total = mod01.get("total_rules", 0)
        hit = mod01.get("hit_count", 0)
        rate = mod01.get("hit_rate_pct", 0.0)
        summary_df = mod01.get("summary_df")
        unused, indeterminate = self._unused_split()
        if indeterminate and not mod01.get("indeterminate_count"):
            # mod01 的摘要表是用舊口徑建的，依對齊後的數字重建。
            summary_df = build_summary_df(total, hit, unused, indeterminate)
        _s = self._s

        stats = (
            "<p>"
            f'{_s("rpt_pu_total_rules")}: <strong>{human_number(total)}</strong> &nbsp;|&nbsp; '
            f'<span class="badge badge-hit" data-tone="ok">{_s("rpt_pu_hit_rules")}</span> {human_number(hit)} &nbsp;|&nbsp; '
            f'<span class="badge badge-unused" data-tone="crit">{_s("rpt_pu_unused_rules")}</span> {human_number(unused)} &nbsp;|&nbsp; '
            f'{_s("rpt_pu_hit_rate")}: <strong>{rate}%</strong>'
            "</p>"
        )
        if indeterminate:
            stats += (
                '<p class="note note-warn" data-tone="warn">'
                + t("rpt_pu_overview_indeterminate", lang=self._lang, n=indeterminate)
                + "</p>"
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
                svg = render_matplotlib_svg(spec, lang=self._lang)
                if svg:
                    chart_html = f'<figure class="chart-static">{svg}</figure>'
            except Exception:
                pass
        html_parts.append(stats + chart_html + _df_to_html(summary_df, lang=self._lang))
        return "".join(html_parts)

    def _mod02_html(self) -> str:
        html_parts = []
        html_parts.append(render_section_guidance("pu_mod02_hit_detail",
                                                  profile="security_risk",
                                                  detail_level="full",
                                                  lang=self._lang))

        mod02 = self._r.get("mod02", {})
        hit_df = mod02.get("hit_df")
        top_ports_df = mod02.get("top_ports_df")
        count = mod02.get("record_count", 0)
        shown = 0 if hit_df is None or getattr(hit_df, "empty", True) else len(hit_df)
        if count and shown and count > shown:
            # Full hit-rule count exceeds the display cap — disclose the truncation
            # rather than printing "{count} rows" over a 500-row table.
            _msg = t("rpt_table_truncated_note", lang=self._lang).replace(
                "{shown}", str(shown)).replace("{total}", str(count))
            note = f'<p class="note">{_msg}</p>'
        else:
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
                                                  detail_level="full",
                                                  lang=self._lang))

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
            # Disclose against the TRUE unused total (before the 1000-row df cap),
            # not the post-cap record_count.
            total_unused = mod03.get("total_unused", count)
            if total_unused > 50:
                note_text = t("rpt_pu_unused_truncated", lang=self._lang, count=total_unused)
            else:
                note_text = f"{total_unused} rows" if total_unused else ""
            note = f'<p style="color:#718096;font-size:12px;">{note_text}</p>' if note_text else ""
            html_parts.append(
                caveat_html + note + _rule_cards_html(unused_df.head(50), mode="unused", lang=self._lang)
            )
        return "".join(html_parts)

    def _mod04_html(self) -> str:
        html_parts = []
        html_parts.append(render_section_guidance("pu_mod04_deny_effectiveness",
                                                  profile="security_risk",
                                                  detail_level="full",
                                                  lang=self._lang))

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
            f'<span class="badge badge-hit" data-tone="ok">{_s("rpt_pu_deny_hit")}</span> {deny_hit} &nbsp;|&nbsp; '
            f'<span class="badge badge-unused" data-tone="crit">{_s("rpt_pu_deny_unused")}</span> {deny_unused} &nbsp;|&nbsp; '
            f'{_s("rpt_pu_deny_hit_rate")}: <strong>{deny_hit_rate}%</strong>'
            "</p>"
        )

        if override_count > 0:
            stats += (
                '<p class="note note-warn" data-tone="warn">'
                f'<strong>{_s("rpt_pu_override_deny")}</strong> {override_count} '
                f'— {_s("rpt_pu_override_deny_note")}</p>'
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
