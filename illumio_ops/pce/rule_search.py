"""PCE Rule Search (Public Experimental): which allow / deny / override-deny rules cover a flow.

Recovered from 5.x src/api_client.py rule_search and src/api/policy_explain.py (5.x aa81f477). Contract
facts measured on lab 25.2 (5.x tools/probe_rule_search.py, 2026-09-03), not taken from the docs:
consumers are the flow's source side and providers its destination; omitting a side widens it to
"any"; active and draft are independent views; a schema error answers 406 with an error list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from illumio_ops.pce.client import PceClient

RULE_TYPES = ["sec_rules", "deny_rules", "override_deny_rules"]


@dataclass(frozen=True)
class RuleSearchResult:
    status: int
    body: Any
    error: str | None  # the PCE's own words when it refused (non-2xx); None on success


def rule_search(client: PceClient, *, consumers: list[dict[str, Any]] | None, providers: list[dict[str, Any]] | None,
                port: int, proto: int, pversion: Literal["active", "draft"], deadline: float) -> RuleSearchResult:
    """One search; only the sides given are sent. A refusal is returned with the PCE's error body (never
    turned into an empty answer); a transport failure raises PceTransportError."""
    if pversion not in ("active", "draft"):
        raise ValueError("pversion must be 'active' or 'draft'")
    body: dict[str, Any] = {"ingress_services": [{"port": port, "proto": proto}], "rule_types": RULE_TYPES}
    if consumers:
        body["consumers"] = consumers
    if providers:
        body["providers"] = providers
    resp = client.request("POST", f"/sec_policy/{pversion}/rule_search", json=body, timeout=30, deadline=deadline)
    try:
        parsed: Any = resp.json()
    except ValueError:
        parsed = None
    if 200 <= resp.status < 300 and isinstance(parsed, dict):
        return RuleSearchResult(status=resp.status, body=parsed, error=None)
    return RuleSearchResult(status=resp.status, body=parsed,
                            error=str(parsed)[:500] if parsed is not None else "no response body")
