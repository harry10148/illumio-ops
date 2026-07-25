"""
pu_mod01_overview.py
Policy usage overview — hit vs unused rule counts and percentages.
"""
from __future__ import annotations

import pandas as pd

# 查詢失敗／逾時的規則同樣「不在 hit 名單裡」，但那是「不知道」而不是「沒用到」。
# 把它們算進 unused_count，操作者就會照著這個 KPI 去下架其實從未被檢查過的規則。
# 標籤刻意寫成完整句子：summary_df 的 Status 值不走 i18n（Hit/Unused 亦然），
# 讀者必須能只看表格就知道這一列不是「未使用」。
_INDETERMINATE_LABEL = "Indeterminate (traffic query did not complete)"


def indeterminate_hrefs(execution_stats: dict | None) -> set:
    """Rule hrefs whose per-rule traffic query failed or never completed."""
    out: set = set()
    for key in ("failed_rule_details", "pending_rule_details"):
        for item in (execution_stats or {}).get(key, []) or []:
            if isinstance(item, dict) and item.get("rule_href"):
                out.add(str(item["rule_href"]))
    return out


def build_summary_df(total: int, hit: int, unused: int,
                     indeterminate: int = 0) -> pd.DataFrame:
    """Status/Count/Percentage table; the indeterminate row appears only when > 0."""
    def _pct(n: int) -> str:
        return f"{round(n / total * 100, 1) if total > 0 else 0.0}%"

    rows = [
        {"Status": "Hit", "Count": hit, "Percentage": _pct(hit)},
        {"Status": "Unused", "Count": unused, "Percentage": _pct(unused)},
    ]
    if indeterminate:
        rows.append({"Status": _INDETERMINATE_LABEL, "Count": indeterminate,
                     "Percentage": _pct(indeterminate)})
    return pd.DataFrame(rows)


def pu_overview(baseline_rules: list, hit_rule_hrefs: set,
                execution_stats: dict | None = None) -> dict:
    """Compute top-level policy usage statistics.

    Args:
        baseline_rules: Flat list of rule dicts from active rulesets.
        hit_rule_hrefs: Set of rule hrefs found in allowed traffic flows.
        execution_stats: Per-rule query outcomes; used to split the non-hit
            rules into confirmed-unused vs indeterminate (query failed/pending).

    Returns:
        dict with keys:
            total_rules         (int)
            hit_count           (int)
            unused_count        (int) — confirmed unused only
            indeterminate_count (int) — non-hit rules whose query never completed
            hit_rate_pct        (float, 0-100)
            summary_df          (pd.DataFrame: Status, Count, Percentage)
    """
    total = len(baseline_rules)
    hit = len(hit_rule_hrefs)
    unknown = indeterminate_hrefs(execution_stats)
    indeterminate = sum(
        1 for r in baseline_rules
        if r.get("href") and r.get("href") not in hit_rule_hrefs
        and str(r.get("href")) in unknown
    )
    unused = max(total - hit - indeterminate, 0)
    hit_rate = round(hit / total * 100, 1) if total > 0 else 0.0

    return {
        "total_rules":         total,
        "hit_count":           hit,
        "unused_count":        unused,
        "indeterminate_count": indeterminate,
        "hit_rate_pct":        hit_rate,
        "summary_df":          build_summary_df(total, hit, unused, indeterminate),
    }
