"""Rule Hit Count on System › Report settings (spec §6.5 RHC): status, confirm, turn on; SaaS refusal in words."""
from tests_v6.e2e.conftest import sign_in

ORG = "/api/v2/orgs/1"


def _configure(live_app, fake_pce, **pce):
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision, lambda d: d["pce"].update(
        url=fake_pce.url, org_id="1", api_key="k", api_secret="s", write_api_key="wk", write_api_secret="ws", **pce))


def _open(page, live_app):
    sign_in(page, live_app.url)
    page.click("nav >> text=Report settings")
    page.wait_for_selector("[data-role=rhc-state]")


def test_turn_on_after_confirming(context, live_app, fake_pce):
    _configure(live_app, fake_pce)
    fake_pce.set(f"{ORG}/report_templates/rule_hit_count_report", 200, {"enabled": False})
    fake_pce.set(f"{ORG}/sec_policy/active/firewall_settings", 200, {"rule_hit_count_enabled_scopes": []})
    fake_pce.set(f"{ORG}/sec_policy/draft/firewall_settings", 200, {"rule_hit_count_enabled_scopes": []})
    fake_pce.set(f"{ORG}/sec_policy", 201, {})
    page = context.new_page()
    _open(page, live_app)
    assert page.inner_text("[data-role=rhc-state]").startswith("Off")
    page.click("text=Turn on Rule Hit Count")
    confirm = page.locator("[data-role=rhc-confirm]")
    assert confirm.locator("li").count() == 3 and "every VEN" in confirm.inner_text()
    assert f"{ORG}/sec_policy" not in fake_pce.calls  # nothing sent before confirming
    page.click("[data-role=rhc-confirm] >> text=Confirm")
    page.wait_for_selector("text=All steps finished.")
    assert fake_pce.calls.count(f"{ORG}/sec_policy") == 1


def test_saas_refusal_says_ask_illumio(context, live_app, fake_pce):
    _configure(live_app, fake_pce, deployment_type="saas")
    fake_pce.set(f"{ORG}/report_templates/rule_hit_count_report", 403, {"error": "Access denied."})
    fake_pce.set(f"{ORG}/sec_policy/active/firewall_settings", 200, {"rule_hit_count_enabled_scopes": []})
    page = context.new_page()
    _open(page, live_app)
    assert "Cannot tell" in page.inner_text("[data-role=rhc-state]")
    page.click("text=Turn on Rule Hit Count")
    page.click("[data-role=rhc-confirm] >> text=Confirm")
    err = page.locator("[data-role=rhc-error]")
    err.wait_for()
    assert "support case" in err.inner_text() and "Steps done: none" in err.inner_text()
