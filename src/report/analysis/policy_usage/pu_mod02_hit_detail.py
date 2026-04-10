"""
Detail tables for policy rules that were hit by traffic.
"""
import logging
import pandas as pd

logger = logging.getLogger(__name__)

_MAX_ROWS = 500


def pu_hit_detail(
    baseline_rules: list,
    ruleset_map: dict,
    hit_counts: dict,
    execution_stats: dict | None = None,
    api_client=None,
) -> dict:
    """Build hit-rule detail and top hit port distribution tables."""
    execution_stats = execution_stats or {}
    port_details = {
        str(item.get("rule_href", "")): item
        for item in execution_stats.get("hit_rule_port_details", []) or []
        if item.get("rule_href")
    }

    rows = []
    for rule in baseline_rules:
        href = rule.get("href", "")
        if href not in hit_counts:
            continue
        rows.append(
            _build_row(
                rule,
                ruleset_map,
                int(hit_counts.get(href, 0) or 0),
                port_details.get(href, {}),
                api_client,
            )
        )

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
        "Hit Count",
        "Top Hit Ports",
        "Enabled",
    ]
    hit_df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)

    top_ports = execution_stats.get("top_hit_ports", []) or []
    top_port_rows = [
        {
            "Port / Proto": item.get("port_proto", ""),
            "Flow Count": int(item.get("flow_count", 0) or 0),
        }
        for item in top_ports
    ]
    top_ports_df = pd.DataFrame(top_port_rows, columns=["Port / Proto", "Flow Count"])

    return {
        "hit_df": hit_df,
        "record_count": len(rows),
        "top_ports_df": top_ports_df,
    }


def _build_row(rule: dict, ruleset_map: dict, hit_count: int, port_detail: dict, api_client) -> dict:
    rs_href = rule.get("_ruleset_href", "")
    rs_name = ruleset_map.get(rs_href, rule.get("_ruleset_name", rs_href))
    rs_id = rule.get("_ruleset_id", "")
    rule_id = rule.get("_rule_id", "")
    rule_no = rule.get("_rule_no", "")

    providers = _resolve_actors(rule.get("providers", []), api_client)
    consumers = _resolve_actors(rule.get("consumers", []), api_client)
    services = _resolve_services(rule.get("ingress_services", []), api_client)

    desc = rule.get("description", "") or "No description"
    ruleset_label = f"{rs_name} ({rs_id})" if rs_id else rs_name
    top_hit_ports = str(port_detail.get("top_hit_ports", "") or "").strip()
    if not top_hit_ports:
        top_hit_ports = str(rule.get("_csv_flows_by_port", "") or "").strip() or "No dominant port"

    return {
        "No": rule_no,
        "Rule ID": rule_id,
        "Type": rule.get("_rule_type", "Allow"),
        "Description": desc,
        "Ruleset": ruleset_label,
        "Destination": providers,
        "Source": consumers,
        "Services": services,
        "Hit Count": hit_count,
        "Top Hit Ports": top_hit_ports,
        "Enabled": rule.get("enabled", True),
    }


def _resolve_actors(actors: list, api_client) -> str:
    if not actors:
        return "Any"
    if api_client and hasattr(api_client, "resolve_actor_str"):
        try:
            return api_client.resolve_actor_str(actors)
        except Exception:
            logger.debug("resolve_actor_str failed", exc_info=True)
    parts = []
    for actor in actors:
        if not isinstance(actor, dict):
            parts.append(str(actor))
            continue
        if "actors" in actor:
            parts.append(str(actor["actors"]))
        elif "label" in actor:
            parts.append(actor["label"].get("href", "label"))
        elif "label_group" in actor:
            parts.append(actor["label_group"].get("href", "label_group"))
        elif "ip_list" in actor:
            parts.append(actor["ip_list"].get("href", "ip_list"))
        elif "workload" in actor:
            parts.append(actor["workload"].get("href", "workload"))
        else:
            parts.append(str(actor))
    return ", ".join(parts) if parts else "Any"


def _resolve_services(services: list, api_client) -> str:
    if not services:
        return "All Services"
    if api_client and hasattr(api_client, "resolve_service_str"):
        try:
            return api_client.resolve_service_str(services)
        except Exception:
            logger.debug("resolve_service_str failed", exc_info=True)
    parts = []
    for service in services:
        if not isinstance(service, dict):
            parts.append(str(service))
            continue
        if "port" in service:
            proto = {6: "TCP", 17: "UDP", 1: "ICMP"}.get(service.get("proto"), str(service.get("proto", "")))
            suffix = f"-{service['to_port']}" if service.get("to_port") else ""
            parts.append(f"{proto}/{service['port']}{suffix}")
        elif "href" in service:
            parts.append(service["href"].split("/")[-1])
    return ", ".join(parts) if parts else "All Services"
