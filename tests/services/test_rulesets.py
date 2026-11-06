"""Rule set browsing (5.x #/policy/rulesets; parity 2026-11-06): the active rule sets with their allow and deny rules,
read-only, described by the PCE's own names, with which have a pending draft and which are scheduled."""
import re

import pytest
import responses

from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services import rulesets
from tests.services.collect.conftest import configured_ctx

ORG = "https://pce.example.com:8443/api/v2/orgs/1"
RS = "/orgs/1/sec_policy/active/rule_sets/5"
R9 = RS + "/sec_rules/9"
D3 = RS + "/deny_rules/3"
LBL = "/orgs/1/labels/3"


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path, mode="full")


def _pce(active_status=200):
    allow = {"href": R9, "enabled": True, "description": "backups to NAS", "consumers": [{"label": {"href": LBL}}],
             "providers": [{"actors": "ams"}], "ingress_services": [{"port": 445, "proto": 6}]}
    deny = {"href": D3, "enabled": False, "override": True, "consumers": [{"actors": "ams"}],
            "providers": [{"label": {"href": LBL}}], "ingress_services": [{"port": 3389, "proto": 6}]}
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/active/rule_sets\?.*"), status=active_status,
                  json=[{"href": RS, "name": "Backups", "enabled": True, "description": "nightly", "rules": [allow],
                         "deny_rules": [deny]}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/draft/rule_sets\?.*"),
                  json=[{"href": RS.replace("active", "draft"), "update_type": "update", "rules": [], "deny_rules": []}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/labels\?.*"),
                  json=[{"href": LBL, "key": "app", "value": "backup"}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/active/ip_lists\?.*"), json=[])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/active/services\?.*"), json=[])


@responses.activate
def test_lists_every_rule_set_with_allow_and_deny_rules(ctx):
    _pce()
    view = rulesets.browse(ctx, "")
    [rs] = view.items
    assert (rs.name, rs.enabled, rs.description, rs.draft_pending) == ("Backups", True, "nightly", True)
    allow, deny = rs.rules
    assert (allow.kind, allow.label, allow.enabled, allow.description) == ("allow", "#9", True, "backups to NAS")
    assert allow.summary == "app=backup → All workloads: 445/TCP"
    assert (deny.kind, deny.enabled) == ("override_deny", False) and deny.summary.endswith("3389/TCP")
    assert view.limited is False and view.total == 1
    assert "name=" not in responses.calls[0].request.url  # no filter: every rule set


@responses.activate
def test_name_filter_is_passed_to_the_pce(ctx):
    _pce()
    rulesets.browse(ctx, "back")
    assert "name=back" in responses.calls[0].request.url


@responses.activate
def test_a_pce_failure_is_raised_not_shown_as_empty(ctx):
    _pce(active_status=500)
    with pytest.raises(PceCollectionIncomplete):
        rulesets.browse(ctx, "")
