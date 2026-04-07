"""
pu_mod02_hit_detail.py
Detail table for rules that were hit by allowed traffic.
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)

_MAX_ROWS = 500


def pu_hit_detail(
    baseline_rules: list,
    ruleset_map: dict,
    hit_counts: dict,
    api_client=None,
) -> dict:
    """Build the hit-rules detail table.

    Args:
        baseline_rules: Flat list of rule dicts (augmented with _ruleset_name/_ruleset_href).
        ruleset_map:    {ruleset_href -> ruleset_name}
        hit_counts:     {rule_href -> total_connections}
        api_client:     ApiClient instance for label/service resolution.

    Returns:
        dict with keys:
            hit_df       (pd.DataFrame)
            record_count (int)
    """
    rows = []
    for rule in baseline_rules:
        href = rule.get("href", "")
        if href not in hit_counts:
            continue
        rows.append(_build_row(rule, ruleset_map, hit_counts.get(href, 0), api_client))

    rows.sort(key=lambda r: (r.get("Ruleset", ""), r.get("No", 0)))
    rows = rows[:_MAX_ROWS]

    columns = ["Ruleset", "No", "Rule ID", "Type", "Description", "Destination", "Source", "Services", "Hit Count", "Enabled"]
    hit_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    return {"hit_df": hit_df, "record_count": len(rows)}


def _build_row(rule: dict, ruleset_map: dict, hit_count: int, api_client) -> dict:
    rs_href = rule.get("_ruleset_href", "")
    rs_name = ruleset_map.get(rs_href, rule.get("_ruleset_name", rs_href))
    rs_id = rule.get("_ruleset_id", "")
    rule_id = rule.get("_rule_id", "")
    rule_no = rule.get("_rule_no", "")

    providers = _resolve_actors(rule.get("providers", []), api_client)
    consumers = _resolve_actors(rule.get("consumers", []), api_client)
    services  = _resolve_services(rule.get("ingress_services", []), api_client)

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
        "Hit Count":   hit_count,
        "Enabled":     rule.get("enabled", True),
    }


def _resolve_actors(actors: list, api_client) -> str:
    if not actors:
        return "任何"
    if api_client and hasattr(api_client, "resolve_actor_str"):
        try:
            return api_client.resolve_actor_str(actors)
        except Exception:
            pass
    parts = []
    for a in actors:
        if isinstance(a, dict):
            if "actors" in a:
                parts.append(str(a["actors"]))
            elif "label" in a:
                lbl = a["label"]
                parts.append(lbl.get("href", str(lbl)))
            elif "ip_list" in a:
                parts.append(a["ip_list"].get("href", "ip_list"))
            else:
                parts.append(str(a))
        else:
            parts.append(str(a))
    return ", ".join(parts) if parts else "任何"


def _resolve_services(services: list, api_client) -> str:
    if not services:
        return "所有服務"
    if api_client and hasattr(api_client, "resolve_service_str"):
        try:
            return api_client.resolve_service_str(services)
        except Exception:
            pass
    parts = []
    for s in services:
        if isinstance(s, dict):
            if "port" in s:
                proto = {6: "TCP", 17: "UDP"}.get(s.get("proto"), str(s.get("proto", "")))
                parts.append(f"{proto}/{s['port']}")
            elif "href" in s:
                parts.append(s["href"].split("/")[-1])
        else:
            parts.append(str(s))
    return ", ".join(parts) if parts else "所有服務"
