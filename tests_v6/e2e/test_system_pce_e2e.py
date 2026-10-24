from playwright.sync_api import expect

from tests_v6.e2e.conftest import sign_in


def _fill_connection(page, pce_url: str) -> None:
    page.fill("input[name=url]", pce_url)
    page.fill("input[name=org_id]", "1")
    page.fill("input[name=api_key]", "api_e2e_key")
    page.fill("input[name=api_secret]", "e2e-secret-value")
    page.select_option("select[name=deployment_type]", "on_prem")


def _open_pce_page(page, base_url: str) -> None:
    sign_in(page, base_url)
    page.click("nav >> text=PCE connection")
    page.wait_for_selector("input[name=url]")


def test_save_and_probe_happy_path(context, live_app, fake_pce):
    page = context.new_page()
    _open_pce_page(page, live_app.url)
    _fill_connection(page, fake_pce.url)
    page.click("button[type=submit]")
    page.wait_for_selector("text=Saved.")
    assert live_app.ctx.settings.current().pce.api_secret == "e2e-secret-value"
    assert page.input_value("input[name=api_secret]") == "********"

    page.click("text=Test connection")
    page.wait_for_selector(".probe-row >> nth=2")
    rows = page.locator(".probe-row")
    assert [rows.nth(i).get_attribute("data-tone") for i in range(3)] == ["ok", "ok", "ok"]
    assert rows.nth(0).inner_text().startswith("API authentication")
    assert "Last checked" in page.inner_text(".probe-results")
    assert fake_pce.calls == ["/api/v2/noop", "/api/v2/health", "/api/v2/node_available"]


def test_probe_shows_auth_failure_in_words(context, live_app, fake_pce):
    fake_pce.set("/api/v2/noop", 401)
    page = context.new_page()
    _open_pce_page(page, live_app.url)
    _fill_connection(page, fake_pce.url)
    page.click("button[type=submit]")
    page.wait_for_selector("text=Saved.")
    page.click("text=Test connection")
    row = page.locator(".probe-row").first
    row.wait_for()
    assert row.get_attribute("data-tone") == "crit"
    assert "Authentication failed (HTTP 401)" in row.inner_text()
    assert page.locator(".probe-row").count() == 1


def test_invalid_url_is_reported_next_to_the_field(context, live_app):
    page = context.new_page()
    _open_pce_page(page, live_app.url)
    _fill_connection(page, "pce.example.com")
    page.click("button[type=submit]")
    page.wait_for_selector(".field-error")
    assert page.locator("label:has(input[name=url]) .field-error").count() == 1


def test_two_tabs_second_save_sees_conflict(context, live_app, fake_pce):
    first, second = context.new_page(), context.new_page()
    _open_pce_page(first, live_app.url)
    second.goto(live_app.url + "/system/pce")
    second.wait_for_selector("input[name=url]")

    _fill_connection(first, fake_pce.url)
    first.click("button[type=submit]")
    first.wait_for_selector("text=Saved.")

    _fill_connection(second, "https://other.example.com:8443")
    second.click("button[type=submit]")
    alert = second.locator("[role=alert]")
    alert.wait_for()
    assert "Someone else saved these settings first" in alert.inner_text()
    assert live_app.ctx.settings.current().pce.url == fake_pce.url
    second.click("text=Reload")
    expect(second.locator("input[name=url]")).to_have_value(fake_pce.url)


def test_url_guidance_follows_the_deployment_type(context, live_app):
    page = context.new_page()
    _open_pce_page(page, live_app.url)
    url_label = page.locator("label:has(input[name=url])")
    console = page.locator("input[name=console_url]")
    page.select_option("select[name=deployment_type]", "on_prem")
    expect(url_label).to_contain_text("8443")
    assert page.get_attribute("input[name=url]", "placeholder") == "https://pce.example.com:8443"
    page.select_option("select[name=deployment_type]", "saas")
    expect(url_label).to_contain_text("illum.io")
    expect(url_label).not_to_contain_text("8443")
    assert console.get_attribute("placeholder") == "https://console.illum.io"
