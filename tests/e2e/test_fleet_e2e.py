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
    # the sentence to confirm names what the preview showed: Full's connections, Selective's Deny Rules
    ack = dialog.locator("[data-role=fleet-ack]")
    expect(ack).to_contain_text("the Potentially Blocked connections")
    dialog.locator("select[name=target]").select_option("selective")
    expect(dialog.locator("[data-role=fleet-blocks-selective]")).to_be_visible()
    expect(ack).to_contain_text("checked in the PCE the Deny Rules that apply to these hosts")
    expect(ack).not_to_contain_text("Potentially Blocked")
    dialog.locator("select[name=target]").select_option("full")
    expect(dialog.locator("[data-role=fleet-would-block]")).to_have_text("4")
    expect(ack).to_contain_text("the Potentially Blocked connections")
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


def test_a_slow_answer_to_an_earlier_filter_does_not_replace_the_newer_list(context, live_app, fake_pce):
    """Review 2026-11-06: every filter change sent a request and every answer was shown; Prod answering after Dev
    left the Dev filter over Prod's hosts (and "choose shown" picked them)."""
    import time
    _setup(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)

    def slow_prod(route):
        if "env=Prod" in route.request.url:
            time.sleep(1.5)
        route.continue_()

    page.route("**/api/fleet/hosts*", slow_prod)
    page.click(".sidenav .nav-item[data-nav='/fleet']")
    fleet = page.locator("[data-role=fleet]")
    expect(fleet.locator("[data-role=fleet-list] tbody tr")).to_have_count(2)
    fleet.locator("select[name=env]").select_option("Prod")
    fleet.locator("select[name=env]").select_option("Dev")
    page.wait_for_timeout(2500)  # Prod's answer has come back by now
    rows = fleet.locator("[data-role=fleet-list] tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("web")


# ── the VEN overview is the way in to hosts (2026-11-12): a search across what names a host, and where to start ──

def _find(live_app, fake_pce):
    from dataclasses import replace

    from tests.e2e.test_alerts_e2e import AlertRuleType, _about
    _setup(live_app, fake_pce)
    ctx = live_app.ctx
    now = datetime.now(UTC)
    with ctx.flows().connect() as conn:
        prod = label_store.label_set_id(conn, (("app", "DB"), ("env", "Prod")))
        held = label_store.label_set_id(conn, (("Quarantine", "Severe"),))
        workloads.replace_inventory(conn, [
            replace(_wl(DB, "db", "visibility_only", prod, now), addresses_json='["10.1.2.3"]'),
            replace(_wl(WEB, "web", "selective", held, now), last_heartbeat_at=db_time(now - timedelta(hours=30))),
            _wl("/orgs/1/workloads/app", "app", "selective", None, now)])
        conn.commit()
    for _ in range(2):
        _about(ctx, [(DB, "subject"), ("ip:192.168.20.99", "subject")], rule_type=AlertRuleType.EVENT, subject=DB,
               pack_key="rule_agent_tampering")


def _rows(page):
    return page.locator("[data-role=fleet-list] tbody tr")


def test_a_host_is_found_by_its_address_and_opened(context, live_app, fake_pce):
    _find(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/fleet']")
    expect(_rows(page)).to_have_count(3)
    page.fill("[data-role=fleet-find] input[name=q]", "10.1.2")
    expect(_rows(page)).to_have_count(1)
    row = page.locator(f"[data-role=fleet-list] [data-host='{DB}']")
    expect(row.locator("[data-role=host-addresses]")).to_have_text("10.1.2.3")
    expect(row).to_contain_text("2 alerts in the last 7 days")
    row.locator("[data-role=host-link]").click()
    expect(page.locator("h1")).to_have_text("db")
    page.click("[data-role=host-profile] >> text=← VEN fleet")
    expect(page.locator("[data-role=fleet-find]")).to_be_visible()


def test_the_quick_filters_say_how_many_and_list_them(context, live_app, fake_pce):
    _find(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/fleet")
    groups = page.locator("[data-role=fleet-groups]")
    expect(groups.locator("button[data-value=alerted]")).to_have_text("With alerts1")
    expect(groups.locator("button[data-value=lost]")).to_have_text("Lost contact1")
    expect(groups.locator("button[data-value=quarantined]")).to_have_text("In quarantine1")
    groups.locator("button[data-value=quarantined]").click()
    expect(_rows(page)).to_have_count(1)
    expect(_rows(page).first).to_contain_text("In quarantine: Severe")
    groups.locator("button[data-value=alerted]").click()
    expect(_rows(page)).to_have_count(1)
    # an address with alerts that the PCE does not manage is not a row of this list: it is named under it
    loose = page.locator("[data-role=fleet-unmanaged] [data-role=host-link]")
    expect(loose).to_have_text("192.168.20.99")
    assert loose.get_attribute("href").endswith("#alerts")


def test_an_address_the_inventory_does_not_hold_is_offered_as_unmanaged(context, live_app, fake_pce):
    _find(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/fleet")
    page.fill("[data-role=fleet-find] input[name=q]", "203.0.113.7")
    offer = page.locator("[data-role=fleet-open-unmanaged] [data-role=host-link]")
    expect(offer).to_have_text("203.0.113.7")
    offer.click()
    expect(page.locator("[data-role=page-conclusion]")).to_contain_text("an unmanaged address")


def test_the_old_host_search_address_leads_to_the_overview_with_what_was_asked(context, live_app, fake_pce):
    _find(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?q=web")
    page.wait_for_url("**/fleet?q=web")
    expect(_rows(page)).to_have_count(1)
