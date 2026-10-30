"""Draft against active policy (spec §6.5 policy_diff, P5c-3), ported from 5.x policy_diff (diff_engine, object_diff,
risk; no pandas). Pure: no I/O.

Draft relative to active: added = only in Draft (created on provision), removed = only in active (deleted on
provision), modified = in both with a compared field that differs. Rules are keyed "collection/id" (sec_rules/3 and
deny_rules/3 are different rules); allow rules, Deny Rules and Override Deny are all compared — reading only the allow
collection made Deny Rule changes vanish in 5.x."""
from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Kind = Literal["rule_set", "rule", "ip_list", "service", "label_group"]
ChangeType = Literal["added", "removed", "modified"]
Risk = Literal["high", "medium", ""]
_ALLOW_KEYS = ("sec_rules", "rules")  # two shapes of the same collection
_RULE_FIELDS = ("rule_type", "enabled", "description", "providers", "consumers", "services")
_RULE_SET_FIELDS = ("name", "enabled", "description", "rule_count")
# Member lists where a new member widens what the object lets through.
_EXPANSION = frozenset({"ip_ranges", "fqdns", "service_ports", "labels", "sub_groups"})


class Change(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Kind
    change: ChangeType
    ruleset: str  # the ruleset's name (rules and rule sets); "" for policy objects
    name: str  # rule: its description or ref; object / rule set: its name
    ref: str  # rule: "sec_rules/3"; rule set / object: its id
    href: str  # the Draft href when there is one, else the active one
    field: str  # "*" for an added or removed object
    draft: str
    active: str
    rule_type: str = ""  # rules: allow | deny | override_deny
    rule_count: int | None = None  # an added or removed rule set: how many rules it brings or takes
    scope_expanded: bool = False
    risk: Risk = ""


def _id(href: str) -> str:
    return str(href or "").rstrip("/").rsplit("/", 1)[-1]


def _actors(items: Sequence[Any] | None, names: Mapping[str, str]) -> str:
    """Order-stable summary of providers / consumers / services; unknown hrefs stay as hrefs."""
    if not items:
        return "(any)"
    tokens = []
    for it in items:
        if not isinstance(it, dict):
            tokens.append(str(it))
            continue
        neg = "−" if it.get("exclusion") else ""
        if it.get("actors"):
            tokens.append(f"{neg}actors:{it['actors']}")
            continue
        for key in ("label", "label_group", "ip_list", "workload", "virtual_service"):
            ref = it.get(key)
            if isinstance(ref, dict) and ref.get("href"):
                tokens.append(f"{neg}{key}:{names.get(ref['href'], ref['href'])}")
                break
        else:
            if it.get("proto") is not None or it.get("port") is not None:
                tokens.append(_port(it))
            elif isinstance(it.get("href"), str):
                tokens.append(f"service:{names.get(it['href'], it['href'])}")
            else:
                tokens.append(str(sorted(it.items())))
    return ", ".join(sorted(tokens))


def _port(it: Mapping[str, Any]) -> str:
    if it.get("port") is None:
        return f"proto:{it.get('proto')}"
    text = f"{it.get('proto')}/{it['port']}"
    return f"{text}-{it['to_port']}" if it.get("to_port") is not None else text


def _rules(rs: Mapping[str, Any]) -> Iterator[tuple[dict[str, Any], str, str]]:
    """(rule, type, key) for every rule of a rule set, allow and deny, once each."""
    seen: set[str] = set()
    for key in _ALLOW_KEYS:
        for rule in rs.get(key) or []:
            if isinstance(rule, dict) and rule.get("href") and rule["href"] not in seen:
                seen.add(rule["href"])
                yield rule, "allow", _rule_key(rule["href"], "sec_rules")
    for rule in rs.get("deny_rules") or []:
        if isinstance(rule, dict) and rule.get("href") and rule["href"] not in seen:
            seen.add(rule["href"])
            yield rule, "override_deny" if rule.get("override") else "deny", _rule_key(rule["href"], "deny_rules")


def _rule_key(href: str, collection: str) -> str:
    parts = href.rstrip("/").split("/")
    return f"{parts[-2]}/{parts[-1]}" if len(parts) >= 2 and parts[-2] else f"{collection}/{_id(href)}"


def _rule_view(rule: Mapping[str, Any], rule_type: str, names: Mapping[str, str]) -> dict[str, str]:
    services = [*(rule.get("ingress_services") or []), *(rule.get("service_ports") or [])]
    return {"rule_type": rule_type, "enabled": str(rule.get("enabled", True)),
            "description": str(rule.get("description") or ""),
            "providers": _actors(rule.get("providers"), names), "consumers": _actors(rule.get("consumers"), names),
            "services": _actors(services, names)}


def _rule_set_view(rs: Mapping[str, Any]) -> dict[str, str]:
    return {"name": str(rs.get("name") or ""), "enabled": str(rs.get("enabled", True)),
            "description": str(rs.get("description") or ""), "rule_count": str(sum(1 for _ in _rules(rs)))}


def _by_id(items: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {_id(x["href"]): x for x in items or [] if isinstance(x, dict) and x.get("href")}


def diff_rule_sets(draft: Sequence[Mapping[str, Any]], active: Sequence[Mapping[str, Any]],
                   names: Mapping[str, str]) -> list[Change]:
    d_idx, a_idx = _by_id(draft), _by_id(active)
    out: list[Change] = []
    for rid in sorted(d_idx.keys() - a_idx.keys()):
        rs = d_idx[rid]
        out.append(Change(kind="rule_set", change="added", ruleset=str(rs.get("name") or ""),
                          name=str(rs.get("name") or ""), ref=rid, href=rs["href"], field="*",
                          draft=str(rs.get("name") or ""), active="", rule_count=sum(1 for _ in _rules(rs))))
    for rid in sorted(a_idx.keys() - d_idx.keys()):
        rs = a_idx[rid]
        out.append(Change(kind="rule_set", change="removed", ruleset=str(rs.get("name") or ""),
                          name=str(rs.get("name") or ""), ref=rid, href=rs["href"], field="*", draft="",
                          active=str(rs.get("name") or ""), rule_count=sum(1 for _ in _rules(rs))))
    for rid in sorted(d_idx.keys() & a_idx.keys()):
        d_rs, a_rs = d_idx[rid], a_idx[rid]
        rs_name = str(d_rs.get("name") or a_rs.get("name") or "")
        dv, av = _rule_set_view(d_rs), _rule_set_view(a_rs)
        out.extend(Change(kind="rule_set", change="modified", ruleset=rs_name, name=rs_name, ref=rid,
                          href=d_rs["href"], field=f, draft=dv[f], active=av[f])
                   for f in _RULE_SET_FIELDS if dv[f] != av[f])
        d_rules = {k: (r, t) for r, t, k in _rules(d_rs)}
        a_rules = {k: (r, t) for r, t, k in _rules(a_rs)}

        def label(rule: Mapping[str, Any], key: str) -> str:
            return str(rule.get("description") or "") or f"#{key.rsplit('/', 1)[-1]}"
        for k in sorted(d_rules.keys() - a_rules.keys()):
            r, t = d_rules[k]
            out.append(Change(kind="rule", change="added", ruleset=rs_name, name=label(r, k), ref=k, href=r["href"],
                              field="*", draft=t, active="", rule_type=t))
        for k in sorted(a_rules.keys() - d_rules.keys()):
            r, t = a_rules[k]
            out.append(Change(kind="rule", change="removed", ruleset=rs_name, name=label(r, k), ref=k,
                              href=r["href"], field="*", draft="", active=t, rule_type=t))
        for k in sorted(d_rules.keys() & a_rules.keys()):
            (dr, dt), (ar, at) = d_rules[k], a_rules[k]
            dv2, av2 = _rule_view(dr, dt, names), _rule_view(ar, at, names)
            out.extend(Change(kind="rule", change="modified", ruleset=rs_name, name=label(dr, k), ref=k,
                              href=dr["href"], field=f, draft=dv2[f], active=av2[f], rule_type=dt)
                       for f in _RULE_FIELDS if dv2[f] != av2[f])
    return out


def _range(it: Mapping[str, Any]) -> str:
    text = str(it.get("from_ip", ""))
    if it.get("to_ip"):
        text += f"-{it['to_ip']}"
    return f"!{text}" if it.get("exclusion") else text


def _members(field: str, value: Any, names: Mapping[str, str]) -> list[str]:
    out = []
    for it in value if isinstance(value, list) else []:
        if not isinstance(it, dict):
            out.append(str(it))
        elif field == "ip_ranges":
            out.append(_range(it))
        elif field == "fqdns":
            out.append(str(it.get("fqdn", "")))
        elif field == "service_ports":
            out.append(_port(it))
        elif field == "windows_services":
            out.append(str(it.get("service_name") or it.get("process_name") or sorted(it.items())))
        elif field in ("labels", "sub_groups"):
            href = str(it.get("href", ""))
            out.append(names.get(href.replace("/active/", "/draft/"), names.get(href, href)))
        else:
            out.append(str(sorted(it.items())))
    return out


def _field(field: str, obj: Mapping[str, Any], names: Mapping[str, str]) -> tuple[str, frozenset[str]]:
    if field in _EXPANSION or field == "windows_services":
        tokens = _members(field, obj.get(field), names)
        return ", ".join(sorted(tokens)), frozenset(tokens)
    text = str(obj.get(field) or "").strip()
    return text, frozenset([text])


def diff_objects(draft: Sequence[Mapping[str, Any]], active: Sequence[Mapping[str, Any]], *, kind: Kind,
                 fields: Sequence[str], names: Mapping[str, str]) -> list[Change]:
    d_idx, a_idx = _by_id(draft), _by_id(active)
    out: list[Change] = []
    for oid in sorted(d_idx.keys() - a_idx.keys()):
        o = d_idx[oid]
        out.append(Change(kind=kind, change="added", ruleset="", name=str(o.get("name") or ""), ref=oid,
                          href=o["href"], field="*", draft=str(o.get("name") or ""), active=""))
    for oid in sorted(a_idx.keys() - d_idx.keys()):
        o = a_idx[oid]
        out.append(Change(kind=kind, change="removed", ruleset="", name=str(o.get("name") or ""), ref=oid,
                          href=o["href"], field="*", draft="", active=str(o.get("name") or "")))
    for oid in sorted(d_idx.keys() & a_idx.keys()):
        d, a = d_idx[oid], a_idx[oid]
        for f in fields:
            (dt, ds), (at, as_) = _field(f, d, names), _field(f, a, names)
            if dt != at:
                out.append(Change(kind=kind, change="modified", ruleset="", name=str(d.get("name") or ""), ref=oid,
                                  href=d["href"], field=f, draft=dt, active=at,
                                  scope_expanded=f in _EXPANSION and bool(ds - as_)))
    return out


def object_refs(active_rule_sets: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """How many enabled allow rules (in enabled rule sets) use each IP list, label group and service, keyed
    "kind:id". A Deny Rule's reference opens nothing, so it is not counted."""
    refs: dict[str, int] = {}

    def bump(kind: str, href: Any) -> None:
        oid = _id(str(href or ""))
        if oid:
            refs[f"{kind}:{oid}"] = refs.get(f"{kind}:{oid}", 0) + 1
    for rs in active_rule_sets or []:
        if not isinstance(rs, dict) or not rs.get("enabled", True):
            continue
        for rule, rule_type, _ in _rules(rs):
            if rule_type != "allow" or not rule.get("enabled", True):
                continue
            for side in ("providers", "consumers"):
                for it in rule.get(side) or []:
                    if isinstance(it, dict) and isinstance(it.get("ip_list"), dict):
                        bump("ip_list", it["ip_list"].get("href"))
                    elif isinstance(it, dict) and isinstance(it.get("label_group"), dict):
                        bump("label_group", it["label_group"].get("href"))
            for svc in rule.get("ingress_services") or []:
                if isinstance(svc, dict) and svc.get("href"):
                    bump("service", svc["href"])
    return refs


def _risk(c: Change, refs: Mapping[str, int]) -> Risk:
    if c.kind in ("rule_set", "rule"):
        if c.change == "modified" and c.field == "enabled":
            if c.draft == "False" and c.active == "True":
                return "high"  # e.g. a Quarantine rule set: containment goes away on provision
            if c.draft == "True" and c.active == "False":
                return "medium"
        return "medium" if c.change == "removed" else ""
    if c.change == "removed":
        return "medium"
    if c.change == "modified" and c.scope_expanded and refs.get(f"{c.kind}:{c.ref}", 0) > 0:
        return "high"  # widened, and allow rules in force use it
    return ""


def grade(changes: Sequence[Change], refs: Mapping[str, int]) -> list[Change]:
    return [c.model_copy(update={"risk": _risk(c, refs)}) for c in changes]
