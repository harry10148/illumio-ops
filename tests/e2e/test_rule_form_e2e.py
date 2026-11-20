"""Task 4: the event and flow rules share one form on the rules page."""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from illumio_ops.domain.alertpack import pack_rule_id
from tests.e2e.conftest import sign_in

NEW_ID = "0" * 32


def _new(page, live_app, kind="event"):
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    if kind == "flow":
        form.locator("input[name=rule_kind][value=flow]").check()
    return form


def _expected_base(name):
    return {"id": NEW_ID, "name": name, "pack_key": None, "enabled": True, "notify": True,
            "cooldown_minutes": 30, "throttle": None}


def _create_and_capture(page, form):
    with page.expect_request(lambda req: req.method == "POST" and req.url.endswith("/api/alert-rules")) as request:
        form.locator("button[type=submit]").click()
    return request.value.post_data_json["rule"]


def test_new_event_rule_sends_every_expected_field(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    form = _new(page, live_app)
    form.locator("input[name=name]").fill("Sign-in errors")
    form.locator("textarea[name=event_types]").fill("user.sign_in")
    actual = _create_and_capture(page, form)
    expected = _expected_base("Sign-in errors") | {
        "type": "event", "severity": None, "event_types": ["user.sign_in"], "status": "all",
        "event_severity": "all", "match_fields": {}, "threshold": "immediate", "threshold_count": 1,
        "window_minutes": 10,
    }
    assert actual == expected


@pytest.mark.parametrize(("metric", "field", "default", "unit"), [
    ("traffic", "threshold_connections", 25, "matching connections"),
    ("bandwidth", "threshold_mbps", 100, "any one connection's rate"),
    ("volume", "threshold_mb", 1024, "these connections total"),
])
def test_new_flow_metrics_send_exactly_their_own_threshold_field(context, live_app, metric, field, default, unit):
    page = context.new_page()
    sign_in(page, live_app.url)
    form = _new(page, live_app, "flow")
    form.locator("input[name=name]").fill(f"{metric} threshold")
    if metric != "traffic":
        form.locator(f"input[name=flow_metric][value={metric}]").check()
    expect(form.locator("input[name=threshold]")).to_have_value(str(default))
    form.locator("input[name=window_minutes]").fill("17")
    threshold = 73
    form.locator("input[name=threshold]").fill(str(threshold))
    expect(form.locator(".sentence")).to_contain_text(unit)
    actual = _create_and_capture(page, form)
    expected = _expected_base(f"{metric} threshold") | {
        "type": metric, "severity": "medium", "condition": {}, "window_minutes": 17,
        field: threshold,
    }
    assert actual == expected
    assert field in actual and not ({"threshold_connections", "threshold_mbps", "threshold_mb"} - {field}) & actual.keys()


def test_existing_immediate_event_keeps_three_same_host_count(context, live_app):
    rid = pack_rule_id("rule_agent_tampering")
    ctx = live_app.ctx
    original = next(item for item in ctx.settings.current().alerts.rules if item.id == rid).model_dump(mode="json")
    changed = original | {"threshold_count": 3}
    ctx.settings.update(ctx.settings.current().revision, lambda data: data["alerts"]["rules"].__setitem__(
        next(index for index, item in enumerate(data["alerts"]["rules"]) if item["id"] == rid), changed))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    expect(form.locator("input[name=threshold_count]")).to_have_value("3")
    with page.expect_request(lambda req: req.method == "PUT" and req.url.endswith(f"/api/alert-rules/{rid}")) as request:
        form.locator("button[type=submit]").click()
    assert request.value.post_data_json["rule"] == changed
    after = next(item for item in ctx.settings.current().alerts.rules if item.id == rid).model_dump(mode="json")
    assert after == changed


def test_switching_flow_metric_drops_the_previous_metric_field(context, live_app):
    rid = pack_rule_id("rule_high_blocked")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    form.locator("input[name=flow_metric][value=bandwidth]").check()
    with page.expect_request(lambda req: req.method == "PUT" and req.url.endswith(f"/api/alert-rules/{rid}")) as request:
        form.locator("button[type=submit]").click()
    saved = request.value.post_data_json["rule"]
    assert saved["type"] == "bandwidth" and saved["threshold_mbps"] == 100 and saved["window_minutes"] == 60
    assert "threshold_connections" not in saved and "threshold_mb" not in saved


def test_changed_rule_is_not_overwritten_and_reload_is_offered(context, live_app):
    rid = pack_rule_id("rule_agent_tampering")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    # the form must hold the rule as it was before someone else changes it
    expect(form.locator("textarea[name=event_types]")).to_have_value("agent.tampering")
    ctx = live_app.ctx
    def change_rule(data):
        next(item for item in data["alerts"]["rules"] if item["id"] == rid).update(cooldown_minutes=999)
    ctx.settings.update(ctx.settings.current().revision, change_rule)
    updates = []
    page.on("request", lambda request: updates.append(request) if request.method == "PUT" and request.url.endswith(f"/api/alert-rules/{rid}") else None)
    with page.expect_response(lambda response: response.request.method == "GET" and response.url.endswith("/api/alert-rules")):
        form.locator("button[type=submit]").click()
    expect(form.locator("[data-role=rule-form-error]")).to_contain_text("This rule changed while you were editing")
    expect(form.get_by_role("button", name="Reload")).to_be_visible()
    assert updates == []
    assert next(item for item in ctx.settings.current().alerts.rules if item.id == rid).cooldown_minutes == 999


def test_row_state_is_shared_with_form_and_does_not_conflict(context, live_app):
    rid = pack_rule_id("rule_agent_tampering")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    row = page.locator(f"tr[data-rule-id='{rid}']")
    with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith(f"/api/alert-rules/{rid}")):
        row.locator("[data-role=rule-state] input[value=rec]").check()
    form = page.locator("[data-role=rule-form]")
    expect(form.locator("input[name=form_rule_state][value=rec]")).to_be_checked()
    with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith(f"/api/alert-rules/{rid}")):
        form.locator("button[type=submit]").click()
    expect(form.locator("[data-role=rule-form-error]")).to_have_count(0)
    saved = next(item for item in live_app.ctx.settings.current().alerts.rules if item.id == rid)
    assert saved.enabled and not saved.notify


def test_rule_can_be_deleted_from_the_form(context, live_app):
    rid = pack_rule_id("rule_agent_tampering")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    form.get_by_role("button", name="Delete rule").click()
    expect(form.locator("[data-role=delete-confirm]")).to_be_visible()
    form.locator("[data-role=delete-confirm]").click()
    expect(page.locator(f"tr[data-rule-id='{rid}']")).to_have_count(0)
    assert all(item.id != rid for item in live_app.ctx.settings.current().alerts.rules)


def test_legacy_event_flow_rule_urls_redirect_to_the_new_form(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    for key in ("rule_agent_tampering", "rule_high_blocked"):
        rid = pack_rule_id(key)
        page.goto(f"{live_app.url}/alerts/rules/{rid}")
        page.wait_for_url(f"{live_app.url}/alert-rules?rule={rid}")
        expect(page.locator("[data-role=rule-form]")).to_be_visible()


def test_legacy_special_rule_stays_in_the_existing_editor(context, live_app):
    rid = pack_rule_id("rule_lateral_fanout")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/{rid}")
    page.wait_for_url(f"{live_app.url}/alerts/rules/{rid}")
    expect(page.locator("[data-role=rule-editor]")).to_be_visible()

