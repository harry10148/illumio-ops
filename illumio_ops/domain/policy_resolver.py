"""Policy resolver core (spec §6.5 policy_resolver, P5c-4), ported from 5.x src/report/analysis/policy_resolver.py
and the lookup builders of src/report/policy_resolver_report.py. Pure: no I/O.

Expands one active ruleset into flat src_ip/dst_ip/port/protocol rows for other tools (e.g. a comparison with
traditional firewall rules): consumers -> source IPs, providers -> destination IPs (narrowed by the ruleset's
scopes), services -> (port, protocol); the deduplicated product becomes the rows. One rule's source x destination is
capped at _MAX_RULE_PAIRS: the larger side becomes a summary token and the row says truncated (never ANY, which would
read wider than it is)."""
from __future__ import annotations

import ipaddress
from typing import Any

_ANY = "ANY"

# 單一 rule 的 src×dst 上限。scoped ruleset 內「ams → ams」是常見寫法，兩側
# 都會展開成 scope 內全部 workload IP：5,000 台就是 2,500 萬列（每列一個
# dict，數 GB 記憶體），足以讓報表行程 OOM。超過上限時把較大的一側收斂成一
# 個摘要 token，並在列上標記 truncated，讓「被收斂」看得出來（不是靜默截斷，
# 也不是用 ANY 假裝成全域——那會比實際更寬）。
_MAX_RULE_PAIRS = 100_000


_PROTO_NAMES = {6: "TCP", 17: "UDP", 1: "ICMP", 58: "ICMPv6", 47: "GRE", 50: "ESP", -1: "ANY"}


def _proto_name(proto: Any) -> str:
    # Illumio ingress_services proto numbers: 6=TCP, 17=UDP, 1=ICMP, 58=ICMPv6,
    # -1/None=ANY. Map known values; fall back to str(proto) for unknowns rather
    # than mislabelling everything non-UDP as TCP.
    if proto is None:
        return "ANY"
    try:
        return _PROTO_NAMES.get(int(proto), str(proto))
    except (TypeError, ValueError):
        return str(proto)


Lookups = dict[str, Any]
_WORKLOAD_KINDS = ("label", "label_group", "workload")  # what a scope narrows; IP lists and literals it does not


def _label_ips(href: str, lk: Lookups) -> set[str]:
    return set(lk["label_to_ips"].get(href, []))


def _group_ips(href: str, lk: Lookups) -> set[str]:
    return {ip for lh in lk["label_group_to_labels"].get(href, []) for ip in lk["label_to_ips"].get(lh, [])}


def _unknown(actor: dict[str, Any], lk: Lookups) -> bool:
    """With `known` (every object the PCE has), a reference it does not hold: the rule cannot be expanded faithfully
    (final review #5). A known object with no members is not unknown."""
    known = lk.get("known")
    if known is None:
        return False
    for kind in ("label", "label_group", "ip_list", "workload"):
        ref = actor.get(kind)
        if isinstance(ref, dict):
            return ref.get("href", "") not in known.get(kind, set())
    return False


def _key(kind: str, href: str, lk: Lookups) -> str:
    """The label dimension (role, env, ...) a label or label group is in; one shared key without label_keys (the
    5.x behaviour, where every label was ORed)."""
    keys = lk.get("label_keys")
    return "" if keys is None else f"{keys.get(href, href)}"


def _actor_ips(actor: dict[str, Any], lk: Lookups) -> tuple[set[str], str]:
    """(addresses, kind) of one actor; an unknown reference gives none."""
    if actor.get("actors") == "ams":  # All Workloads: every workload's address, never ANY (security review)
        return set(_all_workloads(lk["workload_to_ips"])), "all_workloads"
    if "label" in actor:
        return _label_ips(actor["label"].get("href", ""), lk), "label"
    if "label_group" in actor:
        return _group_ips(actor["label_group"].get("href", ""), lk), "label_group"
    if "ip_list" in actor:
        return set(lk["iplist_to_cidrs"].get(actor["ip_list"].get("href", ""), [])), "ip_list"
    if "workload" in actor:
        return set(lk["workload_to_ips"].get(actor["workload"].get("href", ""), [])), "workload"
    if "ip_address" in actor:
        val = actor["ip_address"].get("value")
        return ({val} if val else set()), "ip_address"
    return set(), "unknown"


def _scope_sets(scopes: list[Any], lk: Lookups) -> list[set[str]] | None:
    """Each scope's workload addresses, kept apart (final review #2: one union let an intra-scope rule cross from
    Prod to Dev); None when the ruleset is not scoped. Within a scope, labels of different keys are ANDed, of the
    same key ORed (label groups count as their key); exclusions are subtracted. A scope with only exclusions, or
    labels that resolve to nothing, is empty (fail closed)."""
    out: list[set[str]] = []
    for scope in scopes or []:
        by_key: dict[str, set[str]] = {}
        exc: set[str] = set()
        for entry in scope or []:
            kind = "label" if "label" in entry else "label_group" if "label_group" in entry else None
            if kind is None:
                continue
            href = entry[kind].get("href", "")
            ips = _label_ips(href, lk) if kind == "label" else _group_ips(href, lk)
            if entry.get("exclusion"):
                exc |= ips
            else:
                by_key.setdefault(_key(kind, href, lk) if lk.get("label_keys") is not None else href, set()).update(ips)
        if not by_key and not exc:
            return None  # an "All" scope: not narrowed
        cur = set.intersection(*by_key.values()) if by_key else set()
        out.append(cur - exc)
    return out or None


def _side_ips(actors: list[dict[str, Any]], lk: Lookups, *, scope_ips: set[str] | None = None,
              subnets: bool = False) -> tuple[list[str], str]:
    """A consumer or provider list as addresses. Labels and label groups: different keys ANDed, the same key ORed
    (final review #1); the other actors are added. The scope narrows the workload kinds — labels, label groups, All
    Workloads and explicit workloads (final review #3) — not IP lists or literal addresses. Exclusions are
    subtracted by containment. `subnets`: workload addresses become their interface networks (use_workload_subnets,
    final review #6). An empty list is ANY (5.x)."""
    if not actors:
        return [_ANY], "any"
    excludes: set[str] = set()
    by_key: dict[str, set[str]] = {}
    workload_part: set[str] = set()
    explicit: set[str] = set()
    kind = "any"
    for actor in actors:
        ips, k = _actor_ips(actor, lk)
        if actor.get("exclusion"):
            excludes |= ips
            continue
        kind = k
        if k in ("label", "label_group"):
            href = actor[k].get("href", "")
            group = _key(k, href, lk) if lk.get("label_keys") is not None else ""
            by_key.setdefault(group, set()).update(ips)
        elif k == "all_workloads":  # in a scope: the scope's addresses (5.x); else every workload's
            workload_part |= set(scope_ips) if scope_ips is not None else ips
        elif k == "workload":
            workload_part |= ips
        else:
            explicit |= ips
    if by_key:
        workload_part |= set.intersection(*by_key.values())
    if scope_ips is not None:
        workload_part &= scope_ips
    if subnets:
        to_net = lk.get("ip_to_subnet") or {}
        workload_part = {to_net.get(ip, ip) for ip in workload_part}
    out = _subtract(sorted(workload_part) + sorted(explicit - workload_part), excludes)
    return list(dict.fromkeys(out)), kind


def _services(rule: dict[str, Any], service_to_ports: dict[str, list[dict[str, Any]]],
              service_to_names: dict[str, str]) -> list[dict[str, Any]]:
    """Resolve ingress_services to a list of {port, port_to?, protocol, name}.

    For named services ({"href": ...}) the human-friendly service name is used
    when available (via service_to_names), falling back to the raw href.
    """
    out: list[dict[str, Any]] = []
    # A Deny Rule carries its services in service_ports (lab event 2026-10-27); 5.x read only ingress_services and
    # expanded a Deny Rule to every port.
    svcs = [*(rule.get("ingress_services") or []), *(rule.get("service_ports") or [])]
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
            if not ports:  # unknown, or process-based (windows_services): not a port, never ANY (security review)
                out.append({"port": f"<service without ports: {svc_name}>", "protocol": "", "name": svc_name})
            for p in ports:
                entry = {"port": p.get("port", _ANY),
                         "protocol": _proto_name(p.get("proto")), "name": svc_name}
                if p.get("to_port"):
                    entry["port_to"] = p["to_port"]
                out.append(entry)
        elif "proto" in s:
            # Proto-only inline service (no port): ICMP ({"proto": 1}), ICMPv6,
            # GRE, etc. Represent it instead of silently dropping the rule.
            out.append({"port": _ANY, "protocol": _proto_name(s.get("proto")), "name": ""})
    return out


def _summary_token(n: int) -> str:
    """被收斂那一側的替代值——刻意不是合法 IP，讀者/下游不會誤當成可套用位址。"""
    return f"<{n} hosts: expansion capped>"


def _cap_sides(srcs: list[str], dsts: list[str], services: int = 1) -> tuple[list[str], list[str], str]:
    """(srcs, dsts, truncated); truncated is ""/"src"/"dst"/"src,dst". The cap counts rows: pairs x services
    (security review: 90,000 pairs x 50 services was 4.5 million rows under a 100,000 cap)."""
    per = max(services, 1)
    if len(srcs) * len(dsts) * per <= _MAX_RULE_PAIRS:
        return srcs, dsts, ""
    capped: list[str] = []
    # 先收斂較大的一側；若仍超過上限，兩側都收斂。
    if len(srcs) >= len(dsts):
        srcs, first, other = [_summary_token(len(srcs))], "src", "dst"
    else:
        dsts, first, other = [_summary_token(len(dsts))], "dst", "src"
    capped.append(first)
    if len(srcs) * len(dsts) * per > _MAX_RULE_PAIRS:
        if other == "dst":
            dsts = [_summary_token(len(dsts))]
        else:
            srcs = [_summary_token(len(srcs))]
        capped.append(other)
    return srcs, dsts, ",".join(capped)


def resolve_ruleset(ruleset: dict[str, Any], **lookups: Any) -> list[dict[str, Any]]:
    """Every row of one ruleset (no total limit)."""
    return resolve_ruleset_within(ruleset, limit=None, **lookups)[0]


def resolve_ruleset_within(
    ruleset: dict[str, Any],
    *,
    limit: int | None,
    label_to_ips: dict[str, list[str]],
    iplist_to_cidrs: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
    workload_to_ips: dict[str, list[str]],
    service_to_ports: dict[str, list[dict[str, Any]]] | None = None,
    service_to_names: dict[str, str] | None = None,
    label_keys: dict[str, str] | None = None,
    known: dict[str, set[str]] | None = None,
    ip_to_subnet: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int, list[tuple[str, str]]]:
    """(rows, omitted, not_expanded). At most `limit` rows: a rule that would pass it is counted, never built
    (security review). not_expanded: (rule href, reason) for a rule that cannot be expanded faithfully — a
    reference the PCE does not hold, or providers resolved as virtual services (their services come from the virtual
    service) — disclosed by the caller, never dropped or widened (final review #4, #5). Each scope is expanded on
    its own and the rows merged (final review #2). Disabled rulesets and rules are skipped."""
    omitted = 0
    issues: list[tuple[str, str]] = []
    if not ruleset.get("enabled", True):
        return [], 0, issues
    lk: Lookups = {"label_to_ips": label_to_ips, "iplist_to_cidrs": iplist_to_cidrs,
                   "label_group_to_labels": label_group_to_labels, "workload_to_ips": workload_to_ips,
                   "label_keys": label_keys, "known": known, "ip_to_subnet": ip_to_subnet}
    service_to_ports = service_to_ports or {}
    service_to_names = service_to_names or {}
    rs_name = ruleset.get("name", "")
    scope_sets = _scope_sets(ruleset.get("scopes") or [], lk)
    scope_unknown = any(_unknown(e, lk) for sc in ruleset.get("scopes") or [] for e in sc or [])
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    # deny_rules expand too (a firewall needs the deny rows); action: allow / deny / override_deny.
    for action, rules in (("allow", ruleset.get("rules") or []), (None, ruleset.get("deny_rules") or [])):
        for rule in rules:
            if not rule.get("enabled", True):
                continue
            act = action or ("override_deny" if rule.get("override") else "deny")
            rule_href = rule.get("href", "")
            resolve_as = rule.get("resolve_labels_as") or {}
            if any("virtual_services" in (resolve_as.get(side) or []) for side in ("providers", "consumers")):
                issues.append((rule_href, "virtual_services"))
                continue
            actors = [*(rule.get("consumers") or []), *(rule.get("providers") or [])]
            if scope_unknown or any(_unknown(a, lk) for a in actors):
                issues.append((rule_href, "unknown_reference"))
                continue
            svcs = _services(rule, service_to_ports, service_to_names)
            subnet_sides = set(rule.get("use_workload_subnets") or [])
            for scope_ips in (scope_sets if scope_sets is not None else [None]):
                cons_scope = None if rule.get("unscoped_consumers") else scope_ips
                srcs, src_kind = _side_ips(rule.get("consumers") or [], lk, scope_ips=cons_scope,
                                           subnets="consumers" in subnet_sides)
                dsts, dst_kind = _side_ips(rule.get("providers") or [], lk, scope_ips=scope_ips,
                                           subnets="providers" in subnet_sides)
                if not srcs or not dsts:  # nothing in this scope (or a side resolves to no address)
                    continue
                srcs, dsts, truncated = _cap_sides(srcs, dsts, len(svcs))
                if limit is not None and len(rows) + len(srcs) * len(dsts) * len(svcs) > limit:
                    omitted += len(srcs) * len(dsts) * len(svcs)  # counted, never built (security review)
                    continue
                for svc in svcs:
                    for s_ip in srcs:
                        for d_ip in dsts:
                            key = (rule_href, act, s_ip, d_ip, svc["port"], svc.get("port_to"), svc["protocol"])
                            if key in seen:
                                continue
                            seen.add(key)
                            row = {"ruleset_name": rs_name, "rule_href": rule_href, "action": act, "src_ip": s_ip,
                                   "dst_ip": d_ip, "port": svc["port"], "protocol": svc["protocol"],
                                   "src_kind": src_kind, "dst_kind": dst_kind, "service_name": svc["name"]}
                            if "port_to" in svc:
                                row["port_to"] = svc["port_to"]
                            if truncated:
                                row["truncated"] = truncated
                            rows.append(row)
    return rows, omitted, issues


def _all_workloads(workload_to_ips: dict[str, list[str]]) -> list[str]:
    return sorted({ip for ips in workload_to_ips.values() for ip in ips})


def _network(value: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network] | None:
    """An address, CIDR or a-b range as networks; None for what is not one (ANY, an FQDN, a summary token)."""
    try:
        if "-" in value:
            a, b = (ipaddress.ip_address(x.strip()) for x in value.split("-", 1))
            return list(ipaddress.summarize_address_range(a, b))
        return [ipaddress.ip_network(value, strict=False)]
    except (ValueError, TypeError):
        return None


def _minus(nets: list[Any], excluded: list[Any]) -> list[Any]:
    for ex in excluded:
        nxt: list[Any] = []
        for n in nets:
            if n.version != ex.version or not n.overlaps(ex):
                nxt.append(n)
            elif not ex.supernet_of(n):  # n contains part of ex: keep the rest
                nxt.extend(n.address_exclude(ex))
        nets = nxt
    return nets


def _subtract(values: list[str], excludes: set[str]) -> list[str]:
    """values minus the excluded addresses, by containment, not by string (security review): an excluded CIDR
    removes the hosts and the part of a wider network it covers. What is not an address (an FQDN) is removed only
    by an identical exclusion. Single hosts are set lookups; network arithmetic only where a side is wider than one
    host (security review: 5,000 x 5,000 hosts took 28 s)."""
    if not excludes:
        return values
    hosts: set[Any] = set()
    wide: list[Any] = []
    for e in excludes:
        for n in _network(e) or []:
            (hosts.add(n.network_address) if n.num_addresses == 1 else wide.append(n))
    if not hosts and not wide:
        return [v for v in values if v not in excludes]
    out: list[str] = []
    for v in values:
        if v in excludes:
            continue
        nets = _network(v)
        if nets is None:
            out.append(v)
        elif len(nets) == 1 and nets[0].num_addresses == 1:
            addr = nets[0].network_address
            if addr not in hosts and not any(addr in w for w in wide):
                out.append(v)
        else:
            inside = [ipaddress.ip_network(h) for h in hosts if any(h in n for n in nets)]
            rest = _minus(nets, [*wide, *inside])
            if rest == nets:
                out.append(v)
            else:
                out.extend(str(n.network_address) if n.num_addresses == 1 else str(n) for n in rest)
    return out


def _ip_list_values(ranges: list[dict[str, Any]]) -> list[str]:
    """An IP list's ranges with its exclusion ranges taken out (security review: 5.x listed an excluded range as
    included)."""
    def text(r: dict[str, Any]) -> str | None:
        frm, to = r.get("from_ip"), r.get("to_ip")
        return f"{frm}-{to}" if frm and to else (str(frm) if frm else None)
    inc = [t for r in ranges if not r.get("exclusion") and (t := text(r))]
    exc = {t for r in ranges if r.get("exclusion") and (t := text(r))}
    return _subtract(inc, exc)


def _workload_ips(wl: dict[str, Any]) -> list[str]:
    """A workload's interface addresses; an unmanaged one often has only public_ip."""
    ips = [i["address"] for i in (wl.get("interfaces") or []) if i.get("address")]
    if not ips and wl.get("public_ip"):
        ips = [str(wl["public_ip"])]
    return ips


def build_workload_to_ips(workloads: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for wl in workloads:
        href = wl.get("href")
        if not href:
            continue
        ips = _workload_ips(wl)
        if ips:
            out[href] = ips
    return out


def build_label_to_ips(workloads: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Single O(N) pass: attribute each workload's IPs to each of its labels."""
    out: dict[str, list[str]] = {}
    seen_per_label: dict[str, set[str]] = {}
    for wl in workloads:
        ips = _workload_ips(wl)
        if not ips:
            continue
        for lbl in wl.get("labels") or []:
            href = lbl.get("href")
            if not href:
                continue
            bucket = out.setdefault(href, [])
            seen = seen_per_label.setdefault(href, set())
            for ip in ips:
                if ip not in seen:
                    seen.add(ip)
                    bucket.append(ip)
    return out


def build_iplist_to_cidrs(ip_lists: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ipl in ip_lists:
        href = ipl.get("href")
        if not href:
            continue
        vals = _ip_list_values(ipl.get("ip_ranges") or [])
        for f in ipl.get("fqdns") or []:
            fq = f.get("fqdn")
            if fq:
                vals.append(fq)
        if vals:
            out[href] = vals
    return out


def build_label_group_to_labels(groups: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Recursively flatten each group to its full set of member label hrefs."""
    by_href: dict[str, dict[str, Any]] = {str(g["href"]): g for g in groups if g.get("href")}

    def expand(href: str, seen: set[str]) -> list[str]:
        if href in seen:
            return []
        seen.add(href)
        g = by_href.get(href, {})
        labels = [l.get("href") for l in (g.get("labels") or []) if l.get("href")]
        for sg in g.get("sub_groups") or []:
            sgh = sg.get("href")
            if sgh:
                labels.extend(expand(sgh, seen))
        # de-dup preserving order
        out, s = [], set()
        for lh in labels:
            if lh not in s:
                s.add(lh)
                out.append(lh)
        return out

    return {h: expand(h, set()) for h in by_href}


def build_service_to_ports(services: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for s in services:
        href = s.get("href")
        if href:
            out[href] = s.get("service_ports") or []
    return out


def build_service_to_names(services: list[dict[str, Any]]) -> dict[str, str]:
    """Map service href -> human-friendly name (e.g. 'HTTPS') for labelling."""
    out: dict[str, str] = {}
    for s in services:
        href, name = s.get("href"), s.get("name")
        if href and name:
            out[href] = name
    return out


def build_label_keys(labels: list[dict[str, Any]], groups: list[dict[str, Any]]) -> dict[str, str]:
    """Label and label group href -> its key (role, app, env, loc, ...): the dimension rules AND across."""
    return {str(x["href"]): str(x.get("key") or "") for x in [*labels, *groups] if x.get("href")}


def build_ip_to_subnet(workloads: list[dict[str, Any]]) -> dict[str, str]:
    """Interface address -> its network (address/cidr_block), for rules with use_workload_subnets."""
    out: dict[str, str] = {}
    for wl in workloads:
        for i in wl.get("interfaces") or []:
            if i.get("address") and i.get("cidr_block") is not None:
                try:
                    out[i["address"]] = str(ipaddress.ip_network(f"{i['address']}/{i['cidr_block']}", strict=False))
                except ValueError:
                    continue
    return out

