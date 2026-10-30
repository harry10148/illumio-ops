"""Investigation workbench in a browser (P6a): from an alert, the dimension panel adds conditions, two-level ranking,
event mode, and the conditions survive a reload."""
from datetime import UTC, datetime

from playwright.sync_api import expect

from illumio_ops.domain.alerting import Confidence, Trigger
from illumio_ops.domain.filter import FlowCondition
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import AlertRuleType, DataOrigin, SegmentView, Severity
from illumio_ops.store import alerts as store
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.e2e.conftest import sign_in
from tests_v6.services.reports.test_findings import flow

START, END = datetime(2026, 10, 21, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)


def _seed(live_app):
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="full"))
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [flow(src="adm", dst="db", port=3389), flow(src="adm", dst="db", port=3389),
                            flow(src="bak", dst="db", port=445), flow(src="bak", dst="web", port=443)],
                     origin=DataOrigin.INGEST, now=END)
    seg = FlowSegment(filter=FlowCondition().within(START, END), view=SegmentView.DETAIL, limit=50)
    now = datetime.now(UTC)
    t = Trigger(rule_id="b" * 32, rule_type=AlertRuleType.LATERAL, subject_key="x", severity=Severity.HIGH,
                first_seen=now, last_seen=now, late=False, message_key="alert_system_disk_low",
                params={"free": "1", "warn": "2"}, facts={}, evidence=seg, confidence=Confidence())
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        return store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="Fan-out", pack_key=None,
                                  trigger=t, at=now, channels=[], hold=None)


def test_from_alert_dimensions_ranking_events(context, live_app):
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{alert_id}")
    page.click("[data-role=open-workbench]")
    page.wait_for_selector("[data-role=wb-detail]")
    assert page.locator("[data-chip=alert]").count() == 1
    assert page.locator("[data-role=wb-detail] tbody tr").count() == 4

    # the panel: destination hosts, click db → a chip, the detail narrows to db's three rows
    dst = page.locator("[data-dim=dst_host]")
    dst.locator(".wb-dim-row").first.wait_for()
    dst.locator(".wb-dim-row", has_text="db").click()
    page.wait_for_selector("[data-chip^='dst:h:']")
    expect(page.locator("[data-role=wb-detail] tbody tr")).to_have_count(3)  # the page's CSP allows no eval
    assert dst.locator(".wb-dim-row[data-chosen=true]").count() == 1

    # two-level ranking: source host → port
    page.click("role=tab[name=/Ranking|排名/]")
    page.select_option("select[name=group_0]", "src_host")
    page.select_option("select[name=group_1]", "service")
    page.wait_for_selector("[data-role=wb-ranking] tr td:nth-child(3)")
    assert "adm" in page.inner_text("[data-role=wb-ranking]")

    # the conditions are in the address: a reload keeps them
    page.reload()
    page.wait_for_selector("[data-chip^='dst:h:']")

    # events mode swaps the panel to event dimensions
    page.click("text=Events")
    page.wait_for_selector("[data-dim=event_type]")
    assert page.locator("[data-dim=dst_host]").count() == 0
