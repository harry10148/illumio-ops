"""Keyboard and focus behavior for the signed-in UI."""
from playwright.sync_api import expect

from tests.e2e import test_alerts_e2e as alerts_e2e
from tests.e2e.conftest import sign_in


def test_alert_rows_can_be_selected_with_the_keyboard(context, live_app):
    alerts_e2e.seed(live_app.ctx)
    alerts_e2e.seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    rows = page.locator("[data-role=alert-list] tbody tr[data-row]")
    expect(rows).to_have_count(2)
    first, second = rows.nth(0), rows.nth(1)
    expect(first).to_have_attribute("tabindex", "0")
    expect(first).to_have_attribute("aria-selected", "true")
    page.locator("[data-role=alert-seen] button").last.focus()
    page.keyboard.press("Tab")
    expect(first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(second).to_be_focused()
    page.keyboard.press("Enter")
    expect(second).to_have_attribute("aria-selected", "true")
    side = page.locator("[data-role=alert-side]")
    expect(side).to_have_attribute("data-alert-id", second.get_attribute("data-row"))


def test_alert_group_button_keeps_its_own_keyboard_behavior(context, live_app):
    alerts_e2e._lateral(live_app.ctx, "new_process", subject="/orgs/1/workloads/keyboard")
    alerts_e2e._lateral(live_app.ctx, "new_process", subject="/orgs/1/workloads/keyboard")
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr[data-row]").first
    toggle = row.locator("button.alert-group-toggle")
    expect(toggle).to_be_visible()
    selected_before = page.locator('[data-role=alert-list] tr[aria-selected="true"]').get_attribute("data-row")
    toggle.focus()
    page.keyboard.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.locator('[data-role=alert-list] tr[aria-selected="true"]')).to_have_attribute("data-row", selected_before)


def test_skip_link_is_first_and_moves_focus_to_main(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to main content")
    expect(skip).to_be_focused()
    expect(skip).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.locator("main#main-content")).to_be_focused()


def test_control_border_contrast_and_disabled_cursor(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    input_control = page.locator("input[type=search]")
    expect(input_control).to_be_visible()
    ratio = input_control.evaluate("""(e) => {
      const rgb = getComputedStyle(e).borderTopColor.match(/[0-9.]+/g).slice(0, 3).map(Number);
      const luminance = rgb.map((v) => { const c = v / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; })
        .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
      return 1.05 / (luminance + 0.05);
    }""")
    assert ratio >= 3
    cursor = page.evaluate("""() => {
      const button = document.createElement('button');
      button.disabled = true;
      document.body.append(button);
      return getComputedStyle(button).cursor;
    }""")
    assert cursor == "not-allowed"
