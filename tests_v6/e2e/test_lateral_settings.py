"""Settings › Lateral movement in a browser: pick labels, save, see the change kept; errors in words."""
from playwright.sync_api import expect

from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.labels import label_set_id
from tests_v6.e2e.conftest import sign_in


def _inventory(ctx):
    with ctx.flows().connect() as conn:
        fin = label_set_id(conn, (("app", "Finance"), ("role", "DB")))
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/w1", hostname="fin-db", name=None, managed=1, enforcement_mode="selective",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=fin, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])


def _open(page, base_url):
    sign_in(page, base_url)
    page.click("nav >> text=Lateral movement")
    page.wait_for_selector("[data-role=lateral-settings]")


def test_critical_asset_picked_saved_and_kept(context, live_app):
    _inventory(live_app.ctx)
    page = context.new_page()
    _open(page, live_app.url)
    picker = page.locator("[data-picker=critical_assets]")
    expect(picker).to_contain_text("None set")
    picker.locator("select[name=critical_assets_key]").select_option("app")
    picker.locator("select[name=critical_assets_value]").select_option("Finance")
    picker.get_by_role("button", name="Add").click()
    form = page.locator("[data-role=lateral-settings]")
    form.get_by_role("button", name="Save").click()
    expect(form.locator(".form-ok")).to_have_text("Saved.")
    assert [(s.key, s.value) for s in live_app.ctx.settings.current().lateral.critical_assets] == [("app", "Finance")]
    page.reload()
    page.wait_for_selector("[data-role=lateral-settings]")
    expect(page.locator("[data-picker=critical_assets] .chip")).to_have_text(["app=Finance×"])


def test_invalid_value_is_said_in_words_and_ports_listed(context, live_app):
    page = context.new_page()
    _open(page, live_app.url)
    expect(page.locator("[data-role=admin-ports] tr[data-port='3389']")).to_contain_text("Built in")
    expect(page.locator("[data-role=baseline]")).to_contain_text("of 30 days")
    form = page.locator("[data-role=lateral-settings]")
    form.locator("input[name=graph_hops]").fill("9")
    form.get_by_role("button", name="Save").click()
    alert = form.locator(".form-error")
    expect(alert).to_be_visible()
    expect(alert).to_have_attribute("data-field", "settings.graph_hops")
    assert live_app.ctx.settings.current().lateral.graph_hops == 3


def test_observation_beyond_baseline_says_what_is_used(context, live_app):
    page = context.new_page()
    _open(page, live_app.url)
    form = page.locator("[data-role=lateral-settings]")
    form.locator("input[name=observation_days]").fill("60")
    expect(form).to_contain_text("The graph uses 30 days")
