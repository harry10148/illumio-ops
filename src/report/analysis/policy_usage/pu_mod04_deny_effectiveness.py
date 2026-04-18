"""
pu_mod04_deny_effectiveness.py
Deny rule effectiveness analysis for the Policy Usage report.

Analyses:
  - Deny vs Allow rule ratio
  - Hit vs unused deny rules (are deny rules actually blocking traffic?)
  - Deny rules by scope (narrow vs broad)
  - Override Deny rules and their risk profile
  - Deny rules targeting high-risk ports
"""
from loguru import logger
import pandas as pd

_HIGH_RISK_PORTS = frozenset({
    22, 23, 135, 139, 445, 1433, 1521, 3306, 3389,
    5432, 5900, 5985, 5986, 8080, 8443,
})

def pu_deny_effectiveness(
    baseline_rules: list,
    hit_counts: dict,
    ruleset_map: dict,
) -> dict:
    """Analyze deny rule coverage and effectiveness.

    Args:
        baseline_rules: Flat list of all rule dicts (Allow + Deny).
        hit_counts: {rule_href: flow_count} for rules that matched traffic.
        ruleset_map: {ruleset_href: ruleset_name}.

    Returns:
        dict with deny analysis DataFrames and scalar KPIs.
    """
    deny_rules = [r for r in baseline_rules if r.get("_rule_type", "Allow") in ("Deny", "Override Deny")]
    allow_rules = [r for r in baseline_rules if r.get("_rule_type", "Allow") == "Allow"]

    total_rules = len(baseline_rules)
    total_deny = len(deny_rules)
    total_allow = len(allow_rules)
    deny_ratio_pct = round(total_deny / total_rules * 100, 1) if total_rules > 0 else 0.0

    # Hit vs unused deny rules
    deny_hit = [r for r in deny_rules if r.get("href", "") in hit_counts]
    deny_unused = [r for r in deny_rules if r.get("href", "") not in hit_counts]
    deny_hit_rate = round(len(deny_hit) / total_deny * 100, 1) if total_deny > 0 else 0.0

    # Override deny rules (highest priority — risky if too many)
    override_deny = [r for r in deny_rules if r.get("_rule_type") == "Override Deny"]

    # Build deny rule detail table
    deny_rows = []
    for rule in deny_rules:
        href = rule.get("href", "")
        rs_href = rule.get("_ruleset_href", "")
        rs_name = ruleset_map.get(rs_href, rule.get("_ruleset_name", rs_href))
        flows = int(hit_counts.get(href, 0) or 0)

        # Scope analysis: count how broad the rule is
        providers = rule.get("providers", [])
        consumers = rule.get("consumers", [])
        services = rule.get("ingress_services", [])
        scope = _classify_scope(providers, consumers, services)

        # High-risk port check
        targets_high_risk = _targets_high_risk_ports(services)

        deny_rows.append({
            "Ruleset": f"{rs_name}" if rs_name else rs_href,
            "Rule No": rule.get("_rule_no", ""),
            "Type": rule.get("_rule_type", "Deny"),
            "Description": rule.get("description", "") or "No description",
            "Scope": scope,
            "Blocked Flows": flows,
            "Status": "Hit" if flows > 0 else "Unused",
            "Targets High-Risk Ports": targets_high_risk,
            "Source": rule.get("_csv_consumers", "") or _summarize_actors(consumers),
            "Destination": rule.get("_csv_providers", "") or _summarize_actors(providers),
            "Services": rule.get("_csv_services", "") or _summarize_services(services),
        })

    deny_rows.sort(key=lambda r: (-r["Blocked Flows"], r["Ruleset"]))
    deny_df = pd.DataFrame(deny_rows) if deny_rows else pd.DataFrame()

    # Summary by status
    summary_rows = [
        {"Category": "Deny Rules (Hit)", "Count": len(deny_hit), "Pct": f"{deny_hit_rate}%"},
        {"Category": "Deny Rules (Unused)", "Count": len(deny_unused), "Pct": f"{round(100 - deny_hit_rate, 1)}%" if total_deny > 0 else "0%"},
        {"Category": "Override Deny", "Count": len(override_deny), "Pct": f"{round(len(override_deny) / total_deny * 100, 1)}%" if total_deny > 0 else "0%"},
    ]
    summary_df = pd.DataFrame(summary_rows)

    return {
        "total_deny": total_deny,
        "total_allow": total_allow,
        "deny_ratio_pct": deny_ratio_pct,
        "deny_hit_count": len(deny_hit),
        "deny_unused_count": len(deny_unused),
        "deny_hit_rate_pct": deny_hit_rate,
        "override_deny_count": len(override_deny),
        "deny_detail_df": deny_df,
        "deny_summary_df": summary_df,
    }

def _classify_scope(providers: list, consumers: list, services: list) -> str:
    """Classify rule scope as Narrow, Medium, or Broad."""
    any_providers = _is_any(providers)
    any_consumers = _is_any(consumers)
    any_services = not services

    broad_count = sum([any_providers, any_consumers, any_services])
    if broad_count >= 2:
        return "Broad"
    if broad_count == 1:
        return "Medium"
    return "Narrow"

def _is_any(actors: list) -> bool:
    """Check if actor list effectively means 'Any'."""
    if not actors:
        return True
    for a in actors:
        if isinstance(a, dict) and a.get("actors") == "ams":
            return True
    return False

def _targets_high_risk_ports(services: list) -> bool:
    """Check if the rule's services include known high-risk ports."""
    if not services:
        return False
    for svc in services:
        if isinstance(svc, dict):
            port = svc.get("port")
            if port is not None and int(port) in _HIGH_RISK_PORTS:
                return True
    return False

def _summarize_actors(actors: list) -> str:
    if not actors:
        return "Any"
    parts = []
    for a in actors:
        if not isinstance(a, dict):
            parts.append(str(a))
        elif "actors" in a:
            parts.append(str(a["actors"]))
        elif "label" in a:
            parts.append(a["label"].get("value", a["label"].get("href", "label")))
        else:
            parts.append(str(a))
    return ", ".join(parts[:5]) if parts else "Any"

def _summarize_services(services: list) -> str:
    if not services:
        return "All Services"
    parts = []
    for svc in services:
        if isinstance(svc, dict) and "port" in svc:
            proto = {6: "TCP", 17: "UDP", 1: "ICMP"}.get(svc.get("proto"), str(svc.get("proto", "")))
            parts.append(f"{proto}/{svc['port']}")
        elif isinstance(svc, dict) and "href" in svc:
            parts.append(svc["href"].split("/")[-1])
    return ", ".join(parts[:5]) if parts else "All Services"
