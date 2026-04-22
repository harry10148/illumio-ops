"""
pu_mod01_overview.py
Policy usage overview — hit vs unused rule counts and percentages.
"""
import pandas as pd

def pu_overview(baseline_rules: list, hit_rule_hrefs: set) -> dict:
    """Compute top-level policy usage statistics.

    Args:
        baseline_rules: Flat list of rule dicts from active rulesets.
        hit_rule_hrefs: Set of rule hrefs found in allowed traffic flows.

    Returns:
        dict with keys:
            total_rules   (int)
            hit_count     (int)
            unused_count  (int)
            hit_rate_pct  (float, 0-100)
            summary_df    (pd.DataFrame: Status, Count, Percentage)
    """
    total = len(baseline_rules)
    hit = len(hit_rule_hrefs)
    unused = total - hit
    hit_rate = round(hit / total * 100, 1) if total > 0 else 0.0

    summary_df = pd.DataFrame([
        {"Status": "Hit", "Count": hit, "Percentage": f"{hit_rate}%"},
        {"Status": "Unused", "Count": unused, "Percentage": f"{round(100 - hit_rate, 1)}%"},
    ])

    return {
        "total_rules":  total,
        "hit_count":    hit,
        "unused_count": unused,
        "hit_rate_pct": hit_rate,
        "summary_df":   summary_df,
    }
