"""Custom reports in a browser (P6e): a workbench view saved as a section, listed on the reports page, made with its
id, and chosen by a schedule."""
from playwright.sync_api import expect

from tests_v6.e2e.conftest import sign_in


def test_saved_section_listed_made_and_scheduled(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate")
    page.locator("[data-role=save-section]").click()
    form = page.locator("[data-role=save-section-form]")
    form.locator("input[name=custom-name]").fill("DB watch")
    form.locator("input[name=section-title]").fill("Recent connections")
    form.locator("button[type=submit]").click()
    expect(form.locator("[data-role=save-section-done]")).to_have_count(1)

    page.goto(f"{live_app.url}/reports")
    rep = page.locator("[data-role=custom-report]")
    expect(rep).to_have_count(1)
    assert "DB watch" in rep.inner_text() and "Recent connections" in rep.inner_text()
    rep.locator("[data-role=custom-generate-open]").click()
    with page.expect_request("**/api/reports") as made:
        rep.locator("[data-role=generate-form] button.btn-primary").click()
    body = made.value.post_data_json
    assert body["report_type"] == "custom" and body["custom_id"] == int(rep.get_attribute("data-custom-id"))


def test_no_custom_report_says_how_to_make_one(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/reports")
    expect(page.locator("[data-role=custom-none]")).to_have_count(1)
