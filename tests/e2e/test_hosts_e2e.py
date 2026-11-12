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
from tests.e2e.conftest import sign_in
from tests.services.analysis.test_tamper import VEN, _tamper
from tests.services.reports.test_findings import flow

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
        # as the lightweight store answers: no name it knew, the words for one (final review: not the href)
        body["data"]["name"], body["data"]["named"] = "Removed workload …db", False
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
    # The other sections' answers may still be in the handler: let them finish, then drop the route without racing a
    # fulfill (behavior="wait" could still collide with one: "Route is already handled", CI 2026-11-09).
    page.wait_for_load_state("networkidle")
    page.unroute_all(behavior="ignoreErrors")


# ── the host page (UI redesign spec §4.4) ───────────────────────────────────

def test_host_search_then_open(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav .nav-item[data-nav='/hosts']")
    page.fill("input[name=host_q]", "db")
    page.locator("[data-role=host-hits] a", has_text="db").click()
    expect(page.locator("[data-role=host-profile] h1")).to_have_text("db")


def test_unmanaged_host_has_no_quarantine_button(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key=ip:10.0.0.250")
    expect(page.locator("[data-role=q-not-eligible]")).to_contain_text("not a managed host")
    expect(page.locator("[data-section=quarantine]")).to_have_count(0)


def test_not_in_inventory_no_button(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key=/orgs/1/workloads/gone")
    expect(page.locator("[data-role=q-not-eligible]")).to_contain_text("not in the current inventory")
    expect(page.locator("[data-section=quarantine]")).to_have_count(0)


def test_visibility_host_marked_no_effect(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("[data-role=q-no-effect]")).to_contain_text("no effect")
    expect(page.locator("[data-role=q-remove]")).to_have_class("btn-danger")


def test_usual_basic_mode_explained(context, live_app):
    _seed(live_app)
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision,
                                 lambda d: d["collection"].update(mode="lightweight"))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("[data-role=usual] [data-role=needs-advanced]")).to_have_count(1)


def test_host_no_overflow_760(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    _seed(live_app)
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    page.locator("[data-role=usual]").wait_for()
    assert no_horizontal_overflow(page)


def test_the_enforcement_mode_is_said_in_plain_words_with_the_pce_term_beside(context, live_app):
    _seed(live_app)  # db is in Visibility Only
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    expect(page.locator("[data-role=host-mode]")).to_have_text("Recording only (Visibility Only)")


# ── the host page is where every host name leads (purpose-led UI spec §6.2, §6.3) ──

def _alert_about(ctx, key, *, pack_key="rule_agent_tampering", n=1):
    from tests.e2e.test_alerts_e2e import AlertRuleType, _about
    return [_about(ctx, [(key, "subject")], rule_type=AlertRuleType.EVENT, subject=key, pack_key=pack_key) for _ in range(n)]


def test_arriving_with_an_anchor_lands_on_that_section(context, live_app):
    _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}#tamper")
    section = page.locator("#tamper")
    expect(section.locator("[data-role=tamper-readings]")).to_be_visible()
    expect(section).to_be_in_viewport()
    box = section.bounding_box()
    assert 0 <= box["y"] < 900, box


def test_the_host_page_says_what_it_comes_to_and_lists_the_alerts_about_this_host(context, live_app):
    _seed(live_app)
    ids = _alert_about(live_app.ctx, DB, n=2)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={DB}")
    said = page.locator("[data-role=page-conclusion]")
    expect(said).to_contain_text("db: Recording only (Visibility Only); VEN ")
    expect(said).to_contain_text("2 alerts in the last 7 days; not quarantined.")
    listed = page.locator("#alerts [data-role=host-alert-list] li")
    expect(listed).to_have_count(2)
    listed.first.locator("a").click()
    page.wait_for_url(f"**/alerts/{ids[-1]}")


def test_without_a_host_the_page_offers_where_to_start(context, live_app, fake_pce):
    from tests.e2e import test_fleet_e2e as fleet_e2e
    from tests.e2e.test_ui_rules_e2e import seed_everything
    seed_everything(live_app, fake_pce)
    _alert_about(live_app.ctx, fleet_e2e.DB, n=3)
    _alert_about(live_app.ctx, fleet_e2e.WEB)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts")
    alerted = page.locator("[data-role=start-alerted] li")
    expect(alerted).to_have_count(2)
    expect(alerted.first).to_contain_text("db")
    expect(alerted.first).to_contain_text("3 alerts")
    assert alerted.first.locator("[data-role=host-link]").get_attribute("href").endswith("#alerts")
    expect(page.locator("[data-role=start-quarantined]")).to_contain_text("No host is in quarantine.")
    expect(page.locator("[data-role=start-lost]")).to_be_visible()
    expect(page.locator("[data-role=start-attention]")).to_be_visible()
    alerted.first.locator("[data-role=host-link]").click()
    expect(page.locator("h1")).to_have_text("db")
    # typing a name puts the lists away: the page is then about what is being looked for
    page.goto(f"{live_app.url}/hosts")
    page.fill("input[name=host_q]", "we")
    expect(page.locator("[data-role=host-start]")).to_have_count(0)


def test_basic_mode_keeps_the_lists_and_says_what_the_attention_list_needs(context, live_app, fake_pce):
    from tests.e2e.test_ui_rules_e2e import seed_everything
    seed_everything(live_app, fake_pce)
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["collection"].update(mode="lightweight"))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts")
    expect(page.locator("[data-role=start-alerted]")).to_be_visible()
    expect(page.locator("[data-role=start-quarantined]")).to_be_visible()
    expect(page.locator("[data-role=start-attention] [data-role=needs-advanced]")).to_be_visible()


def test_a_host_no_longer_in_the_inventory_still_opens_and_says_so(context, live_app):
    _seed(live_app)
    gone = "/orgs/1/workloads/gone"
    _alert_about(live_app.ctx, gone)
    page = context.new_page()
    sign_in(page, live_app.url)
    link = page.locator("[data-role=alert-list] [data-role=host-link]").first
    expect(link).to_be_visible()
    link.click()
    expect(page.locator("[data-role=page-conclusion]")).to_contain_text("not in the current inventory")
    expect(page.locator("[data-role=page-conclusion]")).to_contain_text("1 alerts in the last 7 days")
    expect(page.locator(".form-error")).to_have_count(0)


def test_the_alerts_page_can_be_narrowed_to_one_host_and_widened_again(context, live_app):
    _seed(live_app)
    _alert_about(live_app.ctx, DB)
    from tests.e2e.test_alerts_e2e import seed as seed_alert
    seed_alert(live_app.ctx)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/?device={DB}")
    expect(page.locator("[data-role=alert-list] tbody tr")).to_have_count(1)
    expect(page.locator("[data-role=alert-device-filter]")).to_contain_text("Host: db")
    page.locator("[data-role=alert-device-filter] button").click()
    expect(page.locator("[data-role=alert-list] tbody tr")).to_have_count(2)
