"""App Summary HTML exporter — standalone single-app report.

Self-contained (mirrors policy_diff_html_exporter): inline CSS, no chart deps.
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
from src.report.exporters.table_renderer import render_df_table

_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2937;}
h1{font-size:22px;} h2{font-size:16px;margin-top:28px;}
.sub{font-size:13px;color:#6b7280;margin-top:4px;}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0;}
.card{border:1px solid #e5e7eb;border-radius:8px;padding:10px 16px;min-width:120px;}
.card .n{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;}
.card .l{font-size:12px;color:#6b7280;}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px;}
th,td{border:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:top;}
th{background:#f9fafb;}
.sev-CRITICAL{color:#b91c1c;font-weight:700;} .sev-HIGH{color:#b91c1c;font-weight:600;}
.sev-MEDIUM{color:#b45309;font-weight:600;} .sev-INFO{color:#6b7280;}
.note{font-size:13px;color:#6b7280;margin-top:24px;}
.report-table-panel--empty{border:1px dashed #d1d5db;border-radius:8px;padding:16px;color:#9ca3af;font-size:13px;}
"""


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _card(n, label) -> str:
    return f'<div class="card"><div class="n">{_esc(n)}</div><div class="l">{_esc(label)}</div></div>'


class AppSummaryHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _kpi_row(self) -> str:
        base = self._r.get("baseline", {})
        mod03 = self._r.get("mod03", {})
        coverage = mod03.get("enforced_coverage_pct", 0.0)
        return (
            _card(base.get("flow_count", 0), t("rpt_app_count", lang=self._lang))
            + _card(base.get("inbound_count", 0), t("rpt_app_inbound", lang=self._lang))
            + _card(base.get("outbound_count", 0), t("rpt_app_outbound", lang=self._lang))
            + _card(f"{coverage}%", t("rpt_app_coverage", lang=self._lang))
        )

    def _coverage_section(self) -> str:
        mod03 = self._r.get("mod03", {})
        cards = (
            _card(mod03.get("n_allowed", 0), t("rpt_enforced", default="Enforced", lang=self._lang))
            + _card(mod03.get("pb_uncovered_count", 0), t("rpt_staged", default="Staged", lang=self._lang))
            + _card(mod03.get("n_blocked", 0) + mod03.get("n_unknown", 0),
                    t("rpt_gap", default="Gap", lang=self._lang))
        )
        top = render_df_table(mod03.get("top_flows"), col_i18n={}, lang=self._lang)
        return f'<div class="cards">{cards}</div>{top}'

    def _findings_section(self) -> str:
        findings = self._r.get("findings", []) or []
        if not findings:
            return render_df_table(None, col_i18n={}, lang=self._lang)
        rows = []
        for f in findings:
            sev = _esc(getattr(f, "severity", ""))
            rows.append(
                f'<tr><td class="sev-{sev}">{sev}</td>'
                f"<td>{_esc(getattr(f, 'rule_id', ''))}</td>"
                f"<td>{_esc(getattr(f, 'description', ''))}</td></tr>"
            )
        return (
            "<table><thead><tr>"
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
        sub = _esc(app) + (f" / {_esc(env)}" if env else "")

        if self._r.get("empty"):
            body = f'<p class="note">{_esc(t("rpt_app_empty", lang=lang))}</p>'
        else:
            base = self._r.get("baseline", {})
            inbound = render_df_table(base.get("inbound"), col_i18n={}, lang=lang)
            outbound = render_df_table(base.get("outbound"), col_i18n={}, lang=lang)
            body = (
                f'<div class="cards">{self._kpi_row()}</div>'
                f'<h2 id="inbound">{_esc(t("rpt_app_inbound", lang=lang))}</h2>{inbound}'
                f'<h2 id="outbound">{_esc(t("rpt_app_outbound", lang=lang))}</h2>{outbound}'
                f'<h2 id="coverage">{_esc(t("rpt_app_coverage", lang=lang))}</h2>{self._coverage_section()}'
                f'<h2 id="findings">{_esc(t("rpt_app_findings", lang=lang))}</h2>{self._findings_section()}'
            )

        return f"""<!doctype html><html lang="{_esc(lang)}"><head>
<meta charset="utf-8"><title>{_esc(title)}</title><style>{_CSS}</style></head><body>
<h1>{_esc(title)}</h1>
<div class="sub">{sub}</div>
{body}
</body></html>"""

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        html = self._render_html()
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        token = _safe_filename_token(self._r.get("app", "app"))
        path = os.path.join(output_dir, f"Illumio_App_Summary_{token}_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return path
