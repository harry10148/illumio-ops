"""Policy Diff HTML exporter — renders DRAFT-vs-ACTIVE diff + attribution.

Self-contained (no chart deps): summary cards + a Ruleset-changes table + a
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

_ROW_CLASS = {"added": "pd-added", "removed": "pd-removed", "modified": "pd-modified"}
_CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:24px;color:#1f2937;}
h1{font-size:22px;} h2{font-size:16px;margin-top:28px;}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0;}
.card{border:1px solid #e5e7eb;border-radius:8px;padding:10px 16px;min-width:120px;}
.card .n{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;}
.card .l{font-size:12px;color:#6b7280;}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px;}
th,td{border:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:top;}
th{background:#f9fafb;}
.pd-added{background:#ecfdf5;} .pd-removed{background:#fef2f2;} .pd-modified{background:#fffbeb;}
.note{font-size:12px;color:#6b7280;margin-top:24px;}
"""


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _card(n, label) -> str:
    return f'<div class="card"><div class="n">{n}</div><div class="l">{_esc(label)}</div></div>'


class PolicyDiffHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

    def _table(self, df: pd.DataFrame, id_col: str) -> str:
        if df is None or df.empty:
            return f'<p>{_esc(t("rpt_policy_diff_no_changes", lang=self._lang))}</p>'
        cols = ["change_type", "ruleset_name", id_col, "field",
                "draft_value", "active_value", "last_actor", "last_changed"]
        cols = [c for c in cols if c in df.columns]
        head = "".join(f"<th>{_esc(c)}</th>" for c in cols)
        body = []
        for _, row in df.iterrows():
            cls = _ROW_CLASS.get(str(row.get("change_type", "")), "")
            cells = "".join(f"<td>{_esc(row.get(c, ''))}</td>" for c in cols)
            body.append(f'<tr class="{cls}">{cells}</tr>')
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    def export(self, output_dir: str = "reports") -> str:
        os.makedirs(output_dir, exist_ok=True)
        s = self._r.get("summary", {})
        title = t("rpt_policy_diff_report_title", lang=self._lang)
        cards = (
            _card(s.get("rulesets_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " RS")
            + _card(s.get("rulesets_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " RS")
            + _card(s.get("rulesets_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " RS")
            + _card(s.get("rules_added", 0), t("rpt_policy_diff_added", lang=self._lang) + " Rule")
            + _card(s.get("rules_removed", 0), t("rpt_policy_diff_removed", lang=self._lang) + " Rule")
            + _card(s.get("rules_modified", 0), t("rpt_policy_diff_modified", lang=self._lang) + " Rule")
        )
        html = f"""<!doctype html><html lang="{self._lang}"><head>
<meta charset="utf-8"><title>{_esc(title)}</title><style>{_CSS}</style></head><body>
<h1>{_esc(title)}</h1>
<div class="cards">{cards}</div>
<h2>{_esc(t("rpt_policy_diff_ruleset_changes", lang=self._lang))}</h2>
{self._table(self._r.get("ruleset_changes"), "ruleset_id")}
<h2>{_esc(t("rpt_policy_diff_rule_changes", lang=self._lang))}</h2>
{self._table(self._r.get("rule_changes"), "rule_id")}
<p class="note">{_esc(t("rpt_policy_diff_attribution_note", lang=self._lang))}</p>
</body></html>"""

        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
        path = os.path.join(output_dir, f"Illumio_Policy_Diff_Report_{ts}.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        return path
