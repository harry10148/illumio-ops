"""Phase 3A Task 4 — ApiClient.rule_search: URL, method, and error-body passthrough."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def api_client():
    """Same shape as tests/test_api_client_request_contract.py's fixture."""
    from src.api_client import ApiClient
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "test-key", "secret": "test-secret", "verify_ssl": False}}
    return ApiClient(cm)


def _capture(api_client, status, body):
    calls = []

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return status, body

    api_client._request = fake_request
    return calls


def test_rule_search_posts_to_versioned_endpoint(api_client):
    calls = _capture(api_client, 200, json.dumps({"sec_rules": [], "deny_rules": []}).encode())
    status, data = api_client.rule_search({"providers": []}, pversion="active")
    assert status == 200 and data == {"sec_rules": [], "deny_rules": []}
    url, kw = calls[0]
    org = api_client.api_cfg["org_id"]
    assert url.endswith(f"/api/v2/orgs/{org}/sec_policy/active/rule_search")
    assert kw["method"] == "POST" and kw["data"] == {"providers": []}
    assert kw["timeout"] == 30


def test_rule_search_draft_and_invalid_pversion(api_client):
    calls = _capture(api_client, 200, b"{}")
    api_client.rule_search({}, pversion="draft")
    assert "/sec_policy/draft/rule_search" in calls[0][0]
    with pytest.raises(ValueError):
        api_client.rule_search({}, pversion="live")


def test_rule_search_returns_parsed_error_body_on_4xx(api_client):
    _capture(api_client, 406, json.dumps([{"token": "invalid_uri", "message": "bad href"}]).encode())
    status, data = api_client.rule_search({"providers": [{"label": {"href": "x"}}]})
    assert status == 406
    assert data == [{"token": "invalid_uri", "message": "bad href"}]


def test_rule_search_non_json_body_and_transport_failure(api_client):
    _capture(api_client, 502, b"<html>gateway</html>")
    status, data = api_client.rule_search({})
    assert status == 502 and data == "<html>gateway</html>"

    def boom(url, **kw):
        raise ConnectionError("down")

    api_client._request = boom
    assert api_client.rule_search({}) == (0, None)


# ── recorded lab responses (tools/probe_rule_search.py, 2026-09-03) ──────────

def _fixture(name):
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures" / "pce_rule_search" / f"{name}.json").read_text())


def test_recorded_hit_shape_is_what_policy_explain_expects():
    hit = _fixture("allow_hit")
    assert hit["request"]["consumers"] and hit["request"]["providers"]
    resp = hit["response"]
    assert set(resp) == {"counts", "sec_rules", "deny_rules", "override_deny_rules", "ip_tables_rules"}
    rule = resp["sec_rules"][0]
    assert rule["href"].startswith("/orgs/") and "rule_set" in rule
    assert rule["consumers"][0]["label"]["key"] and "exclusion" in rule["consumers"][0]
    assert rule["ingress_services"][0] == {"port": 22, "proto": 6}
    assert set(rule["rule_set"]) >= {"href", "name", "enabled", "scopes", "update_type"}
    assert _fixture("no_match")["response"]["sec_rules"] == []
    assert _fixture("swapped_miss")["response"]["counts"]["sec_rules"]["matched"] == 0


def test_recorded_schema_error_names_the_rejected_field():
    err = _fixture("schema_error_destinations")
    assert err["status"] == 406 and "destinations" in json.dumps(err["response"])
