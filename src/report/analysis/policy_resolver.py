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


def _scope_ip_set(
    scopes: list,
    *,
    label_to_ips: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
) -> set[str] | None:
    """Ruleset scopes → 允許的 workload IP 集合；None＝不設限。

    Illumio scope 語意：同一 scope 內的 entries 取 AND（workload 必須同時帶有
    全部 scope label → IP 交集）；多個 scope 取 OR（聯集）。label_group entry
    以成員 label 的 IP 聯集視為單一 entry。帶 ``exclusion: true`` 的 entry 於
    該 scope 交集後扣除。空 scopes 或「All」scope（無任何 label entry）→ None。

    限制：只有 exclusion entry 而無 include entry 的 scope 無法從 lookups 推得
    全集，保守解析為空集合（fail-closed）。
    """
    constrained = False
    union: set[str] = set()
    for scope in scopes or []:
        inc_sets: list[set[str]] = []
        exc: set[str] = set()
        for entry in scope or []:
            if "label" in entry:
                ips = set(label_to_ips.get(entry["label"].get("href", ""), []))
            elif "label_group" in entry:
                ips = set()
                for lh in label_group_to_labels.get(entry["label_group"].get("href", ""), []):
                    ips.update(label_to_ips.get(lh, []))
            else:
                continue
            if entry.get("exclusion"):
                exc.update(ips)
            else:
                inc_sets.append(ips)
        if not inc_sets and not exc:
            continue  # 「All」scope：不設限
        constrained = True
        cur = set.intersection(*inc_sets) if inc_sets else set()
        union.update(cur - exc)
    return union if constrained else None


def _side_ips(
    actors: list[dict],
    lookups: dict[str, Any],
    *,
    scope_ips: set[str] | None = None,
) -> tuple[list[str], str]:
    """Resolve a consumer/provider actor list to (deduped IPs, kind).

    Returns ([], kind) when concrete actors exist but all resolve to zero IPs
    (unknown refs, scoped out, etc.) — the caller should then drop the rule.
    Returns ([ANY], "any") only when the actors list is empty.

    scope_ips 語意（2026-07-13 修正：舊實作以「actor 的 label href 是否在
    scope label 清單內」過濾——role-type actor 幾乎不會是 scope label，帶
    scope 的 ruleset 因此恆解析為 0 列）：
    - None → 不設限；
    - set → label / label_group actor 的 IP 與 scope IP 取**交集**；``ams``
      （All Workloads）展開為 scope IP 全集（排序後，輸出確定性）；明確 IP
      來源（ip_list / workload / ip_address）不受 scope 過濾，原樣通過。

    Note: for a multi-actor list the returned ``kind`` reflects the LAST
    actor's kind; it is metadata only and does not affect IP correctness.
    """
    if not actors:
        return [_ANY], "any"

    out: list[str] = []
    kind = "any"
    seen: set[str] = set()
    for actor in actors:
        if actor.get("actors") == "ams" and scope_ips is not None:
            ips, k = sorted(scope_ips), "any"
        else:
            ips, k = _actor_ips(actor, **lookups)
            if scope_ips is not None and ("label" in actor or "label_group" in actor):
                ips = [ip for ip in ips if ip in scope_ips]
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
    scope_ips = _scope_ip_set(ruleset.get("scopes") or [],
                              label_to_ips=label_to_ips,
                              label_group_to_labels=label_group_to_labels)

    rows: list[dict] = []
    seen: set[tuple] = set()
    # deny_rules 也展開（第三方防火牆實作需要 deny 列；2026-07-13 前只讀
    # rules，deny-only ruleset 恆為 0 列）。action：allow / deny / override_deny。
    rule_groups = (
        ("allow", ruleset.get("rules") or []),
        (None, ruleset.get("deny_rules") or []),
    )
    for action, rules in rule_groups:
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            act = action or ("override_deny" if rule.get("override") else "deny")
            rule_href = rule.get("href", "")
            # consumers 同受 scope 約束（intra-scope ruleset 雙側都在 scope 內）；
            # unscoped_consumers=true 時 consumers 恢復全域。
            cons_scope = None if rule.get("unscoped_consumers") else scope_ips
            srcs, src_kind = _side_ips(rule.get("consumers") or [], lookups,
                                       scope_ips=cons_scope)
            dsts, dst_kind = _side_ips(rule.get("providers") or [], lookups,
                                       scope_ips=scope_ips)
            # Drop the rule if either side resolved to zero IPs (unknown refs,
            # scoped out, or empty after scope filtering).
            if not srcs or not dsts:
                continue
            for svc in _services(rule, service_to_ports, service_to_names):
                for s_ip in srcs:
                    for d_ip in dsts:
                        key = (rule_href, act, s_ip, d_ip, svc["port"],
                               svc.get("port_to"), svc["protocol"])
                        if key in seen:
                            continue
                        seen.add(key)
                        row = {
                            "ruleset_name": rs_name,
                            "rule_href": rule_href,
                            "action": act,
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
