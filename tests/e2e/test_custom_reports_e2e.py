"""Custom reports in a browser (P6e): a workbench view saved as a section, listed on the reports page, made with its
id, and chosen by a schedule."""
from playwright.sync_api import expect

from tests.e2e.conftest import sign_in


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


def test_saved_section_reopened_in_the_workbench(context, live_app):
    """5.x saved queries could be reopened: a section opens Investigate with what was saved."""
    import json
    from urllib.parse import parse_qs, urlparse
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate")
    page.locator("[data-role=save-section]").click()
    form = page.locator("[data-role=save-section-form]")
    form.locator("input[name=custom-name]").fill("Reopen")
    form.locator("input[name=section-title]").fill("Saved view")
    form.locator("button[type=submit]").click()
    expect(form.locator("[data-role=save-section-done]")).to_have_count(1)
    saved = json.loads(parse_qs(urlparse(page.url).query)["q"][0])

    page.goto(f"{live_app.url}/reports")
    with page.expect_request("**/api/workbench/run") as ran:
        page.locator("[data-role=custom-section-open]").first.click()
    assert "/investigate" in page.url
    sent = ran.value.post_data_json["request"]
    def dims(r):
        return [g["dimension"] for g in r.get("group_by", [])]
    assert (sent["mode"], sent["view"], dims(sent)) == (saved["mode"], saved["view"], dims(saved))
