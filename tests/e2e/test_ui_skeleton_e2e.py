"""The skeleton every page shares (purpose-led UI spec §5.5): its name and the question it answers, long explanations
closed until asked for, an empty list that says where to go next."""
import re

from playwright.sync_api import expect

from tests.e2e import test_fleet_e2e as fleet_e2e
from tests.e2e import ui_rules
from tests.e2e.conftest import sign_in
from tests.e2e.test_ui_rules_e2e import WIDE, seed_everything, set_language


def _page(browser, live_app):
    ctx = browser.new_context(locale="en-US", viewport=WIDE)
    page = ctx.new_page()
    sign_in(page, live_app.url)
    return ctx, page


def test_every_page_says_what_it_is_for_in_both_languages(live_app, fake_pce, browser):
    extra = seed_everything(live_app, fake_pce)
    for language in ("en", "zh_TW"):
        set_language(live_app, language)
        ctx, page = _page(browser, live_app)
        said = {}
        for path in (*ui_rules.PATHS, *extra):
            page.goto(live_app.url + path)
            purpose = page.locator("main [data-role=page-purpose]")
            page.wait_for_load_state("networkidle")
            assert (purpose.count(), page.locator("main h1").count()) == (1, 1), (path, page.locator("main h1").all_inner_texts())
            text = purpose.inner_text().strip()
            assert len(text) >= 6 and not re.fullmatch(r"[a-z0-9_]+", text), (path, text)  # a sentence, not a key left untranslated
            said[path] = text
        ctx.close()
        assert said["/"] != said["/fleet"] != said["/reports"]


def test_a_long_explanation_starts_closed_and_opens(live_app, browser):
    ctx, page = _page(browser, live_app)
    page.goto(f"{live_app.url}/siem")
    about = page.locator("main details.disclosure").first
    expect(about).to_be_visible()
    assert about.get_attribute("open") is None
    expect(about.locator(".disclosure-body")).to_be_hidden()
    about.locator("summary").click()
    expect(about.locator(".disclosure-body")).to_be_visible()
    ctx.close()


def test_what_changes_how_numbers_are_read_is_never_folded_away(live_app, fake_pce, browser):
    seed_everything(live_app, fake_pce)
    ctx, page = _page(browser, live_app)
    page.goto(f"{live_app.url}/hosts?key={fleet_e2e.DB}")
    caveat = page.locator("[data-role=caveat]").first
    expect(caveat).to_be_visible()
    assert caveat.evaluate("(e) => !e.closest('details')")
    ctx.close()


def test_an_empty_list_says_where_to_go_next(live_app, browser):
    ctx, page = _page(browser, live_app)
    page.goto(f"{live_app.url}/reports?tab=produced")
    empty = page.locator("[data-role=empty-state]")
    expect(empty).to_be_visible()
    empty.locator("a").click()
    expect(page.locator("[data-role=report-catalog]")).to_be_visible()
    ctx.close()
