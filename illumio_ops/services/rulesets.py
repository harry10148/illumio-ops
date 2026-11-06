"""Rule set browsing (5.x #/policy/rulesets; parity 2026-11-06): the PCE's active rule sets with their rules — allow
rules, deny rules and override deny rules — read-only, described by the PCE's own names (labels, IP lists, services),
with which have a change pending in the draft and which have a rule schedule. Read with the main (read-only) key, the
same way the rule schedule target search reads them; the PCE's failures propagate, never an empty list."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from illumio_ops.services.context import AppContext
from illumio_ops.services.rule_schedule_targets import (
    read_policy,
    rule_label,
    rule_summary,
)

MAX_RULESETS = 200

RuleKind = Literal["allow", "deny", "override_deny"]


class RuleItem(BaseModel):
    href: str
    kind: RuleKind
    label: str  # "#9", or the deny rule's name
    enabled: bool
    summary: str  # sources → destinations: services, in the PCE's names
    description: str
    draft_pending: bool
    scheduled: bool


class RulesetItem(BaseModel):
    href: str
    name: str
    enabled: bool
    description: str
    draft_pending: bool
    scheduled: bool
    rules: list[RuleItem]


class RulesetBrowse(BaseModel):
    items: list[RulesetItem]
    total: int  # rule sets the PCE returned
    limited: bool  # more than MAX_RULESETS: only the first are listed


def _rule(rule: dict[str, Any], kind: RuleKind, names: dict[str, str], ctx: AppContext, *, pending: bool,
          scheduled: bool) -> RuleItem:
    lang = ctx.settings.current().display.language
    return RuleItem(href=rule["href"], kind=kind, label=rule_label(rule["href"], lang),
                    enabled=bool(rule.get("enabled")), summary=rule_summary(rule, names, lang),
                    description=str(rule.get("description") or ""), draft_pending=pending, scheduled=scheduled)


def browse(ctx: AppContext, q: str) -> RulesetBrowse:
    """q: the PCE's rule set name filter; blank lists every rule set (the first MAX_RULESETS)."""
    read = read_policy(ctx, q.strip() or None)
    items = []
    for rs in read.active[:MAX_RULESETS]:
        held = rs["href"] in read.pending
        rules = [_rule(r, "allow", read.names, ctx, pending=held or r["href"] in read.pending,
                       scheduled=r["href"] in read.scheduled)
                 for r in [*(rs.get("rules") or []), *(rs.get("sec_rules") or [])]]
        rules += [_rule(r, "override_deny" if r.get("override") else "deny", read.names, ctx,
                        pending=held or r["href"] in read.pending, scheduled=r["href"] in read.scheduled)
                  for r in rs.get("deny_rules") or []]
        items.append(RulesetItem(href=rs["href"], name=str(rs.get("name") or ""), enabled=bool(rs.get("enabled")),
                                 description=str(rs.get("description") or ""), draft_pending=held,
                                 scheduled=rs["href"] in read.scheduled, rules=rules))
    return RulesetBrowse(items=items, total=len(read.active), limited=len(read.active) > MAX_RULESETS)
