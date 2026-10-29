"""Policy objects read from the PCE: rule sets with their deny rules, and the names their actors and
services refer to (rule objects carry only hrefs). All reads are open to the read_only role."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from illumio_ops.pce.client import PceClient
from illumio_ops.pce.collections import PceCollectionIncomplete, get_all

Version = Literal["draft", "active"]


def fetch_rule_sets(client: PceClient, pversion: Version, *, deadline: float) -> list[dict[str, Any]]:
    """Every rule set with its deny rules: inline when the PCE sends them, otherwise read from the rule
    set (an organisation-wide deny_rules collection answers 404 on lab, spec §6.6 F8)."""
    sets = get_all(client, f"/sec_policy/{pversion}/rule_sets", params={}, deadline=deadline)
    for rs in sets:
        if "deny_rules" not in rs and rs.get("href"):
            path = f"{rs['href']}/deny_rules"
            resp = client.request("GET", path, org_scoped=False, timeout=60, deadline=deadline)
            body = resp.json() if resp.status == 200 else None
            if not isinstance(body, list):  # a failed read is not "no deny rules" (P3 final review #16)
                raise PceCollectionIncomplete(path, 0, f"HTTP {resp.status}" if resp.status != 200 else
                                              "response is not a list")
            rs["deny_rules"] = body
    return sets


@dataclass(frozen=True)
class PolicyNames:
    labels: dict[str, tuple[str, str]]  # label href -> (key, value)
    names: dict[str, str]               # ip list / service / label group href -> name


def fetch_policy_names(client: PceClient, pversion: Version, *, deadline: float) -> PolicyNames:
    labels = {r["href"]: (str(r.get("key")), str(r.get("value")))
              for r in get_all(client, "/labels", params={}, deadline=deadline) if r.get("href")}
    names: dict[str, str] = {}
    for kind in ("ip_lists", "services", "label_groups"):
        for r in get_all(client, f"/sec_policy/{pversion}/{kind}", params={}, deadline=deadline):
            if r.get("href"):
                names[r["href"]] = str(r.get("name") or "")
    return PolicyNames(labels=labels, names=names)


class PendingItem(BaseModel):
    """A draft change not yet provisioned (GET /sec_policy/pending, lab 2026-10-29: {"rule_sets": [{href, name,
    update_type, updated_at, ...}], ...})."""
    model_config = ConfigDict(frozen=True)
    kind: str
    href: str
    name: str | None
    update_type: str | None
    updated_at: str | None


def parse_pending(body: Any) -> list[PendingItem]:
    if not isinstance(body, dict):
        raise TypeError("pending changes: response is not an object")
    return [PendingItem(kind=str(kind), href=str(item["href"]), name=item.get("name"),
                        update_type=item.get("update_type"), updated_at=item.get("updated_at"))
            for kind, items in body.items() if isinstance(items, list)
            for item in items if isinstance(item, dict) and item.get("href")]


def fetch_pending(client: PceClient, *, deadline: float) -> list[PendingItem]:
    """Every change the draft holds that is not active yet; a failed read is raised, never "nothing pending"."""
    resp = client.request("GET", "/sec_policy/pending", timeout=60, deadline=deadline)
    if resp.status != 200:
        raise PceCollectionIncomplete("/sec_policy/pending", 0, f"HTTP {resp.status}")
    return parse_pending(resp.json())
