from playwright.sync_api import expect

from tests.e2e.conftest import open_system, sign_in


def test_change_language_switches_ui(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    expect(page.locator(".sidenav")).to_contain_text("Alerts")
    open_system(page, "Display")
    page.select_option("select[name=language]", "zh_TW")
    page.get_by_role("button", name="Save").click()
    expect(page.locator(".sidenav")).to_contain_text("告警")
    expect(page.locator("h1")).to_contain_text("顯示")
    page.reload()
    expect(page.locator(".sidenav")).to_contain_text("告警")


def test_default_password_banner_and_lockout_guard(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    banner = page.locator(".shell-banner")
    expect(banner).to_contain_text("default password")
    open_system(page, "Security")
    page.fill("textarea[name=allowed_ips]", "10.0.0.0/8")
    page.get_by_role("button", name="Save addresses").click()
    expect(page.locator("[role=alert]")).to_contain_text("127.0.0.1")
    assert live_app.ctx.settings.current().web.allowed_ips == ()


def test_change_password_then_save_addresses(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    open_system(page, "Security")
    page.fill("form:has(input[autocomplete=new-password]) input[autocomplete=current-password]", "illumio")
    page.fill("input[autocomplete=new-password] >> nth=0", "a-new-password-1")
    page.fill("input[autocomplete=new-password] >> nth=1", "a-new-password-1")
    page.get_by_role("button", name="Change password").click()
    expect(page.locator("text=Password changed.")).to_be_visible()
    page.fill("textarea[name=allowed_ips]", "127.0.0.1")
    page.get_by_role("button", name="Save addresses").click()
    expect(page.locator(".form-ok", has_text="Saved.")).to_be_visible()
    assert live_app.ctx.settings.current().web.allowed_ips == ("127.0.0.1",)


def test_change_username_keeps_this_browser_signed_in(context, live_app):
    """5.x could change the admin name (parity 2026-11-06); it takes the current password."""
    page = context.new_page()
    sign_in(page, live_app.url)
    open_system(page, "Security")
    form = page.locator("[data-role=username-change]")
    form.locator("input[name=username]").fill("opsadmin")
    form.locator("input[name=current_password]").fill("illumio")
    form.get_by_role("button", name="Change username").click()
    expect(form.locator(".form-ok")).to_contain_text("Username changed.")
    expect(page.locator(".nav-user")).to_contain_text("opsadmin")
    assert live_app.ctx.settings.current().web.username == "opsadmin"
    page.fill("textarea[name=allowed_ips]", "127.0.0.1")  # the session still works after the key rotation
    page.get_by_role("button", name="Save addresses").click()
    expect(page.locator(".form-ok", has_text="Saved.")).to_be_visible()
