"""The console frame: navigation order and sections, basic-mode marks, the narrow layout, offline fonts."""
from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.conftest import no_horizontal_overflow, sign_in


def _nav_texts(page) -> list[str]:
    return [t.strip().rstrip("◆").strip() for t in page.locator(".sidenav .nav-item").all_inner_texts()]


def test_the_navigation_is_grouped_by_what_a_page_is_for(live_app, context):
    """Purpose-led UI spec §4.1: watching first (alerts, their rules, reports), then hosts, analysis, automation and
    settings — each group under its heading."""
    page = context.new_page()
    sign_in(page, live_app.url)
    groups = {}
    for group in page.locator(".sidenav [data-nav-group]").all():
        title = group.locator(".nav-section").text_content().strip()  # the words; the eyebrow shows them in capitals
        groups[title] = [t.strip().rstrip("◆").strip() for t in group.locator(".nav-item").all_inner_texts()]
    assert list(groups) == ["Watch", "Hosts", "Analyse", "Automation", "Settings"]
    assert groups["Watch"] == ["Alerts", "Alert rules and notifications", "Reports"]
    assert groups["Hosts"] == ["Hosts", "VEN fleet", "Quarantine"]
    assert groups["Analyse"] == ["Detection", "Investigate"]
    assert groups["Automation"] == ["Rule schedules"]
    assert groups["Settings"] == ["SIEM forwarding", "System"]


def test_every_address_that_opened_a_page_still_does(live_app, context):
    """Regrouping the navigation moves no page: an address in a bookmark or an emailed link still opens."""
    from tests.e2e import ui_rules
    page = context.new_page()
    sign_in(page, live_app.url)
    for path in ui_rules.PATHS:
        page.goto(live_app.url + path)
        expect(page.locator("main h1")).to_have_count(1)
        assert page.url.split("?")[0].rstrip("/") == (live_app.url + path.split("?")[0]).rstrip("/"), path
    # the older addresses that lead on to where the page is now
    for old, now in (("/alerts", "/"), ("/lateral", "/detect"), ("/alerts/rules", "/alert-rules"),
                     ("/system/reports", "/reports"), ("/system/channels", "/alert-rules")):
        page.goto(live_app.url + old)
        page.wait_for_url(lambda url, now=now: url.split("?")[0].rstrip("/") == (live_app.url + now).rstrip("/"))
        expect(page.locator("main h1")).to_have_count(1)


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
    # the monospace face is for values to copy (an address, a port): it loads from this server, and so does Montserrat
    loaded = page.evaluate("""Promise.all(['12px "JetBrains Mono Variable"', '600 12px "Montserrat"']
        .map((f) => document.fonts.load(f).then((faces) => faces.length)))""")
    assert outside == [] and all(n > 0 for n in loaded), (outside, loaded)


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
