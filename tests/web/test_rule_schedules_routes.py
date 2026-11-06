"""Rule scheduling API (UI redesign spec §4.5): signed in, CSRF on writes, conflicts said in words, the PCE's refusal
carried with its status, pause and resume local only."""
import json
from datetime import UTC, datetime

import pytest

from illumio_ops.services import rule_schedules as rs
from illumio_ops.store import rule_schedules as store

from .conftest import LOCAL, csrf, login, post

RS = "/orgs/1/sec_policy/active/rule_sets/5"
PLAN = {"kind": "weekly", "days": ["mon"], "start": "08:00", "end": "18:00", "timezone": "Asia/Taipei",
        "action": "enable_in_window"}
BODY = {"href": RS, "plan": PLAN, "name": "Backups", "ruleset_name": "Backups", "summary": "", "pce_url": "",
        "org_id": ""}


def _add(ctx):
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        sid = store.create(conn, pce_url=pce.url, org_id=pce.org_id, href=RS, is_ruleset=True, name="Backups",
                           ruleset_name="Backups", summary="", plan_json=rs.plan_of(json.dumps(PLAN))
                           .model_dump_json(), paused=False, pce_status="active", by="a", at=datetime.now(UTC))
        conn.commit()
    return sid


def test_list_shows_overview(client, ctx):
    assert client.get("/api/rule-schedules", environ_overrides=LOCAL).status_code == 401
    login(client)
    _add(ctx)
    data = client.get("/api/rule-schedules", environ_overrides=LOCAL).get_json()["data"]
    assert data["overview"]["schedules"] == 1 and data["overview"]["write_key"] is False
    [item] = data["items"]
    assert item["plan"]["kind"] == "weekly" and item["preview_key"] == "rs_preview_weekly_enable"


def test_create_without_write_key_412(client):
    login(client)
    r = post(client, "/api/rule-schedules", BODY)
    assert r.status_code == 412 and r.get_json()["error"]["code"] == "no_write_key"


@pytest.mark.parametrize(("exc", "status", "code"), [
    (rs.DraftPending(), 409, "draft_pending"), (rs.AlreadyScheduled(), 409, "already_scheduled"),
    (rs.NotProvisioned(), 409, "not_provisioned"), (rs.PceSwitched(), 409, "pce_switched")])
def test_create_conflicts(client, monkeypatch, exc, status, code):
    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(rs, "create", boom)
    login(client)
    r = post(client, "/api/rule-schedules", BODY)
    assert r.status_code == status and r.get_json()["error"]["code"] == code


def test_create_pce_refusal_502_carries_pce_answer(client, monkeypatch):
    def boom(*a, **kw):
        raise rs.PceRefused(403, '{"token":"forbidden_error"}')
    monkeypatch.setattr(rs, "create", boom)
    login(client)
    err = post(client, "/api/rule-schedules", BODY).get_json()["error"]
    assert err["code"] == "pce_refused" and err["params"] == {"status": "403", "detail": '{"token":"forbidden_error"}'}


def test_bad_target_href_400(client):
    login(client)
    assert post(client, "/api/rule-schedules", {**BODY, "href": "/orgs/1/workloads/x"}).status_code == 400


def test_pause_resume_local_only(client, ctx):
    login(client)
    sid = _add(ctx)
    r = post(client, f"/api/rule-schedules/{sid}/pause", {})
    assert r.status_code == 200 and r.get_json()["data"]["paused"] is True
    assert post(client, f"/api/rule-schedules/{sid}/resume", {}).get_json()["data"]["paused"] is False
    assert post(client, "/api/rule-schedules/999/pause", {}).status_code == 404


def test_delete_without_write_key_reports_note_not_cleared(client, ctx):
    login(client)
    sid = _add(ctx)
    r = client.delete(f"/api/rule-schedules/{sid}", environ_overrides=LOCAL, headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 200 and r.get_json()["data"]["note_cleared"] is False
    assert client.get("/api/rule-schedules", environ_overrides=LOCAL).get_json()["data"]["items"] == []


def test_csrf_required_for_writes(client):
    login(client)
    r = client.post("/api/rule-schedules", json=BODY, environ_overrides=LOCAL)
    assert r.status_code in (400, 403)


def test_edit_and_check_now_need_the_write_key(client, ctx):
    """5.x edited a schedule in place and checked on demand (parity 2026-11-06); both write to the PCE."""
    login(client)
    sid = _add(ctx)
    r = client.put(f"/api/rule-schedules/{sid}", json={"plan": PLAN}, environ_overrides=LOCAL,
                   headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 412 and r.get_json()["error"]["code"] == "no_write_key"
    r = post(client, f"/api/rule-schedules/{sid}/check", {})
    assert r.status_code == 412 and r.get_json()["error"]["code"] == "no_write_key"
    assert post(client, "/api/rule-schedules/999/check", {}).status_code in (404, 412)


def test_check_now_answers_with_the_outcome(client, ctx, monkeypatch):
    login(client)
    sid = _add(ctx)
    view = rs.schedules(ctx)[1][0]
    monkeypatch.setattr(rs, "check_now", lambda c, i, **kw: rs.CheckResult(outcome="none", item=view))
    data = post(client, f"/api/rule-schedules/{sid}/check", {}).get_json()["data"]
    assert data["outcome"] == "none" and data["item"]["id"] == sid
    monkeypatch.setattr(rs, "check_now", lambda c, i, **kw: (_ for _ in ()).throw(rs.SchedulePaused()))
    r = post(client, f"/api/rule-schedules/{sid}/check", {})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "paused"


def test_edit_answers_with_the_schedule(client, ctx, monkeypatch):
    login(client)
    sid = _add(ctx)
    view = rs.schedules(ctx)[1][0]
    seen = {}
    monkeypatch.setattr(rs, "update", lambda c, i, plan, **kw: seen.update(id=i, plan=plan) or view)
    r = client.put(f"/api/rule-schedules/{sid}", json={"plan": PLAN}, environ_overrides=LOCAL,
                   headers={"X-CSRFToken": csrf(client)})
    assert r.status_code == 200 and seen["id"] == sid and seen["plan"].kind == "weekly"


def test_rulesets_browse_is_read_only_and_says_when_the_pce_fails(client, monkeypatch):
    from illumio_ops.pce.collections import PceCollectionIncomplete
    from illumio_ops.services import rulesets
    login(client)
    r = client.get("/api/rule-schedules/rulesets", environ_overrides=LOCAL)
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "pce_not_configured"
    monkeypatch.setattr(rulesets, "browse", lambda ctx, q: rulesets.RulesetBrowse(items=[], total=0, limited=False))
    assert client.get("/api/rule-schedules/rulesets?q=back", environ_overrides=LOCAL).status_code == 200

    def boom(ctx, q):
        raise PceCollectionIncomplete("/sec_policy/active/rule_sets", 0, "HTTP 500")
    monkeypatch.setattr(rulesets, "browse", boom)
    r = client.get("/api/rule-schedules/rulesets", environ_overrides=LOCAL)
    assert r.status_code == 502 and "HTTP 500" in r.get_json()["error"]["params"]["error"]
