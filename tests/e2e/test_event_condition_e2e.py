"""Task 5: event conditions preserve stored values and change only what the user picks."""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from illumio_ops.domain.event_catalog import catalog
from tests.e2e.conftest import sign_in

EVENT = {
    "name": "", "pack_key": None, "enabled": True, "notify": True, "severity": None,
    "cooldown_minutes": 30, "throttle": None, "type": "event", "event_types": ["*"],
    "status": "all", "event_severity": "all", "match_fields": {}, "threshold": "immediate",
    "threshold_count": 1, "window_minutes": 10,
}


def _add_rules(live_app, rules: list[dict]) -> list[dict]:
    saved = [rule | {"id": uuid.uuid4().hex} for rule in rules]
    settings = live_app.ctx.settings
    settings.update(settings.current().revision, lambda data: data["alerts"]["rules"].extend(saved))
    return saved


def _open(page, live_app, rule_id: str):
    page.goto(f"{live_app.url}/alert-rules?rule={rule_id}")
    page.wait_for_load_state("networkidle")
    return page.locator("[data-role=rule-form]")


def _save(form) -> None:
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0)


def _stored(live_app, rule_id: str) -> dict:
    return next(rule.model_dump(mode="json") for rule in live_app.ctx.settings.current().alerts.rules if rule.id == rule_id)


def test_other_event_shapes_save_back_unchanged(context, live_app):
    shapes = [
        EVENT | {"name": "err and warning", "event_types": ["*"], "event_severity": "err|warning"},
        EVENT | {"name": "negated status", "event_types": ["agent.tampering"], "status": "!admin"},
        EVENT | {"name": "comma pattern", "event_types": ["^agent\\.(a|b){1,3}$", "user.login"]},
        EVENT | {"name": "alternatives", "event_types": ["agent.tampering|agent.suspend"]},
        EVENT | {"name": "outside catalog", "event_types": ["vendor.brand_new", "agent.tampering"], "enabled": False},
    ]
    rules = _add_rules(live_app, shapes)
    page = context.new_page()
    sign_in(page, live_app.url)
    for rule in rules:
        form = _open(page, live_app, rule["id"])
        _save(form)
        assert _stored(live_app, rule["id"]) == rule


def test_event_severity_alias_any_raw_and_empty_values_round_trip(context, live_app):
    values = ["error", "*", "", "!info"]
    rules = _add_rules(live_app, [EVENT | {"name": f"severity {index}", "event_severity": value}
                                  for index, value in enumerate(values)])
    page = context.new_page()
    sign_in(page, live_app.url)
    for rule, value in zip(rules, values, strict=True):
        form = _open(page, live_app, rule["id"])
        if value == "error":
            expect(form.locator("input[name=event_severity_err]")).to_be_checked()
            expect(form.locator("input[name=event_severity_info]")).not_to_be_checked()
        elif value in ("*", ""):
            for level in ("info", "warning", "err"):
                expect(form.locator(f"input[name=event_severity_{level}]")).to_be_checked()
            expect(form.locator("input[name=event_severity]")).to_have_count(0)
        else:
            expect(form.locator("input[name=event_severity]")).to_have_value(value)
            expect(form.locator("input[name=event_severity_err]")).to_have_count(0)
        _save(form)
        assert _stored(live_app, rule["id"])["event_severity"] == value


def test_group_tick_selects_exact_types_and_event_order_is_preserved(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    form = page.locator("[data-role=rule-form]")
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    group = form.locator("input[data-group='rule_set']")
    expect(group).to_be_visible()
    expected_group = [event.event_type for event in catalog() if event.event_type.startswith("rule_set.")]
    group.check()
    form.locator("input[name=name]").fill("Rule set group")
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0)
    made = next(rule for rule in live_app.ctx.settings.current().alerts.rules if rule.name == "Rule set group")
    assert list(made.event_types) == expected_group

    original_types = ["vendor.first", "label.delete", "agent.tampering"]
    ordered = _add_rules(live_app, [EVENT | {"name": "order edit", "event_types": original_types}])[0]
    form = _open(page, live_app, ordered["id"])
    form.locator("input[data-event-type='agent.tampering']").uncheck()
    form.locator("input[data-event-type='user.sign_in']").check()
    _save(form)
    assert list(_stored(live_app, ordered["id"])["event_types"]) == ["vendor.first", "label.delete", "user.sign_in"]


def test_action_filter_and_search_cross_category(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    picker = page.locator("[data-role=event-picker]")
    picker.locator("input[name=event_verb][value=delete]").check()
    visible_types = picker.locator("input[data-event-type]").evaluate_all("els => els.map(e => e.dataset.eventType)")
    assert visible_types and all(event_type.endswith(".delete") for event_type in visible_types)
    # Choose a category other than the category containing user.sign_in, then search globally.
    user_category = next(event.category for event in catalog() if event.event_type == "user.sign_in")
    other_category = next(event.category for event in catalog() if event.category != user_category)
    picker.locator(f"button[data-category='{other_category}']").click()
    picker.locator("input[name=event_search]").fill("user.sign_in")
    picker.locator("input[name=event_verb][value=all]").check()
    expect(picker.locator("input[data-event-type='user.sign_in']")).to_be_visible()
    expect(picker.locator("input[data-event-type]")).to_have_count(1)


def test_owner_hint_does_not_disable_selection_and_opens_after_confirmation(context, live_app):
    owner = _add_rules(live_app, [EVENT | {"name": "Manual sign-in owner", "event_types": ["user.sign_in"],
                                            "status": "failure", "enabled": False}])[0]
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    picker = form.locator("[data-role=event-picker]")
    row = picker.locator(".event-picker-row").filter(has=page.locator("input[data-event-type='user.sign_in']"))
    expect(row.locator("[data-role=event-owner]")).to_contain_text("Manual sign-in owner")
    expect(row.locator("[data-role=event-owner]")).to_contain_text("failure only")
    expect(row.locator("[data-role=event-owner]")).to_contain_text("disabled")
    expect(row.locator("input[data-event-type='user.sign_in']")).to_be_enabled()
    row.locator("input[data-event-type='user.sign_in']").check()
    form.locator("input[name=name]").fill("Dirty event rule")
    page.once("dialog", lambda dialog: dialog.accept())
    row.get_by_role("button", name="Manual sign-in owner").click()
    page.wait_for_url(f"**/alert-rules?rule={owner['id']}")
    expect(page.locator("[data-role=rule-form] input[name=name]")).to_have_value("Manual sign-in owner")


def test_result_filter_is_shown_only_when_catalog_says_it_matters(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    picker = form.locator("[data-role=event-picker]")
    picker.locator("input[data-event-type='rule_set.create']").check()
    expect(form.locator("select[name=status], input[name=status]")).to_have_count(0)
    expect(form).to_contain_text("one result")
    picker.locator("input[data-event-type='user.sign_in']").check()
    expect(form.locator("select[name=status]")).to_be_visible()


def test_clearing_every_severity_is_a_field_error_and_blocks_save(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule=new")
    form = page.locator("[data-role=rule-form]")
    form.locator("input[name=name]").fill("No severity selected")
    form.locator("input[name=event_scope][value=all]").check()
    for level in ("info", "warning", "err"):
        form.locator(f"input[name=event_severity_{level}]").uncheck()
    expect(form).to_contain_text("Select at least one event severity.")
    form.locator("button[type=submit]").click()
    expect(form).to_be_visible()
    assert "No severity selected" not in [rule.name for rule in live_app.ctx.settings.current().alerts.rules]
