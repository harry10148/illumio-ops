"""What a rule schedule can target (UI redesign spec §4.5): the active rule sets whose name matches, each with its
rules, described by the PCE's own names (labels, IP lists, services), with whether the draft has a change pending
(the schedule cannot be made then) and whether a schedule already exists. Read with the main (read-only) key."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from illumio_ops.domain.values import Language
from illumio_ops.i18n import translate
from illumio_ops.pce.collections import get_all
from illumio_ops.pce.policy_write import active_href
from illumio_ops.services.context import AppContext
from illumio_ops.store import rule_schedules as store

DEADLINE_S = 60
MAX_RULESETS = 20
PROTO = {6: "TCP", 17: "UDP", 1: "ICMP"}


class TargetHit(BaseModel):
    href: str
    is_ruleset: bool
    name: str
    ruleset_name: str
    summary: str
    enabled: bool
    draft_pending: bool
    scheduled: bool


class TargetSearch(BaseModel):
    items: list[TargetHit]
    limited: bool  # more rule sets matched than MAX_RULESETS
    pce_url: str = ""  # the PCE these were found on: a schedule is created only on it (Codex review round 2)
    org_id: str = ""


def _actor(a: dict[str, Any], names: dict[str, str], lang: Language) -> str:
    if a.get("actors") == "ams":
        return translate(lang, "rs_actor_all_workloads")
    for kind in ("label", "label_group", "ip_list", "workload", "virtual_service"):
        ref = a.get(kind)
        if isinstance(ref, dict) and ref.get("href"):
            return names.get(ref["href"], kind)
    return "?"


def _service(s: dict[str, Any], names: dict[str, str]) -> str:
    if s.get("href"):
        return names.get(s["href"], "service")
    port, proto = s.get("port"), s.get("proto")
    word = PROTO.get(int(proto), str(proto)) if proto is not None else ""
    if port is None:
        return word or "?"
    to = s.get("to_port")
    return f"{port}{'-' + str(to) if to else ''}/{word}" if word else str(port)


def _summary(rule: dict[str, Any], names: dict[str, str], lang: Language) -> str:
    """The rule in the PCE's own names; the words around them in the display language at search time (the summary is
    kept with the schedule as it was shown)."""
    src = ", ".join(_actor(a, names, lang) for a in rule.get("consumers") or []) or "?"
    dst = ", ".join(_actor(a, names, lang) for a in rule.get("providers") or []) or "?"
    svc = ", ".join(_service(s, names) for s in rule.get("ingress_services") or [])
    return f"{src} → {dst}: {svc or translate(lang, 'rs_service_all')}"


def search(ctx: AppContext, q: str) -> TargetSearch:
    text = q.strip()
    if not text:
        return TargetSearch(items=[], limited=False)
    cfg = ctx.settings.current().pce
    deadline = time.monotonic() + DEADLINE_S
    with ctx.pce_client(cfg) as client:
        active = get_all(client, "/sec_policy/active/rule_sets", params={"name": text}, deadline=deadline)
        draft = get_all(client, "/sec_policy/draft/rule_sets", params={"name": text}, deadline=deadline)
        names = {x["href"]: f"{x.get('key')}={x.get('value')}" for x in get_all(client, "/labels", params={},
                                                                              deadline=deadline) if x.get("href")}
        for path in ("/sec_policy/active/ip_lists", "/sec_policy/active/services"):
            names |= {x["href"]: str(x.get("name") or "") for x in get_all(client, path, params={}, deadline=deadline)
                      if x.get("href")}
    pending = {active_href(x["href"]) for x in draft if x.get("update_type")}
    pending |= {active_href(r["href"]) for x in draft for kind in ("rules", "deny_rules")
                for r in x.get(kind) or [] if r.get("update_type")}
    # the whole rule set is provisioned: one pending rule makes every target in it wait (Codex review of plan B)
    pending |= {active_href(x["href"]) for x in draft
                if any(r.get("update_type") for kind in ("rules", "deny_rules") for r in x.get(kind) or [])}
    with ctx.db() as conn:
        scheduled = {r["href"] for r in store.list_for(conn, pce_url=cfg.url, org_id=cfg.org_id)}
    lang = ctx.settings.current().display.language
    items = []
    for rs in active[:MAX_RULESETS]:
        rs_name = str(rs.get("name") or "")
        rules = [*(rs.get("rules") or []), *(rs.get("deny_rules") or [])]  # deny rules too: 5.x scheduled them
        items.append(TargetHit(href=rs["href"], is_ruleset=True, name=rs_name, ruleset_name=rs_name,
                               summary=translate(lang, "rs_summary_rules", {"n": str(len(rules))}),
                               enabled=bool(rs.get("enabled")),
                               draft_pending=rs["href"] in pending, scheduled=rs["href"] in scheduled))
        for rule in rules:
            href = rule["href"]
            number = href.rsplit("/", 1)[-1]
            label = translate(lang, "rs_deny_rule_name", {"id": number}) if "/deny_rules/" in href else f"#{number}"
            items.append(TargetHit(href=href, is_ruleset=False, name=label,
                                   ruleset_name=rs_name, summary=_summary(rule, names, lang),
                                   enabled=bool(rule.get("enabled")),
                                   draft_pending=href in pending or rs["href"] in pending,
                                   scheduled=href in scheduled))
    return TargetSearch(items=items, limited=len(active) > MAX_RULESETS, pce_url=cfg.url, org_id=cfg.org_id)
