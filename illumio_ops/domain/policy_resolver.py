"""Policy resolver core (spec §6.5 policy_resolver, P5c-4), ported from 5.x src/report/analysis/policy_resolver.py
and the lookup builders of src/report/policy_resolver_report.py. Pure: no I/O.

Expands one active ruleset into flat src_ip/dst_ip/port/protocol rows for other tools (e.g. a comparison with
traditional firewall rules): consumers -> source IPs, providers -> destination IPs (narrowed by the ruleset's
scopes), services -> (port, protocol); the deduplicated product becomes the rows. One rule's source x destination is
capped at _MAX_RULE_PAIRS: the larger side becomes a summary token and the row says truncated (never ANY, which would
read wider than it is)."""
from __future__ import annotations

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


def _actor_ips(
    actor: dict[str, Any],
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
    scopes: list[Any],
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
    actors: list[dict[str, Any]],
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

    # 真 PCE 形狀：entry 可帶 exclusion: true（「A 排除 B」）。先收集排除集，
    # include 結果最後扣除；排除 actor 不受 scope 交集影響（先取全集再扣）。
    excludes: set[str] = set()
    has_exclusion = False
    for actor in actors:
        if actor.get("exclusion"):
            has_exclusion = True
            ips, _k = _actor_ips(actor, **lookups)
            excludes.update(ips)

    out: list[str] = []
    kind = "any"
    seen: set[str] = set()
    for actor in actors:
        if actor.get("exclusion"):
            continue
        if actor.get("actors") == "ams":
            if scope_ips is not None:
                ips, k = sorted(scope_ips), "any"
            elif has_exclusion:
                # ANY 無法表達「全部除了 X」：以 managed workload 全集展開
                # 後扣除（寧窄勿寬；fail-closed）。
                universe: set[str] = set()
                for wl_ips in lookups["workload_to_ips"].values():
                    universe.update(wl_ips)
                ips, k = sorted(universe), "any"
            else:
                ips, k = [_ANY], "any"
        else:
            ips, k = _actor_ips(actor, **lookups)
            if scope_ips is not None and ("label" in actor or "label_group" in actor):
                ips = [ip for ip in ips if ip in scope_ips]
        kind = k
        for ip in ips:
            if ip not in seen and ip not in excludes:
                seen.add(ip)
                out.append(ip)
    return out, kind


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
            if not ports:
                out.append({"port": _ANY, "protocol": _ANY, "name": svc_name})
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


def _cap_sides(srcs: list[str], dsts: list[str]) -> tuple[list[str], list[str], str]:
    """回傳 (srcs, dsts, truncated)；truncated 為 ""/"src"/"dst"/"src,dst"。"""
    if len(srcs) * len(dsts) <= _MAX_RULE_PAIRS:
        return srcs, dsts, ""
    capped: list[str] = []
    # 先收斂較大的一側；若仍超過上限，兩側都收斂。
    if len(srcs) >= len(dsts):
        srcs, first, other = [_summary_token(len(srcs))], "src", "dst"
    else:
        dsts, first, other = [_summary_token(len(dsts))], "dst", "src"
    capped.append(first)
    if len(srcs) * len(dsts) > _MAX_RULE_PAIRS:
        if other == "dst":
            dsts = [_summary_token(len(dsts))]
        else:
            srcs = [_summary_token(len(srcs))]
        capped.append(other)
    return srcs, dsts, ",".join(capped)


def resolve_ruleset(
    ruleset: dict[str, Any],
    *,
    label_to_ips: dict[str, list[str]],
    iplist_to_cidrs: dict[str, list[str]],
    label_group_to_labels: dict[str, list[str]],
    workload_to_ips: dict[str, list[str]],
    service_to_ports: dict[str, list[dict[str, Any]]] | None = None,
    service_to_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Expand a single ruleset's rules into flat src/dst/port/proto rows.

    Disabled rulesets (and disabled rules) are skipped — the report describes
    policy that is actually enforced, so non-enforced entries are excluded.
    """
    # A disabled ruleset is not enforced: nothing to resolve.
    if not ruleset.get("enabled", True):
        return []
    lookups = {
        "label_to_ips": label_to_ips,
        "iplist_to_cidrs": iplist_to_cidrs,
        "label_group_to_labels": label_group_to_labels,
        "workload_to_ips": workload_to_ips,
    }
    service_to_ports = service_to_ports or {}
    service_to_names = service_to_names or {}
    rs_name = ruleset.get("name", "")
    scope_ips = _scope_ip_set(ruleset.get("scopes") or [],
                              label_to_ips=label_to_ips,
                              label_group_to_labels=label_group_to_labels)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
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
            srcs, dsts, truncated = _cap_sides(srcs, dsts)
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
                        if truncated:
                            row["truncated"] = truncated
                        rows.append(row)
    return rows


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
        vals: list[str] = []
        for r in ipl.get("ip_ranges") or []:
            frm, to = r.get("from_ip"), r.get("to_ip")
            if frm and to:
                vals.append(f"{frm}-{to}")
            elif frm:
                vals.append(frm)
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
