"""Spacing, tables and action rows (purpose-led UI spec §5.4): what the rule checker cannot say by measuring boxes
alone — a long name kept whole, a notice said once, a column drawn only when something fills it."""
from dataclasses import replace
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb import workloads
from tests.e2e import test_fleet_e2e as fleet_e2e
from tests.e2e.conftest import no_horizontal_overflow, sign_in
from tests.e2e.test_ui_rules_e2e import WIDE, seed_everything

LONG = "a-very-long-host-name-that-keeps-going." + "x" * 60 + ".example.internal"


def _wide(browser, live_app):
    ctx = browser.new_context(locale="en-US", viewport=WIDE)
    page = ctx.new_page()
    sign_in(page, live_app.url)
    return ctx, page


def test_a_long_host_name_wraps_inside_its_cell_and_is_whole(live_app, fake_pce, browser):
    seed_everything(live_app, fake_pce)
    now = datetime.now(UTC)
    with live_app.ctx.flows().connect() as conn:
        rows = [replace(fleet_e2e._wl("/orgs/1/workloads/long", LONG, "selective", None, now), os_id="ubuntu-x86_64-noble")]
        workloads.replace_inventory(conn, rows)
        conn.commit()
    ctx, page = _wide(browser, live_app)
    for width in (1440, 760):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(f"{live_app.url}/fleet")
        cell = page.locator("[data-role=fleet-list] tbody td", has_text=LONG)
        expect(cell).to_be_visible()
        assert cell.inner_text().strip() == LONG                       # whole: no ellipsis, nothing cut
        assert cell.evaluate("(e) => e.scrollWidth <= e.clientWidth + 1")
        assert cell.bounding_box()["width"] < 320  # it took more lines, not the width of the table
        assert no_horizontal_overflow(page), width
    ctx.close()


def test_the_fleet_action_bar_sits_above_the_table_head(live_app, fake_pce, browser):
    seed_everything(live_app, fake_pce)
    ctx, page = _wide(browser, live_app)
    page.goto(f"{live_app.url}/fleet")
    expect(page.locator("[data-role=fleet-actions] button").first).to_be_visible()
    expect(page.locator("[data-role=fleet-list] tbody tr").first).to_be_visible()
    page.wait_for_load_state("networkidle")
    # measured in one reading: the page above the list is still filling in while it loads (the tallies arrive after
    # the list), and two readings a moment apart are of two different layouts (CI, 2026-11-11)
    bottoms, head_top = page.evaluate("""() => [
        [...document.querySelectorAll('[data-role=fleet-actions] button')].map((b) => b.getBoundingClientRect().bottom),
        document.querySelector('[data-role=fleet-list] thead').getBoundingClientRect().top]""")
    assert bottoms and all(bottom <= head_top for bottom in bottoms), (bottoms, head_top)
    ctx.close()


def test_a_gap_in_the_collection_is_said_once_on_the_host_page(live_app, fake_pce, browser):
    seed_everything(live_app, fake_pce)  # nothing was ever collected: the period has a gap
    ctx, page = _wide(browser, live_app)
    page.goto(f"{live_app.url}/hosts?key={fleet_e2e.DB}")
    expect(page.locator("[data-section=src_host] tbody tr").first).to_be_visible()
    page.wait_for_load_state("networkidle")
    said = [s.strip() for s in page.locator("[data-role=caveat]").all_inner_texts()]
    assert said and len(said) == len(set(said)), said
    assert page.locator("[data-role=caveat]").first.evaluate("(e) => !e.closest('.card, .panel')")  # at the head, not in a section
    # it stays while the sections that have the gap are on the page: another period and back, it is still said, once
    for hours in ("168", "24"):
        page.select_option("select[name=period]", hours)
        page.wait_for_load_state("networkidle")
        expect(page.locator("[data-section=src_host]").first.locator("tbody tr, .muted").first).to_be_visible()
        again = [s.strip() for s in page.locator("[data-role=caveat]").all_inner_texts()]
        assert again and len(again) == len(set(again)), (hours, again)
    ctx.close()


def test_rule_state_is_always_available_and_non_ok_status_is_shown_under_activity(live_app, browser):
    ctx, page = _wide(browser, live_app)
    page.goto(f"{live_app.url}/alert-rules")
    heads = page.locator("[data-role=rules-event] thead th")
    expect(heads.first).to_be_visible()
    # the headings are set in capitals by the style sheet: their text is compared without case
    assert "state" in " | ".join(heads.all_inner_texts()).lower()
    assert page.locator("[data-role=rules-event] [data-role=rule-state]").count() > 0
    before = heads.count()
    c = live_app.ctx
    rid = c.settings.current().alerts.rules[0].id
    with c.db() as conn:
        store.set_rule_status(conn, rid, "accumulating", datetime.now(UTC))
    page.reload()
    expect(page.locator("[data-role=rules-event] thead th")).to_have_count(before)
    expect(page.locator(f"tr[data-rule-id='{rid}'] [data-role=rule-last-status]")).to_have_text("accumulating")
    ctx.close()


def test_a_button_is_as_wide_as_its_words(live_app, fake_pce, browser):
    seed_everything(live_app, fake_pce)
    ctx, page = _wide(browser, live_app)
    page.goto(f"{live_app.url}/detect")
    page.locator("#lat-reach [data-role=fold-toggle]").click()  # the ranking is a detail: folded until asked for
    more = page.locator("[data-role=lat-more]")
    expect(more).to_be_visible()
    assert more.bounding_box()["width"] < 400
    ctx.close()
