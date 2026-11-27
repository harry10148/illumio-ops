"""Regression coverage for phase E request and unsaved-form guards."""
from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.conftest import sign_in


def test_second_siem_save_click_does_not_send_another_request(live_app, context):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/siem")
    save = page.locator('[data-role="siem-settings"] button[type="submit"]')
    expect(save).to_be_enabled()
    page.locator('input[name="siem_enabled"]').click()
    held = []
    requests = []
    page.on("request", lambda request: requests.append(request) if request.url.endswith("/api/siem/settings") else None)
    page.route("**/api/siem/settings", lambda route: held.append(route))
    save.click()
    page.wait_for_timeout(100)
    expect(save).to_be_disabled()
    assert len(requests) == 1
    held[0].continue_()
    expect(save).to_be_enabled()
    assert len(requests) == 1


def test_dirty_siem_navigation_can_be_declined(live_app, context):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/siem")
    page.locator('[data-role="siem-settings"] details summary').click()
    page.locator('input[name="siem_tick_seconds"]').fill("31")
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator('.sidenav .nav-item[data-nav="/fleet"]').click()
    expect(page.locator("[data-role=siem-settings]")).to_have_count(1)
    assert page.url.endswith("/siem")


def test_fleet_search_waits_for_typing_to_pause(live_app, context):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/fleet")
    page.locator('[data-role="fleet-list"]').wait_for()
    requests = []
    page.on("request", lambda request: requests.append(request) if request.url.startswith(live_app.url + "/api/fleet/hosts") else None)
    search = page.locator('[data-role="fleet-find"] input[name="q"]')
    search.fill("")
    search.type("db", delay=40)
    page.wait_for_timeout(450)
    assert len(requests) == 1
