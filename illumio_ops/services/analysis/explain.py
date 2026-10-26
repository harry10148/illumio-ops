"""Policy explanation: which PCE rules cover a flow (alert detail, P4), or which allow rules expose a
workload's service to any source (the ransomware breakdown). Ends are resolved to PCE actors first; only
resolved sides are sent, because an omitted side means "any" to the PCE."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from illumio_ops.domain.policy import RuleRef, iplist_href_for_ip, parse_rule_search
from illumio_ops.domain.values import RuleAction
from illumio_ops.pce.client import PceClient
from illumio_ops.pce.collections import get_all
from illumio_ops.pce.rule_search import rule_search
from illumio_ops.services.collect.traffic import PCE_FAILURES
from illumio_ops.services.context import AppContext

Basis = Literal["active", "draft"]
DEADLINE_SECONDS = 120
_KINDS = (("/kubernetes_workloads/", "kubernetes_workload"), ("/container_workloads/", "container_workload"),
          ("/ip_lists/", "ip_list"), ("/workloads/", "workload"))


@dataclass(frozen=True)
class Endpoint:
    href: str | None
    ip: str | None


class PolicyExplanation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    basis: Basis
    source: Literal["pce", "none"]  # none: neither end could be placed, nothing was asked
    allow: list[RuleRef]
    deny: list[RuleRef]
    override_deny: list[RuleRef]
    pce_status: int | None
    pce_error: str | None
    unresolved: list[str]           # ends that could not be placed (their address)
    partial: bool                   # one side unresolved: the rules listed hold for the resolved side only


def _actor(href: str) -> dict[str, Any] | None:
    for marker, kind in _KINDS:
        if marker in href:
            return {kind: {"href": href}}
    return None


def _resolve(client: PceClient, end: Endpoint, basis: Basis, cache: dict[str, Any], deadline: float) -> dict[str, Any] | None:
    if end.href:
        actor = _actor(end.href)
        if actor:
            return actor
    if end.ip:
        if "ip_lists" not in cache:
            cache["ip_lists"] = get_all(client, f"/sec_policy/{basis}/ip_lists", params={}, deadline=deadline)
        href = iplist_href_for_ip(cache["ip_lists"], end.ip)
        if href:
            return {"ip_list": {"href": href}}
    return None


def _answer(basis: Basis, client: PceClient, consumers: list[dict[str, Any]] | None,
            providers: list[dict[str, Any]] | None, port: int, proto: int, deadline: float,
            unresolved: list[str], partial: bool) -> PolicyExplanation:
    try:
        found = rule_search(client, consumers=consumers, providers=providers, port=port, proto=proto, pversion=basis,
                            deadline=deadline)
    except PCE_FAILURES as exc:
        return PolicyExplanation(basis=basis, source="pce", allow=[], deny=[], override_deny=[], pce_status=None,
                                 pce_error=f"{type(exc).__name__}: {exc}"[:500], unresolved=unresolved, partial=partial)
    rules = parse_rule_search(found.body) if found.error is None else []
    return PolicyExplanation(
        basis=basis, source="pce", pce_status=found.status, pce_error=found.error, unresolved=unresolved,
        partial=partial, allow=[r for r in rules if r.rule_type is RuleAction.ALLOW],
        deny=[r for r in rules if r.rule_type is RuleAction.DENY],
        override_deny=[r for r in rules if r.rule_type is RuleAction.OVERRIDE_DENY])


def explain_flow(ctx: AppContext, src: Endpoint, dst: Endpoint, port: int, proto: int, *,
                 basis: Basis = "active") -> PolicyExplanation:
    deadline = time.monotonic() + DEADLINE_SECONDS
    cache: dict[str, Any] = {}
    with ctx.pce_client(ctx.settings.current().pce) as client:
        try:
            consumer, provider = (_resolve(client, src, basis, cache, deadline),
                                  _resolve(client, dst, basis, cache, deadline))
        except PCE_FAILURES as exc:
            return PolicyExplanation(basis=basis, source="pce", allow=[], deny=[], override_deny=[], pce_status=None,
                                     pce_error=f"{type(exc).__name__}: {exc}"[:500], unresolved=[], partial=False)
        unresolved = [e.ip or e.href or "" for e, a in ((src, consumer), (dst, provider)) if a is None]
        if consumer is None and provider is None:
            return PolicyExplanation(basis=basis, source="none", allow=[], deny=[], override_deny=[], pce_status=None,
                                     pce_error=None, unresolved=unresolved, partial=False)
        return _answer(basis, client, [consumer] if consumer else None, [provider] if provider else None, port, proto,
                       deadline, unresolved, partial=consumer is None or provider is None)


def explain_service(ctx: AppContext, workload_href: str, port: int, proto: int, *,
                    basis: Basis = "active") -> PolicyExplanation:
    """The rules covering any source reaching this workload's port: the consumers side is left out on
    purpose (it means "any"), so this is not a partial answer."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    provider = _actor(workload_href) or {"workload": {"href": workload_href}}
    with ctx.pce_client(ctx.settings.current().pce) as client:
        return _answer(basis, client, None, [provider], port, proto, deadline, [], partial=False)
