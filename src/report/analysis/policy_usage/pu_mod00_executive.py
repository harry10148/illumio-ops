"""
pu_mod00_executive.py
Executive summary KPIs and top-unused-rulesets for the Policy Usage report.
"""
import datetime
import logging
from collections import Counter

logger = logging.getLogger(__name__)


def pu_executive_summary(results: dict, lookback_days: int) -> dict:
    """Aggregate KPIs and surface attention items.

    Args:
        results:       dict containing mod01, mod02, mod03 outputs.
        lookback_days: Number of days covered by the traffic query.

    Returns:
        dict with keys:
            generated_at    (str, ISO)
            lookback_days   (int)
            kpis            (list[dict]: label, value)
            attention_items (list[dict]: ruleset, unused_count)
    """
    mod01 = results.get("mod01", {})
    mod03 = results.get("mod03", {})

    total   = mod01.get("total_rules", 0)
    hit     = mod01.get("hit_count", 0)
    unused  = mod01.get("unused_count", 0)
    rate    = mod01.get("hit_rate_pct", 0.0)

    kpis = [
        {"label": "啟用規則總數", "value": str(total)},
        {"label": "已命中規則", "value": str(hit)},
        {"label": "未使用規則", "value": str(unused)},
        {"label": "命中率", "value": f"{rate}%"},
        {"label": "回溯期間", "value": f"{lookback_days} 天"},
    ]

    # Top rulesets by unused rule count
    attention_items = []
    unused_df = mod03.get("unused_df")
    if unused_df is not None and not unused_df.empty and "Ruleset" in unused_df.columns:
        counts = Counter(unused_df["Ruleset"].tolist())
        for rs_name, cnt in counts.most_common(5):
            attention_items.append({"ruleset": rs_name, "unused_count": cnt})

    return {
        "generated_at":   datetime.datetime.now().isoformat(timespec="seconds"),
        "lookback_days":  lookback_days,
        "kpis":           kpis,
        "attention_items": attention_items,
    }
