"""The rule scheduling engine (UI redesign spec §4.5): every five minutes each schedule's desired state against the
PCE's, switched and provisioned on the write key when they differ; drafts skipped, deleted targets marked, expiries
removed only once disabled, the PCE's refusals kept as it said them."""
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
import responses

from illumio_ops.domain.rule_schedule import Expiry, Weekly
from illumio_ops.pce import policy_write as pw
from illumio_ops.services import rule_schedules as rs
from illumio_ops.store import rule_schedules as store
from tests.services.collect.conftest import configured_ctx

API = "https://pce.example.com:8443/api/v2"
NOW = datetime(2026, 11, 2, 1, tzinfo=UTC)  # Monday 09:00 in Taipei
RS = "/orgs/1/sec_policy/active/rule_sets/5"
RULE = "/orgs/1/sec_policy/active/rule_sets/5/sec_rules/9"
OTHER = "/orgs/1/sec_policy/active/rule_sets/6"
WINDOW = Weekly(days=("mon",), start="08:00", end="18:00", timezone="Asia/Taipei", action="enable_in_window")


@pytest.fixture
def ctx(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    c.settings.update(c.settings.current().revision, lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    return c


def _add(ctx, href=RULE, plan=WINDOW, *, paused=False, pce_url=None):
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        sid = store.create(conn, pce_url=pce_url or pce.url, org_id=pce.org_id, href=href, is_ruleset=pw.is_ruleset(href),
                           name="r9", ruleset_name="Backups", summary="a → b: 445", plan_json=plan.model_dump_json(),
                           paused=paused, pce_status="unknown", by="admin", at=NOW)
        conn.commit()
    return sid


def _pce(href=RULE, *, enabled=False, draft=None, parent_draft=None, active_status=200, put=204, provision=201):
    responses.add(responses.GET, API + pw.draft_href(href), json={"update_type": draft, "description": "keep [⏰ Expires: 2026-01-01 00:00]"})
    if pw.draft_href(href) != pw.ruleset_of(href):
        responses.add(responses.GET, API + pw.ruleset_of(href), json={"update_type": parent_draft})
    responses.add(responses.GET, API + pw.active_href(href), status=active_status,
                  json={"enabled": enabled, "href": href} if active_status == 200 else {"error": "not found"})
    responses.add(responses.PUT, API + pw.draft_href(href), status=put, body="" if put == 204 else '{"token":"x"}')
    responses.add(responses.POST, re.compile(re.escape(API) + r"/orgs/1/sec_policy/draft/dependencies"), json={})
    responses.add(responses.POST, API + "/orgs/1/sec_policy", status=provision, json={})


def _runs(ctx):
    with ctx.db() as conn:
        return [(r["action"], r["result"], r["status"]) for r in reversed(store.runs(
            conn, pce_url=ctx.settings.current().pce.url, org_id="1", limit=50))]


def _puts():
    return [json.loads(c.request.body) for c in responses.calls if c.request.method == "PUT"]


@responses.activate
def test_switches_when_live_differs_and_provisions(ctx):
    _add(ctx)
    _pce(enabled=False)
    r = rs.tick(ctx, now=NOW)
    assert (r.checked, r.switched, r.failed) == (1, 1, 0)
    assert _puts() == [{"enabled": True}]
    assert any(c.request.url.endswith("/sec_policy") and c.request.method == "POST" for c in responses.calls)
    assert _runs(ctx) == [("enable", "ok", None)]


@responses.activate
def test_no_action_when_already_in_state(ctx):
    sid = _add(ctx)
    _pce(enabled=True)
    rs.tick(ctx, now=NOW)
    assert _puts() == [] and _runs(ctx) == []
    with ctx.db() as conn:
        row = store.get(conn, sid)
    assert row["live"] == "enabled" and row["pce_status"] == "active" and row["last_checked_at"]


@responses.activate
@pytest.mark.parametrize("own,parent", [("update", None), (None, "update")])
def test_skips_when_rule_or_parent_draft_pending(ctx, own, parent):
    _add(ctx)
    _pce(enabled=False, draft=own, parent_draft=parent)
    r = rs.tick(ctx, now=NOW)
    assert r.skipped == 1 and _puts() == [] and _runs(ctx) == [("skip_draft", "skipped", None)]
    rs.tick(ctx, now=NOW + timedelta(minutes=5))
    assert _runs(ctx) == [("skip_draft", "skipped", None)]  # recorded once while it stays the same


@responses.activate
def test_marks_deleted_on_404_and_continues(ctx):
    gone = _add(ctx, href=RULE)
    _add(ctx, href=OTHER)
    responses.add(responses.GET, API + pw.draft_href(RULE), status=404, json={})
    _pce(href=OTHER, enabled=False)
    r = rs.tick(ctx, now=NOW)
    assert r.switched == 1
    with ctx.db() as conn:
        assert store.get(conn, gone)["pce_status"] == "deleted"
    assert ("not_found", "skipped", 404) in _runs(ctx)


@responses.activate
def test_restores_active_when_found_again(ctx):
    sid = _add(ctx)
    with ctx.db() as conn:
        store.set_checked(conn, sid, pce_status="deleted", live="unknown", at=NOW)
        conn.commit()
    _pce(enabled=True)
    rs.tick(ctx, now=NOW)
    with ctx.db() as conn:
        assert store.get(conn, sid)["pce_status"] == "active"


@responses.activate
def test_expiry_deletes_only_after_disable_provision_ok(ctx):
    sid = _add(ctx, plan=Expiry(expire_at=NOW - timedelta(minutes=1), timezone="Asia/Taipei"))
    _pce(enabled=True, provision=500)
    rs.tick(ctx, now=NOW)
    with ctx.db() as conn:
        assert store.get(conn, sid) is not None  # kept: the rule is still enabled on the PCE
    assert _runs(ctx)[-1] == ("expire", "failed", 500)
    responses.reset()
    _pce(enabled=True)
    rs.tick(ctx, now=NOW + timedelta(minutes=5))
    with ctx.db() as conn:
        assert store.get(conn, sid) is None
    assert {"enabled": False} in _puts() and {"description": "keep"} in _puts()  # the note cleared too
    assert _runs(ctx)[-1] == ("expire", "ok", None)


@responses.activate
def test_paused_and_other_pce_not_evaluated(ctx):
    _add(ctx, paused=True)
    _add(ctx, href=OTHER, pce_url="https://other.example:8443")
    r = rs.tick(ctx, now=NOW)
    assert r.checked == 0 and len(responses.calls) == 0


@responses.activate
def test_pce_refusal_recorded_verbatim(ctx):
    _add(ctx)
    _pce(enabled=False, put=403)
    r = rs.tick(ctx, now=NOW)
    assert r.failed == 1
    with ctx.db() as conn:
        [run] = store.runs(conn, pce_url=ctx.settings.current().pce.url, org_id="1", limit=5)
    assert (run["action"], run["result"], run["status"]) == ("enable", "failed", 403) and "token" in run["detail"]


def test_no_write_key_does_nothing(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    _add(c)
    assert rs.tick(c, now=NOW).checked == 0


@responses.activate
def test_stops_when_pce_changes_mid_tick(ctx, monkeypatch):
    _add(ctx, href=RULE)
    _add(ctx, href=OTHER)
    _pce(href=RULE, enabled=False)
    _pce(href=OTHER, enabled=False)
    real = rs._check_one

    def switch_after_first(*a, **kw):
        out = real(*a, **kw)
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://b.example:8443"))
        return out
    monkeypatch.setattr(rs, "_check_one", switch_after_first)
    r = rs.tick(ctx, now=NOW)
    assert r.checked == 1


@responses.activate
def test_create_refuses_draft_pending(ctx):
    _pce(href=RS, enabled=True, draft="update")
    with pytest.raises(rs.DraftPending):
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW)


@responses.activate
def test_create_refuses_unprovisioned_target(ctx):
    _pce(href=RS, active_status=404)
    with pytest.raises(rs.NotProvisioned):
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW)


@responses.activate
def test_create_writes_note_and_provisions(ctx):
    _pce(href=RS, enabled=True)
    view = rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin",
                     now=NOW)
    assert view.id and _puts() == [{"description": "keep\n[📅 Recurring: Mon 08:00-18:00 (Asia/Taipei) Enable in window]"}]
    with pytest.raises(rs.AlreadyScheduled):
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW)


@responses.activate
def test_create_pce_refusal_saves_nothing(ctx):
    _pce(href=RS, enabled=True, put=403)
    with pytest.raises(rs.PceRefused) as e:
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW)
    assert e.value.status == 403
    with ctx.db() as conn:
        assert store.list_for(conn, pce_url=ctx.settings.current().pce.url, org_id="1") == []


@responses.activate
def test_delete_clears_note_even_when_draft_pending(ctx):
    sid = _add(ctx, href=RS)
    responses.add(responses.GET, API + pw.draft_href(RS),
                  json={"update_type": "update", "description": "keep [📅 Recurring: x]"})
    responses.add(responses.PUT, API + pw.draft_href(RS), status=204)
    out = rs.delete(ctx, sid, by="admin", now=NOW)
    assert out.note_cleared and out.provisioned is False
    assert _puts() == [{"description": "keep"}]
    assert not any(c.request.url.endswith("/sec_policy") for c in responses.calls)


def test_job_registered_every_300s(tmp_path):
    from illumio_ops.jobs.scheduler import job_intervals
    assert job_intervals(configured_ctx(tmp_path).settings.current())["rule_schedules_tick"] == 300
