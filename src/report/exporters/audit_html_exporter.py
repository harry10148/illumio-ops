"""Self-contained HTML report for the Audit & System Events Report."""

from __future__ import annotations

import datetime
import html
from loguru import logger
import os

import pandas as pd

from ._output_paths import discard_reserved, reserve_unique_path, write_text_atomic
# _body_tone / _marks_tone / _sev_attrs are the v2 shell's tone helpers; they
# live next to the traffic exporter that first needed them, which is also where
# _trend_deltas_section and render_section_guidance already come from.
from .html_exporter import (
    _body_tone,
    _marks_tone,
    _sev_attrs,
    _trend_deltas_section,
    render_section_guidance,
)
from src.i18n import t
from src.report.section_guidance import visible_in
from src.humanize_ext import human_number
from .report_i18n import COL_I18N as _COL_I18N
from .report_i18n import STRINGS
from .report_shell import ShellCover, ShellSection, build_shell_document
from .table_renderer import render_df_table
from .chart_renderer import render_matplotlib_svg
from .code_highlighter import get_highlight_css
from src.report.analysis.audit.audit_risk import get_risk
from src.report.exporters._exec_summary import render_exec_summary_html
from src.report.exporters.concern_card import render_concern_cards

_HIGHLIGHT_CSS = f'<style>\n{get_highlight_css()}\n</style>'
_REPORT_DETAIL_LEVEL = "full"


def _chart_html(spec: dict | None, lang: str = "en") -> str:
    """Render a chart_spec as inline static SVG, or '' on failure."""
    if not spec:
        return ""
    try:
        svg = render_matplotlib_svg(spec, lang=lang)
        return f'<figure class="chart-static">{svg}</figure>' if svg else ""
    except Exception as exc:
        logger.warning("audit chart render failed: {}", exc)
        return ""


def _norm_col(name) -> str:
    """Tolerant column-name match: case-insensitive, whitespace/dash collapsed."""
    return str(name).strip().lower().replace(" ", "_").replace("-", "_")

_LONG_TEXT_TRUNCATE_AT = 150


def _wbr_at_dots(text: str) -> str:
    """Insert <wbr> at each dot so `agent.update_request` can wrap cleanly."""
    import html as _html
    if text is None:
        return ""
    s = _html.escape(str(text))
    return s.replace(".", ".<wbr>").replace("_", "_<wbr>")


def _truncate_long_cell(text: str, limit: int = _LONG_TEXT_TRUNCATE_AT) -> str:
    """Wrap long cell content in <details> so the row stays narrow when printed."""
    import html as _html
    if text is None:
        return ""
    s = str(text)
    if len(s) <= limit:
        return _html.escape(s)
    head = _html.escape(s[:limit].rstrip()) + "…"
    full = _html.escape(s)
    return (
        f'<details class="cell-long"><summary>{head}</summary>'
        f'<pre class="cell-long-full">{full}</pre></details>'
    )


_RECENT_HTML_LIMIT = 10


def _capped_recent(df, limit: int = _RECENT_HTML_LIMIT):
    """近期事件表僅顯示前 limit 筆，完整清單見 CSV/XLSX 匯出（spec I1）。"""
    if df is None or not hasattr(df, "empty") or df.empty:
        return df
    return df.head(limit)


def _df_to_html(df, no_data_key: str = "rpt_no_data", show_risk: bool = False, lang: str = "en") -> str:
    event_type_col = None
    long_text_cols: set[str] = set()
    if df is not None and not (hasattr(df, "empty") and df.empty):
        for c in df.columns:
            norm = _norm_col(c)
            if norm == "event_type" and show_risk:
                event_type_col = c
            if norm in ("change_detail", "notification_detail"):
                long_text_cols.add(c)

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
            # The v2 shell colours .risk-badge from data-tone/data-sev (it even
            # carries the CRITICAL-solid rule for this class), so the inline
            # RISK_COLOR/RISK_BG hexes are gone: an inline colour would win over
            # the shell and freeze the badge outside the tone system.
            badge = (
                f'<span class="risk-badge"{_sev_attrs(risk_level)}>'
                f"{risk_level}</span>"
            )
            return f"{badge}{_wbr_at_dots(row[col])}"
        norm = _norm_col(col)
        if col in long_text_cols:
            return _truncate_long_cell(row[col])
        if norm in ("event_type", "action"):
            return _wbr_at_dots(row[col])
        return "" if row[col] is None else html.escape(str(row[col]))

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
                 profile: str = "security_risk", detail_level: str = _REPORT_DETAIL_LEVEL, lang: str = "en",
                 pce_url: str = "", org_name: str = ""):
        self._r = results
        self._df = df
        self._date_range = date_range
        self._data_source = data_source
        self._profile = profile
        self._detail_level = _REPORT_DETAIL_LEVEL
        self._lang = lang
        self._pce_url = pce_url
        self._org_name = org_name

    def _attention_section(self, attention_items: list) -> str:
        if not attention_items:
            return ""
        _s = self._s
        items_html = render_concern_cards(attention_items, self._lang)
        # The old heading was `style="color:var(--red)"`, and --red was declared
        # on report_css.py's :root, so it really did render red — measured on a
        # 730dbd8f checkout: rgb(220,38,38). My first pass dropped the colour on
        # the theory that the token disappears with build_css. That reasoned
        # about the implementation instead of the shipped output, which is the
        # same mistake as judging against the design file, and the heading came
        # out in default ink. The block's whole reason to exist is to flag the
        # section, and the per-card badges only compensate when a card is HIGH
        # or worse — a list of LOW items lost every warning signal.
        # data-tone drives it now: the heading takes var(--ink), which the tone
        # sets, so no colour is frozen into the markup.
        return (
            '<div style="margin-bottom:20px" data-tone="crit">'
            f'<h2 style="color:var(--ink)">{_s("rpt_au_attention_title")}</h2>'
            + items_html
            + '</div>'
        )

    def _attention_marks(self, attention_items: list) -> dict[str, int]:
        """Risk histogram of the attention items — the summary chapter's marks.

        Audit has no ``findings`` list; the attention items ARE its findings, so
        they are the only thing allowed to add to a chapter mark tally (B10).
        The severity cells in the event tables must not, which is why this reads
        the source data rather than the rendered markup.
        """
        counts: dict[str, int] = {}
        for item in attention_items or []:
            risk = str(item.get("risk", "") or "").upper() or "INFO"
            counts[risk] = counts.get(risk, 0) + 1
        return counts

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        filename = f"illumio_audit_report_{ts}.html"
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
        logger.info("[AuditHtmlExporter] Saved: {}", filepath)
        return filepath

    def _build(self, profile: str = "", detail_level: str = "") -> str:
        profile = profile or self._profile
        detail_level = _REPORT_DETAIL_LEVEL
        _sl = self._lang
        _s = lambda k: STRINGS[k].get(_sl) or STRINGS[k]["en"]
        self._s = _s

        mod00 = self._r.get("mod00", {})
        # The v2 shell builds its own table of contents from the section list,
        # so the hard-coded aside.report-toc is gone. Chapter titles come from
        # each chapter's own heading key (rpt_au_sec_*), not the sidebar
        # abbreviations (rpt_au_nav_*): the sidebar dropped the qualifiers
        # ("1 System Health" vs "1 System Health & Agent") and using it would
        # silently delete them from the document.
        date_str = " ~ ".join(self._date_range) if any(self._date_range) else ""
        today_str = str(datetime.date.today())
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

        _report_type = _s("rpt_cover_type_audit")
        # The exec block no longer prints its own <h2>; the shell prints the
        # chapter head. The suffix keeps the key the old heading used
        # (gui_btn_audit_report) — unlike the traffic family this report already
        # named its own type, so there is nothing to correct here.
        _exec_title = f'{t("rpt_exec_summary_label", lang=self._lang)} — ' \
                      f'{t("gui_btn_audit_report", lang=self._lang)}'
        _exec_body = (
            render_exec_summary_html(
                mod00, report_name=t('gui_btn_audit_report', lang=self._lang),
                lang=self._lang, include_heading=False)
            + render_section_guidance("audit_mod00_executive", profile="security_risk",
                                      detail_level="full", lang=self._lang)
        )

        # The hero's title block (kicker / h1 / "Generated:" subtitle) becomes
        # the shell cover; everything else it carried opens the first chapter in
        # the order it had inside the hero card.
        _attention_items = mod00.get("attention_items", [])
        _summary_body = (
            summary_pills
            + self._attention_section(_attention_items)
            + self._trend_deltas_html()
            + self._severity_dist_html(mod00)
            + f'<h2>{_s("rpt_au_top_events")}</h2>'
            + _chart_html(mod00.get("chart_spec"), lang=self._lang)
            + _df_to_html(mod00.get("top_events_overall"), lang=_sl)
        )

        sections: list[ShellSection] = []
        if _exec_body:
            sections.append(ShellSection(id="exec-summary", title=_exec_title,
                                         html=_exec_body, kind="exec"))
        # 'summary' cannot reuse rpt_au_nav_summary ("Executive Summary") — the
        # table of contents would then list two chapters under the same name.
        # It carries the attention cards, so it is this report's finding chapter
        # and its marks come from those items alone (B10): zero attention items
        # must read as neutral even though the event tables print risk badges.
        sections.append(self._section(
            "summary", "rpt_tr_sec_snapshot", _summary_body,
            kind="finding", marks=self._attention_marks(_attention_items)))
        sections.append(self._section("health", "rpt_au_sec_health", self._mod01_html()))
        sections.append(self._section("users", "rpt_au_sec_users", self._mod02_html()))
        if visible_in('audit_mod03_policy', profile, detail_level):
            sections.append(self._section("policy", "rpt_au_sec_policy", self._mod03_html()))
        if visible_in('audit_mod04_correlation', profile, detail_level):
            sections.append(self._section("correlation", "rpt_au_sec_correlation",
                                          self._mod04_html()))

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

        _kicker = _s("rpt_kicker_audit")
        cover = ShellCover(
            title=_s("rpt_au_title"),
            doc_title=t('rpt_page_title_audit', lang=self._lang),
            type_label=_report_type,
            eyebrow=_report_type,
            # Suppress the kicker when it says the same thing as the eyebrow —
            # the cover would print one string twice (T3/F6, different slot).
            kicker='' if _kicker == _report_type else _kicker,
            meta=_meta,
        )
        return build_shell_document(
            lang=self._lang,
            cover=cover,
            sections=sections,
            appendix_html=f'{_s("rpt_au_footer")} &middot; {today_str}',
            extra_head=_HIGHLIGHT_CSS,
        )

    def _section(self, id_: str, i18n_key: str, content: str, *,
                 kind: str = "detail",
                 marks: dict[str, int] | None = None) -> ShellSection:
        """One chapter for the v2 shell.

        The heading is printed by ``build_shell_document`` now, so this returns
        the body plus the metadata the shell needs. ``marks`` selects where the
        tone comes from, and the distinction is ``None`` vs ``{}``:
        ``None`` reads the tone off the rendered body, a dict (even an empty
        one) reads it off the tally.
        """
        tone = _body_tone(content) if marks is None else _marks_tone(marks)
        return ShellSection(id=id_, title=self._s(i18n_key), html=content,
                            kind=kind, tone=tone, marks=dict(marks or {}))

    def _trend_deltas_html(self) -> str:
        return _trend_deltas_section(
            self._r.get("_trend_deltas"), lang=self._lang,
            mismatch=self._r.get("_trend_mismatch"),
        )

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
                    "type": "bar",
                    "title": "Event Severity Distribution",
                    "title_key": "rpt_au_severity_dist",
                    "data": {"labels": labels, "values": values},
                }
                chart_html = _chart_html(spec, lang=self._lang)
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
        import html as _html
        html = (
            f"<div style='margin-bottom:14px; padding:12px 16px; background:#FEF2F2; border:1px solid #FCA5A5; border-radius:8px;'>"
            f"<div style='font-weight:700; font-size:13px; color:#991B1B; margin-bottom:6px;'>{_s('rpt_au_high_impact_title')}</div>"
            f"<p style='font-size:12px; color:#7F1D1D; margin:0 0 10px 0;'>{_s('rpt_au_high_impact_desc')} (threshold: {threshold}+)</p>"
        )
        for item in items:
            wa = item.get("workloads_affected", 0)
            ts = _html.escape(str(item.get("timestamp", "")))
            et = _html.escape(str(item.get("event_type", "")))
            actor = _html.escape(str(item.get("actor", "N/A")))
            src_ip = _html.escape(str(item.get("src_ip", "")))
            resource_name = _html.escape(str(item.get("resource_name", "")))
            status = _html.escape(str(item.get("status", "")))
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
        import html as _html
        m = self._r.get("mod01", {})
        if "error" in m:
            return f'<p class="note">{_html.escape(str(m["error"]))}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod01_health", profile="security_risk", detail_level="full", lang=_lang)]

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
                f'<p class="note note-warn" data-tone="warn">{_s("rpt_au_sec_concern_desc")}</p>'
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
        html += f'<h3>{_s("rpt_au_recent")}</h3>' + _df_to_html(_capped_recent(m.get("recent")), show_risk=True, lang=_lang)
        return "".join(html_parts) + html

    def _mod02_html(self) -> str:
        import html as _html
        m = self._r.get("mod02", {})
        if "error" in m:
            return f'<p class="note">{_html.escape(str(m["error"]))}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod02_users", profile="security_risk", detail_level="full", lang=_lang)]

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
                + f'<p class="note note-warn" data-tone="warn">{_s("rpt_au_failed_detail_desc")}</p>'
                + _df_to_html(failed_detail, show_risk=True, lang=_lang)
            )

        per_user = m.get("per_user")
        if per_user is not None and not (hasattr(per_user, "empty") and per_user.empty):
            html += (
                f'<h3>{_s("rpt_au_per_user")}</h3>'
                + _chart_html(m.get("chart_spec"), lang=self._lang)
                + _df_to_html(per_user, lang=_lang)
            )

        html += f'<h3>{_s("rpt_au_summary_type")}</h3>' + _df_to_html(m.get("summary"), lang=_lang)
        html += f'<h3>{_s("rpt_au_recent")}</h3>' + _df_to_html(_capped_recent(m.get("recent")), show_risk=True, lang=_lang)
        return "".join(html_parts) + html

    def _mod03_html(self) -> str:
        import html as _html
        m = self._r.get("mod03", {})
        if "error" in m:
            return f'<p class="note">{_html.escape(str(m["error"]))}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod03_policy", profile="security_risk", detail_level="full", lang=_lang)]

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
                + f'<p class="note note-warn" data-tone="warn">{_s("rpt_au_provision_desc")}</p>'
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
                + _chart_html(m.get("chart_spec"), lang=self._lang)
                + _df_to_html(per_user, lang=_lang)
            )

        html += f'<h3>{_s("rpt_au_summary_type")}</h3>' + _df_to_html(m.get("summary"), lang=_lang)
        html += f'<h3>{_s("rpt_au_recent")}</h3>' + _df_to_html(_capped_recent(m.get("recent")), show_risk=True, lang=_lang)
        return "".join(html_parts) + html

    def _mod04_html(self) -> str:
        import html as _html
        m = self._r.get("mod04", {})
        if "error" in m:
            return f'<p class="note">{_html.escape(str(m["error"]))}</p>'

        _s = self._s
        _lang = self._lang
        html_parts = [render_section_guidance("audit_mod04_correlation", profile="security_risk", detail_level="full", lang=_lang)]

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
                f'<p class="note note-warn" data-tone="warn">{_s("rpt_au_corr_desc")}</p>'
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
