"""Policy resolver (spec §6.5 policy_resolver, P5c-4): the active policy read live from the PCE and expanded to
IP-level rows (domain/policy_resolver). Every workload is read, unmanaged included: label rules apply to them too.

Beyond MAX_TOTAL_ROWS a ruleset's remaining rows are dropped and a notice row says how many (5.x): it is deliberately
not an IP or port, so a tool importing the rows cannot apply it, and a reader cannot miss it. A failed read raises."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from illumio_ops.domain.policy_resolver import (
    build_ip_to_subnet,
    build_iplist_to_cidrs,
    build_label_group_to_labels,
    build_label_keys,
    build_label_to_ips,
    build_service_to_names,
    build_service_to_ports,
    build_workload_to_ips,
    resolve_ruleset_within,
)
from illumio_ops.pce.collections import get_all
from illumio_ops.pce.policy import fetch_objects, fetch_rule_sets
from illumio_ops.services.context import AppContext

DEADLINE_SECONDS = 900
MAX_TOTAL_ROWS = 500_000
COLUMNS = ("ruleset_name", "rule_href", "action", "src_ip", "dst_ip", "port", "port_to", "protocol", "src_kind",
           "dst_kind", "service_name", "truncated")


class Resolved(BaseModel):
    rows: list[dict[str, Any]]
    per_ruleset: dict[str, int]  # rows kept per ruleset
    rule_count: int  # enabled rules in enabled rulesets
    rules_capped: int  # rules whose source x destination was summarized
    truncated_rulesets: list[str]
    rows_omitted: int
    not_expanded: list[tuple[str, str, str]]  # (ruleset, rule href, reason): disclosed, never dropped or widened
    computed_at: datetime


def _notice(ruleset: str, omitted: int) -> dict[str, Any]:
    token = f"<report row cap {MAX_TOTAL_ROWS} reached: about {omitted} rows omitted>"
    return {"ruleset_name": ruleset, "rule_href": "", "action": "", "src_ip": token, "dst_ip": token, "port": "",
            "protocol": "", "src_kind": "", "dst_kind": "", "service_name": "", "truncated": "total_row_cap"}


def _not_expanded(ruleset: str, rule: str, reason: str) -> dict[str, Any]:
    token = f"<rule not expanded: {reason}>"
    return {"ruleset_name": ruleset, "rule_href": rule, "action": "", "src_ip": token, "dst_ip": token, "port": "",
            "protocol": "", "src_kind": "", "dst_kind": "", "service_name": "", "truncated": "not_expanded"}


def resolve(ctx: AppContext, *, now: datetime | None = None) -> Resolved:
    at = (now or datetime.now(UTC)).astimezone(UTC)
    deadline = time.monotonic() + DEADLINE_SECONDS
    with ctx.pce_client(ctx.settings.current().pce) as client:
        rule_sets = fetch_rule_sets(client, "active", deadline=deadline)
        workloads = get_all(client, "/workloads", params={}, deadline=deadline)
        labels = get_all(client, "/labels", params={}, deadline=deadline)
        ip_lists = fetch_objects(client, "active", "ip_lists", deadline=deadline)
        groups = fetch_objects(client, "active", "label_groups", deadline=deadline)
        services = fetch_objects(client, "active", "services", deadline=deadline)
    lookups: dict[str, Any] = {
        "label_to_ips": build_label_to_ips(workloads), "iplist_to_cidrs": build_iplist_to_cidrs(ip_lists),
        "label_group_to_labels": build_label_group_to_labels(groups), "workload_to_ips": build_workload_to_ips(workloads),
        "service_to_ports": build_service_to_ports(services), "service_to_names": build_service_to_names(services),
        # Every object the PCE holds: a reference to anything else cannot be expanded faithfully (final review #5).
        "label_keys": build_label_keys(labels, groups), "ip_to_subnet": build_ip_to_subnet(workloads),
        "known": {"label": {str(x["href"]) for x in labels if x.get("href")},
                  "label_group": {str(x["href"]) for x in groups if x.get("href")},
                  "ip_list": {str(x["href"]) for x in ip_lists if x.get("href")},
                  "workload": {str(x["href"]) for x in workloads if x.get("href")}}}
    rows: list[dict[str, Any]] = []
    per: dict[str, int] = {}
    truncated: list[str] = []
    omitted = 0
    rule_count = 0
    capped: set[str] = set()
    not_expanded: list[tuple[str, str, str]] = []
    for rs in rule_sets:
        name = str(rs.get("name") or rs.get("href") or "ruleset")
        if rs.get("enabled", True):
            rule_count += sum(1 for r in [*(rs.get("rules") or []), *(rs.get("deny_rules") or [])]
                              if isinstance(r, dict) and r.get("enabled", True))
        kept, left_out, issues = resolve_ruleset_within(rs, limit=max(MAX_TOTAL_ROWS - sum(per.values()), 0),
                                                        **lookups)
        capped.update(r["rule_href"] for r in kept if r.get("truncated"))
        per[name] = per.get(name, 0) + len(kept)
        rows.extend(kept)
        for rule, reason in issues:
            not_expanded.append((name, rule, reason))
            rows.append(_not_expanded(name, rule, reason))
        if left_out:
            omitted += left_out
            truncated.append(name)
            rows.append(_notice(name, left_out))
    return Resolved(rows=rows, per_ruleset=per, rule_count=rule_count, rules_capped=len(capped),
                    truncated_rulesets=truncated, rows_omitted=omitted, not_expanded=not_expanded, computed_at=at)
