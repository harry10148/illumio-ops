"""Quarantine (spec §6.5.1 防堵, P6d): only the Quarantine label changes on a workload, and which policy refers to each
level — the rule set shapes are the PCE's own (lab 2026-10-31: an unscoped "Quarantine" rule set with two override
deny rules on Severe; Mild and Moderate referred to by nothing)."""
from illumio_ops.domain.quarantine import LEVELS, level_states, policy_refs, relabel

MILD, MOD, SEV = "/orgs/1/labels/232", "/orgs/1/labels/133", "/orgs/1/labels/134"
HREFS = {"Mild": MILD, "Moderate": MOD, "Severe": SEV}
APP = {"href": "/orgs/1/labels/49", "key": "app", "value": "Jumpdesk"}
ENV = {"href": "/orgs/1/labels/7", "key": "env", "value": "Prod"}


def test_relabel_adds_one_level_and_keeps_the_rest():
    labels = [APP, ENV, {"href": MILD, "key": "Quarantine", "value": "Mild"}]
    assert relabel(labels, SEV, set(HREFS.values())) == [{"href": APP["href"]}, {"href": ENV["href"]}, {"href": SEV}]


def test_relabel_removes_a_quarantine_label_it_does_not_know_by_href():
    # a level created after the check (another href) still goes: the key says what it is
    labels = [APP, {"href": "/orgs/1/labels/999", "key": "Quarantine", "value": "Custom"}]
    assert relabel(labels, None, set(HREFS.values())) == [{"href": APP["href"]}]


def test_relabel_remove_keeps_everything_else():
    labels = [APP, ENV, {"href": SEV, "key": "Quarantine", "value": "Severe"}]
    assert relabel(labels, None, set(HREFS.values())) == [{"href": APP["href"]}, {"href": ENV["href"]}]


LAB_SET = {
    "href": "/orgs/1/sec_policy/active/rule_sets/100", "name": "Quarantine", "enabled": True, "scopes": [[]],
    "rules": [],
    "deny_rules": [
        {"href": "/orgs/1/sec_policy/active/rule_sets/100/deny_rules/293", "enabled": True, "override": True,
         "consumers": [{"label": {"href": APP["href"]}}, {"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/126"}}],
         "providers": [{"label": {"href": SEV}}],
         "ingress_services": [{"href": "/orgs/1/sec_policy/active/services/1"}]},
        {"href": "/orgs/1/sec_policy/active/rule_sets/100/deny_rules/237", "enabled": True, "override": True,
         "consumers": [{"label": {"href": SEV}}],
         "providers": [{"actors": "ams"}, {"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/1"}}],
         "ingress_services": [{"href": "/orgs/1/sec_policy/active/services/1"}]}]}


def test_policy_refs_lab_shape():
    refs = policy_refs([LAB_SET], HREFS)
    assert refs["Mild"] == [] and refs["Moderate"] == []
    inbound, outbound = sorted(refs["Severe"], key=lambda r: r.side, reverse=True)
    assert (inbound.side, inbound.rule_type, inbound.ruleset, inbound.enabled) == ("provider", "override_deny",
                                                                                     "Quarantine", True)
    assert inbound.consumers == [APP["href"], "/orgs/1/sec_policy/active/ip_lists/126"]
    assert (outbound.side, outbound.providers) == ("consumer", ["all_workloads", "/orgs/1/sec_policy/active/ip_lists/1"])
    assert outbound.services == ["/orgs/1/sec_policy/active/services/1"]


def test_policy_refs_scope_and_allow_rule():
    rs = {"name": "Q-scope", "enabled": True, "scopes": [[{"label": {"href": MOD}}]],
          "rules": [{"enabled": True, "consumers": [{"label": {"href": MILD}}], "providers": [{"actors": "ams"}],
                     "ingress_services": [{"port": 53, "proto": 17}]}], "deny_rules": []}
    refs = policy_refs([rs], HREFS)
    assert [(r.rule_type, r.side) for r in refs["Moderate"]] == [("scope", "scope")]
    [allow] = refs["Mild"]
    assert (allow.rule_type, allow.side, allow.services) == ("allow", "consumer", ["53/17"])


def test_level_states():
    active = policy_refs([LAB_SET], HREFS)
    none = policy_refs([], HREFS)
    assert level_states(active=active, draft=active) == {"Mild": "none", "Moderate": "none", "Severe": "active"}
    # the rule set is turned off (lab: a 5.x schedule turns it on and off): the label goes on and nothing isolates
    off = policy_refs([{**LAB_SET, "enabled": False}], HREFS)
    assert level_states(active=off, draft=off)["Severe"] == "disabled"
    rule_off = policy_refs([{**LAB_SET, "deny_rules": [{**r, "enabled": False} for r in LAB_SET["deny_rules"]]}], HREFS)
    assert level_states(active=rule_off, draft=rule_off)["Severe"] == "disabled"
    # only in draft: not provisioned yet
    assert level_states(active=none, draft=active)["Severe"] == "draft_only"
    assert set(LEVELS) == {"Mild", "Moderate", "Severe"}
