"""PCE Rule Search (recovered from 5.x api_client.rule_search and policy_explain, 5.x aa81f477): the six
responses recorded on lab, parsed into rules."""
import json
import time
from pathlib import Path

import pytest
import responses

from illumio_ops.domain.policy import iplist_href_for_ip, parse_rule_search
from illumio_ops.domain.values import RuleAction
from illumio_ops.pce.rule_search import RULE_TYPES, rule_search

from .conftest import BASE

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "rule_search"


def _fx(name):
    return json.loads((FIX / f"{name}.json").read_text())


@responses.activate
@pytest.mark.parametrize("name", ["allow_hit", "no_match", "iplist_actor", "k8s_actor", "swapped_miss"])
def test_recorded_requests_and_answers(client, name):
    fx = _fx(name)
    req = fx["request"]
    responses.add(responses.POST, f"{BASE}/api/v2/orgs/1/sec_policy/{fx['pversion']}/rule_search",
                  json=fx["response"], status=fx["status"])
    port, proto = req["ingress_services"][0]["port"], req["ingress_services"][0]["proto"]
    r = rule_search(client, consumers=req.get("consumers"), providers=req.get("providers"), port=port, proto=proto,
                    pversion=fx["pversion"], deadline=time.monotonic() + 30)
    sent = json.loads(responses.calls[0].request.body)
    assert sent == {k: v for k, v in req.items() if k in ("consumers", "providers", "ingress_services", "rule_types")}
    assert r.status == 200 and r.error is None
    rules = parse_rule_search(r.body)
    counts = fx["response"]["counts"]
    assert len([x for x in rules if x.rule_type is RuleAction.ALLOW]) == counts["sec_rules"]["matched"]


def test_allow_hit_is_parsed_with_its_rule_set_and_labels():
    rules = parse_rule_search(_fx("allow_hit")["response"])
    [allow] = [r for r in rules if r.rule_type is RuleAction.ALLOW]
    assert allow.href.endswith("/sec_rules/1733") and allow.ruleset_name and allow.ruleset_href.startswith("/orgs/")
    assert [(a.kind, a.key, a.value) for a in allow.consumers] == [("label", "role", "Web")]
    assert [(s.port, s.proto) for s in allow.services] == [(22, 6)]


@responses.activate
def test_pce_error_body_is_reported(client):
    fx = _fx("schema_error_destinations")
    responses.add(responses.POST, f"{BASE}/api/v2/orgs/1/sec_policy/active/rule_search", json=fx["response"],
                  status=406)
    r = rule_search(client, consumers=None, providers=[{"label": {"href": "/orgs/1/labels/1"}}], port=22, proto=6,
                    pversion="active", deadline=time.monotonic() + 30)
    assert r.status == 406 and "input_validation_error" in r.error and r.body is not None


def test_rule_types_and_bad_version():
    assert RULE_TYPES == ["sec_rules", "deny_rules", "override_deny_rules"]
    with pytest.raises(ValueError):
        rule_search(None, consumers=None, providers=None, port=1, proto=6, pversion="live", deadline=0)


def test_iplist_resolution_picks_the_narrowest_and_honours_exclusions():
    lists = [
        {"href": "/ipl/any", "ip_ranges": [{"from_ip": "0.0.0.0/0"}]},
        {"href": "/ipl/corp", "ip_ranges": [{"from_ip": "192.168.0.0/16"},
                                            {"from_ip": "192.168.99.0/24", "exclusion": True}]},
        {"href": "/ipl/site", "ip_ranges": [{"from_ip": "192.168.5.0", "to_ip": "192.168.5.255"}]},
        {"href": "/ipl/fqdn", "ip_ranges": [], "fqdns": [{"fqdn": "x.example"}]},
    ]
    assert iplist_href_for_ip(lists, "192.168.5.5") == "/ipl/site"
    assert iplist_href_for_ip(lists, "192.168.7.7") == "/ipl/corp"
    assert iplist_href_for_ip(lists, "192.168.99.5") == "/ipl/any"  # excluded from corp: only Any covers it
    assert iplist_href_for_ip(lists, "8.8.8.8") == "/ipl/any"
    assert iplist_href_for_ip(lists, "not-an-ip") is None
