"""Policy Usage：多 scope 規則集、scope 內的 All Workloads、停用的規則。"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.api_client import ApiClient
from src.report.policy_usage_generator import build_rule_baseline

L_APP_A = {"href": "/orgs/1/labels/11"}
L_APP_B = {"href": "/orgs/1/labels/12"}
L_ROLE_DB = {"href": "/orgs/1/labels/21"}


def _client():
    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.example.com:8443", "org_id": "1",
                         "key": "k", "secret": "s", "verify_ssl": True}}
    c = ApiClient(cm)
    c.label_cache.update({
        "/orgs/1/labels/11": "app:A", "/orgs/1/labels/12": "app:B", "/orgs/1/labels/21": "role:db",
    })
    return c


def _ruleset(**rule):
    return {
        "href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "rs",
        "scopes": [[{"label": L_APP_A}], [{"label": L_APP_B}]],
        "rules": [{"href": "/orgs/1/sec_policy/draft/rule_sets/1/sec_rules/1",
                   "consumers": [{"label": L_ROLE_DB}], "providers": [{"label": L_ROLE_DB}],
                   "ingress_services": [], **rule}],
    }


def test_every_scope_is_queried():
    rules, _ = build_rule_baseline([_ruleset()])
    payload = _client()._build_rule_query_payload(rules[0], "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z")
    dst = payload["destinations"]["include"]
    assert [{"label": L_APP_A}, {"label": L_ROLE_DB}] in dst
    assert [{"label": L_APP_B}, {"label": L_ROLE_DB}] in dst


def test_all_workloads_is_limited_to_the_scope():
    rules, _ = build_rule_baseline([_ruleset(consumers=[{"actors": "ams"}])])
    payload = _client()._build_rule_query_payload(rules[0], "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z")
    src = payload["sources"]["include"]
    assert [{"actors": "ams"}] not in src
    assert [{"label": L_APP_A}] in src and [{"label": L_APP_B}] in src


def test_unscoped_all_workloads_stays_global():
    rules, _ = build_rule_baseline([_ruleset(consumers=[{"actors": "ams"}], unscoped_consumers=True)])
    payload = _client()._build_rule_query_payload(rules[0], "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z")
    assert payload["sources"]["include"] == [[{"actors": "ams"}]]


def test_disabled_rules_are_marked():
    rs = _ruleset(enabled=False)
    rules, _ = build_rule_baseline([rs, dict(_ruleset(), enabled=False, href="/x/2")])
    assert [r["_rule_enabled"] for r in rules] == [False, False]
    rules, _ = build_rule_baseline([_ruleset()])
    assert rules[0]["_rule_enabled"] is True
