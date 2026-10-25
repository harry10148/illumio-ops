"""PCE rules as data: what a rule href names (rule set, type, actors, services), and what a draft recompute
says about one flow (P3 Task 0: enforcement_boundaries carries the deny rules that block it, rules the
allow rules or essential-service rules that allow it)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from illumio_ops.domain.values import RuleAction, parse_draft_policy_decision

ActorKind = Literal["label", "label_group", "ip_list", "workload", "all_workloads", "virtual_service", "other"]


@dataclass(frozen=True)
class ActorRef:
    kind: ActorKind
    key: str | None
    value: str | None
    name: str | None
    href: str | None
    exclusion: bool = False  # "everything except this" (a deny rule may exclude a label)


@dataclass(frozen=True)
class ServiceRef:
    port: int | None
    to_port: int | None
    proto: int | None
    name: str | None
    href: str | None


@dataclass(frozen=True)
class RuleRef:
    href: str
    rule_type: RuleAction
    enabled: bool
    ruleset_name: str
    ruleset_href: str
    description: str | None
    consumers: tuple[ActorRef, ...]
    providers: tuple[ActorRef, ...]
    services: tuple[ServiceRef, ...]


_ACTOR_KEYS: tuple[tuple[str, ActorKind], ...] = (
    ("label", "label"), ("label_group", "label_group"), ("ip_list", "ip_list"), ("workload", "workload"),
    ("virtual_service", "virtual_service"))


def _actor(raw: Mapping[str, Any], labels: Mapping[str, tuple[str, str]], names: Mapping[str, str]) -> ActorRef:
    exclusion = bool(raw.get("exclusion"))
    if raw.get("actors") == "ams" or raw.get("all_workloads"):
        return ActorRef("all_workloads", None, None, None, None, exclusion)
    for field, kind in _ACTOR_KEYS:
        obj = raw.get(field)
        if isinstance(obj, Mapping):
            href = str(obj["href"]) if obj.get("href") else None
            key: str | None = None
            value: str | None = None
            if kind == "label":
                key, value = labels[href] if href is not None and href in labels else (obj.get("key"), obj.get("value"))
            name = obj.get("name") or (names.get(href) if href else None) or obj.get("hostname")
            return ActorRef(kind, key, value, name, href, exclusion)
    return ActorRef("other", None, None, None, None, exclusion)


def _service(raw: Mapping[str, Any], names: Mapping[str, str]) -> ServiceRef:
    href = raw.get("href")
    return ServiceRef(port=raw.get("port"), to_port=raw.get("to_port"), proto=raw.get("proto"),
                      name=raw.get("name") or (names.get(href) if href else None), href=href)


def _rule(raw: Mapping[str, Any], rule_type: RuleAction, rs: Mapping[str, Any],
          labels: Mapping[str, tuple[str, str]], names: Mapping[str, str]) -> RuleRef:
    return RuleRef(
        href=str(raw["href"]), rule_type=rule_type, enabled=bool(raw.get("enabled", True)),
        ruleset_name=str(rs.get("name") or ""), ruleset_href=str(rs.get("href") or ""),
        description=raw.get("description") or None,
        consumers=tuple(_actor(a, labels, names) for a in raw.get("consumers") or ()),
        providers=tuple(_actor(a, labels, names) for a in raw.get("providers") or ()),
        services=tuple(_service(s, names) for s in raw.get("ingress_services") or ()))


def _deny_type(raw: Mapping[str, Any]) -> RuleAction:
    if raw.get("override") is True or str(raw.get("rule_type", "")).lower() == "override_deny":
        return RuleAction.OVERRIDE_DENY
    return RuleAction.DENY


def index_rules(rule_sets: Sequence[Mapping[str, Any]], *, labels: Mapping[str, tuple[str, str]] | None = None,
                names: Mapping[str, str] | None = None) -> dict[str, RuleRef]:
    """Every allow, deny and override-deny rule by href. Rule objects name labels, IP lists and services by
    href only; `labels` and `names` (read from the PCE) give them their names."""
    labels, names = labels or {}, names or {}
    out: dict[str, RuleRef] = {}
    for rs in rule_sets:
        for raw in rs.get("rules") or ():
            if raw.get("href"):
                out[raw["href"]] = _rule(raw, RuleAction.ALLOW, rs, labels, names)
        for raw in rs.get("deny_rules") or ():
            if raw.get("href"):
                out[raw["href"]] = _rule(raw, _deny_type(raw), rs, labels, names)
    return out


@dataclass(frozen=True)
class DraftView:
    draft_decision: str
    deny_rule_hrefs: tuple[str, ...]
    override_deny_hrefs: tuple[str, ...]
    allow_rule_hrefs: tuple[str, ...]
    essential_service_rules: tuple[str, ...]


def _hrefs(items: Any) -> tuple[str, ...]:
    return tuple(str(i["href"]) for i in items or () if isinstance(i, Mapping) and i.get("href"))


def parse_draft(raw: Mapping[str, Any]) -> DraftView:
    """A flow's draft decision (an open domain: unknown values pass through) and the rules behind it."""
    rules = [r for r in raw.get("rules") or () if isinstance(r, Mapping)]
    return DraftView(
        draft_decision=parse_draft_policy_decision(str(raw.get("draft_policy_decision") or "unknown")),
        deny_rule_hrefs=_hrefs(raw.get("enforcement_boundaries")),
        override_deny_hrefs=_hrefs(raw.get("override_deny_rules")),
        allow_rule_hrefs=_hrefs(rules),
        essential_service_rules=tuple(str(r["essential_service_rule"]) for r in rules if r.get("essential_service_rule")))
