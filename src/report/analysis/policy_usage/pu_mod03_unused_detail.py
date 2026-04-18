"""
Detail table for rules with zero observed traffic hits in the lookback period.
"""
from loguru import logger
import pandas as pd

from src.report.analysis.policy_usage.pu_mod02_hit_detail import _resolve_actors, _resolve_services

_MAX_ROWS = 1000

CAVEAT = (
    "Rules listed here had no observed traffic hits in the selected lookback window. "
    "This does not automatically mean the rules are safe to remove because the PCE traffic "
    "retention window, low-frequency workloads, or exceptional failover paths may hide valid usage."
)

def pu_unused_detail(
    baseline_rules: list,
    ruleset_map: dict,
    hit_rule_hrefs: set,
    execution_stats: dict | None = None,
    api_client=None,
) -> dict:
    """Build the unused-rules detail table."""
    execution_stats = execution_stats or {}
    hit_rule_port_details = {
        str(item.get("rule_href", "")): item
        for item in execution_stats.get("hit_rule_port_details", []) or []
        if item.get("rule_href")
    }

    rows = []
    for rule in baseline_rules:
        href = rule.get("href", "")
        if href in hit_rule_hrefs:
            continue
        rows.append(_build_unused_row(rule, ruleset_map, hit_rule_port_details.get(href, {}), api_client))

    rows.sort(key=lambda r: (r.get("Ruleset", ""), r.get("No", 0)))
    rows = rows[:_MAX_ROWS]

    columns = [
        "Ruleset",
        "No",
        "Rule ID",
        "Type",
        "Description",
        "Destination",
        "Source",
        "Services",
        "Observed Hit Ports",
        "Enabled",
        "Created At",
    ]
    unused_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    return {
        "unused_df": unused_df,
        "record_count": len(rows),
        "caveat": CAVEAT,
    }

def _build_unused_row(rule: dict, ruleset_map: dict, port_detail: dict, api_client) -> dict:
    rs_href = rule.get("_ruleset_href", "")
    rs_name = ruleset_map.get(rs_href, rule.get("_ruleset_name", rs_href))
    rs_id = rule.get("_ruleset_id", "")
    rule_id = rule.get("_rule_id", "")
    rule_no = rule.get("_rule_no", "")

    providers = _resolve_actors(rule.get("providers", []), api_client)
    consumers = _resolve_actors(rule.get("consumers", []), api_client)
    services = _resolve_services(rule.get("ingress_services", []), api_client)

    created_at = rule.get("created_at", "")
    if created_at and "T" in created_at:
        created_at = created_at[:10]

    desc = rule.get("description", "") or "No description"
    ruleset_label = f"{rs_name} ({rs_id})" if rs_id else rs_name
    observed_hit_ports = str(port_detail.get("top_hit_ports", "") or "").strip() or "None in lookback"

    return {
        "No": rule_no,
        "Rule ID": rule_id,
        "Type": rule.get("_rule_type", "Allow"),
        "Description": desc,
        "Ruleset": ruleset_label,
        "Destination": providers,
        "Source": consumers,
        "Services": services,
        "Observed Hit Ports": observed_hit_ports,
        "Enabled": rule.get("enabled", True),
        "Created At": created_at,
    }
