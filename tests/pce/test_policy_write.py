"""PCE writes for rule scheduling (UI redesign spec §4.5): draft checks, enable / description changes on the draft,
and a provision that carries the change's dependencies (5.x provision_changes)."""
import json

import pytest
import responses

from illumio_ops.pce import policy_write as pw

API = "https://pce.example.com:8443/api/v2"  # tests/pce/conftest.py client()
RS = "/orgs/1/sec_policy/active/rule_sets/5"
RULE = "/orgs/1/sec_policy/active/rule_sets/5/sec_rules/9"


def test_href_forms():
    assert pw.draft_href(RULE) == "/orgs/1/sec_policy/draft/rule_sets/5/sec_rules/9"
    assert pw.active_href(pw.draft_href(RULE)) == RULE
    assert pw.ruleset_of(RULE) == "/orgs/1/sec_policy/draft/rule_sets/5"
    assert pw.ruleset_of(RS) == "/orgs/1/sec_policy/draft/rule_sets/5"


@responses.activate
def test_draft_pending_on_the_rule_or_its_ruleset(client):
    responses.add(responses.GET, API + pw.draft_href(RULE), json={"update_type": None})
    responses.add(responses.GET, API + pw.ruleset_of(RULE), json={"update_type": "update"})
    assert pw.draft_pending(client, RULE) is True


@responses.activate
def test_no_draft_pending(client):
    responses.add(responses.GET, API + pw.draft_href(RULE), json={"update_type": None})
    responses.add(responses.GET, API + pw.ruleset_of(RULE), json={})
    assert pw.draft_pending(client, RULE) is False


@responses.activate
def test_draft_read_failure_raises(client):
    responses.add(responses.GET, API + pw.draft_href(RS), status=500, body="boom")
    with pytest.raises(pw.PolicyReadError) as e:
        pw.draft_pending(client, RS)
    assert e.value.status == 500


@responses.activate
def test_set_fields_puts_the_draft(client):
    responses.add(responses.PUT, API + pw.draft_href(RULE), status=204)
    assert pw.set_fields(client, RULE, {"enabled": False}).status == 204
    assert json.loads(responses.calls[0].request.body) == {"enabled": False}


@responses.activate
def test_provision_refuses_other_pending_objects(client):
    """Security review: provisioning the PCE's dependencies would push someone's unreviewed draft (an edited IP list)."""
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy/draft/dependencies", json=[  # as lab 26.2 answers
        {"dependency": {"ip_lists": {"href": "/orgs/1/sec_policy/draft/ip_lists/7", "caps": ["write", "provision"]}},
         "required_by": {"rule_sets": [{"href": pw.ruleset_of(RS), "caps": ["write", "provision"]}]}}])
    with pytest.raises(pw.DependenciesPending) as e:
        pw.provision(client, pw.ruleset_of(RS), "illumio-ops rule schedule")
    assert e.value.hrefs == ["/orgs/1/sec_policy/draft/ip_lists/7"]
    assert not any(c.request.url.endswith("/sec_policy") for c in responses.calls)


@responses.activate
def test_provision_only_the_rule_set(client):
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy/draft/dependencies", json=[])  # none: lab 26.2 sends []
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy", status=201, json={})
    assert pw.provision(client, pw.ruleset_of(RS), "illumio-ops rule schedule").status == 201
    body = json.loads(responses.calls[1].request.body)
    assert body["change_subset"] == {"rule_sets": [{"href": pw.ruleset_of(RS)}]}


@responses.activate
def test_the_dependency_check_names_the_commit_operation(client):
    """lab 26.2 2026-11-03: without `operation` the PCE answers 406 input_validation_error and nothing is provisioned."""
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy/draft/dependencies", json=[])
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy", status=201, json={})
    pw.provision(client, pw.ruleset_of(RS), "illumio-ops rule schedule")
    assert json.loads(responses.calls[0].request.body) == {
        "operation": "commit", "change_subset": {"rule_sets": [{"href": pw.ruleset_of(RS)}]}}


@responses.activate
def test_a_dependency_given_as_a_list_is_found_too(client):
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy/draft/dependencies", json=[
        {"dependency": {"services": [{"href": "/orgs/1/sec_policy/draft/services/3"}]},
         "required_by": {"rule_sets": [{"href": pw.ruleset_of(RS)}]}}])
    with pytest.raises(pw.DependenciesPending) as e:
        pw.provision(client, pw.ruleset_of(RS), "illumio-ops rule schedule")
    assert e.value.hrefs == ["/orgs/1/sec_policy/draft/services/3"]


@responses.activate
def test_revert_discards_only_the_rule_sets_draft(client):
    """The PCE reverts every pending object when the subset is empty, so the rule set is always named."""
    responses.add(responses.PUT, f"{API}/orgs/1/sec_policy/delete", status=204)
    assert pw.revert(client, pw.ruleset_of(RULE)).status == 204
    assert json.loads(responses.calls[0].request.body) == {
        "change_subset": {"rule_sets": [{"href": "/orgs/1/sec_policy/draft/rule_sets/5"}]}}
    with pytest.raises(ValueError):
        pw.revert(client, "")
