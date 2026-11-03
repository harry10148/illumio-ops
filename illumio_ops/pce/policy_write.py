"""The PCE calls rule scheduling makes (UI redesign spec §4.5; 5.x api_client toggle_and_provision, has_draft_changes,
update_rule_note, provision_changes). Hrefs are the PCE's own (/orgs/<n>/sec_policy/...), so calls are not
org-scoped again. Writes go to the draft, and only the rule set is provisioned: when the PCE says the change needs
other objects provisioned with it, nothing is provisioned — 5.x added them to the change, which would push someone
else's unreviewed draft (an edited IP list) live (security review 2026-11-03)."""
from __future__ import annotations

from typing import Any

from illumio_ops.pce.client import PceClient, PceResponse

DEPENDENCY_TYPES = ("rule_sets", "ip_lists", "services", "label_groups", "virtual_services", "firewall_settings",
                    "enforcement_boundaries", "virtual_servers", "secure_connect_gateways")
TIMEOUT = 30


class DependenciesPending(Exception):
    """Provisioning the rule set would need these other draft objects provisioned too."""

    def __init__(self, hrefs: list[str]) -> None:
        super().__init__(", ".join(hrefs))
        self.hrefs = hrefs


class PolicyReadError(Exception):
    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.body = body


def draft_href(href: str) -> str:
    return href.replace("/sec_policy/active/", "/sec_policy/draft/")


def active_href(href: str) -> str:
    return href.replace("/sec_policy/draft/", "/sec_policy/active/")


def ruleset_of(href: str) -> str:
    """The rule set a rule (allow or deny) belongs to, or the rule set itself, in the draft:
    /orgs/1/sec_policy/draft/rule_sets/5."""
    return "/".join(draft_href(href).split("/")[:7])


def is_ruleset(href: str) -> bool:
    return draft_href(href) == ruleset_of(href)


def _get(client: PceClient, href: str) -> PceResponse:
    return client.request("GET", href, org_scoped=False, timeout=TIMEOUT)


def draft_pending(client: PceClient, href: str) -> bool:
    """Anything in the target's rule set has a change not yet provisioned: the target, the rule set, or any other rule
    in it — the whole rule set is what gets provisioned, so a sibling's unreviewed change would go live too (Codex
    review of plan B)."""
    for path in dict.fromkeys((draft_href(href), ruleset_of(href))):
        r = _get(client, path)
        if r.status != 200:
            raise PolicyReadError(r.status, r.body)
        body = r.json() or {}
        if body.get("update_type"):
            return True
        for kind in ("rules", "sec_rules", "deny_rules"):
            if any(isinstance(x, dict) and x.get("update_type") for x in body.get(kind) or []):
                return True
    return False


def get_draft(client: PceClient, href: str) -> PceResponse:
    return _get(client, draft_href(href))


def get_active(client: PceClient, href: str) -> PceResponse:
    return _get(client, active_href(href))


def set_fields(client: PceClient, href: str, fields: dict[str, Any]) -> PceResponse:
    """PUT on the draft; 204 when done."""
    return client.request("PUT", draft_href(href), json=fields, org_scoped=False, timeout=TIMEOUT)


def provision(client: PceClient, ruleset_href: str, description: str) -> PceResponse:
    """Provision the rule set alone; 201 when done. DependenciesPending (nothing provisioned) when the PCE names other
    objects that would have to go live with it."""
    org = ruleset_href.split("/")[2]
    deps = client.request("POST", f"/orgs/{org}/sec_policy/draft/dependencies", org_scoped=False, timeout=TIMEOUT,
                          json={"change_subset": {"rule_sets": [{"href": ruleset_href}]}})
    if deps.status != 200:
        return deps
    found = (deps.json() or {}) if deps.body else {}
    others = [item["href"] for kind in DEPENDENCY_TYPES for item in found.get(kind) or []
              if item.get("href") and item["href"] != ruleset_href]
    if others:
        raise DependenciesPending(others)
    return client.request("POST", f"/orgs/{org}/sec_policy", org_scoped=False, timeout=TIMEOUT,
                          json={"update_description": description,
                                "change_subset": {"rule_sets": [{"href": ruleset_href}]}})
