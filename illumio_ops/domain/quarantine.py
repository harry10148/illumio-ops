"""Quarantine (spec §6.5.1 防堵, P6d): a workload is isolated by giving it a `Quarantine` label (Mild, Moderate,
Severe) that policy on the PCE refers to. Putting the label on changes nothing by itself, so which policy refers to
each level is read first, from the rule sets as the PCE sends them: scopes, allow rules, deny and override deny rules
(lab 2026-10-31: an unscoped "Quarantine" rule set with two override deny rules on Severe; Mild and Moderate referred
to by nothing). Pure: the PCE calls are the service's."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

KEY = "Quarantine"
LEVELS = ("Mild", "Moderate", "Severe")
ALL_WORKLOADS = "all_workloads"

RuleType = Literal["allow", "deny", "override_deny", "scope"]
Side = Literal["consumer", "provider", "scope"]
LevelState = Literal["active", "disabled", "draft_only", "none"]


class QuarantineRuleRef(BaseModel):
    """One place a level is referred to. Actors and services are hrefs ("all_workloads" for every workload,
    "<port>/<proto>" for a port written into the rule); the service names them."""
    ruleset: str
    ruleset_enabled: bool
    rule_type: RuleType
    enabled: bool
    side: Side
    consumers: list[str]
    providers: list[str]
    services: list[str]


def relabel(labels: Iterable[Mapping[str, Any]], target: str | None,
            quarantine_hrefs: set[str]) -> list[dict[str, str]]:
    """A workload's labels with its Quarantine label replaced by `target` (None: removed). Every other label stays: the
    PCE replaces the whole set on PUT. A label is Quarantine by its key, or by href when the key is not sent."""
    kept = [{"href": str(lb["href"])} for lb in labels
            if lb.get("href") and lb.get("key") != KEY and lb.get("href") not in quarantine_hrefs]
    return kept + ([{"href": target}] if target else [])


def _actors(items: Sequence[Mapping[str, Any]] | None) -> list[str]:
    out = []
    for a in items or ():
        if a.get("actors") == "ams":
            out.append(ALL_WORKLOADS)
            continue
        for kind in ("label", "label_group", "ip_list", "workload", "virtual_service", "virtual_server"):
            ref = a.get(kind)
            if isinstance(ref, Mapping) and ref.get("href"):
                out.append(str(ref["href"]))
                break
    return out


def _services(items: Sequence[Mapping[str, Any]] | None) -> list[str]:
    out = []
    for s in items or ():
        if s.get("href"):
            out.append(str(s["href"]))
        elif s.get("port") is not None or s.get("proto") is not None:
            port = s.get("port")
            out.append(f"{port if port is not None else '*'}{'-' + str(s['to_port']) if s.get('to_port') else ''}"
                       f"/{s.get('proto') if s.get('proto') is not None else '*'}")
    return out


def _refers(items: Sequence[Mapping[str, Any]] | None, href: str) -> bool:
    return any(isinstance(a.get("label"), Mapping) and a["label"].get("href") == href for a in items or ())


def policy_refs(rule_sets: Iterable[Mapping[str, Any]],
                level_hrefs: Mapping[str, str | None]) -> dict[str, list[QuarantineRuleRef]]:
    """Every scope and rule that names each level's label, per level."""
    out: dict[str, list[QuarantineRuleRef]] = {level: [] for level in LEVELS}
    for rs in rule_sets:
        name, rs_on = str(rs.get("name") or rs.get("href") or ""), bool(rs.get("enabled", True))
        rules: list[tuple[RuleType, Mapping[str, Any]]] = [("allow", r) for r in rs.get("rules") or ()]
        rules += [("override_deny" if r.get("override") else "deny", r) for r in rs.get("deny_rules") or ()]
        for level, href in level_hrefs.items():
            if not href or level not in out:
                continue
            for scope in rs.get("scopes") or ():
                if _refers(scope, href):
                    out[level].append(QuarantineRuleRef(
                        ruleset=name, ruleset_enabled=rs_on, rule_type="scope", enabled=True, side="scope",
                        consumers=[], providers=[], services=[]))
                    break
            for kind, r in rules:
                pairs: tuple[tuple[Side, str], ...] = (("consumer", "consumers"), ("provider", "providers"))
                sides = [side for side, k in pairs if _refers(r.get(k), href)]
                for side in sides:
                    out[level].append(QuarantineRuleRef(
                        ruleset=name, ruleset_enabled=rs_on, rule_type=kind, enabled=bool(r.get("enabled", True)),
                        side=side, consumers=_actors(r.get("consumers")), providers=_actors(r.get("providers")),
                        services=_services(r.get("ingress_services"))))
    return out


def level_states(*, active: Mapping[str, Sequence[QuarantineRuleRef]],
                 draft: Mapping[str, Sequence[QuarantineRuleRef]]) -> dict[str, LevelState]:
    """active: an enabled rule in an enabled rule set of the active policy refers to it; disabled: only turned-off ones
    do (the label would change nothing now); draft_only: only the draft refers to it (not provisioned); none."""
    states: dict[str, LevelState] = {}
    for level in LEVELS:
        refs = active.get(level) or []
        if any(r.ruleset_enabled and r.enabled for r in refs):
            states[level] = "active"
        elif refs:
            states[level] = "disabled"
        elif draft.get(level):
            states[level] = "draft_only"
        else:
            states[level] = "none"
    return states
