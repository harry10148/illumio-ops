"""Report KPIs recomputed from raw PCE data, written here from the definitions in the spec's appendix A — not by calling
the report builders. Pure functions over parsed PCE records and events; reports.py does the reading.

Every KPI of appendix A is listed in KPI_KEYS. The ones this version recomputes are RECOMPUTED; every other one has
its one-line reason in REASONS and is reported as unchecked, never left out.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# ── appendix A: every KPI, and why the ones not recomputed are not ───────────

KPI_KEYS: dict[str, tuple[str, ...]] = {
    "weekly_overview": ("new_alerts", "vens_not_online", "pb_connections", "critical_high_alerts", "new_connections",
                        "provisions"),
    "lateral_posture": ("assets_reachable", "pivots", "new_detections", "cross_env"),
    "new_connections": ("new", "admin", "critical", "unmanaged_source"),
    "unmanaged_endpoints": ("total", "private", "admin_sources", "public"),
    "traffic": ("flows", "connections", "sources", "destinations"),
    "security_risk": ("maturity", "enforced_hosts_pct", "allowed_pct", "pb_flows", "blocked_flows",
                      "unmanaged_connections", "admin_open_connections", "critical_high_findings",
                      "ransomware_protected_pct"),
    "network_inventory": ("managed_hosts", "hosts_missing_labels", "apps", "cross_env_connections"),
    "app_summary": ("inbound_connections", "outbound_connections", "intra_connections", "allowed_pct", "pb_flows",
                    "hosts", "enforced_hosts_pct"),
    "ven_status": ("managed", "online", "lost_24h", "lost_48h", "long_offline", "status_unknown", "sync_problems",
                   "unexplained_tamper"),
    "audit": ("total", "high_risk", "auth_failed", "authz_denied", "policy_provisions", "draft_changes",
              "agent_security", "actors", "source_ips"),
    "ransomware": ("rated_hosts", "org_percent", "priority", "safe_to_block", "suspicious", "contradictions",
                   "unprotected"),
    "policy_usage": ("rules", "used", "unused", "disabled", "deny_hit", "no_rule", "rhc_hit", "rhc_zero",
                     "rhc_no_record"),
    "policy_diff": ("total", "high", "rule_sets", "rules", "objects", "other_pending"),
    "policy_resolver": ("rulesets", "rules", "rows", "capped", "omitted", "not_expanded", "no_address"),
    "readiness": ("apps", "ready", "held_back", "overall", "predicted_blocked"),
    "custom": (),
}

RECOMPUTED: dict[str, frozenset[str]] = {
    "audit": frozenset({"total", "high_risk", "auth_failed", "authz_denied", "policy_provisions", "draft_changes",
                        "agent_security", "actors"}),
    "traffic": frozenset({"sources", "destinations"}),
    "unmanaged_endpoints": frozenset({"total", "private", "public"}),
    "weekly_overview": frozenset({"provisions"}),
    "policy_usage": frozenset({"used", "unused", "deny_hit", "no_rule"}),
    "readiness": frozenset({"predicted_blocked"}),
}

_NO = "not recomputable: "
_LATER = "partly recomputable, not in this version: "
_OWN = _NO + "this system's own analysis or score, not PCE data"
_ALERTS = _NO + "this system's own alert records (event-rule alerts are checked in the alerts area)"
_NOW = _LATER + "inventory state; only today's PCE state could be compared"
_PAIR = _LATER + "needs this system's pairing of flow records reimplemented and checked first"
_ADMIN = _LATER + "needs the management-port list (built-in, PCE admin services and settings)"
_POLICY_NOW = _LATER + "the policy as it was when the report ran; only today's policy could be compared"
_RHC = _NO + "the PCE's Rule Hit Count report needs POST /reports, a write this tool may not make"

REASONS: dict[tuple[str, str], str] = {
    ("weekly_overview", "new_alerts"): _ALERTS,
    ("weekly_overview", "critical_high_alerts"): _ALERTS,
    ("weekly_overview", "vens_not_online"): _NOW,
    ("weekly_overview", "pb_connections"): _PAIR,
    ("weekly_overview", "new_connections"): _LATER + "the connection baseline's first sightings since install",
    **{("lateral_posture", k): _NO + "this system's exposure graph and detectors"
       for k in KPI_KEYS["lateral_posture"]},
    ("new_connections", "new"): _LATER + "the connection baseline's first sightings since install",
    ("new_connections", "admin"): _LATER + "the connection baseline, and the management-port list",
    ("new_connections", "critical"): _LATER + "the connection baseline, and the critical-asset selector",
    ("new_connections", "unmanaged_source"): _LATER + "the connection baseline's first sightings since install",
    ("unmanaged_endpoints", "admin_sources"): _ADMIN,
    ("traffic", "flows"): _LATER + "the store's record count after re-pulls and merges (appendix A.17 item 3)",
    ("traffic", "connections"): _PAIR,
    ("security_risk", "maturity"): _OWN,
    ("security_risk", "critical_high_findings"): _NO + "this system's rule engine",
    ("security_risk", "enforced_hosts_pct"): _NOW,
    ("security_risk", "ransomware_protected_pct"): _NOW,
    ("security_risk", "allowed_pct"): _PAIR,
    ("security_risk", "pb_flows"): _PAIR,
    ("security_risk", "blocked_flows"): _PAIR,
    ("security_risk", "unmanaged_connections"): _PAIR,
    ("security_risk", "admin_open_connections"): _ADMIN,
    ("network_inventory", "managed_hosts"): _NOW,
    ("network_inventory", "hosts_missing_labels"): _NOW,
    ("network_inventory", "apps"): _PAIR,
    ("network_inventory", "cross_env_connections"): _PAIR,
    **{("app_summary", k): _PAIR for k in ("inbound_connections", "outbound_connections", "intra_connections",
                                            "allowed_pct", "pb_flows")},
    ("app_summary", "hosts"): _NOW,
    ("app_summary", "enforced_hosts_pct"): _NOW,
    **{("ven_status", k): _NOW for k in KPI_KEYS["ven_status"] if k != "unexplained_tamper"},
    ("ven_status", "unexplained_tamper"): _NO + "this system's tamper analysis",
    ("audit", "source_ips"): _LATER + "the source address paths are this system's heuristic",
    ("ransomware", "rated_hosts"): _NOW,
    ("ransomware", "org_percent"): _NOW,
    **{("ransomware", k): _NO + "this system's ransomware classification"
       for k in ("priority", "safe_to_block", "suspicious", "contradictions", "unprotected")},
    ("policy_usage", "rules"): _POLICY_NOW,
    ("policy_usage", "disabled"): _POLICY_NOW,
    ("policy_usage", "rhc_hit"): _RHC,
    ("policy_usage", "rhc_zero"): _RHC,
    ("policy_usage", "rhc_no_record"): _RHC,
    ("policy_diff", "high"): _NO + "this system's risk rules",
    **{("policy_diff", k): _POLICY_NOW for k in ("total", "rule_sets", "rules", "objects", "other_pending")},
    ("policy_resolver", "rulesets"): _POLICY_NOW,
    ("policy_resolver", "rules"): _POLICY_NOW,
    **{("policy_resolver", k): _NO + "this system's expansion of rules to addresses"
       for k in ("rows", "capped", "omitted", "not_expanded", "no_address")},
    ("readiness", "apps"): _PAIR,
    **{("readiness", k): _NO + "this system's readiness score" for k in ("ready", "held_back", "overall")},
}


def reason(report_type: str, key: str) -> str | None:
    """None when this version recomputes the KPI; otherwise why not."""
    if key in RECOMPUTED.get(report_type, frozenset()):
        return None
    return REASONS.get((report_type, key), "not in the spec's appendix A: not checked")


# ── flow records ─────────────────────────────────────────────────────────────

PAIRING_GAP = timedelta(seconds=600)
LONG_RECORD = timedelta(days=2)  # a record longer than this is a weekly one: older traffic the PCE keeps by the week


@dataclass(frozen=True)
class Draft:
    decision: str
    allow: tuple[str, ...]
    deny: tuple[str, ...]  # enforcement boundaries (Deny Rules)
    override: tuple[str, ...]


@dataclass(frozen=True)
class Flow:
    direction: str  # "outbound" | "inbound"
    src_ip: str
    dst_ip: str
    src_href: str | None
    dst_href: str | None
    src_managed: bool
    dst_managed: bool
    port: int | None
    proto: int
    decision: str
    first: datetime
    last: datetime
    connections: int
    draft: Draft | None

    @property
    def identity(self) -> tuple[str, str, str, int | None, int, datetime]:
        """One PCE record: the same record read again (a split window, a neighbouring day) is the same."""
        return (self.direction, self.src_ip, self.dst_ip, self.port, self.proto, self.first)

    @property
    def src_key(self) -> str:
        return self.src_href or f"ip:{self.src_ip}"

    @property
    def dst_key(self) -> str:
        return self.dst_href or f"ip:{self.dst_ip}"


def _time(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        return None
    return t.astimezone(UTC) if t.tzinfo is not None else None


def _hrefs(items: Any) -> tuple[str, ...]:
    return tuple(str(i["href"]) for i in items or () if isinstance(i, Mapping) and i.get("href"))


def parse_flow(raw: Mapping[str, Any], *, draft: bool = False) -> Flow | None:
    """A traffic record from the PCE's JSON, or None without the fields every record has."""
    src, dst = raw.get("src"), raw.get("dst")
    svc, tr = raw.get("service"), raw.get("timestamp_range")
    if not (isinstance(src, Mapping) and isinstance(dst, Mapping) and isinstance(svc, Mapping)
            and isinstance(tr, Mapping)):
        return None
    sip, dip, proto = src.get("ip"), dst.get("ip"), svc.get("proto")
    direction, decision = raw.get("flow_direction"), raw.get("policy_decision")
    first, last = _time(tr.get("first_detected")), _time(tr.get("last_detected"))
    if (not isinstance(sip, str) or not sip or not isinstance(dip, str) or not dip or not isinstance(proto, int)
            or isinstance(proto, bool) or direction not in ("outbound", "inbound") or not isinstance(decision, str)
            or not decision or first is None or last is None):
        return None
    sw, dw = src.get("workload"), dst.get("workload")
    swl: Mapping[str, Any] = sw if isinstance(sw, Mapping) else {}
    dwl: Mapping[str, Any] = dw if isinstance(dw, Mapping) else {}
    port = svc.get("port")
    conns = raw.get("num_connections")
    d = None
    if draft:
        d = Draft(decision=str(raw.get("draft_policy_decision") or "unknown").strip().lower(),
                  allow=_hrefs(raw.get("rules")), deny=_hrefs(raw.get("enforcement_boundaries")),
                  override=_hrefs(raw.get("override_deny_rules")))
    return Flow(direction=direction, src_ip=sip, dst_ip=dip, src_href=swl.get("href") or None,
                dst_href=dwl.get("href") or None, src_managed=bool(swl.get("managed")),
                dst_managed=bool(dwl.get("managed")),
                port=port if isinstance(port, int) and not isinstance(port, bool) else None, proto=proto,
                decision=decision.strip().lower(), first=first, last=last,
                connections=conns if isinstance(conns, int) and not isinstance(conns, bool) and conns >= 0 else 0,
                draft=d)


def pair(flows: Iterable[Flow]) -> list[tuple[Flow, Flow | None]]:
    """(primary, partner) per connection: per 4-tuple, each outbound record (in first-seen order) takes the first
    unused inbound record whose time range overlaps or lies at most PAIRING_GAP away; the rest stand alone. The
    primary is the outbound record of a pair."""
    groups: dict[tuple[str, str, int | None, int], list[Flow]] = {}
    for f in flows:
        groups.setdefault((f.src_ip, f.dst_ip, f.port, f.proto), []).append(f)
    out: list[tuple[Flow, Flow | None]] = []
    for group in groups.values():
        group.sort(key=lambda f: (f.first, repr(f.identity)))
        outs = [f for f in group if f.direction == "outbound"]
        ins = [f for f in group if f.direction == "inbound"]
        used: set[int] = set()
        for o in outs:
            partner = None
            for i, f in enumerate(ins):
                if i not in used and max(o.first, f.first) - min(o.last, f.last) <= PAIRING_GAP:
                    used.add(i)
                    partner = f
                    break
            out.append((o, partner))
        out += [(f, None) for i, f in enumerate(ins) if i not in used]
    return out


def long_records(flows: Iterable[Flow]) -> int:
    return sum(1 for f in flows if f.last - f.first > LONG_RECORD)


# ── traffic: distinct sources and destinations ───────────────────────────────

def traffic_values(primaries: Sequence[Flow], start: datetime, end: datetime,
                   decisions: frozenset[str]) -> dict[str, int | None]:
    """Over the primary records overlapping [start, end] (last seen at or after start, first seen at or before end)
    and, with a decision filter, of those decisions. None when there is no such record (the report gives none)."""
    rows = [f for f in primaries if f.last >= start and f.first <= end and (not decisions or f.decision in decisions)]
    if not rows:
        return {"sources": None, "destinations": None}
    return {"sources": len({f.src_key for f in rows}), "destinations": len({f.dst_key for f in rows})}


# ── unmanaged endpoints ──────────────────────────────────────────────────────

def _is_public(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def unmanaged_values(primaries: Sequence[Flow], first_day: str, last_day: str) -> dict[str, int | None]:
    """Addresses without a workload that talk with a workload, over the primary records last seen on the UTC days
    first_day..last_day (the daily rollups' days)."""
    found: set[str] = set()
    for f in primaries:
        day = f.last.strftime("%Y-%m-%d")
        if not first_day <= day <= last_day:
            continue
        if f.src_href is None and f.dst_href is not None:
            found.add(f.src_ip)
        elif f.dst_href is None and f.src_href is not None:
            found.add(f.dst_ip)
    public = sum(1 for ip in found if _is_public(ip))
    return {"total": len(found), "private": len(found) - public, "public": public}


# ── draft recompute: rule usage and predicted blocks ─────────────────────────

ALLOWED = frozenset({"allowed", "allowed_across_boundary"})
BY_DENY = frozenset({"blocked_by_boundary", "potentially_blocked_by_boundary"})
BY_OVERRIDE = frozenset({"blocked_by_override_deny", "potentially_blocked_by_override_deny"})
NO_RULE = frozenset({"potentially_blocked", "blocked"})
KNOWN_DRAFT = ALLOWED | BY_DENY | BY_OVERRIDE | NO_RULE | {"unknown"}


@dataclass(frozen=True)
class RuleHits:
    hit: frozenset[str]  # rule hrefs that took effect for at least one connection
    no_rule_connections: int


def rule_hits(pairs: Iterable[tuple[Flow, Flow | None]]) -> RuleHits:
    """An allow rule takes effect when its end's draft decision allows the connection; a Deny Rule (or an override
    deny) when it blocks it, or would once enforced. A connection with neither, whose decisions are all a default
    block, counts its connections as 'no rule'."""
    hit: set[str] = set()
    no_rule = 0
    for primary, partner in pairs:
        ends = [e.draft for e in (primary, partner) if e is not None and e.draft is not None]
        named = {h for v in ends if v.decision in ALLOWED for h in v.allow}
        named |= {h for v in ends for h in (v.deny if v.decision in BY_DENY
                                            else v.override if v.decision in BY_OVERRIDE else ())}
        hit |= named
        if not named and ends and {v.decision for v in ends} <= NO_RULE:
            no_rule += primary.connections
    return RuleHits(frozenset(hit), no_rule)


def policy_usage_values(rule_sets: Sequence[Mapping[str, Any]], hits: RuleHits) -> dict[str, int | None]:
    """used: allow rules of the draft that took effect; unused: enabled allow rules that did not; deny_hit: Deny and
    override-deny rules that took effect; no_rule: connections no rule allowed or denied."""
    allow = {str(r["href"]): bool(r.get("enabled", True)) for rs in rule_sets for r in rs.get("rules") or ()
             if isinstance(r, Mapping) and r.get("href")}
    deny = {str(r["href"]) for rs in rule_sets for r in rs.get("deny_rules") or ()
            if isinstance(r, Mapping) and r.get("href")}
    allow = {h: e for h, e in allow.items() if h not in deny}  # one href listed as both: it is a Deny Rule
    return {"used": sum(1 for h in allow if h in hits.hit),
            "unused": sum(1 for h, enabled in allow.items() if enabled and h not in hits.hit),
            "deny_hit": sum(1 for h in deny if h in hits.hit), "no_rule": hits.no_rule_connections}


@dataclass(frozen=True)
class Predicted:
    blocked_flows: int
    blocked_connections: int
    undetermined_flows: int

    def value(self) -> int | None:
        """As the readiness report gives it: no number when nothing was found blocked while some connections had
        no draft decision (zero is then not a confirmed answer)."""
        return self.blocked_connections if self.blocked_flows > 0 or not self.undetermined_flows else None


def predicted(pairs: Iterable[tuple[Flow, Flow | None]]) -> Predicted:
    """Connections into managed hosts the draft would block: a connection's decision is the first of its ends that
    is a block, else the primary's; a decision the PCE did not give (or one not known) is undetermined."""
    flows = conns = undetermined = 0
    for primary, partner in pairs:
        if not primary.dst_managed:
            continue
        ends = [e.draft for e in (primary, partner) if e is not None and e.draft is not None]
        if not ends:
            continue
        decision = next((v.decision for v in ends if v.decision.startswith("blocked")), ends[0].decision)
        if decision not in KNOWN_DRAFT - {"unknown"}:
            undetermined += 1
            continue
        if decision.startswith("blocked"):
            flows += 1
            conns += primary.connections
    return Predicted(flows, conns, undetermined)


# ── events: the audit numbers ────────────────────────────────────────────────

CREATOR_KINDS = ("ven", "agent", "user", "service_account", "system")
PEOPLE = ("user", "service_account")
HIGH_RISK = frozenset({"agent.tampering", "agent.clone_detected", "agent.suspend", "workloads.unpair",
                       "agents.unpair", "request.authorization_failed"})
AGENT_SECURITY = frozenset({"agent.tampering", "agent.clone_detected", "agent.suspend", "workloads.unpair",
                            "agents.unpair"})
PROVISION = "sec_policy.create"


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    timestamp: datetime
    creator_kind: str | None
    creator_name: str | None


def parse_audit_event(raw: Mapping[str, Any]) -> AuditEvent | None:
    """None without an href, an event_type or a readable timestamp (the system does not store those)."""
    href, et, ts = raw.get("href"), raw.get("event_type"), _time(raw.get("timestamp"))
    if not isinstance(href, str) or not href or not isinstance(et, str) or not et or ts is None:
        return None
    kind = name = None
    by = raw.get("created_by")
    if isinstance(by, Mapping):
        for k in CREATOR_KINDS:
            v = by.get(k)
            if isinstance(v, Mapping):
                kind = k
                n = v.get("hostname") or v.get("username") or v.get("name")
                name = n if isinstance(n, str) else None
                break
    return AuditEvent(et, ts, kind, name)


def audit_values(evs: Sequence[AuditEvent]) -> dict[str, int | None]:
    """The audit report's numbers over the events given (already in the period); None for every one when there are
    none (the report gives no count then)."""
    keys = ("total", "high_risk", "auth_failed", "authz_denied", "policy_provisions", "draft_changes",
            "agent_security", "actors")
    if not evs:
        return dict.fromkeys(keys)
    return {
        "total": len(evs),
        "high_risk": sum(1 for e in evs if e.event_type in HIGH_RISK),
        "auth_failed": sum(1 for e in evs if e.event_type == "request.authentication_failed"),
        "authz_denied": sum(1 for e in evs if e.event_type == "request.authorization_failed"),
        "policy_provisions": sum(1 for e in evs if e.event_type == PROVISION),
        "draft_changes": sum(1 for e in evs if e.event_type.startswith(("rule_set.", "sec_rule."))),
        "agent_security": sum(1 for e in evs if e.event_type in AGENT_SECURITY),
        "actors": len({e.creator_name for e in evs if e.creator_kind in PEOPLE and e.creator_name
                       and e.creator_name.strip()}),
    }


# What changes the draft's answer: its rules and the objects they name, and the workloads (labels, enforcement). A
# provision (sec_policy.create) makes the draft active and leaves it as it is.
DRAFT_RESOURCES = frozenset({"rule_set", "rule_sets", "sec_rule", "sec_rules", "deny_rule", "deny_rules",
                             "enforcement_boundary", "enforcement_boundaries", "ip_list", "ip_lists", "service",
                             "services", "label_group", "label_groups"})
WORKLOAD_RESOURCES = frozenset({"workload", "workloads"})
WORKLOAD_CHANGES = frozenset({"create", "update", "delete", "unpair", "bulk_update", "bulk_delete"})
DRAFT_REVERTS = frozenset({"sec_policy.delete", "sec_policy.restore"})


def draft_changes(evs: Iterable[AuditEvent]) -> dict[str, int]:
    """The event types among `evs` that change what a draft recompute answers, with how many of each."""
    out: dict[str, int] = {}
    for e in evs:
        resource, _, action = e.event_type.partition(".")
        if (resource in DRAFT_RESOURCES or e.event_type in DRAFT_REVERTS
                or (resource in WORKLOAD_RESOURCES and action in WORKLOAD_CHANGES)):
            out[e.event_type] = out.get(e.event_type, 0) + 1
    return out


def provisions_value(evs: Sequence[AuditEvent]) -> int | None:
    """The weekly overview's provisions: None when the period has no event at all."""
    return sum(1 for e in evs if e.event_type == PROVISION) if evs else None
