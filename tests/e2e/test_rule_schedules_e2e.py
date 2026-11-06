"""Rule schedules in a browser (UI redesign sample 05): greyed out without the write key, a target picked from the
search (a pending draft cannot be picked), the preview sentence, the PCE's refusal shown as it said it."""
from __future__ import annotations

from playwright.sync_api import expect

from illumio_ops.services import rule_schedules as rs
from illumio_ops.services.rule_schedule_targets import TargetHit, TargetSearch
from tests.e2e.conftest import no_horizontal_overflow, sign_in

RS = "/orgs/1/sec_policy/active/rule_sets/5"


def _write_key(live_app):
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["pce"].update(write_api_key="wk", write_api_secret="ws"))


def _targets(monkeypatch):
    hits = [TargetHit(href=RS, is_ruleset=True, name="Backups", ruleset_name="Backups", summary="2 rules",
                      enabled=True, draft_pending=False, scheduled=False),
            TargetHit(href=RS + "/sec_rules/9", is_ruleset=False, name="#9", ruleset_name="Backups",
                      summary="app=backup → NAS: 445/TCP", enabled=True, draft_pending=True, scheduled=False)]
    monkeypatch.setattr("illumio_ops.web.routes.rule_schedules.targets.search",
                        lambda ctx, q: TargetSearch(items=hits, limited=False))


def _open(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/rule-schedules']")
    page.locator("[data-role=rule-schedules]").wait_for()
    return page


def test_no_write_key_greys_out(context, live_app):
    page = _open(context, live_app)
    expect(page.locator("[data-role=rs-no-write-key]")).to_have_count(1)
    assert page.locator("input[name=rs_q]").is_disabled()


def test_draft_target_disabled_in_picker_and_preview(context, live_app, monkeypatch):
    _write_key(live_app)
    _targets(monkeypatch)
    page = _open(context, live_app)
    page.fill("input[name=rs_q]", "back")
    page.get_by_role("button", name="Search").click()
    radios = page.locator("[data-role=rs-targets] input[name=rs_target]")
    expect(radios).to_have_count(2)
    assert radios.nth(1).is_disabled()
    expect(page.locator("[data-role=rs-target-why]")).to_contain_text("draft is pending")
    radios.nth(0).check()
    page.fill("input[name=rs_start]", "18:00")
    page.fill("input[name=rs_end]", "09:00")
    page.locator("input[name=rs_action]").nth(1).check()
    expect(page.locator("[data-role=rs-preview]")).to_contain_text("disable and provision, the next day 09:00 enable")


def test_refusal_shows_pce_answer(context, live_app, monkeypatch):
    _write_key(live_app)
    _targets(monkeypatch)

    def refuse(*a, **kw):
        raise rs.PceRefused(403, '{"token":"forbidden_error"}')
    monkeypatch.setattr("illumio_ops.web.routes.rule_schedules.rs.create", refuse)
    page = _open(context, live_app)
    page.fill("input[name=rs_q]", "back")
    page.get_by_role("button", name="Search").click()
    page.locator("[data-role=rs-targets] input[name=rs_target]").nth(0).check()
    page.get_by_role("button", name="Create schedule").click()
    expect(page.locator("[data-role=rs-error]")).to_contain_text("HTTP 403")
    expect(page.locator("[data-role=rs-error]")).to_contain_text("forbidden_error")


def test_rule_schedules_no_overflow_760(narrow_context, live_app):
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/rule-schedules")
    page.locator("[data-role=rule-schedules]").wait_for()
    assert no_horizontal_overflow(page)


def test_a_new_search_clears_the_earlier_pick(context, live_app, monkeypatch):
    """Codex review: a target picked from an earlier search stayed selected (and submittable) out of sight."""
    _write_key(live_app)
    _targets(monkeypatch)
    page = _open(context, live_app)
    page.fill("input[name=rs_q]", "back")
    page.get_by_role("button", name="Search").click()
    page.locator("[data-role=rs-targets] input[name=rs_target]").nth(0).check()
    expect(page.get_by_role("button", name="Create schedule")).to_be_visible()
    monkeypatch.setattr("illumio_ops.web.routes.rule_schedules.targets.search",
                        lambda ctx, q: TargetSearch(items=[], limited=False))
    page.fill("input[name=rs_q]", "nothing")
    page.get_by_role("button", name="Search").click()
    expect(page.get_by_role("button", name="Create schedule")).to_have_count(0)


def _scheduled(live_app):
    from datetime import UTC, datetime

    from illumio_ops.domain.rule_schedule import Weekly
    from illumio_ops.store import rule_schedules as store
    pce = live_app.ctx.settings.current().pce
    plan = Weekly(days=("mon",), start="08:00", end="18:00", timezone="Asia/Taipei", action="enable_in_window")
    with live_app.ctx.db() as conn:
        sid = store.create(conn, pce_url=pce.url, org_id=pce.org_id, href=RS, is_ruleset=True, name="Backups",
                           ruleset_name="Backups", summary="2 rules", plan_json=plan.model_dump_json(), paused=False,
                           pce_status="active", by="a", at=datetime.now(UTC))
        conn.commit()
    return sid


def test_edit_prefills_the_plan_and_check_now_says_what_happened(context, live_app, monkeypatch):
    """5.x edited a schedule in place and checked on demand (parity 2026-11-06)."""
    _write_key(live_app)
    _scheduled(live_app)
    sent = {}

    def update(ctx, sid, plan, **kw):
        sent["plan"] = plan
        return rs.schedules(ctx)[1][0]
    monkeypatch.setattr("illumio_ops.web.routes.rule_schedules.rs.update", update)
    monkeypatch.setattr("illumio_ops.web.routes.rule_schedules.rs.check_now",
                        lambda ctx, sid, **kw: rs.CheckResult(outcome="none", item=rs.schedules(ctx)[1][0]))
    page = _open(context, live_app)
    page.locator("[data-role=rs-edit-open]").click()
    edit = page.locator("[data-role=rs-edit]")
    expect(edit.locator("input[name=rs_start]")).to_have_value("08:00")
    assert edit.locator("input[name=rs_day_mon]").is_checked() and not edit.locator("input[name=rs_day_tue]").is_checked()
    edit.locator("input[name=rs_day_tue]").check()
    edit.get_by_role("button", name="Save and provision the note").click()
    expect(page.locator("[data-role=rs-new]")).to_have_count(1)  # back to the new-schedule pane
    assert sent["plan"].days == ("mon", "tue") and sent["plan"].timezone == "Asia/Taipei"
    page.locator("[data-role=rs-check]").click()
    expect(page.locator("[data-role=rs-checked]")).to_contain_text("already as planned")
