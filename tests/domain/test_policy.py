"""Rules by href, and what a draft recompute says about one flow (spec §6.6 F1, P3 Task 0 shapes)."""
import json
from pathlib import Path

from illumio_ops.domain.policy import index_rules, parse_draft
from illumio_ops.domain.values import RuleAction

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "pce"
RULE_SETS = json.loads((FIX / "rule_sets_draft.json").read_text())
ROWS = json.loads((FIX / "draft_rows.json").read_text())
TEDT_DENY = "/orgs/1/sec_policy/draft/rule_sets/673/deny_rules/309"


def test_index_rules_allow_deny_override():
    rules = index_rules(RULE_SETS, labels={"/orgs/1/labels/21": ("env", "Server")},
                        names={"/orgs/1/sec_policy/draft/services/1": "All Services"})
    deny = rules[TEDT_DENY]
    assert (deny.rule_type, deny.ruleset_name, deny.enabled) == (RuleAction.DENY, "tedt", True)
    assert [(a.kind, a.key, a.value) for a in deny.consumers] == [("label", "env", "Server")]
    assert [s.name for s in deny.services] == ["All Services"]
    override = rules["/orgs/1/sec_policy/draft/rule_sets/100/deny_rules/293"]
    assert override.rule_type is RuleAction.OVERRIDE_DENY
    assert [(a.kind, a.exclusion) for a in override.consumers] == [("label", True), ("ip_list", False)]
    allow = rules["/orgs/1/sec_policy/draft/rule_sets/671/sec_rules/1757"]
    assert allow.rule_type is RuleAction.ALLOW and [a.kind for a in allow.consumers] == ["all_workloads"]
    assert [(s.port, s.proto) for s in allow.services] == [(8787, 6)]
    # a deny rule given in the rule_type form (as some views of the API send it) reads the same
    alt = index_rules([{"href": "/rs/9", "name": "x", "rules": [], "deny_rules": [
        {"href": "/rs/9/deny_rules/1", "rule_type": "override_deny", "consumers": [], "providers": [],
         "ingress_services": []}]}])
    assert alt["/rs/9/deny_rules/1"].rule_type is RuleAction.OVERRIDE_DENY


def test_parse_draft_boundary_href():
    v = parse_draft(next(r for r in ROWS if r["draft_policy_decision"] == "blocked_by_boundary"))
    assert v.draft_decision == "blocked_by_boundary" and v.deny_rule_hrefs == (TEDT_DENY,)
    assert v.allow_rule_hrefs == () and v.essential_service_rules == ()


def test_parse_draft_essential_service_rule():
    v = parse_draft(next(r for r in ROWS if r["draft_policy_decision"] == "allowed"))
    assert v.draft_decision == "allowed" and v.essential_service_rules and not v.deny_rule_hrefs
    with_href = parse_draft({"draft_policy_decision": "allowed", "rules": [{"href": "/x/sec_rules/1"}]})
    assert with_href.allow_rule_hrefs == ("/x/sec_rules/1",)


def test_parse_draft_unknown_decision_passes_through():
    v = parse_draft({"draft_policy_decision": "Potentially_Blocked_By_Something_New",
                     "override_deny_rules": [{"href": "/od/1"}]})
    assert v.draft_decision == "potentially_blocked_by_something_new" and v.override_deny_hrefs == ("/od/1",)
    assert parse_draft({}).draft_decision == "unknown"
