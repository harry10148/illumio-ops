"""Policy objects read from the PCE: rule sets with their deny rules, and the names their actors and
services refer to (rule objects carry only hrefs). All reads are open to the read_only role."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from illumio_ops.pce.client import PceClient
from illumio_ops.pce.collections import get_all

Version = Literal["draft", "active"]


def fetch_rule_sets(client: PceClient, pversion: Version, *, deadline: float) -> list[dict[str, Any]]:
    """Every rule set with its deny rules: inline when the PCE sends them, otherwise read from the rule
    set (an organisation-wide deny_rules collection answers 404 on lab, spec §6.6 F8)."""
    sets = get_all(client, f"/sec_policy/{pversion}/rule_sets", params={}, deadline=deadline)
    for rs in sets:
        if "deny_rules" not in rs and rs.get("href"):
            resp = client.request("GET", f"{rs['href']}/deny_rules", org_scoped=False, timeout=60, deadline=deadline)
            rs["deny_rules"] = resp.json() if resp.status == 200 and isinstance(resp.json(), list) else []
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
