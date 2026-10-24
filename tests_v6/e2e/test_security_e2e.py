from playwright.sync_api import expect

from tests_v6.e2e.conftest import sign_in


def test_change_language_switches_ui(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    expect(page.locator("nav")).to_contain_text("Home")
    page.click("nav >> text=Display")
    page.select_option("select[name=language]", "zh_TW")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("nav")).to_contain_text("首頁")
    expect(page.locator("h1")).to_contain_text("顯示")
    page.reload()
    expect(page.locator("nav")).to_contain_text("首頁")


def test_default_password_banner_and_lockout_guard(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    banner = page.locator(".shell-banner")
    expect(banner).to_contain_text("default password")
    page.click("nav >> text=Security")
    page.fill("textarea[name=allowed_ips]", "10.0.0.0/8")
    page.get_by_role("button", name="Save addresses").click()
    expect(page.locator("[role=alert]")).to_contain_text("127.0.0.1")
    assert live_app.ctx.settings.current().web.allowed_ips == ()


def test_change_password_then_save_addresses(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click("nav >> text=Security")
    page.fill("input[autocomplete=current-password]", "illumio")
    page.fill("input[autocomplete=new-password] >> nth=0", "a-new-password-1")
    page.fill("input[autocomplete=new-password] >> nth=1", "a-new-password-1")
    page.get_by_role("button", name="Change password").click()
    expect(page.locator("text=Password changed.")).to_be_visible()
    page.fill("textarea[name=allowed_ips]", "127.0.0.1")
    page.get_by_role("button", name="Save addresses").click()
    expect(page.locator(".form-ok", has_text="Saved.")).to_be_visible()
    assert live_app.ctx.settings.current().web.allowed_ips == ("127.0.0.1",)
