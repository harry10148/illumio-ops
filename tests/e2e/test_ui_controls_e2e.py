"""What the rule checker cannot measure about buttons, tags and type (purpose-led UI spec §5.1–§5.3): where the
reason for an action goes, which values are set in monospace."""
from playwright.sync_api import expect

from tests.e2e import test_alerts_e2e as alerts_e2e
from tests.e2e import test_hosts_e2e as hosts_e2e
from tests.e2e.conftest import sign_in

MONO = "JetBrains Mono"


def _family(locator) -> str:
    return str(locator.evaluate("(e) => getComputedStyle(e).fontFamily"))


def test_why_quarantine_would_do_nothing_is_under_the_button_not_in_it(context, live_app):
    hosts_e2e._seed(live_app)  # db: a managed host in Visibility Only
    alerts_e2e._lateral(live_app.ctx, "new_process", subject=hosts_e2e.DB)
    page = context.new_page()
    sign_in(page, live_app.url)
    side = page.locator("[data-role=alert-side]")
    button = side.locator("[data-role=quarantine]")
    expect(button).to_have_text("Quarantine db…")
    note = side.locator("[data-role=action-note]")
    expect(note).to_contain_text("no effect")
    assert note.bounding_box()["y"] >= button.bounding_box()["y"] + button.bounding_box()["height"] - 1


def test_times_and_counts_are_in_the_reading_face(context, live_app):
    alerts_e2e.seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    row = page.locator("[data-role=alert-list] tbody tr").first
    expect(row).to_be_visible()
    assert MONO not in _family(row.locator("td").first)
    assert MONO not in _family(page.locator(".kpi-value").first)
    assert MONO not in _family(page.locator("[data-role=alert-side] [data-role=timeline] li span").first)


def test_an_address_is_monospace_and_a_host_name_is_not(context, live_app):
    alerts_e2e._lateral(live_app.ctx, "new_process", subject="ip:10.0.0.9")  # an older alert: its ends are words only
    page = context.new_page()
    sign_in(page, live_app.url)
    ends = page.locator("[data-role=alert-list] tbody tr").first.locator("td").nth(3)
    expect(ends).to_contain_text("10.0.0.9")
    address = ends.locator("[data-role=address]")
    expect(address).to_have_text("10.0.0.9")
    assert MONO in _family(address)
    assert MONO not in _family(ends)


def test_recorded_only_is_said_in_words_not_as_a_tag(context, live_app):
    from illumio_ops.domain.values import DeliveryStatus
    alerts_e2e.seed(live_app.ctx, hold=DeliveryStatus.NOT_NOTIFIED)
    page = context.new_page()
    sign_in(page, live_app.url)
    cell = page.locator("[data-role=alert-list] [data-delivery=not_notified]")
    expect(cell).to_have_text("recorded only (rule setting)")
    expect(cell.locator(".tag")).to_have_count(0)
    assert page.locator("[data-role=alert-list] [data-delivery=not_notified].tag").count() == 0


# ── switches, segments, checkboxes (spec §5.3) ──────────────────────────────

def _rules_page(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alert-rules")
    switch = page.locator("[data-role=rule-list] [role=switch]").first
    expect(switch).to_be_visible()
    return page, switch


def test_a_switch_that_fails_to_save_goes_back_and_says_so(context, live_app):
    page, switch = _rules_page(context, live_app)
    before = switch.get_attribute("aria-checked")
    page.route("**/api/alert-rules/*", lambda route: route.fulfill(
        status=500, content_type="application/json",
        body='{"ok": false, "data": null, "error": {"code": "internal", "message_key": "error_internal", "params": {}}}')
        if route.request.method == "PUT" else route.continue_())
    switch.click()
    expect(switch).to_have_attribute("data-state", "failed")
    expect(switch).to_have_attribute("aria-checked", before)
    expect(page.locator(".form-error")).to_be_visible()


def test_a_switch_that_saves_shows_it_and_the_change_is_kept(context, live_app):
    page, switch = _rules_page(context, live_app)
    after = "false" if switch.get_attribute("aria-checked") == "true" else "true"
    switch.click()
    expect(switch).to_have_attribute("data-state", "saved")
    expect(switch).to_have_attribute("aria-checked", after)
    page.reload()
    expect(page.locator("[data-role=rule-list] [role=switch]").first).to_have_attribute("aria-checked", after)


def test_a_segment_is_chosen_from_the_keyboard_and_shows_where_the_focus_is(context, live_app):
    alerts_e2e.seed(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    choice = page.locator("[data-role=alert-seen] button[data-value=new]")
    expect(choice).to_have_attribute("aria-pressed", "false")
    choice.focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Shift+Tab")  # arrive by keyboard, so the focus ring is the visible kind
    assert choice.evaluate("(e) => e === document.activeElement && getComputedStyle(e).outlineStyle !== 'none'")
    page.keyboard.press("Space")
    expect(choice).to_have_attribute("aria-pressed", "true")


def test_a_checkbox_is_drawn_by_the_page_and_sits_on_its_text_line(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/rules/new?form=full")
    box = page.locator("input[name=enabled]")
    expect(box).to_be_visible()
    off = box.evaluate("""(e) => { const label = e.closest('label'), r = e.getBoundingClientRect();
        const range = document.createRange(); range.selectNodeContents(label);
        const line = [...range.getClientRects()].find((x) => x.width > 20 && x.height > 0) || label.getBoundingClientRect();
        return Math.abs((r.top + r.bottom) / 2 - (line.top + line.bottom) / 2); }""")
    assert off <= 3, off
    assert box.evaluate("(e) => getComputedStyle(e).appearance") == "none"
    before = box.is_checked()
    box.focus()
    page.keyboard.press("Space")
    assert box.is_checked() != before
