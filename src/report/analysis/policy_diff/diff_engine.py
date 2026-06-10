"""DRAFT-vs-ACTIVE policy diff engine.

PURE derivation (no I/O). Aligns draft and active ruleset lists by stable id
and emits field-level added/removed/modified rows. Scope is Ruleset/Rule ONLY
(IP lists, services, label groups, virtual services, firewall settings are out
of scope for v1). Diff semantics are "DRAFT relative to ACTIVE":
  - added    = id present only in draft (will be created on provision)
  - removed  = id present only in active (will be deleted on provision)
  - modified = id in both, but a whitelisted field differs
"""
from __future__ import annotations

import pandas as pd

_RULESET_COLS = ["change_type", "ruleset_name", "ruleset_id",
                 "field", "draft_value", "active_value",
                 "last_actor", "last_changed", "last_event"]
_RULE_COLS = ["change_type", "ruleset_name", "rule_id",
              "field", "draft_value", "active_value",
              "last_actor", "last_changed", "last_event"]


def _id_from_href(href: str) -> str:
    return str(href or "").rstrip("/").split("/")[-1]


def _summarize_actors(items: list) -> str:
    """Order-stable string summary of a providers/consumers/services list."""
    if not items:
        return "(any)"
    tokens = []
    for it in items:
        if not isinstance(it, dict):
            tokens.append(str(it))
            continue
        if it.get("actors"):
            tokens.append(f"actors:{it['actors']}")
        elif isinstance(it.get("label"), dict) and it["label"].get("href"):
            tokens.append(f"label:{it['label']['href']}")
        elif isinstance(it.get("ip_list"), dict) and it["ip_list"].get("href"):
            tokens.append(f"ip_list:{it['ip_list']['href']}")
        elif isinstance(it.get("workload"), dict) and it["workload"].get("href"):
            tokens.append(f"workload:{it['workload']['href']}")
        elif it.get("proto") is not None or it.get("port") is not None:
            tokens.append(f"svc:{it.get('proto')}/{it.get('port')}")
        elif isinstance(it.get("href"), str):
            tokens.append(f"svc:{it['href']}")
        else:
            tokens.append(str(sorted(it.items())))
    return ", ".join(sorted(tokens))


def _ruleset_fields(rs: dict) -> dict:
    return {
        "name": str(rs.get("name", "")),
        "enabled": str(rs.get("enabled", True)),
        "description": str(rs.get("description", "") or ""),
        "rule_count": str(len(rs.get("rules", []) or [])),
    }


def _rule_fields(rule: dict) -> dict:
    return {
        "enabled": str(rule.get("enabled", True)),
        "providers": _summarize_actors(rule.get("providers", []) or []),
        "consumers": _summarize_actors(rule.get("consumers", []) or []),
        "ingress_services": _summarize_actors(rule.get("ingress_services", []) or []),
    }


def _index_by_id(rulesets: list) -> dict:
    return {_id_from_href(rs.get("href", "")): rs for rs in (rulesets or []) if rs.get("href")}


def _index_rules(rs: dict) -> dict:
    out = {}
    for rule in rs.get("rules", []) or []:
        if rule.get("href"):
            out[_id_from_href(rule["href"])] = rule
    return out


def diff_rulesets(draft: list[dict], active: list[dict]) -> dict:
    draft_idx = _index_by_id(draft)
    active_idx = _index_by_id(active)

    rs_rows: list[dict] = []
    rule_rows: list[dict] = []
    s = {"rulesets_added": 0, "rulesets_removed": 0, "rulesets_modified": 0,
         "rules_added": 0, "rules_removed": 0, "rules_modified": 0}

    def _blank():
        return {"last_actor": "", "last_changed": "", "last_event": ""}

    # ── Ruleset-level ────────────────────────────────────────────────────────
    for rs_id in draft_idx.keys() - active_idx.keys():
        rs = draft_idx[rs_id]
        s["rulesets_added"] += 1
        rs_rows.append({"change_type": "added", "ruleset_name": rs.get("name", ""),
                        "ruleset_id": rs_id, "field": "*",
                        "draft_value": _ruleset_fields(rs)["name"], "active_value": "",
                        **_blank()})
    for rs_id in active_idx.keys() - draft_idx.keys():
        rs = active_idx[rs_id]
        s["rulesets_removed"] += 1
        rs_rows.append({"change_type": "removed", "ruleset_name": rs.get("name", ""),
                        "ruleset_id": rs_id, "field": "*",
                        "draft_value": "", "active_value": _ruleset_fields(rs)["name"],
                        **_blank()})
    for rs_id in draft_idx.keys() & active_idx.keys():
        d_rs, a_rs = draft_idx[rs_id], active_idx[rs_id]
        df_f, af_f = _ruleset_fields(d_rs), _ruleset_fields(a_rs)
        rs_modified = False
        for field in df_f:
            if df_f[field] != af_f[field]:
                rs_modified = True
                rs_rows.append({"change_type": "modified",
                                "ruleset_name": d_rs.get("name", a_rs.get("name", "")),
                                "ruleset_id": rs_id, "field": field,
                                "draft_value": df_f[field], "active_value": af_f[field],
                                **_blank()})
        if rs_modified:
            s["rulesets_modified"] += 1

        # ── Rule-level (within a shared ruleset) ─────────────────────────────
        d_rules, a_rules = _index_rules(d_rs), _index_rules(a_rs)
        rs_name = d_rs.get("name", a_rs.get("name", ""))
        for rid in d_rules.keys() - a_rules.keys():
            s["rules_added"] += 1
            rule_rows.append({"change_type": "added", "ruleset_name": rs_name,
                              "rule_id": rid, "field": "*",
                              "draft_value": "rule", "active_value": "", **_blank()})
        for rid in a_rules.keys() - d_rules.keys():
            s["rules_removed"] += 1
            rule_rows.append({"change_type": "removed", "ruleset_name": rs_name,
                              "rule_id": rid, "field": "*",
                              "draft_value": "", "active_value": "rule", **_blank()})
        for rid in d_rules.keys() & a_rules.keys():
            df_r, af_r = _rule_fields(d_rules[rid]), _rule_fields(a_rules[rid])
            rule_modified = False
            for field in df_r:
                if df_r[field] != af_r[field]:
                    rule_modified = True
                    rule_rows.append({"change_type": "modified", "ruleset_name": rs_name,
                                      "rule_id": rid, "field": field,
                                      "draft_value": df_r[field],
                                      "active_value": af_r[field], **_blank()})
            if rule_modified:
                s["rules_modified"] += 1

    s["total_changes"] = (s["rulesets_added"] + s["rulesets_removed"] + s["rulesets_modified"]
                          + s["rules_added"] + s["rules_removed"] + s["rules_modified"])

    return {
        "ruleset_changes": pd.DataFrame(rs_rows, columns=_RULESET_COLS),
        "rule_changes": pd.DataFrame(rule_rows, columns=_RULE_COLS),
        "summary": s,
    }
