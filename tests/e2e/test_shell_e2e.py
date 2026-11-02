"""The console frame: navigation order and sections, basic-mode marks, the narrow layout, offline fonts."""
from __future__ import annotations

from tests.e2e.conftest import no_horizontal_overflow, sign_in

MAIN_ORDER = ["Alerts", "Detection", "Investigate"]


def _nav_texts(page) -> list[str]:
    return [t.strip().rstrip("◆").strip() for t in page.locator(".sidenav .nav-item").all_inner_texts()]


def test_nav_order_and_sections(live_app, context):
    page = context.new_page()
    sign_in(page, live_app.url)
    texts = _nav_texts(page)
    assert texts[:3] == MAIN_ORDER
    assert texts.index("Reports") < texts.index("SIEM forwarding") < texts.index("Alert rules and notifications")
    assert texts[-1] == "System"
    assert page.locator(".nav-section").first.inner_text().strip() == "Output"


def test_status_line_says_mode_and_collection(live_app, context):
    page = context.new_page()
    sign_in(page, live_app.url)
    line = page.locator("[data-role=shell-status]")
    line.wait_for()
    assert "Advanced mode" in line.inner_text() and "Not collected yet" in line.inner_text()


def test_basic_mode_marks_advanced_items(live_app, context):
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["collection"].update({"mode": "lightweight"}))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.locator("[data-role=shell-status]").wait_for()
    detect = page.locator(".nav-item[data-nav='/detect']")
    assert detect.get_attribute("data-dimmed") == "true" and "◆" in detect.inner_text()
    assert detect.get_attribute("aria-disabled") is None
    detect.click()
    page.wait_for_url("**/detect")


def test_system_subnav(live_app, context):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.locator(".nav-item[data-nav='/system']").click()
    page.locator(".subnav").wait_for()
    assert page.locator(".subnav-item").count() >= 8


def test_no_horizontal_overflow_760(live_app, narrow_context):
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    assert no_horizontal_overflow(page)
    page.get_by_role("button", name="Menu").click()
    page.locator(".nav-item[data-nav='/investigate']").click()
    page.wait_for_url("**/investigate")
    assert no_horizontal_overflow(page)


def test_fonts_offline(live_app, context):
    page = context.new_page()
    outside: list[str] = []
    page.on("request", lambda r: outside.append(r.url) if not r.url.startswith(live_app.url) else None)
    sign_in(page, live_app.url)
    page.locator(".sidenav").wait_for()
    family = page.evaluate("getComputedStyle(document.querySelector('.nav-user .mono')).fontFamily")
    assert outside == [] and "JetBrains Mono" in family


def test_a_failed_dictionary_is_fetched_again(live_app, context):
    """Acceptance on .135: one failed dictionary answer left every label as its key until the next page load."""
    page = context.new_page()
    failed = []

    def once(route):
        if not failed:
            failed.append(route.request.url)
            route.fulfill(status=503, body="busy")
        else:
            route.continue_()
    page.route("**/api/i18n/*", once)
    sign_in(page, live_app.url)
    page.locator("[data-role=shell-status]").wait_for()
    assert failed and "nav_" not in page.inner_text("body")


def test_fonts_load_under_the_csp(live_app, context):
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "font" in m.text.lower() else None)
    sign_in(page, live_app.url)
    page.locator(".sidenav").wait_for()
    page.wait_for_timeout(500)
    assert errors == []
