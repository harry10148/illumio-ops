"""App Summary HTML exporter — standalone single-app report.

Renders into the design/v2 report shell (``report_shell.build_shell_document``)
like every other HTML report: the shell owns the cover, the table of contents,
the chapter frames and the appendix.

Chapters: a KPI strip as the executive chapter, then inbound baseline, outbound
dependencies, policy coverage (this app), policy impact, enforcement and
findings. Empty App Labels still render a valid report — cover plus one chapter
carrying the rpt_app_empty note — rather than raising.

Contract: __init__(results, lang) + export(output_dir) -> path.
"""
from __future__ import annotations

import datetime
import html as _html
import os

from src.i18n import t
from src.report.app_summary_report import _safe_filename_token
from src.report.exporters._output_paths import (
    discard_reserved,
    reserve_unique_path,
    write_text_atomic,
)
from src.report.exporters.html_exporter import _sev_attrs
from src.report.exporters.report_shell import (
    ShellCover,
    ShellSection,
    build_shell_document,
)
from src.report.exporters.table_renderer import render_df_table, wrap_table_panel
from src.report.report_metadata import write_metadata_sidecar


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


def _kpi_strip(cards: str) -> str:
    return f'<div class="kpi-strip">{cards}</div>'


class AppSummaryHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _section(self, id_: str, title: str, content: str) -> ShellSection:
        """One chapter for the v2 shell.

        The heading is printed by ``build_shell_document`` now, so this returns
        the body plus the metadata the shell needs. No ``marks``: this report
        has no findings tally to chip the chapter head with, and the severity
        badges in the findings table are table data (B10/C6).
        """
        return ShellSection(id=id_, title=title, html=content)

    def _trunc_note(self, shown_df, total: int) -> str:
        """Disclose truncation when a KPI counts the full set but the table shows
        only the top N (the baseline tables cap at top_n)."""
        shown = 0 if shown_df is None or getattr(shown_df, "empty", True) else len(shown_df)
        if total and shown and total > shown:
            msg = _esc(t("rpt_table_truncated_note", lang=self._lang)
                       .replace("{shown}", str(shown)).replace("{total}", str(total)))
            return f'<p class="note">{msg}</p>'
        return ""

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
        top_df = mod03.get("top_flows")
        caption = (f'<h3>{_esc(t("rpt_app_top_uncovered", lang=self._lang))}</h3>'
                   if top_df is not None and not getattr(top_df, "empty", True) else "")
        top = caption + render_df_table(top_df, col_i18n={}, lang=self._lang)
        return _kpi_strip(cards) + top

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
        return _kpi_strip(cards) + f'<p class="note">{note}</p>'

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
            # data-tone/data-sev, not the badge-<SEV> class alone: SHELL_CSS's
            # .badge reads var(--mark)/var(--fill)/var(--ink) with no fallback,
            # so a badge without a tone of its own inherits the chapter's and
            # every severity in the table ends up looking identical. data-sev is
            # what keeps CRITICAL (solid) apart from HIGH (outlined) — they
            # share a tone. The legacy badge-<SEV> class is kept alongside.
            badge = (f'<span class="badge badge-{sev}"{_sev_attrs(sev)}>{sev}</span>'
                     if sev else "")
            rows.append(
                f"<tr><td>{badge}</td>"
                f"<td>{_esc(getattr(f, 'rule_id', ''))}</td>"
                f"<td>{_esc(getattr(f, 'description', ''))}</td></tr>"
            )
        table_html = (
            "<div class='report-table-wrap'><table class='report-table'><thead><tr>"
            f"<th>{_esc(t('rpt_col_severity', lang=self._lang))}</th>"
            f"<th>{_esc(t('rpt_col_rule_name', lang=self._lang))}</th>"
            f"<th>{_esc(t('rpt_col_description', lang=self._lang))}</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
        # Three columns: the panel's job here is the compact modifier and the
        # break-inside rule in print, not the wide treatment.
        return wrap_table_panel(table_html, None, ["severity", "rule", "desc"],
                                self._lang)

    def _render_html(self) -> str:
        lang = self._lang
        title = t("rpt_app_title", lang=lang)
        report_type = t("rpt_cover_type_app_summary", lang=lang)
        app = self._r.get("app", "")
        env = self._r.get("env", "")
        sub = app + (f" / {env}" if env else "")

        if self._r.get("empty"):
            # Still a real document: cover, table of contents, one chapter
            # carrying the narrative, appendix. The note text is unchanged.
            sections = [self._section(
                "findings", t("rpt_app_findings", lang=lang),
                f'<p class="note">{_esc(t("rpt_app_empty", lang=lang))}</p>',
            )]
        else:
            base = self._r.get("baseline", {})
            inbound_df = base.get("inbound")
            outbound_df = base.get("outbound")
            # _trunc_note stays exactly as it was: it is this report's explicit
            # disclosure that a KPI counts the full set while the table shows
            # only the top N (CLAUDE.md's no-silent-truncation rule).
            inbound = render_df_table(inbound_df, col_i18n={}, lang=lang) + self._trunc_note(inbound_df, base.get("inbound_count", 0))
            outbound = render_df_table(outbound_df, col_i18n={}, lang=lang) + self._trunc_note(outbound_df, base.get("outbound_count", 0))
            sections = [
                # The KPI row had no heading of its own before (a bare
                # <section class="card"> holding a .kpi-grid), so naming it here
                # takes nothing away.
                ShellSection(
                    id="exec-summary",
                    title=(f'{t("rpt_exec_summary_label", lang=lang)} '
                           f'— {report_type}'),
                    html=self._kpi_row(),
                    kind="exec"),
                self._section("inbound", t("rpt_app_inbound", lang=lang), inbound),
                self._section("outbound", t("rpt_app_outbound", lang=lang), outbound),
                self._section("coverage", t("rpt_app_coverage", lang=lang),
                              self._coverage_section()),
                self._section("policy-impact", t("rpt_app_policy_impact", lang=lang),
                              self._policy_impact_section()),
                self._section("enforcement", t("rpt_app_enforcement", lang=lang),
                              self._enforcement_section()),
                self._section("findings", t("rpt_app_findings", lang=lang),
                              self._findings_section()),
            ]

        # Raw strings: build_shell_document escapes every ShellCover scalar.
        # The app/env line is real data, not a label, so it rides in the kicker
        # slot; the eyebrow keeps the report type, which the legacy cover showed
        # in .cover-type and which would otherwise leave the text layer (
        # type_label alone only reaches body[data-report-title]).
        cover = ShellCover(
            title=title,
            doc_title=title,
            type_label=report_type,
            eyebrow=report_type,
            kicker=sub,
        )
        return build_shell_document(lang=lang, cover=cover, sections=sections)

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        html = self._render_html()
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        token = _safe_filename_token(self._r.get("app", "app"))
        # 以 O_EXCL 搶下唯一檔名（同分鐘、同 app 併發產出會撞名）＋暫存檔
        # os.replace，避免兩張同型報表互相截斷、或半寫檔被 GUI 列出。
        path = reserve_unique_path(
            os.path.join(output_dir, f"Illumio_App_Summary_{token}_{ts}.html"))
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
        app = str(self._r.get("app", "") or "")
        env = str(self._r.get("env", "") or "")
        mod01 = self._r.get("mod01") if isinstance(self._r.get("mod01"), dict) else {}
        flows = int(mod01.get("total_flows", 0) or 0)
        # Language-neutral, like the audit/traffic sidecars ("audit events N").
        summary = f"app {app}" + (f" / env {env}" if env else "")
        summary += " | no flows in window" if self._r.get("empty") else f" | flows {flows}"
        write_metadata_sidecar(report_path, {
            "report_type": "app_summary",
            "file_format": "html",
            "generated_at": datetime.datetime.now().isoformat(),
            "record_count": flows,
            "summary": summary,
        })
