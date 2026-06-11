"""PURE policy resolution core.

Expands one Illumio ACTIVE ruleset into flat src_ip/dst_ip/port/protocol rows
ready for third-party firewall implementation. Zero I/O: it consumes
pre-built lookups (label->IPs, ip_list->CIDRs, label_group->member labels,
workload->IPs, optional service->ports) and returns a list of dict rows.

Resolution per rule:
  consumers -> src IP set, providers -> dst IP set (scope-narrowed), and
  ingress_services -> (port, protocol) set; the cartesian product of those,
  deduplicated, becomes the rows.
"""
from __future__ import annotations

from typing import Any

_ANY = "ANY"


def _proto_name(proto: Any) -> str:
    # Assumes Illumio ingress_services proto is 6 (TCP) or 17 (UDP); anything non-17 maps to TCP.
    return "UDP" if proto == 17 else "TCP"


def _actor_ips(
    actor: dict,
    *,
    label_to_ips: dict[str, list[str]],
    iplist_to_cidrs: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
    workload_to_ips: dict[str, list[str]],
) -> tuple[list[str], str]:
    """Return (ip_values, kind) for one actor; unknown refs -> ([], kind)."""
    if actor.get("actors") == "ams":
        return [_ANY], "any"
    if "label" in actor:
        href = actor["label"].get("href", "")
        return list(label_to_ips.get(href, [])), "label"
    if "label_group" in actor:
        href = actor["label_group"].get("href", "")
        ips: list[str] = []
        for lh in label_group_to_labels.get(href, []):
            ips.extend(label_to_ips.get(lh, []))
        return ips, "label_group"
    if "ip_list" in actor:
        href = actor["ip_list"].get("href", "")
        return list(iplist_to_cidrs.get(href, [])), "ip_list"
    if "workload" in actor:
        href = actor["workload"].get("href", "")
        return list(workload_to_ips.get(href, [])), "workload"
    if "ip_address" in actor:
        val = actor["ip_address"].get("value")
        return ([val], "ip_address") if val else ([], "ip_address")
    return [], "unknown"


def _scope_label_hrefs(scopes: list) -> set[str]:
    """Flatten a ruleset's scopes into the set of label hrefs they require."""
    hrefs: set[str] = set()
    for scope in scopes or []:
        for entry in scope or []:
            if "label" in entry:
                hrefs.add(entry["label"].get("href", ""))
    return hrefs


def _side_ips(
    actors: list[dict],
    lookups: dict[str, Any],
    *,
    scope_hrefs: set[str] | None = None,
) -> tuple[list[str], str]:
    """Resolve a consumer/provider actor list to (deduped IPs, kind).

    Returns ([], kind) when concrete actors exist but all resolve to zero IPs
    (unknown refs, scoped out, etc.) — the caller should then drop the rule.
    Returns ([ANY], "any") only when the actors list is empty.

    When scope_hrefs is given (providers side), scope filtering applies only
    to ``label`` actors whose href is NOT in scope_hrefs (they are skipped).
    ``label_group`` actors are NOT scope-filtered — known limitation.
    Explicit IP sources (ip_list/workload/ip_address) and ANY pass through
    unconditionally.

    Note: for a multi-actor list the returned ``kind`` reflects the LAST
    actor's kind; it is metadata only and does not affect IP correctness.
    """
    if not actors:
        return [_ANY], "any"

    out: list[str] = []
    kind = "any"
    seen: set[str] = set()
    for actor in actors:
        if scope_hrefs:
            lbl = actor.get("label", {}).get("href") if "label" in actor else None
            if lbl is not None and lbl not in scope_hrefs:
                continue
        ips, k = _actor_ips(actor, **lookups)
        kind = k
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                out.append(ip)
    return out, kind


def _services(rule: dict, service_to_ports: dict[str, list[dict]],
              service_to_names: dict[str, str]) -> list[dict]:
    """Resolve ingress_services to a list of {port, port_to?, protocol, name}.

    For named services ({"href": ...}) the human-friendly service name is used
    when available (via service_to_names), falling back to the raw href.
    """
    out: list[dict] = []
    svcs = rule.get("ingress_services") or []
    if not svcs:
        out.append({"port": _ANY, "protocol": _ANY, "name": ""})
        return out
    for s in svcs:
        if "port" in s:
            entry = {"port": s["port"], "protocol": _proto_name(s.get("proto")),
                     "name": ""}
            if s.get("to_port"):
                entry["port_to"] = s["to_port"]
            out.append(entry)
        elif "href" in s:
            href = s["href"]
            svc_name = service_to_names.get(href, href)
            ports = service_to_ports.get(href, [])
            if not ports:
                out.append({"port": _ANY, "protocol": _ANY, "name": svc_name})
            for p in ports:
                entry = {"port": p.get("port", _ANY),
                         "protocol": _proto_name(p.get("proto")), "name": svc_name}
                if p.get("to_port"):
                    entry["port_to"] = p["to_port"]
                out.append(entry)
    return out


def resolve_ruleset(
    ruleset: dict,
    *,
    label_to_ips: dict[str, list[str]],
    iplist_to_cidrs: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
    workload_to_ips: dict[str, list[str]],
    service_to_ports: dict[str, list[dict]] | None = None,
    service_to_names: dict[str, str] | None = None,
) -> list[dict]:
    """Expand a single ruleset's rules into flat src/dst/port/proto rows.

    Disabled rulesets (and disabled rules) are skipped — the report describes
    policy that is actually enforced, so non-enforced entries are excluded.
    """
    # A disabled ruleset is not enforced: nothing to resolve.
    if not ruleset.get("enabled", True):
        return []
    lookups = dict(
        label_to_ips=label_to_ips,
        iplist_to_cidrs=iplist_to_cidrs,
        label_group_to_labels=label_group_to_labels,
        workload_to_ips=workload_to_ips,
    )
    service_to_ports = service_to_ports or {}
    service_to_names = service_to_names or {}
    rs_name = ruleset.get("name", "")
    scope_hrefs = _scope_label_hrefs(ruleset.get("scopes") or [])

    rows: list[dict] = []
    seen: set[tuple] = set()
    for rule in ruleset.get("rules") or []:
        if not rule.get("enabled", True):
            continue
        rule_href = rule.get("href", "")
        srcs, src_kind = _side_ips(rule.get("consumers") or [], lookups)
        dsts, dst_kind = _side_ips(rule.get("providers") or [], lookups,
                                   scope_hrefs=scope_hrefs or None)
        # Drop the rule if either side resolved to zero IPs (unknown refs,
        # scoped out, or empty after scope filtering).
        if not srcs or not dsts:
            continue
        for svc in _services(rule, service_to_ports, service_to_names):
            for s_ip in srcs:
                for d_ip in dsts:
                    key = (rule_href, s_ip, d_ip, svc["port"],
                           svc.get("port_to"), svc["protocol"])
                    if key in seen:
                        continue
                    seen.add(key)
                    row = {
                        "ruleset_name": rs_name,
                        "rule_href": rule_href,
                        "src_ip": s_ip,
                        "dst_ip": d_ip,
                        "port": svc["port"],
                        "protocol": svc["protocol"],
                        "src_kind": src_kind,
                        "dst_kind": dst_kind,
                        "service_name": svc["name"],
                    }
                    if "port_to" in svc:
                        row["port_to"] = svc["port_to"]
                    rows.append(row)
    return rows
