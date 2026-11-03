"""Targets for a rule schedule (UI redesign spec §4.5): active rule sets matching a name, with their rules described
by the PCE's own names, which have a pending draft, and which already have a schedule."""
import re
from datetime import UTC, datetime

import pytest
import responses

from illumio_ops.services import rule_schedule_targets as targets
from illumio_ops.store import rule_schedules as store
from tests.services.collect.conftest import configured_ctx

ORG = "https://pce.example.com:8443/api/v2/orgs/1"
RS = "/orgs/1/sec_policy/active/rule_sets/5"
R9 = RS + "/sec_rules/9"
R10 = RS + "/sec_rules/10"
LBL = "/orgs/1/labels/3"
IPL = "/orgs/1/sec_policy/active/ip_lists/7"


@pytest.fixture
def ctx(tmp_path):
    return configured_ctx(tmp_path, mode="full")


def _pce():
    rule = {"href": R9, "enabled": True, "consumers": [{"label": {"href": LBL}}],
            "providers": [{"ip_list": {"href": IPL}}], "ingress_services": [{"port": 445, "proto": 6}]}
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/active/rule_sets\?.*"),
                  json=[{"href": RS, "name": "Backups", "enabled": True,
                         "rules": [rule, {"href": R10, "enabled": False, "consumers": [{"actors": "ams"}],
                                          "providers": [{"actors": "ams"}], "ingress_services": []}]}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/draft/rule_sets\?.*"),
                  json=[{"href": RS.replace("active", "draft"), "update_type": None,
                         "rules": [{"href": R9.replace("active", "draft"), "update_type": None},
                                   {"href": R10.replace("active", "draft"), "update_type": "update"}]}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/labels\?.*"),
                  json=[{"href": LBL, "key": "app", "value": "backup"}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/active/ip_lists\?.*"),
                  json=[{"href": IPL, "name": "Backup servers"}])
    responses.add(responses.GET, re.compile(re.escape(ORG) + r"/sec_policy/active/services\?.*"), json=[])


@responses.activate
def test_search_lists_ruleset_and_rules_with_names(ctx):
    _pce()
    hits = {h.href: h for h in targets.search(ctx, "back").items}
    assert set(hits) == {RS, R9, R10}
    assert hits[RS].is_ruleset and hits[RS].name == "Backups"
    assert hits[R9].summary == "app=backup → Backup servers: 445/TCP" and hits[R9].enabled
    assert hits[R10].draft_pending and not hits[R9].draft_pending
    assert "All workloads" in hits[R10].summary


@responses.activate
def test_already_scheduled_flagged(ctx):
    _pce()
    with ctx.db() as conn:
        store.create(conn, pce_url=ctx.settings.current().pce.url, org_id="1", href=R9, is_ruleset=False, name="r9",
                     ruleset_name="Backups", summary="", plan_json="{}", paused=False, pce_status="active", by="a",
                     at=datetime.now(UTC))
        conn.commit()
    hits = {h.href: h for h in targets.search(ctx, "back").items}
    assert hits[R9].scheduled and not hits[R10].scheduled


def test_empty_query(ctx):
    assert targets.search(ctx, " ").items == []
