"""Host profile in a browser (P6b): who connects and the ports from the workbench, tamper investigation with a
known cause, and an unmanaged address showing only its traffic."""
from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.db import db_time
from illumio_ops.store.flowdb.events import upsert_events
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.e2e.conftest import sign_in
from tests_v6.services.analysis.test_tamper import VEN, _tamper
from tests_v6.services.reports.test_findings import flow

DB = "/orgs/1/workloads/db"


def _seed(live_app):
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="full"))
    now = datetime.now(UTC)
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [flow(src="adm", dst="db", port=3389), flow(src="bak", dst="db", port=445),
                            flow(src="x", dst="db", port=445, unmanaged_src=True)], origin=DataOrigin.INGEST, now=now)
        conn.execute("UPDATE flows SET first_detected = ?, last_detected = ?",
                     (db_time(now - timedelta(hours=2)), db_time(now - timedelta(hours=1))))
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=DB, hostname="db", name=None, managed=1, enforcement_mode="visibility_only", visibility_level=None,
            os_id="ubuntu-x86_64-noble", ven_version="26.2", ven_href=VEN, label_set=None, online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")])
        start = now - timedelta(hours=3)
        upsert_events(conn, [normalize_event(_tamper(i, start + timedelta(minutes=10 * i))) for i in range(12)],
                      origin=DataOrigin.INGEST, now=now)
        conn.commit()


def test_managed_host_profile(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("h1")).to_have_text("db")
    who = page.locator("[data-section=src_host]").first
    expect(who.locator("tbody tr")).to_have_count(3)
    assert "adm" in who.inner_text() and "bak" in who.inner_text()
    expect(page.locator("[data-section=service]").first.locator("tbody tr")).to_have_count(2)
    expect(page.locator("[data-role=tamper-readings] tbody tr")).to_have_count(12)
    assert page.locator("[data-role=tamper-guidance] li").count() > 0

    form = page.locator("[data-role=tamper-note-form]")
    form.locator("input[name=reason]").fill("NetBird, known")
    form.locator("button[type=submit]").click()
    notes = page.locator("[data-role=tamper-notes] li")
    expect(notes).to_have_count(1)
    assert "NetBird" in notes.inner_text()


def test_unmanaged_address_shows_traffic_only(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key=ip:10.0.0.250")
    page.wait_for_selector("[data-role=host-profile]")
    expect(page.locator("[data-section=tamper]")).to_have_count(0)
    expect(page.locator("[data-section=events]")).to_have_count(0)
    expect(page.locator("[data-section=src_host]")).to_have_count(2)  # who connects, and mode switch by source


def test_unnamed_host_named_from_its_traffic(context, live_app):
    """Lab acceptance 2026-10-30: in lightweight mode the store holds no flows, so a host the inventory has no name
    for was titled with its href; the page names it from the traffic it reads."""
    import json as _json
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)

    def unnamed(route):
        resp = route.fetch()
        body = _json.loads(resp.text())
        body["data"]["name"] = body["data"]["key"]  # as the lightweight store answers
        route.fulfill(response=resp, body=_json.dumps(body))
    page.route("**/api/hosts/profile*", unnamed)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("h1")).to_have_text("db")
    page.unroute_all(behavior="wait")  # the profile asked again may still be rewritten: not at browser close


def test_late_profile_does_not_replace_current(context, live_app):
    """Final review #5: open B from A's page, go back to A before B answers; B's late answer must not show under A."""
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    held = []
    page.route("**/api/hosts/profile*adm*", lambda route: held.append(route))
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("h1")).to_have_text("db")
    page.locator("[data-section=src_host]").first.locator("a", has_text="adm").click()
    page.wait_for_timeout(500)
    page.go_back()
    expect(page.locator("h1")).to_have_text("db")
    held[0].continue_()
    page.wait_for_timeout(1500)
    expect(page.locator("h1")).to_have_text("db")


def test_cut_answer_is_said(context, live_app):
    """Final review #2: a section whose answer was cut at the PCE's limit says so, rather than looking complete."""
    import json as _json
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)

    def truncated(route):
        resp = route.fetch()
        body = _json.loads(resp.text())
        body["data"]["coverage"]["truncated"] = True
        route.fulfill(response=resp, body=_json.dumps(body))
    page.route("**/api/workbench/dimension", truncated)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("[data-section=src_host] [data-role=caveat]").first).to_have_count(1)
    page.unroute_all(behavior="wait")  # the other sections' answers are still being rewritten: not at browser close
