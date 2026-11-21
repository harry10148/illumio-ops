from __future__ import annotations

from illumio_ops.domain.alertpack import best_practice_rules, pack_rule_id
from tests.e2e.conftest import sign_in

SKIP_TEMPLATE_FIELDS = {"id", "pack_key", "name", "enabled", "notify"}


def _rules(live_app) -> dict[str, dict]:
    return {rule.id: rule.model_dump(mode="json") for rule in live_app.ctx.settings.current().alerts.rules}


def _without_template_fields(rule: dict) -> dict:
    return {key: value for key, value in rule.items() if key not in SKIP_TEMPLATE_FIELDS}


def _templates():
    return [rule for rule in best_practice_rules(notify_new_defaults=True)
            if rule.type in ("event", "traffic", "bandwidth", "volume")]


def test_each_event_and_traffic_template_saves_the_pack_values(context, live_app):
    from playwright.sync_api import expect

    page = context.new_page()
    sign_in(page, live_app.url)
    expected = _templates()
    assert len(expected) == 17

    for template in expected:
        page.goto(f"{live_app.url}/alert-rules?rule=new")
        form = page.locator("[data-role=rule-form]")
        existing_ids = set(_rules(live_app))
        form.locator("select[name=template]").select_option(template.pack_key)
        form.locator("button[type=submit]").click()
        expect(form).to_have_count(0)
        created = next(rule for rule_id, rule in _rules(live_app).items() if rule_id not in existing_ids)
        assert _without_template_fields(created) == _without_template_fields(template.model_dump(mode="json"))
        assert created["enabled"] is True and created["notify"] is True


def test_template_query_applies_template_and_shows_explanation(context, live_app):
    from playwright.sync_api import expect

    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule=new&template=rule_login_failed")
    form = page.locator("[data-role=rule-form]")
    expect(form.locator("select[name=template]")).to_have_value("rule_login_failed")
    expect(form.locator("input[name=name]")).to_have_value("Login Failures (copy)")
    expect(form).to_contain_text(
        "Failed sign-ins to the PCE. Only many failures in a short time alert; a single mistyped password does not."
    )


def test_builtin_edit_can_be_restored_to_pack_values(context, live_app):
    from playwright.sync_api import expect

    key = "rule_login_failed"
    rid = pack_rule_id(key)
    original = next(rule for rule in best_practice_rules(notify_new_defaults=True) if rule.pack_key == key)

    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    advanced = form.locator("details[data-role=rule-form-advanced]")
    if not advanced.evaluate("element => element.open"):
        advanced.locator("summary").click()
    form.locator("input[name=cooldown_minutes]").fill("77")
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0)
    row = page.locator(f"tr[data-rule-id='{rid}']")
    expect(row).to_contain_text("Differs from default")

    page.goto(f"{live_app.url}/alert-rules?rule={rid}")
    form = page.locator("[data-role=rule-form]")
    expect(form).to_contain_text(
        "Failed sign-ins to the PCE. Only many failures in a short time alert; a single mistyped password does not."
    )
    expect(form.locator("button", has_text="Restore built-in default")).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept())
    form.get_by_role("button", name="Restore built-in default").click()
    form.locator("button[type=submit]").click()
    expect(form).to_have_count(0)

    restored = _rules(live_app)[rid]
    assert _without_template_fields(restored) == _without_template_fields(original.model_dump(mode="json"))
    assert restored["name"] == ""
    page.locator(f"tr[data-rule-id='{rid}']").get_by_text("Differs from default").wait_for(state="detached")


def test_5x_builtin_with_different_cooldown_is_marked(context, live_app):
    from playwright.sync_api import expect

    key = "rule_login_failed"
    rid = pack_rule_id(key)

    def make_legacy_shape(data):
        stored = next(rule for rule in data["alerts"]["rules"] if rule["id"] == rid)
        stored["cooldown_minutes"] = 77
        stored["throttle"] = None

    settings = live_app.ctx.settings
    settings.update(settings.current().revision, make_legacy_shape)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    expect(page.locator(f"tr[data-rule-id='{rid}']")).to_contain_text("Differs from default")
