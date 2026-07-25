"""Tests for the DRAFT-vs-ACTIVE policy diff engine (pure, no I/O)."""
from __future__ import annotations

from src.report.analysis.policy_diff.diff_engine import diff_rulesets


def _rs(rs_id, name, rules, enabled=True, description=""):
    return {
        "href": f"/orgs/1/sec_policy/draft/rule_sets/{rs_id}",
        "name": name,
        "enabled": enabled,
        "description": description,
        "rules": rules,
    }


def _rule(rule_id, *, enabled=True, providers=None, consumers=None, services=None):
    return {
        "href": f"/orgs/1/sec_policy/draft/rule_sets/9/sec_rules/{rule_id}",
        "enabled": enabled,
        "providers": providers or [],
        "consumers": consumers or [],
        "ingress_services": services or [],
    }


def test_added_and_removed_rulesets():
    draft = [_rs(1, "RS-A", []), _rs(2, "RS-NEW", [])]
    active = [_rs(1, "RS-A", []), _rs(3, "RS-GONE", [])]
    out = diff_rulesets(draft, active)
    rs = out["ruleset_changes"]
    changes = {(r["change_type"], r["ruleset_name"]) for r in rs.to_dict("records")}
    assert ("added", "RS-NEW") in changes
    assert ("removed", "RS-GONE") in changes
    assert out["summary"]["rulesets_added"] == 1
    assert out["summary"]["rulesets_removed"] == 1


def test_modified_ruleset_field_level():
    draft = [_rs(1, "RS-A", [], enabled=False)]
    active = [_rs(1, "RS-A", [], enabled=True)]
    out = diff_rulesets(draft, active)
    rows = out["ruleset_changes"].to_dict("records")
    enabled_rows = [r for r in rows if r["field"] == "enabled"]
    assert len(enabled_rows) == 1
    assert enabled_rows[0]["change_type"] == "modified"
    assert enabled_rows[0]["draft_value"] == "False"
    assert enabled_rows[0]["active_value"] == "True"


def test_modified_rule_provider_change():
    d_rule = _rule(5, providers=[{"label": {"href": "/labels/100"}}])
    a_rule = _rule(5, providers=[{"label": {"href": "/labels/200"}}])
    draft = [_rs(9, "RS-R", [d_rule])]
    active = [_rs(9, "RS-R", [a_rule])]
    out = diff_rulesets(draft, active)
    rows = out["rule_changes"].to_dict("records")
    prov_rows = [r for r in rows if r["field"] == "providers"]
    assert len(prov_rows) == 1
    assert "/labels/100" in prov_rows[0]["draft_value"]
    assert "/labels/200" in prov_rows[0]["active_value"]
    assert out["summary"]["rules_modified"] == 1


def test_provider_order_is_not_a_false_diff():
    items_a = [{"label": {"href": "/labels/1"}}, {"label": {"href": "/labels/2"}}]
    items_b = [{"label": {"href": "/labels/2"}}, {"label": {"href": "/labels/1"}}]
    draft = [_rs(9, "RS-R", [_rule(5, providers=items_a)])]
    active = [_rs(9, "RS-R", [_rule(5, providers=items_b)])]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rules_modified"] == 0


def test_empty_inputs_return_valid_empty_structure():
    out = diff_rulesets([], [])
    assert out["summary"]["total_changes"] == 0
    assert out["ruleset_changes"].empty
    assert out["rule_changes"].empty


def test_description_change_detected():
    draft = [_rs(1, "RS-A", [], description="new desc")]
    active = [_rs(1, "RS-A", [], description="")]
    out = diff_rulesets(draft, active)
    rows = [r for r in out["ruleset_changes"].to_dict("records") if r["field"] == "description"]
    assert len(rows) == 1
    assert rows[0]["change_type"] == "modified"
    assert rows[0]["draft_value"] == "new desc"
    assert rows[0]["active_value"] == ""


def test_ruleset_modified_and_rule_added_both_counted():
    # Same ruleset id: enabled flips (modified) AND a rule exists only in draft (added).
    draft = [_rs(1, "RS-A", [_rule(5)], enabled=False)]
    active = [_rs(1, "RS-A", [], enabled=True)]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rulesets_modified"] == 1
    assert out["summary"]["rules_added"] == 1


def test_summarize_actors_uses_friendly_names():
    from src.report.analysis.policy_diff.diff_engine import _summarize_actors

    names = {
        "/orgs/1/sec_policy/active/ip_lists/1": "Any (0.0.0.0/0)",
        "/orgs/1/sec_policy/active/services/9": "HTTPS 443",
    }
    items = [
        {"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/1"}},
        {"href": "/orgs/1/sec_policy/active/services/9"},
    ]
    out = _summarize_actors(items, names=names)
    assert "Any (0.0.0.0/0)" in out
    assert "HTTPS 443" in out
    assert "/orgs/1/" not in out  # 不再出現原始 href


def test_summarize_actors_falls_back_to_href_without_names():
    from src.report.analysis.policy_diff.diff_engine import _summarize_actors

    out = _summarize_actors([{"href": "/orgs/1/sec_policy/active/services/9"}])
    assert "/orgs/1/sec_policy/active/services/9" in out


def test_summarize_actors_resolves_label_group_names():
    from src.report.analysis.policy_diff.diff_engine import _summarize_actors

    names = {"/orgs/1/sec_policy/active/label_groups/3": "Prod-Web-Group"}
    out = _summarize_actors([{"label_group": {"href": "/orgs/1/sec_policy/active/label_groups/3"}}], names=names)
    assert "label_group:Prod-Web-Group" in out
    assert "/orgs/1/" not in out


# ── Deny / Override-Deny rules must be diffed too ────────────────────────────

def _deny_rule(rule_id, *, override=False, enabled=True, providers=None,
               consumers=None, services=None):
    return {
        "href": f"/orgs/1/sec_policy/draft/rule_sets/9/deny_rules/{rule_id}",
        "override": override,
        "enabled": enabled,
        "providers": providers or [],
        "consumers": consumers or [],
        "ingress_services": services or [],
    }


def _rs_with_deny(rs_id, name, rules, deny_rules):
    rs = _rs(rs_id, name, rules)
    rs["deny_rules"] = deny_rules
    return rs


def test_added_override_deny_rule_is_reported():
    """新增的 Override Deny 規則必須出現在 diff（先前恆為 total_changes=0）。"""
    draft = [_rs_with_deny(9, "RS-R", [], [_deny_rule(7, override=True)])]
    active = [_rs_with_deny(9, "RS-R", [], [])]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rules_added"] == 1
    assert out["summary"]["total_changes"] > 0
    rows = out["rule_changes"].to_dict("records")
    added = [r for r in rows if r["change_type"] == "added"]
    assert len(added) == 1
    assert added[0]["rule_id"] == "deny_rules/7"
    assert added[0]["draft_value"] == "Override Deny"


def test_removed_deny_rule_is_reported():
    draft = [_rs_with_deny(9, "RS-R", [], [])]
    active = [_rs_with_deny(9, "RS-R", [], [_deny_rule(7)])]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rules_removed"] == 1
    removed = [r for r in out["rule_changes"].to_dict("records")
               if r["change_type"] == "removed"]
    assert removed[0]["rule_id"] == "deny_rules/7"
    assert removed[0]["active_value"] == "Deny"


def test_deny_rule_field_change_is_reported():
    draft = [_rs_with_deny(9, "RS-R", [], [_deny_rule(7, providers=[{"label": {"href": "/labels/100"}}])])]
    active = [_rs_with_deny(9, "RS-R", [], [_deny_rule(7, providers=[{"label": {"href": "/labels/200"}}])])]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rules_modified"] == 1
    prov = [r for r in out["rule_changes"].to_dict("records") if r["field"] == "providers"]
    assert len(prov) == 1
    assert "/labels/100" in prov[0]["draft_value"]


def test_deny_promoted_to_override_deny_is_reported():
    """Deny → Override Deny 是語意升級，必須以 rule_type 欄位變更呈現。"""
    draft = [_rs_with_deny(9, "RS-R", [], [_deny_rule(7, override=True)])]
    active = [_rs_with_deny(9, "RS-R", [], [_deny_rule(7, override=False)])]
    out = diff_rulesets(draft, active)
    rows = [r for r in out["rule_changes"].to_dict("records") if r["field"] == "rule_type"]
    assert len(rows) == 1
    assert rows[0]["draft_value"] == "Override Deny"
    assert rows[0]["active_value"] == "Deny"


def test_allow_and_deny_ids_do_not_collide():
    """sec_rules/3 與 deny_rules/3 是不同規則，不可被當成同一條而互相對齊。"""
    draft = [_rs_with_deny(9, "RS-R", [_rule(3)], [])]
    active = [_rs_with_deny(9, "RS-R", [], [_deny_rule(3)])]
    out = diff_rulesets(draft, active)
    assert out["summary"]["rules_added"] == 1
    assert out["summary"]["rules_removed"] == 1
    assert out["summary"]["rules_modified"] == 0


def test_rule_count_includes_deny_rules():
    draft = [_rs_with_deny(1, "RS-A", [_rule(1)], [_deny_rule(2)])]
    active = [_rs_with_deny(1, "RS-A", [_rule(1)], [])]
    out = diff_rulesets(draft, active)
    counts = [r for r in out["ruleset_changes"].to_dict("records")
              if r["field"] == "rule_count"]
    assert len(counts) == 1
    assert (counts[0]["draft_value"], counts[0]["active_value"]) == ("2", "1")


def test_sec_rules_and_rules_keys_are_deduped():
    """同一集合的兩種 API 形狀同時出現時不得重複計數。"""
    rule = _rule(5)
    rs = {"href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "RS-A",
          "sec_rules": [rule], "rules": [rule]}
    out = diff_rulesets([rs], [rs])
    assert out["summary"]["total_changes"] == 0
