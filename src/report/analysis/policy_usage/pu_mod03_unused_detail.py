"""
pu_mod03_unused_detail.py
Detail table for rules with zero traffic hits in the lookback period.
"""
import logging
import pandas as pd

from src.report.analysis.policy_usage.pu_mod02_hit_detail import (
    _build_row, _resolve_actors, _resolve_services,
)

logger = logging.getLogger(__name__)

_MAX_ROWS = 1000

CAVEAT = (
    "本分析期間內沒有任何流量命中的規則。"
    "請注意，此分類仍受 PCE 流量保留期間限制。"
    "若某規則僅在回溯範圍之前曾被命中，仍可能在本報表中顯示為未使用。"
    "刪除任何規則前請務必再次確認。"
)


def pu_unused_detail(
    baseline_rules: list,
    ruleset_map: dict,
    hit_rule_hrefs: set,
    api_client=None,
) -> dict:
    """Build the unused-rules detail table.

    Args:
        baseline_rules:  Flat list of rule dicts.
        ruleset_map:     {ruleset_href -> ruleset_name}
        hit_rule_hrefs:  Set of hrefs that appeared in traffic flows.
        api_client:      ApiClient instance for resolution.

    Returns:
        dict with keys:
            unused_df    (pd.DataFrame)
            record_count (int)
            caveat       (str)
    """
    rows = []
    for rule in baseline_rules:
        href = rule.get("href", "")
        if href in hit_rule_hrefs:
            continue
        rows.append(_build_unused_row(rule, ruleset_map, api_client))

    rows.sort(key=lambda r: (r.get("Ruleset", ""), r.get("No", 0)))
    rows = rows[:_MAX_ROWS]

    columns = ["Ruleset", "No", "Rule ID", "Type", "Description", "Destination", "Source", "Services", "Enabled", "Created At"]
    unused_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    return {
        "unused_df":   unused_df,
        "record_count": len(rows),
        "caveat":      CAVEAT,
    }


def _build_unused_row(rule: dict, ruleset_map: dict, api_client) -> dict:
    rs_href = rule.get("_ruleset_href", "")
    rs_name = ruleset_map.get(rs_href, rule.get("_ruleset_name", rs_href))
    rs_id = rule.get("_ruleset_id", "")
    rule_id = rule.get("_rule_id", "")
    rule_no = rule.get("_rule_no", "")

    providers = _resolve_actors(rule.get("providers", []), api_client)
    consumers = _resolve_actors(rule.get("consumers", []), api_client)
    services  = _resolve_services(rule.get("ingress_services", []), api_client)

    created_at = rule.get("created_at", "")
    if created_at and "T" in created_at:
        created_at = created_at[:10]

    desc = rule.get("description", "") or "未填寫"
    ruleset_label = f"{rs_name} ({rs_id})" if rs_id else rs_name

    return {
        "No":          rule_no,
        "Rule ID":     rule_id,
        "Type":        rule.get("_rule_type", "允許"),
        "Description": desc,
        "Ruleset":     ruleset_label,
        "Destination": providers,
        "Source":      consumers,
        "Services":    services,
        "Enabled":     rule.get("enabled", True),
        "Created At":  created_at,
    }
