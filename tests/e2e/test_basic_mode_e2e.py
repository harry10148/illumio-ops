"""Basic mode (lightweight collection) across the console (UI redesign spec §4.6, §5): what needs advanced mode is
explained where it would be — never an empty table, never a 0 for something not computed."""
from __future__ import annotations

from playwright.sync_api import expect

from tests.e2e.conftest import no_horizontal_overflow, open_system, sign_in


def _basic(live_app):
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["collection"].update(mode="lightweight"))


def test_basic_mode_explained_across_pages(context, live_app):
    _basic(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    box = page.locator("[data-role=basic-mode-box]")
    expect(box).to_contain_text("Advanced mode adds lateral-movement detection")
    assert sorted(page.locator("[data-category]").evaluate_all("els => els.map(e => e.dataset.category)")) == [
        "all", "event", "system"]

    page.goto(f"{live_app.url}/detect")
    expect(page.locator("[data-role=detections-need-mode] [data-role=needs-advanced]")).to_have_count(1)
    expect(page.locator("[data-role=kpi-strip] .kpi-value")).to_have_count(0)

    page.goto(f"{live_app.url}/hosts?key=/orgs/1/workloads/x")
    expect(page.locator("[data-role=usual] [data-role=needs-advanced]")).to_have_count(1)

    open_system(page, "Modes and data sources")
    modes = page.locator("[data-role=modes]")
    expect(modes.locator("[data-mode=basic][data-current]")).to_have_count(1)
    expect(page.locator("[data-role=data-status]")).to_contain_text("Basic mode keeps no traffic")


def test_advanced_mode_has_no_basic_box(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    expect(page.locator("[data-role=alerts-home]")).to_have_count(1)
    expect(page.locator("[data-role=basic-mode-box]")).to_have_count(0)


def test_system_subnav_order(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/system']")
    page.locator(".subnav-item").first.wait_for()
    names = [n.strip() for n in page.locator(".subnav-item").all_inner_texts()]
    assert names[:3] == ["Modes and data sources", "PCE connection", "Lateral movement settings"]
    assert names[-1] == "Display" and "Notification channels" not in names and "Report settings" not in names


def test_modes_page_disk_and_760(narrow_context, live_app):
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/system/collection")
    expect(page.locator("[data-disk=flows]")).to_have_count(1)
    assert no_horizontal_overflow(page)


def test_siem_no_overflow_760(narrow_context, live_app):
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/siem")
    page.locator("h1").wait_for()
    assert no_horizontal_overflow(page)
