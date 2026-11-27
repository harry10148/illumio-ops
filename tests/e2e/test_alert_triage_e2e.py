"""The alerts home page's severity filters, URL view and grouped repeats."""
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from illumio_ops.domain.alert_devices import Device
from illumio_ops.domain.values import Severity
from illumio_ops.store import alerts as store
from tests.e2e.conftest import sign_in
from tests.e2e.test_alerts_e2e import seed


def _host(ctx, alert_id):
    with ctx.db() as conn:
        store._write_devices(conn, alert_id, [Device("/orgs/1/workloads/triage-host", "subject")])


def test_severity_kpi_toggles_filter_and_aria_pressed(context, live_app):
    seed(live_app.ctx)
    low = seed(live_app.ctx)
    with live_app.ctx.db() as conn:
        conn.execute("UPDATE alerts SET severity = ? WHERE id = ?", (Severity.LOW.value, low))
    page = context.new_page()
    sign_in(page, live_app.url)

    high = page.locator("[data-kpi=high]")
    expect(high).to_have_attribute("aria-pressed", "false")
    high.click()
    expect(high).to_have_attribute("aria-pressed", "true")
    assert "severity=high" in page.url
    expect(page.locator("[data-role=alert-total]")).to_have_text("Alerts: 1")
    high.click()
    expect(high).to_have_attribute("aria-pressed", "false")
    assert "severity=high" not in page.url
    expect(page.locator("[data-role=alert-total]")).to_have_text("Alerts: 2")


def test_url_restores_alert_view_after_reload(context, live_app):
    alert_id = seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/?days=30&category=system&severity=high&page=1&alert={alert_id}")
    expect(page.locator("[data-category=system]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-kpi=high]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-role=alert-side]")).to_be_visible()
    page.reload()
    expect(page.locator("[data-category=system]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-kpi=high]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("[data-role=alert-side]")).to_be_visible()
    assert f"alert={alert_id}" in page.url and "days=30" in page.url


def test_grouped_row_expands_and_member_selects_detail(context, live_app):
    at = datetime.now(UTC).replace(minute=10, second=0, microsecond=0)
    first = seed(live_app.ctx, at=at)
    second = seed(live_app.ctx, at=at + timedelta(minutes=20))
    _host(live_app.ctx, first)
    _host(live_app.ctx, second)
    page = context.new_page()
    sign_in(page, live_app.url)
    toggle = page.get_by_role("button", name="Expand 2 alerts")
    expect(toggle).to_be_visible()
    expect(page.locator("[data-role=alert-total]")).to_have_text("Alerts: 2")  # alerts, not the one row they share
    toggle.click()
    members = page.locator("[data-role=alert-group-members]")
    expect(members.locator("[data-member-id]")).to_have_count(2)
    members.locator(f"[data-member-id='{first}']").click()
    assert f"alert={first}" in page.url
    expect(page.locator("[data-role=alert-side]")).to_be_visible()
