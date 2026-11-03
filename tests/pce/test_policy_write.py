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
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy/draft/dependencies",
                  json={"ip_lists": [{"href": "/orgs/1/sec_policy/draft/ip_lists/7"}],
                        "rule_sets": [{"href": pw.ruleset_of(RS)}]})
    with pytest.raises(pw.DependenciesPending) as e:
        pw.provision(client, pw.ruleset_of(RS), "illumio-ops rule schedule")
    assert e.value.hrefs == ["/orgs/1/sec_policy/draft/ip_lists/7"]
    assert not any(c.request.url.endswith("/sec_policy") for c in responses.calls)


@responses.activate
def test_provision_only_the_rule_set(client):
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy/draft/dependencies", json={})
    responses.add(responses.POST, f"{API}/orgs/1/sec_policy", status=201, json={})
    assert pw.provision(client, pw.ruleset_of(RS), "illumio-ops rule schedule").status == 201
    body = json.loads(responses.calls[1].request.body)
    assert body["change_subset"] == {"rule_sets": [{"href": pw.ruleset_of(RS)}]}
