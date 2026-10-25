"""Policy objects read from the PCE: rule sets with their deny rules, and the names their actors refer to."""
import time

import responses

from illumio_ops.pce.policy import fetch_policy_names, fetch_rule_sets

from .conftest import BASE

ORG = f"{BASE}/api/v2/orgs/1"


def _deadline():
    return time.monotonic() + 60


@responses.activate
def test_ruleset_without_inline_deny_rules_fetches_them(client):
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/rule_sets", json=[
        {"href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "inline", "rules": [], "deny_rules": [{"href": "x"}]},
        {"href": "/orgs/1/sec_policy/draft/rule_sets/2", "name": "separate", "rules": []}])
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/rule_sets/2/deny_rules",
                  json=[{"href": "/orgs/1/sec_policy/draft/rule_sets/2/deny_rules/9", "override": False}])
    sets = fetch_rule_sets(client, "draft", deadline=_deadline())
    assert [len(s["deny_rules"]) for s in sets] == [1, 1]
    assert sets[1]["deny_rules"][0]["href"].endswith("/deny_rules/9")
    assert len(responses.calls) == 2


@responses.activate
def test_policy_names_cover_labels_ip_lists_services_and_label_groups(client):
    responses.add(responses.GET, f"{ORG}/labels", json=[{"href": "/orgs/1/labels/21", "key": "env", "value": "Server"}])
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/ip_lists",
                  json=[{"href": "/orgs/1/sec_policy/draft/ip_lists/1", "name": "Any (0.0.0.0/0 and ::/0)"}])
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/services",
                  json=[{"href": "/orgs/1/sec_policy/draft/services/1", "name": "All Services"}])
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/label_groups",
                  json=[{"href": "/orgs/1/sec_policy/draft/label_groups/3", "name": "Prod apps"}])
    names = fetch_policy_names(client, "draft", deadline=_deadline())
    assert names.labels == {"/orgs/1/labels/21": ("env", "Server")}
    assert names.names["/orgs/1/sec_policy/draft/services/1"] == "All Services"
    assert names.names["/orgs/1/sec_policy/draft/label_groups/3"] == "Prod apps"


@responses.activate
def test_failed_deny_rule_read_is_an_error_not_an_empty_list(client):
    # Final review #16: a 500 on the per-rule-set read looked like "this rule set has no deny rules".
    import pytest

    from illumio_ops.pce.collections import PceCollectionIncomplete
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/rule_sets", json=[
        {"href": "/orgs/1/sec_policy/draft/rule_sets/2", "name": "separate", "rules": []}])
    responses.add(responses.GET, f"{ORG}/sec_policy/draft/rule_sets/2/deny_rules", status=500, json={})
    with pytest.raises(PceCollectionIncomplete):
        fetch_rule_sets(client, "draft", deadline=_deadline())
