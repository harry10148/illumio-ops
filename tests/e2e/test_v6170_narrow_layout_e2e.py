"""Phase D narrow layouts: content fits the viewport and host names break at punctuation."""
from playwright.sync_api import expect

from tests.e2e.conftest import no_horizontal_overflow, sign_in

LONG_HOST = "win11-ilo-test.lab.local"


def _page(browser, live_app, width=390):
    context = browser.new_context(locale="en-US", viewport={"width": width, "height": 844})
    page = context.new_page()
    sign_in(page, live_app.url)
    return context, page


def _seed_hostnames(live_app, names):
    from illumio_ops.store.flowdb import workloads

    with live_app.ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=f"/orgs/1/workloads/{name}", hostname=name, name=None, managed=1, enforcement_mode=None,
            visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x") for name in names])
        conn.commit()


def test_alert_list_with_long_hosts_fits_390(browser, live_app):
    from tests.e2e.test_alerts_e2e import _about

    _about(live_app.ctx, [(f"/orgs/1/workloads/{LONG_HOST}", "source"),
                          ("/orgs/1/workloads/batch.lab.local", "destination")])
    _seed_hostnames(live_app, [LONG_HOST, "batch.lab.local"])
    context, page = _page(browser, live_app)
    try:
        page.locator("[data-role=alert-list] [data-role=host-link]").first.wait_for()
        assert no_horizontal_overflow(page)
    finally:
        context.close()


def test_alert_flow_evidence_fits_390(browser, live_app):
    from tests.e2e.test_workbench_e2e import _seed

    alert_id = _seed(live_app)
    context, page = _page(browser, live_app)
    try:
        page.goto(f"{live_app.url}/alerts/{alert_id}")
        page.locator("[data-role=evidence] tbody tr").first.wait_for()
        assert no_horizontal_overflow(page)
    finally:
        context.close()


def test_long_host_profile_fits_390(browser, live_app):
    from tests.e2e.test_hosts_e2e import DB, _seed

    _seed(live_app)
    with live_app.ctx.flows().connect() as conn:
        conn.execute("UPDATE workloads SET hostname = ? WHERE href = ?", (LONG_HOST, DB))
        conn.commit()
    context, page = _page(browser, live_app)
    try:
        page.goto(f"{live_app.url}/hosts?key={DB}")
        expect(page.locator("h1")).to_contain_text(LONG_HOST)
        assert no_horizontal_overflow(page)
    finally:
        context.close()


def test_rule_schedule_fits_390(browser, live_app):
    from tests.e2e.test_rule_schedules_e2e import _scheduled

    _scheduled(live_app)
    context, page = _page(browser, live_app)
    try:
        page.goto(f"{live_app.url}/rule-schedules")
        expect(page.locator("[data-role=rs-list] tbody tr")).to_have_count(1)
        assert no_horizontal_overflow(page)
    finally:
        context.close()


def test_selecting_alert_scrolls_stacked_detail_into_content_view(browser, live_app):
    from tests.e2e.test_alerts_e2e import _about

    _about(live_app.ctx, [(f"/orgs/1/workloads/{LONG_HOST}", "source")])
    _seed_hostnames(live_app, [LONG_HOST])
    context, page = _page(browser, live_app, width=1024)
    try:
        page.locator("[data-role=alert-list] tbody tr").first.click()
        detail = page.locator("[data-role=alert-detail-pane]")
        page.wait_for_function("""() => {
          const content = document.querySelector('main.content');
          const detail = document.querySelector('[data-role=alert-detail-pane]');
          if (!content || !detail) return false;
          const c = content.getBoundingClientRect(), d = detail.getBoundingClientRect();
          return d.top < c.bottom && d.bottom > c.top;
        }""")
        content_box = page.locator("main.content").bounding_box()
        detail_box = detail.bounding_box()
        assert content_box and detail_box
        assert detail_box["y"] < content_box["y"] + content_box["height"]
        assert detail_box["y"] + detail_box["height"] > content_box["y"]
    finally:
        context.close()


def test_host_name_breaks_only_after_dot_or_hyphen(browser, live_app):
    from tests.e2e.test_alerts_e2e import _about

    _about(live_app.ctx, [(f"/orgs/1/workloads/{LONG_HOST}", "source")])
    _seed_hostnames(live_app, [LONG_HOST])
    context, page = _page(browser, live_app)
    try:
        link = page.locator("[data-role=alert-list] [data-role=host-link]").first
        expect(link).to_contain_text(LONG_HOST)
        lines = link.evaluate("""(element) => {
          const lines = new Map();
          const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            const node = walker.currentNode;
            for (let i = 0; i < node.length; i++) {
              const range = document.createRange();
              range.setStart(node, i); range.setEnd(node, i + 1);
              const rect = range.getBoundingClientRect();
              const key = Math.round(rect.top);
              lines.set(key, (lines.get(key) || "") + node.data[i]);
            }
          }
          return [...lines.values()].map((line) => line.trim()).filter(Boolean);
        }""")
        assert len(lines) > 1, lines
        assert all(line.endswith((".", "-")) for line in lines[:-1]), lines
    finally:
        context.close()
