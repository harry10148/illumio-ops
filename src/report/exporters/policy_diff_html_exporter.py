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
.pd-risk-high{color:#b91c1c;font-weight:700;} .pd-risk-medium{color:#b45309;font-weight:600;}
.note{font-size:12px;color:#6b7280;margin-top:24px;}
"""


def _esc(v) -> str:
    return _html.escape(str(v), quote=True)


def _card(n, label) -> str:
    return f'<div class="card"><div class="n">{_esc(n)}</div><div class="l">{_esc(label)}</div></div>'


class PolicyDiffHtmlExporter:
    def __init__(self, results: dict, lang: str = "en"):
        self._r = results
        self._lang = lang

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
            return f'<p>{_esc(t("rpt_policy_diff_no_changes", lang=self._lang))}</p>'
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
        html = f"""<!doctype html><html lang="{_esc(self._lang)}"><head>
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
