from playwright.sync_api import expect

from illumio_ops.services.collect.traffic import run_traffic_cycle
from tests_v6.e2e.conftest import sign_in


def _point_at(live_app, pce_url: str) -> None:
    def mutate(d):
        d["pce"].update({"url": pce_url, "org_id": "1", "api_key": "k", "api_secret": "s"})
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision, mutate)


def _open_collection(page, base_url: str) -> None:
    sign_in(page, base_url)
    page.click("nav >> text=Data collection")
    page.wait_for_selector("[data-role=collection-status]")


def test_collection_page_shows_failure_in_words(context, live_app, fake_pce):
    _point_at(live_app, fake_pce.url)
    fake_pce.set("/api/v2/orgs/1/traffic_flows/async_queries", 503)
    run_traffic_cycle(live_app.ctx)
    run_traffic_cycle(live_app.ctx)
    page = context.new_page()
    _open_collection(page, live_app.url)
    row = page.locator("[data-source=traffic]")
    expect(row.locator(".badge")).to_have_attribute("data-tone", "crit")
    expect(row).to_contain_text("Failing (2 in a row): the PCE returned an error")
    expect(row).to_contain_text("HTTP 503")  # the raw detail stays next to the words
    expect(page.locator("[data-source=events]")).to_contain_text("Not collected yet")
    expect(page.locator("[data-role=collection-gaps]")).to_contain_text("Traffic incomplete (collection failed)")


def test_collection_settings_save_and_reload(context, live_app):
    page = context.new_page()
    _open_collection(page, live_app.url)
    form = page.locator("[data-role=collection-settings]")
    expect(form.locator("input[name=traffic_min]")).to_have_value("10")
    form.locator("input[name=traffic_min]").fill("15")
    form.locator("input[name=flow_days]").fill("40")
    form.get_by_role("button", name="Save").click()
    expect(form.locator(".form-ok")).to_have_text("Saved.")
    c = live_app.ctx.settings.current().collection
    assert c.traffic_interval_seconds == 900 and c.retention.flow_days == 40
    page.reload()
    page.wait_for_selector("[data-role=collection-settings]")
    expect(page.locator("input[name=traffic_min]")).to_have_value("15")
    expect(page.locator("input[name=flow_days]")).to_have_value("40")


def test_collection_settings_rejects_rollup_shorter_than_flows(context, live_app):
    page = context.new_page()
    _open_collection(page, live_app.url)
    form = page.locator("[data-role=collection-settings]")
    form.locator("input[name=rollup_days]").fill("5")
    form.get_by_role("button", name="Save").click()
    expect(form.locator("[role=alert]")).to_contain_text("daily summaries at least as long as flows")
    assert live_app.ctx.settings.current().collection.retention.rollup_days == 90


def test_logs_page_filters_by_level(context, live_app):
    lines = ["2026-10-24 10:00:00.000 | INFO     | illumio_ops.web.app:f:1 - started",
             "2026-10-24 10:00:01.000 | ERROR    | illumio_ops.services.collect.traffic:f:1 - traffic failed"]
    (live_app.ctx.paths.logs_dir / "illumio-ops.log").write_text("\n".join(lines) + "\n")
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click("nav >> text=Logs")
    table = page.locator("[data-role=log-lines]")
    expect(table).to_contain_text("traffic failed")
    expect(table).to_contain_text("started")
    page.select_option("select[name=level]", "ERROR")
    page.get_by_role("button", name="Search").click()
    expect(table).not_to_contain_text("started")
    expect(table).to_contain_text("traffic failed")


def test_collection_settings_explain_short_archive_retention(context, live_app):
    page = context.new_page()
    _open_collection(page, live_app.url)
    form = page.locator("[data-role=collection-settings]")
    form.locator("input[name=archive_enabled]").check()
    form.locator("input[name=archive_days]").fill("7")
    form.get_by_role("button", name="Save").click()
    expect(form.locator("[role=alert]")).to_contain_text("at least as long as flows and events")
    assert live_app.ctx.settings.current().collection.archive.enabled is False


def test_mode_switch_fills_suggested_retention(context, live_app):
    page = context.new_page()
    _open_collection(page, live_app.url)
    form = page.locator("[data-role=collection-settings]")
    form.locator("select[name=mode]").select_option("alert")
    expect(form.locator("input[name=flow_days]")).to_have_value("8")
    expect(form.locator("input[name=rollup_days]")).to_have_value("8")
    expect(form).to_contain_text("past traffic is not read back")
    form.get_by_role("button", name="Save").click()
    expect(form.locator(".form-ok")).to_have_text("Saved.")
    c = live_app.ctx.settings.current().collection
    assert (c.mode, c.retention.flow_days, c.retention.rollup_days) == ("alert", 8, 8)
    form.locator("select[name=mode]").select_option("lightweight")
    form.get_by_role("button", name="Save").click()
    expect(form.locator(".form-ok")).to_have_text("Saved.")
    page.reload()
    expect(page.locator("[data-source=traffic]")).to_contain_text("Not collected in this mode")
    expect(page.locator("select[name=mode]")).to_have_value("lightweight")
