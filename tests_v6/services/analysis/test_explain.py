"""Policy explanation: which rules cover a flow, or every source of a workload's service."""
import json
from pathlib import Path

import responses

from illumio_ops.domain.values import RuleAction
from illumio_ops.services.analysis.explain import (
    Endpoint,
    explain_flow,
    explain_service,
)
from tests_v6.services.collect.conftest import PCE, configured_ctx

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "pce" / "rule_search"
ORG = f"{PCE['url']}/api/v2/orgs/1"
IP_LISTS = [{"href": "/orgs/1/sec_policy/active/ip_lists/any", "ip_ranges": [{"from_ip": "0.0.0.0/0"}]},
            {"href": "/orgs/1/sec_policy/active/ip_lists/corp", "ip_ranges": [{"from_ip": "10.0.0.0/8"}]}]


def _fx(name):
    return json.loads((FIX / f"{name}.json").read_text())


@responses.activate
def test_flow_with_hrefs_sends_both_sides(tmp_path):
    fx = _fx("allow_hit")
    responses.add(responses.POST, f"{ORG}/sec_policy/active/rule_search", json=fx["response"])
    r = explain_flow(configured_ctx(tmp_path), Endpoint(href="/orgs/1/workloads/w-web", ip=None),
                     Endpoint(href="/orgs/1/workloads/w-db", ip=None), 22, 6)
    sent = json.loads(responses.calls[0].request.body)
    assert sent["consumers"] == [{"workload": {"href": "/orgs/1/workloads/w-web"}}]
    assert sent["providers"] == [{"workload": {"href": "/orgs/1/workloads/w-db"}}]
    assert r.source == "pce" and r.pce_status == 200 and [x.rule_type for x in r.allow] == [RuleAction.ALLOW]
    assert r.unresolved == [] and r.partial is False


@responses.activate
def test_ip_resolved_to_ip_list(tmp_path):
    responses.add(responses.GET, f"{ORG}/sec_policy/active/ip_lists", json=IP_LISTS)
    responses.add(responses.POST, f"{ORG}/sec_policy/active/rule_search", json=_fx("no_match")["response"])
    explain_flow(configured_ctx(tmp_path), Endpoint(href=None, ip="10.9.9.9"),
                 Endpoint(href="/orgs/1/workloads/w-db", ip=None), 22, 6)
    sent = json.loads(responses.calls[-1].request.body)
    assert sent["consumers"] == [{"ip_list": {"href": "/orgs/1/sec_policy/active/ip_lists/corp"}}]


@responses.activate
def test_neither_end_resolved_no_search(tmp_path):
    responses.add(responses.GET, f"{ORG}/sec_policy/active/ip_lists", json=[])
    r = explain_flow(configured_ctx(tmp_path), Endpoint(href=None, ip="8.8.8.8"), Endpoint(href=None, ip="9.9.9.9"),
                     443, 6)
    assert r.source == "none" and r.allow == [] and r.pce_status is None
    assert r.unresolved == ["8.8.8.8", "9.9.9.9"]
    assert not any(c.request.method == "POST" for c in responses.calls)


@responses.activate
def test_service_explain_sends_providers_only(tmp_path):
    responses.add(responses.POST, f"{ORG}/sec_policy/active/rule_search", json=_fx("allow_hit")["response"])
    r = explain_service(configured_ctx(tmp_path), "/orgs/1/workloads/w-db", 3389, 6)
    sent = json.loads(responses.calls[0].request.body)
    assert "consumers" not in sent and sent["providers"] == [{"workload": {"href": "/orgs/1/workloads/w-db"}}]
    assert sent["ingress_services"] == [{"port": 3389, "proto": 6}] and r.partial is False  # any source, by design


@responses.activate
def test_pce_error_reported_not_empty(tmp_path):
    fx = _fx("schema_error_destinations")
    responses.add(responses.POST, f"{ORG}/sec_policy/active/rule_search", json=fx["response"], status=406)
    r = explain_service(configured_ctx(tmp_path), "/orgs/1/workloads/w-db", 22, 6)
    assert r.source == "pce" and r.pce_status == 406 and r.pce_error and r.allow == []


@responses.activate
def test_transport_failure_is_reported_not_swallowed(tmp_path, monkeypatch):
    import requests
    from urllib3.util.retry import Retry
    monkeypatch.setattr(Retry, "get_backoff_time", lambda self: 0.0)
    responses.add(responses.POST, f"{ORG}/sec_policy/active/rule_search", body=requests.ConnectionError("refused"))
    r = explain_service(configured_ctx(tmp_path), "/orgs/1/workloads/w-db", 22, 6)
    assert r.source == "pce" and r.pce_status is None and r.pce_error
