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
