"""Regression coverage for phase E request and unsaved-form guards."""
from __future__ import annotations

import re

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
    save.dblclick()
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


def test_alert_auto_selection_replaces_history(context, live_app):
    from tests.e2e.test_alerts_e2e import seed

    seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/fleet']")
    expect(page.locator("[data-role=fleet-list]")).to_be_visible()
    page.click("nav >> text=Alerts")
    expect(page.locator("[data-role=alerts-home]")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/alerts\?.*alert="))
    page.go_back()
    expect(page.locator("[data-role=fleet-list]")).to_be_visible()


def test_latest_alert_filter_response_wins(context, live_app):
    from illumio_ops.domain.values import Severity
    from tests.e2e.test_alerts_e2e import seed

    seed(live_app.ctx, severity=Severity.HIGH)
    critical_id = seed(live_app.ctx, severity=Severity.CRITICAL, subject="critical_disk")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click("nav >> text=Alerts")
    expect(page.locator("[data-role=alert-list] tbody tr[data-row]")).to_have_count(2)
    delayed = []
    page.route("**/api/alerts?*", lambda route: delayed.append(route)
               if "severity=high" in route.request.url else route.continue_())
    with page.expect_request(lambda request: request.url.startswith(live_app.url + "/api/alerts?")
                             and "severity=high" in request.url):
        page.locator('[data-kpi="high"]').click()
    assert len(delayed) == 1
    page.locator('[data-kpi="critical"]').click()
    expect(page.locator('[data-kpi="critical"]')).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-role=alert-list] tbody tr[data-row]")).to_have_count(1)
    assert page.locator("[data-role=alert-list] tbody tr[data-row]").get_attribute("data-row") == str(critical_id)
    expect(page.locator('[data-kpi="critical"] .kpi-value')).to_have_text("1")
    delayed[0].continue_()
    page.wait_for_timeout(150)
    expect(page.locator("[data-role=alert-list] tbody tr[data-row]")).to_have_count(1)
    assert page.locator("[data-role=alert-list] tbody tr[data-row]").get_attribute("data-row") == str(critical_id)
    expect(page.locator('[data-kpi="critical"] .kpi-value')).to_have_text("1")
