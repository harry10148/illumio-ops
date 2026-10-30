"""Policy resolver service (P5c-4): the active policy read live and expanded, with the total row cap disclosed."""
import pytest

from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services.analysis import policy_resolver
from tests_v6.services.collect.conftest import configured_ctx

A = "/orgs/1/sec_policy/active"
WEB, DB = "/orgs/1/labels/1", "/orgs/1/labels/2"
SETS = [{"href": f"{A}/rule_sets/1", "name": "Web", "enabled": True, "scopes": [[]], "rules": [
    {"href": f"{A}/rule_sets/1/sec_rules/1", "enabled": True, "consumers": [{"label": {"href": WEB}}],
     "providers": [{"label": {"href": DB}}], "ingress_services": [{"port": 1433, "proto": 6}]}], "deny_rules": []}]
WORKLOADS = [{"href": "/orgs/1/workloads/a", "interfaces": [{"address": "10.0.0.1"}], "labels": [{"href": WEB}]},
             {"href": "/orgs/1/workloads/b", "interfaces": [{"address": "10.0.0.2"}], "labels": [{"href": DB}]},
             {"href": "/orgs/1/workloads/u", "managed": False, "public_ip": "203.0.113.5", "labels": [{"href": DB}]}]


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    state = {"fail": None}

    def rule_sets(client, pversion, *, deadline):
        if state["fail"]:
            raise state["fail"]
        assert pversion == "active"
        return SETS
    monkeypatch.setattr(policy_resolver, "fetch_rule_sets", rule_sets)
    monkeypatch.setattr(policy_resolver, "fetch_objects", lambda client, pversion, kind, *, deadline: [])
    monkeypatch.setattr(policy_resolver, "get_all", lambda client, path, *, params, deadline: WORKLOADS)
    c = configured_ctx(tmp_path)
    c._state = state
    return c


def test_rows_from_live_policy(ctx):
    r = policy_resolver.resolve(ctx)
    assert {(x["src_ip"], x["dst_ip"], x["port"], x["protocol"]) for x in r.rows} == {
        ("10.0.0.1", "10.0.0.2", 1433, "TCP"), ("10.0.0.1", "203.0.113.5", 1433, "TCP")}
    assert r.per_ruleset == {"Web": 2} and r.rule_count == 1 and r.rows_omitted == 0


def test_total_cap_notice_row(ctx, monkeypatch):
    monkeypatch.setattr(policy_resolver, "MAX_TOTAL_ROWS", 1)
    r = policy_resolver.resolve(ctx)
    # a rule that does not fit is left out whole (counted, never built): no half rule reaches a firewall import
    assert r.rows_omitted == 2 and r.truncated_rulesets == ["Web"] and len(r.rows) == 1
    assert r.rows[-1]["truncated"] == "total_row_cap" and "about 2 rows omitted" in r.rows[-1]["src_ip"]


def test_fetch_failure_raises(ctx):
    ctx._state["fail"] = PceCollectionIncomplete("/sec_policy/active/rule_sets", 0, "HTTP 500")
    with pytest.raises(PceCollectionIncomplete):
        policy_resolver.resolve(ctx)
