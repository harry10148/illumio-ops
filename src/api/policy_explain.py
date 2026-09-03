"""Which PCE rules cover a flow? — the "看規則" hop of the v3 investigate hub.

Given a flow (src, dst, port, proto) this resolves both ends to PCE actors
and asks the PCE Rule Search API (Public Experimental) which allow / deny /
override-deny rules match. Contract facts were measured on LAB-PCE 25.2
(tools/probe_rule_search.py, 2026-09-03), not taken from docs:

  * `consumers` is the flow's SOURCE side, `providers` its DESTINATION.
  * Actor kinds accepted: label, workload, ip_list, kubernetes_workload
    (container_workload is in the schema; not exercised in the lab).
  * Omitting a side widens it to "any" — so we only ever send resolved sides
    and refuse to search when neither resolves.
  * active / draft are independent views.

Resolution order per side: an href from the flow row wins (the traffic row
already carries `source.href` / `destination.href`); otherwise the IP is
matched against managed workload interfaces, then against ip_list ranges.
Kubernetes / container workloads never come back from /workloads, so an
IP-only K8s endpoint stays unresolved (follow-up, see plan 3A Task 5).
"""
from __future__ import annotations

import datetime
import ipaddress
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

from loguru import logger

PROTO_BY_NAME = {"TCP": 6, "UDP": 17, "ICMP": 1, "ICMPV6": 58, "GRE": 47}
RULE_TYPES = ["sec_rules", "deny_rules", "override_deny_rules"]
BASIS_VALUES = ("active", "draft")

_ACTOR_KINDS = ("workload", "kubernetes_workload", "container_workload", "ip_list")
_RESULT_TTL_SECONDS = 60
_RESULT_CACHE_MAX = 256
_result_cache: dict[tuple, tuple[float, dict]] = {}
_result_lock = threading.Lock()


@dataclass
class Actor:
    href: Optional[str]
    kind: str          # workload | kubernetes_workload | container_workload | ip_list | unresolved
    ip: Optional[str]

    def to_search(self) -> Optional[dict]:
        if self.href is None or self.kind == "unresolved":
            return None
        return {self.kind: {"href": self.href}}


def kind_from_href(href: str) -> Optional[str]:
    if "/kubernetes_workloads/" in href:
        return "kubernetes_workload"
    if "/container_workloads/" in href:
        return "container_workload"
    if "/ip_lists/" in href:
        return "ip_list"
    if "/workloads/" in href:
        return "workload"
    return None


def proto_number(proto: Any) -> int:
    if isinstance(proto, bool):
        raise ValueError("proto must be a number or a name")
    if isinstance(proto, int):
        return proto
    text = str(proto).strip()
    if text.isdigit():
        return int(text)
    try:
        return PROTO_BY_NAME[text.upper()]
    except KeyError:
        raise ValueError(f"unknown protocol {proto!r}") from None


# ── lookups (cached through filter_object_cache's TTL + stale-serving) ─────

def _workload_by_ip(api) -> dict[str, str]:
    from src.gui.filter_object_cache import _get_or_fill

    def fetch(a):
        out: dict[str, str] = {}
        for wl in a.fetch_managed_workloads(raise_on_error=True) or []:
            href = wl.get("href")
            if not href:
                continue
            for iface in wl.get("interfaces") or []:
                addr = iface.get("address")
                if addr and addr not in out:
                    out[addr] = href
        return out

    return _get_or_fill(api, "explain_workload_by_ip", fetch) or {}


def _iplists(api) -> list[dict]:
    from src.gui.filter_object_cache import _get_or_fill
    return _get_or_fill(api, "ip_lists", lambda a: a.get_ip_lists(raise_on_error=True)) or []


def _ip_in_range(ip: ipaddress._BaseAddress, rng: dict) -> bool:
    frm, to = rng.get("from_ip"), rng.get("to_ip")
    if not frm:
        return False
    try:
        if to:
            return ipaddress.ip_address(frm) <= ip <= ipaddress.ip_address(to)
        if "/" in frm:
            return ip in ipaddress.ip_network(frm, strict=False)
        return ip == ipaddress.ip_address(frm)
    except ValueError:
        return False


def _range_size(rng: dict) -> int:
    frm, to = rng.get("from_ip"), rng.get("to_ip")
    try:
        if to:
            return int(ipaddress.ip_address(to)) - int(ipaddress.ip_address(frm)) + 1
        if "/" in str(frm):
            return ipaddress.ip_network(frm, strict=False).num_addresses
        return 1
    except ValueError:
        return 0


def iplist_href_for_ip(ip_lists: list[dict], ip_text: str) -> Optional[str]:
    """The MOST SPECIFIC ip_list whose included ranges contain the IP and whose
    excluded ranges do not. Every PCE ships an "Any (0.0.0.0/0)" list that
    contains every address; picking the narrowest match keeps a corporate
    /16 list ahead of it, while a public IP still lands on Any — which is the
    honest answer (only rules whose actor includes Any cover it). Returns
    None for fqdn-only lists and unparsable input."""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return None
    best: Optional[tuple[int, str]] = None
    for ipl in ip_lists:
        ranges = ipl.get("ip_ranges") or []
        included = [r for r in ranges if not r.get("exclusion") and _ip_in_range(ip, r)]
        excluded = any(_ip_in_range(ip, r) for r in ranges if r.get("exclusion"))
        if not included or excluded or not ipl.get("href"):
            continue
        size = min(_range_size(r) for r in included)
        if best is None or size < best[0]:
            best = (size, ipl["href"])
    return best[1] if best else None


def resolve_actor(api, *, href: Optional[str], ip: Optional[str]) -> Actor:
    if href:
        kind = kind_from_href(href)
        if kind:
            return Actor(href=href, kind=kind, ip=ip)
    if ip:
        wl_href = _workload_by_ip(api).get(ip)
        if wl_href:
            return Actor(href=wl_href, kind=kind_from_href(wl_href) or "workload", ip=ip)
        ipl_href = iplist_href_for_ip(_iplists(api), ip)
        if ipl_href:
            return Actor(href=ipl_href, kind="ip_list", ip=ip)
    return Actor(href=None, kind="unresolved", ip=ip)


# ── result shaping ─────────────────────────────────────────────────────────

def _display_actor(entry: dict) -> str:
    if entry.get("actors") == "ams":
        return "All"
    for kind in ("label", "label_group", "workload", "ip_list", "virtual_service", "virtual_server",
                 "kubernetes_workload", "container_workload"):
        obj = entry.get(kind)
        if isinstance(obj, dict):
            if kind == "label" and obj.get("key"):
                text = f"{obj['key']}={obj.get('value', '')}"
            else:
                text = obj.get("name") or obj.get("hostname") or obj.get("href", kind)
            return ("NOT " if entry.get("exclusion") else "") + str(text)
    return str(entry)


def _display_service(svc: dict) -> str:
    if "href" in svc and not svc.get("port"):
        return str(svc.get("name") or svc["href"])
    proto = svc.get("proto")
    name = {v: k for k, v in PROTO_BY_NAME.items()}.get(proto, str(proto) if proto is not None else "")
    port = svc.get("port")
    if port is None:
        return name or "any"
    if svc.get("to_port"):
        return f"{port}-{svc['to_port']}/{name}"
    return f"{port}/{name}"


def _rule_hit(rule: dict) -> dict:
    rs = rule.get("rule_set") or {}
    return {
        "ruleset_href": rs.get("href"),
        "ruleset_name": rs.get("name"),
        "ruleset_enabled": rs.get("enabled"),
        "rule_href": rule.get("href"),
        "rule_enabled": rule.get("enabled"),
        "consumers": [_display_actor(a) for a in rule.get("consumers") or []],
        "providers": [_display_actor(a) for a in rule.get("providers") or []],
        "ingress_services": [_display_service(s) for s in rule.get("ingress_services") or []],
        "update_type": rule.get("update_type"),
        "description": rule.get("description") or "",
    }


def _cache_key(src: Actor, dst: Actor, port: int, proto: int, basis: str) -> tuple:
    return (src.href or src.ip, dst.href or dst.ip, port, proto, basis)


def explain_flow(api, *, src: dict, dst: dict, port: int, proto: Any,
                 basis: str = "active") -> dict:
    """Resolve both ends and ask the PCE which rules cover the flow.

    Returns a fixed shape; `source` says what produced it: "pce_rule_search"
    (PCE answered, allow/deny lists are its), "none" (neither end resolved,
    no search made). A non-2xx PCE reply is NOT swallowed: `pce_status` and
    `pce_error` carry it and the lists stay empty."""
    if basis not in BASIS_VALUES:
        raise ValueError("basis must be 'active' or 'draft'")
    proto_n = proto_number(proto)
    port_n = int(port)
    src_actor = resolve_actor(api, href=(src or {}).get("href"), ip=(src or {}).get("ip"))
    dst_actor = resolve_actor(api, href=(dst or {}).get("href"), ip=(dst or {}).get("ip"))
    result: dict[str, Any] = {
        "basis": basis,
        "evaluated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "none",
        "src": asdict(src_actor), "dst": asdict(dst_actor),
        "port": port_n, "proto": proto_n,
        "allow": [], "deny": [], "override_deny": [],
        "pce_status": None, "pce_error": None, "truncated": False,
    }
    if src_actor.to_search() is None and dst_actor.to_search() is None:
        return result

    key = _cache_key(src_actor, dst_actor, port_n, proto_n, basis)
    now = time.monotonic()
    with _result_lock:
        hit = _result_cache.get(key)
        if hit and now - hit[0] < _RESULT_TTL_SECONDS:
            cached = dict(hit[1])
            cached["cached"] = True
            return cached

    body: dict[str, Any] = {"ingress_services": [{"port": port_n, "proto": proto_n}],
                            "rule_types": RULE_TYPES}
    # Only resolved sides are sent: an omitted side means "any" to the PCE,
    # which would over-report allow rules for an endpoint we could not place.
    if src_actor.to_search():
        body["consumers"] = [src_actor.to_search()]
    if dst_actor.to_search():
        body["providers"] = [dst_actor.to_search()]
    if "consumers" not in body or "providers" not in body:
        result["partial"] = True     # one side unresolved: rules listed are for the resolved side only

    status, data = api.rule_search(body, pversion=basis)
    result["source"] = "pce_rule_search"
    result["pce_status"] = status
    if status not in (200, 201) or not isinstance(data, dict):
        result["pce_error"] = data if data is not None else "no response"
        logger.warning("policy explain: rule_search returned {} ({})", status, str(data)[:200])
        return result
    result["allow"] = [_rule_hit(r) for r in data.get("sec_rules") or []]
    result["deny"] = [_rule_hit(r) for r in data.get("deny_rules") or []]
    result["override_deny"] = [_rule_hit(r) for r in data.get("override_deny_rules") or []]
    counts = data.get("counts") or {}
    result["counts"] = counts
    with _result_lock:
        if len(_result_cache) >= _RESULT_CACHE_MAX:
            oldest = min(_result_cache.items(), key=lambda kv: kv[1][0])[0]
            _result_cache.pop(oldest, None)
        _result_cache[key] = (now, dict(result))
    return result


def clear_result_cache() -> None:
    with _result_lock:
        _result_cache.clear()
