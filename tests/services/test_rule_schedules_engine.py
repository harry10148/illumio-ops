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
PCE_A = ("https://pce.example.com:8443", "1")
WINDOW = Weekly(days=("mon",), start="08:00", end="18:00", timezone="Asia/Taipei", action="enable_in_window")
REVERT_URL = API + "/orgs/1/sec_policy/delete"


def _reverted(href=RULE):
    """The body that discards the rule set's draft (PCE `PUT sec_policy/delete`, lab 26.2 2026-11-03)."""
    return {"change_subset": {"rule_sets": [{"href": pw.ruleset_of(href)}]}}


def _needs(href="/orgs/1/sec_policy/draft/ip_lists/7", kind="ip_lists"):
    """The PCE's dependency answer as lab 26.2 sends it (2026-11-03): a list of {dependency, required_by}."""
    return [{"dependency": {kind: {"href": href, "caps": ["write", "provision"]}},
             "required_by": {"rule_sets": [{"href": pw.ruleset_of(RULE), "caps": ["write", "provision"]}]}}]


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


def _pce(href=RULE, *, enabled=False, draft=None, parent_draft=None, active_status=200, put=204, provision=201,
         deps=None, revert=204):
    responses.add(responses.GET, API + pw.draft_href(href), json={"update_type": draft, "enabled": enabled,
                                                                  "description": "keep [⏰ Expires: 2026-01-01 00:00]"})
    if pw.draft_href(href) != pw.ruleset_of(href):
        responses.add(responses.GET, API + pw.ruleset_of(href), json={"update_type": parent_draft})
    responses.add(responses.GET, API + pw.active_href(href), status=active_status,
                  json={"enabled": enabled, "href": href} if active_status == 200 else {"error": "not found"})
    responses.add(responses.PUT, API + pw.draft_href(href), status=put, body="" if put == 204 else '{"token":"x"}')
    responses.add(responses.PUT, REVERT_URL, status=revert, body="" if revert == 204 else '{"token":"y"}')
    responses.add(responses.POST, re.compile(re.escape(API) + r"/orgs/1/sec_policy/draft/dependencies"),
                  json=deps or [])
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
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW, pce=PCE_A)


@responses.activate
def test_create_refuses_unprovisioned_target(ctx):
    _pce(href=RS, active_status=404)
    with pytest.raises(rs.NotProvisioned):
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW, pce=PCE_A)


@responses.activate
def test_create_writes_note_and_provisions(ctx):
    _pce(href=RS, enabled=True)
    view = rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin",
                     now=NOW, pce=PCE_A)
    assert view.id and _puts() == [{"description": "keep\n[📅 Recurring: Mon 08:00-18:00 (Asia/Taipei) Enable in window]"}]
    with pytest.raises(rs.AlreadyScheduled):
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW, pce=PCE_A)


@responses.activate
def test_create_pce_refusal_saves_nothing(ctx):
    _pce(href=RS, enabled=True, put=403)
    with pytest.raises(rs.PceRefused) as e:
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="admin", now=NOW, pce=PCE_A)
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


@responses.activate
def test_other_pending_objects_are_not_provisioned_and_the_switch_is_undone(ctx):
    """Security review: a switch that would need someone's unprovisioned object provisioned is skipped, and the
    draft is put back as it was."""
    _add(ctx)
    _pce(enabled=False, deps=_needs())
    r = rs.tick(ctx, now=NOW)
    assert r.skipped == 1 and r.switched == 0
    assert _puts() == [{"enabled": True}, _reverted()]
    assert not any(c.request.url.endswith("/sec_policy") and c.request.method == "POST" for c in responses.calls)
    with ctx.db() as conn:
        [run] = store.runs(conn, pce_url=ctx.settings.current().pce.url, org_id="1", limit=5)
    assert (run["action"], run["result"]) == ("skip_draft", "skipped") and "ip_lists/7" in run["detail"]


@responses.activate
def test_expiry_of_a_rule_already_disabled_never_enables_it(ctx):
    """Security review: the undo after a refused provision must restore the draft's own value, never the opposite."""
    sid = _add(ctx, plan=Expiry(expire_at=NOW - timedelta(minutes=1), timezone="Asia/Taipei"))
    _pce(enabled=False, deps=_needs())
    rs.tick(ctx, now=NOW)
    assert {"enabled": True} not in _puts() and {"enabled": False} not in _puts()  # already disabled: nothing to write
    with ctx.db() as conn:
        assert store.get(conn, sid) is None  # expired and disabled: the schedule is done


@responses.activate
def test_a_failed_undo_is_a_failure_that_says_a_draft_change_remains(ctx):
    _add(ctx)
    _pce(enabled=False, deps=_needs(), revert=500)
    r = rs.tick(ctx, now=NOW)
    assert r.failed == 1
    with ctx.db() as conn:
        [run] = store.runs(conn, pce_url=ctx.settings.current().pce.url, org_id="1", limit=5)
    assert run["result"] == "failed" and run["status"] == 500 and "draft change remains" in run["detail"]


# ── Codex review of plan B ──────────────────────────────────────────────────

@responses.activate
def test_failed_provision_puts_the_draft_back(ctx):
    """P1: a refused provision left the schedule's own change in the draft; every later check skipped it as a pending
    draft for good."""
    _add(ctx)
    _pce(enabled=False, provision=500)
    r = rs.tick(ctx, now=NOW)
    assert r.failed == 1 and _puts() == [{"enabled": True}, _reverted()]


@responses.activate
def test_a_sibling_rules_pending_change_stops_the_provision(ctx):
    """P1: the whole rule set is provisioned, so another rule's unreviewed change in it must count as pending."""
    _add(ctx)
    responses.add(responses.GET, API + pw.draft_href(RULE), json={"update_type": None, "enabled": False})
    responses.add(responses.GET, API + pw.ruleset_of(RULE), json={
        "update_type": None, "rules": [{"href": pw.draft_href(RULE), "update_type": None},
                                       {"href": pw.ruleset_of(RULE) + "/sec_rules/10", "update_type": "update"}]})
    r = rs.tick(ctx, now=NOW)
    assert r.skipped == 1 and _puts() == []


@responses.activate
def test_a_schedule_paused_during_the_round_is_not_written(ctx, monkeypatch):
    """P2: rows read at the start of a round must be checked again before each write."""
    first = _add(ctx, href=RULE)
    second = _add(ctx, href=OTHER)
    _pce(href=RULE, enabled=True)   # already in state: no write
    _pce(href=OTHER, enabled=False)
    real = rs._check_one

    def pause_second(c, client, row, at):
        out = real(c, client, row, at)
        if row["id"] == first:
            rs.set_paused(ctx, second, True, now=NOW)
        return out
    monkeypatch.setattr(rs, "_check_one", pause_second)
    rs.tick(ctx, now=NOW)
    assert _puts() == []


@responses.activate
def test_delete_acts_on_the_pce_it_checked(ctx, monkeypatch):
    """P1: a PCE switch between the ownership check and the write must not write to the new PCE."""
    sid = _add(ctx, href=RS)
    responses.add(responses.GET, API + pw.draft_href(RS), json={"update_type": None, "description": "keep [📅 x]"})
    responses.add(responses.PUT, API + pw.draft_href(RS), status=204)
    responses.add(responses.POST, re.compile(re.escape(API) + r"/orgs/1/sec_policy/draft/dependencies"), json=[])
    responses.add(responses.POST, API + "/orgs/1/sec_policy", status=201, json={})
    real = rs._own

    def own_then_switch(*a, **kw):
        row = real(*a, **kw)
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://b.example:8443"))
        return row
    monkeypatch.setattr(rs, "_own", own_then_switch)
    out = rs.delete(ctx, sid, by="admin", now=NOW)
    assert all(c.request.url.startswith(API) for c in responses.calls) and out.note_cleared is False
    assert out.detail == "pce_switched"


@responses.activate
def test_concurrent_create_is_refused_cleanly(ctx):
    """P2: the target is claimed before the PCE is written, so a second create cannot change the note."""
    import sqlite3
    _pce(href=RS, enabled=True)
    rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="a", now=NOW, pce=PCE_A)
    with pytest.raises(rs.AlreadyScheduled):
        rs.create(ctx, href=RS, plan=WINDOW, name="Backups", ruleset_name="Backups", summary="", by="a", now=NOW, pce=PCE_A)
    assert sqlite3  # the IntegrityError of a race is answered as AlreadyScheduled (rs.create)


# ── Codex review round 2 ────────────────────────────────────────────────────

@responses.activate
def test_a_transport_failure_after_the_switch_puts_the_draft_back(ctx):
    """P1: the dependency read failing in transport after the PUT left the change in the draft for good."""
    from requests.exceptions import ConnectionError as RequestsConnectionError
    _add(ctx)
    responses.add(responses.GET, API + pw.draft_href(RULE), json={"update_type": None, "enabled": False})
    responses.add(responses.GET, API + pw.ruleset_of(RULE), json={"update_type": None})
    responses.add(responses.GET, API + pw.active_href(RULE), json={"enabled": False})
    responses.add(responses.PUT, API + pw.draft_href(RULE), status=204)
    responses.add(responses.PUT, REVERT_URL, status=204)
    responses.add(responses.POST, re.compile(re.escape(API) + r"/orgs/1/sec_policy/draft/dependencies"),
                  body=RequestsConnectionError("down"))
    r = rs.tick(ctx, now=NOW)
    assert r.failed == 1 and _puts() == [{"enabled": True}, _reverted()]


@responses.activate
def test_create_refused_provision_puts_the_description_back(ctx):
    """P2: a refused provision left the note in the draft with no schedule behind it."""
    _pce(href=RS, enabled=True, provision=403)
    with pytest.raises(rs.PceRefused):
        rs.create(ctx, href=RS, plan=WINDOW, name="B", ruleset_name="B", summary="", by="a", now=NOW,
                  pce=("https://pce.example.com:8443", "1"))
    assert _puts()[-1] == _reverted(RS)


def test_create_refuses_a_target_from_another_pce(ctx):
    """P1: a target picked while PCE A was set is not created on PCE B."""
    with pytest.raises(rs.PceSwitched):
        rs.create(ctx, href=RS, plan=WINDOW, name="B", ruleset_name="B", summary="", by="a", now=NOW,
                  pce=("https://other.example:8443", "1"))


@responses.activate
def test_an_expiry_record_stays_with_its_pce(ctx, monkeypatch):
    """P2: the run of a deleted schedule kept the PCE read at the end, not the one written."""
    _add(ctx, plan=Expiry(expire_at=NOW - timedelta(minutes=1), timezone="Asia/Taipei"))
    _pce(enabled=True)
    real = rs._clear_note

    def switch(*a, **kw):
        out = real(*a, **kw)
        ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(url="https://b.example:8443"))
        return out
    monkeypatch.setattr(rs, "_clear_note", switch)
    rs.tick(ctx, now=NOW)
    with ctx.db() as conn:
        runs = store.runs(conn, pce_url="https://pce.example.com:8443", org_id="1", limit=5)
    assert [r["action"] for r in runs] == ["expire"]


@responses.activate
def test_skipped_now_clears_after_a_good_check(ctx):
    _add(ctx)
    _pce(enabled=True, draft="update")
    rs.tick(ctx, now=NOW)
    assert rs.schedules(ctx, now=NOW)[0].skipped_now == 1
    responses.reset()
    _pce(enabled=True)
    rs.tick(ctx, now=NOW + timedelta(minutes=5))
    assert rs.schedules(ctx, now=NOW + timedelta(minutes=5))[0].skipped_now == 0


# ── lab 26.2 acceptance (2026-11-03) ────────────────────────────────────────

@responses.activate
def test_a_put_back_discards_the_draft_rather_than_writing_the_old_value(ctx):
    """lab .106 2026-11-03: writing the old value back leaves the object `update_type: update` in the draft, so every
    later check took the schedule's own undone change for someone's pending draft and the next create was refused.
    The rule set's draft is discarded instead (PCE `PUT sec_policy/delete`)."""
    _add(ctx)
    _pce(enabled=False, provision=500)
    rs.tick(ctx, now=NOW)
    reverts = [c for c in responses.calls if c.request.url == REVERT_URL]
    assert len(reverts) == 1 and json.loads(reverts[0].request.body) == _reverted()
    assert {"enabled": False} not in _puts()


# ── edit and "check now" (5.x upsert and POST /api/rule_scheduler/check; parity 2026-11-06) ─────────────

@responses.activate
def test_update_changes_the_plan_and_rewrites_the_note(ctx):
    sid = _add(ctx, href=RS)
    _pce(href=RS, enabled=True)
    evening = Weekly(days=("tue",), start="18:00", end="23:00", timezone="Asia/Taipei", action="disable_in_window")
    view = rs.update(ctx, sid, evening, now=NOW)
    assert view.plan == evening and view.preview_key == "rs_preview_weekly_disable"
    assert _puts() == [{"description": "keep\n[📅 Recurring: Tue 18:00-23:00 (Asia/Taipei) Disable in window]"}]
    with ctx.db() as conn:
        assert rs.plan_of(store.get(conn, sid)["plan_json"]) == evening


@responses.activate
def test_update_refused_by_the_pce_keeps_the_old_plan(ctx):
    sid = _add(ctx, href=RS)
    _pce(href=RS, enabled=True, put=403)
    evening = Weekly(days=("tue",), start="18:00", end="23:00", timezone="Asia/Taipei", action="disable_in_window")
    with pytest.raises(rs.PceRefused):
        rs.update(ctx, sid, evening, now=NOW)
    with ctx.db() as conn:
        assert rs.plan_of(store.get(conn, sid)["plan_json"]) == WINDOW


@responses.activate
def test_check_now_runs_one_schedule_as_the_tick_does(ctx):
    sid = _add(ctx)
    _add(ctx, href=OTHER)  # not asked: an unregistered PCE call would fail the test
    _pce(enabled=False)
    result = rs.check_now(ctx, sid, now=NOW)
    assert result.outcome == "switched" and result.item is not None and result.item.live == "enabled"
    assert _puts() == [{"enabled": True}] and _runs(ctx) == [("enable", "ok", None)]


@responses.activate
def test_check_now_records_a_pce_failure_like_the_tick(ctx):
    sid = _add(ctx)
    responses.add(responses.GET, API + pw.draft_href(RULE), status=500, body="boom")
    result = rs.check_now(ctx, sid, now=NOW)
    assert result.outcome == "failed" and _runs(ctx) == [("error", "failed", 500)]


def test_check_now_needs_the_write_key_and_an_active_schedule(tmp_path):
    c = configured_ctx(tmp_path, mode="full")
    sid = _add(c)
    with pytest.raises(rs.NoWriteKey):
        rs.check_now(c, sid, now=NOW)
    c.settings.update(c.settings.current().revision, lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))
    with pytest.raises(LookupError):
        rs.check_now(c, 999, now=NOW)
    paused = _add(c, href=OTHER, paused=True)
    with pytest.raises(rs.SchedulePaused):
        rs.check_now(c, paused, now=NOW)
