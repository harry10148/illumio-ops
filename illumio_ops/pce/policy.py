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
            # Read like any collection (P5c-3 final review #2): one GET took a full page as the whole set. A failed
            # read raises — it is not "no deny rules" (P3 final review #16).
            rs["deny_rules"] = get_all(client, f"{_org_relative(rs['href'])}/deny_rules", params={},
                                       deadline=deadline)
    return sets


def _org_relative(href: str) -> str:
    """/orgs/1/sec_policy/... -> /sec_policy/... (the client adds the org)."""
    parts = href.split("/", 3)
    return f"/{parts[3]}" if len(parts) == 4 and parts[1] == "orgs" else href


def fetch_objects(client: PceClient, pversion: Version, kind: str, *, deadline: float) -> list[dict[str, Any]]:
    """Every IP list, service or label group (`kind`) of one policy version; a failed read is raised."""
    return get_all(client, f"/sec_policy/{pversion}/{kind}", params={}, deadline=deadline)


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
