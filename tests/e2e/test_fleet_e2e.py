"""VEN fleet in a browser: the counts and the filtered list from the inventory, a chosen host moved to Full only after
the preview (what Full would block) and the confirmation, the traffic update rate increased, and both on record."""
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb import labels as label_store
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.db import db_time
from illumio_ops.store.flowdb.flows import upsert_flows
from tests.e2e.conftest import sign_in
from tests.services.reports.test_findings import flow

ORG = "/api/v2/orgs/1"
DB, WEB = "/orgs/1/workloads/db", "/orgs/1/workloads/web"


def _wl(href, name, mode, label_set, now):
    return workloads.WorkloadRow(
        href=href, hostname=name, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id="ubuntu",
        ven_version="23.2.0", ven_href=None, label_set=label_set, online=1, risk_exposure=None, risk_percent=None,
        risk_updated_at=None, fetched_at=db_time(now), agent_status="active",
        last_heartbeat_at=db_time(now - timedelta(minutes=2)), policy_sync_state="applied",
        policy_applied_at=db_time(now - timedelta(hours=1)))


def _setup(live_app, fake_pce):
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update(
        url=fake_pce.url, org_id="1", api_key="k", api_secret="s", write_api_key="wk", write_api_secret="ws"))
    now = datetime.now(UTC)
    with ctx.flows().connect() as conn:
        prod = label_store.label_set_id(conn, (("app", "DB"), ("env", "Prod")))
        dev = label_store.label_set_id(conn, (("app", "Web"), ("env", "Dev")))
        workloads.replace_inventory(conn, [_wl(DB, "db", "visibility_only", prod, now),
                                           _wl(WEB, "web", "selective", dev, now)])
        upsert_flows(conn, [flow(src="adm", dst="db", decision="potentially_blocked", conns=4),
                            flow(src="bak", dst="db", decision="allowed", conns=2)], origin=DataOrigin.INGEST, now=now)
        conn.execute("UPDATE flows SET first_detected = ?, last_detected = ?",
                     (db_time(now - timedelta(hours=2)), db_time(now - timedelta(hours=1))))
        conn.commit()
    fake_pce.set(f"/api/v2{DB}", 200, {"href": DB, "managed": True, "enforcement_mode": "visibility_only"})
    fake_pce.set(f"{ORG}/workloads/set_flow_reporting_frequency", 204)


def test_overview_filter_progress_and_rate(context, live_app, fake_pce):
    _setup(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/fleet']")
    fleet = page.locator("[data-role=fleet]")
    expect(fleet.locator("[data-kpi=total] .kpi-value")).to_have_text("2")
    expect(fleet.locator("[data-role=fleet-modes] tbody tr")).to_have_count(2)
    expect(fleet.locator("[data-role=fleet-list] tbody tr")).to_have_count(2)
    fleet.locator("select[name=env]").select_option("Prod")
    expect(fleet.locator("[data-role=fleet-list] tbody tr")).to_have_count(1)
    fleet.locator("[data-role=fleet-list] tbody tr input[type=checkbox]").check()

    fleet.locator("[data-role=fleet-open-enforce]").click()
    dialog = page.locator("[data-role=fleet-enforce]")
    expect(dialog.locator("[data-role=fleet-would-block]")).to_have_text("4")
    apply = dialog.locator("[data-role=fleet-apply]")
    expect(apply).to_be_disabled()  # not before the confirmation
    assert f"/api/v2{DB}" not in fake_pce.calls  # nothing read or written before confirming
    dialog.locator("[data-role=fleet-ack] input").check()
    apply.click()
    expect(dialog.locator("[data-role=fleet-outcome] tr[data-status=ok]")).to_have_count(1)
    assert fake_pce.calls.count(f"/api/v2{DB}") == 2  # read right before the write, then written
    assert f"/api/v2{WEB}" not in fake_pce.calls  # not chosen: never touched
    dialog.locator("button.btn-quiet").first.click()  # close

    fleet.locator("[data-role=fleet-open-rate]").click()
    rate = page.locator("[data-role=fleet-rate]")
    rate.locator("[data-role=fleet-rate-apply]").click()
    expect(rate.locator("[data-role=fleet-rate-until]")).to_have_count(1)
    assert f"{ORG}/workloads/set_flow_reporting_frequency" in fake_pce.calls
    expect(fleet.locator("[data-role=fleet-history] tbody tr")).to_have_count(2)
    expect(fleet.locator("[data-role=fleet-history] [data-result=ok]")).to_have_count(2)
