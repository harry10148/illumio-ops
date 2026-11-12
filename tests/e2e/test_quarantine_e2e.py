"""Quarantine in a browser (P6d): the levels with the policy that refers to each, the hosts' last week of traffic, the
Label put on only after a level without policy is acknowledged, the result per host and the record on the host page."""
from playwright.sync_api import expect

from illumio_ops.store.flowdb import workloads
from tests.domain.test_quarantine import LAB_SET, MILD, MOD, SEV
from tests.e2e.conftest import sign_in

ORG = "/api/v2/orgs/1"
WL = "/orgs/1/workloads/w1"


def _setup(live_app, fake_pce, *, write=True):
    live_app.ctx.settings.update(live_app.ctx.settings.current().revision, lambda d: d["pce"].update(
        url=fake_pce.url, org_id="1", api_key="k", api_secret="s", write_api_key="wk" if write else "",
        write_api_secret="ws" if write else ""))
    with live_app.ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=WL, hostname="web-01", name=None, managed=1, enforcement_mode="selective", visibility_level=None,
            os_id=None, ven_version=None, ven_href=None, label_set=None, online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")])
        conn.commit()
    fake_pce.set(f"{ORG}/labels", 200, [
        {"href": MILD, "key": "Quarantine", "value": "Mild", "usage": {"ruleset": False}},
        {"href": MOD, "key": "Quarantine", "value": "Moderate", "usage": {"ruleset": False}},
        {"href": SEV, "key": "Quarantine", "value": "Severe", "usage": {"ruleset": True}}])
    fake_pce.set(f"{ORG}/sec_policy/active/rule_sets", 200, [LAB_SET])
    fake_pce.set(f"{ORG}/sec_policy/draft/rule_sets", 200, [LAB_SET])
    fake_pce.set(f"/api/v2{WL}", 200, {"href": WL, "labels": [{"href": "/orgs/1/labels/49", "key": "app",
                                                                "value": "Jumpdesk"}]})


def _open(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/hosts?key={WL}")
    page.locator("[data-role=q-open]").click()
    dialog = page.locator("[data-role=quarantine]")
    expect(dialog.locator("[data-role=q-policy]")).to_have_count(1)
    return page, dialog


def test_severe_lists_its_rules_and_applies(context, live_app, fake_pce):
    _setup(live_app, fake_pce)
    page, dialog = _open(context, live_app)
    expect(dialog.locator("[data-role=q-policy] li")).to_have_count(2)
    expect(dialog.locator("[data-role=q-traffic-sources]")).to_have_count(1)
    expect(dialog.locator("[data-role=q-ack]")).to_have_count(0)  # Severe has policy in force
    assert f"/api/v2{WL}" not in fake_pce.calls  # nothing read or written before confirming
    dialog.locator("[data-role=q-apply]").click()
    expect(dialog.locator("[data-role=q-outcome] tr[data-status=ok]")).to_have_count(1)
    assert fake_pce.calls.count(f"/api/v2{WL}") == 2  # read right before the write, then written
    expect(page.locator("[data-role=q-history] li")).to_have_count(1)


def test_level_without_policy_needs_acknowledging(context, live_app, fake_pce):
    _setup(live_app, fake_pce)
    _, dialog = _open(context, live_app)
    dialog.locator("select[name=level]").select_option("Mild")
    expect(dialog.locator("[data-role=q-ack]")).to_have_count(1)
    expect(dialog.locator("[data-role=q-apply]")).to_be_disabled()
    dialog.locator("[data-role=q-ack] input").check()
    expect(dialog.locator("[data-role=q-apply]")).to_be_enabled()


def test_refused_write_shown_as_failed(context, live_app, fake_pce):
    _setup(live_app, fake_pce)
    _, dialog = _open(context, live_app)
    fake_pce.set(f"/api/v2{WL}", 403, {"error": "Access denied."})
    dialog.locator("[data-role=q-apply]").click()
    row = dialog.locator("[data-role=q-outcome] tr[data-status=failed]")
    expect(row).to_have_count(1)
    assert "403" in row.inner_text()


def test_no_write_key_greyed_out(context, live_app, fake_pce):
    _setup(live_app, fake_pce, write=False)
    _, dialog = _open(context, live_app)
    expect(dialog.locator("[data-role=q-no-write-key]")).to_have_count(1)
    expect(dialog.locator("[data-role=q-apply]")).to_be_disabled()


def test_history_unread_said(context, live_app, fake_pce):
    """P6d deferred: the host page left the record out when reading it failed, which reads as "nothing was done"."""
    _setup(live_app, fake_pce)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.route("**/api/quarantine/history*", lambda route: route.abort())
    page.goto(f"{live_app.url}/hosts?key={WL}")
    expect(page.locator("[data-role=q-history-error]")).to_have_count(1)
    page.unroute_all(behavior="wait")


# ── the quarantine page: what is quarantined now (purpose-led UI spec §6.4) ──

IDLE = "/orgs/1/workloads/w2"


def _quarantined(live_app, fake_pce, *, write=True):
    from datetime import UTC, datetime

    from illumio_ops.store import quarantine_actions
    from illumio_ops.store.flowdb import labels as label_store
    _setup(live_app, fake_pce, write=write)
    ctx = live_app.ctx
    with ctx.flows().connect() as conn:
        severe = label_store.label_set_id(conn, (("Quarantine", "Severe"), ("app", "Jumpdesk")))
        mild = label_store.label_set_id(conn, (("Quarantine", "Mild"),))

        def wl(href, name, mode, label_set):
            return workloads.WorkloadRow(
                href=href, hostname=name, name=None, managed=1, enforcement_mode=mode, visibility_level=None, os_id=None,
                ven_version=None, ven_href=None, label_set=label_set, online=1, risk_exposure=None, risk_percent=None,
                risk_updated_at=None, fetched_at="x")
        workloads.replace_inventory(conn, [wl(WL, "web-01", "selective", severe), wl(IDLE, "old-02", "idle", mild),
                                           wl("/orgs/1/workloads/w3", "free-03", "selective", None)])
        conn.commit()
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        quarantine_actions.add(conn, pce_url=pce.url, org_id=pce.org_id, at=datetime.now(UTC), by="illumio", action="apply",
                               workload_href=WL, hostname="web-01", level="Severe", previous_level=None,
                               original_labels=[], result="ok", detail=None)
        conn.commit()
    fake_pce.set(f"/api/v2{WL}", 200, {"href": WL, "labels": [{"href": "/orgs/1/labels/49", "key": "app", "value": "Jumpdesk"},
                                                                {"href": SEV, "key": "Quarantine", "value": "Severe"}]})


def _page(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.click(".sidenav [data-nav-group=devices] .nav-item[data-nav='/quarantine']")
    expect(page.locator("[data-role=quarantine-page]")).to_be_visible()
    return page


def test_the_page_lists_what_is_quarantined_now_and_who_did_it(context, live_app, fake_pce):
    _quarantined(live_app, fake_pce)
    page = _page(context, live_app)
    rows = page.locator("[data-role=quarantined] tbody tr")
    expect(rows).to_have_count(2)
    expect(page.locator("[data-role=page-conclusion]")).to_have_text(
        "2 hosts in quarantine. For 1 of them it has no effect (not blocking yet, or recording only).")
    ours = page.locator(f"[data-role=quarantined] tr[data-host='{WL}']")
    expect(ours).to_contain_text("Severe")
    expect(ours).to_contain_text("illumio")
    expect(ours).to_contain_text("Blocking some (Selective)")
    other = page.locator(f"[data-role=quarantined] tr[data-host='{IDLE}']")
    expect(other).to_contain_text("not put on by this tool")
    expect(other.locator("[data-role=action-note]")).to_be_visible()
    assert ours.locator("[data-role=host-link]").get_attribute("href").endswith("#quarantine")
    expect(page.locator("[data-role=q-page-history] tbody tr")).to_have_count(1)


def test_a_quarantine_is_lifted_after_it_is_confirmed(context, live_app, fake_pce):
    _quarantined(live_app, fake_pce)
    page = _page(context, live_app)
    row = page.locator(f"[data-role=quarantined] tr[data-host='{WL}']")
    row.locator("[data-role=q-release]").click()
    assert f"/api/v2{WL}" not in [c for c in fake_pce.calls if c.endswith("/w1")]  # nothing is written before the confirmation
    row.locator("[data-role=q-release-confirm]").click()
    expect(page.locator("[data-role=q-outcome] tbody tr")).to_have_count(1)
    expect(page.locator("[data-role=q-outcome]")).to_contain_text("web-01")
    assert f"/api/v2{WL}" in fake_pce.calls
    expect(page.locator("[data-role=q-page-history] tbody tr")).to_have_count(2)  # the release is on record
    # it leaves the list at once, though the inventory still holds the label until it is read again — and that is said
    expect(page.locator(f"[data-role=quarantined] tr[data-host='{WL}']")).to_have_count(0)
    expect(page.locator("[data-role=quarantined] tbody tr")).to_have_count(1)
    expect(page.locator("[data-role=q-lag]")).to_be_visible()
    expect(page.locator("[data-role=page-conclusion]")).to_contain_text("1 hosts in quarantine.")


def test_without_the_write_key_the_list_is_there_and_nothing_can_be_lifted(context, live_app, fake_pce):
    _quarantined(live_app, fake_pce, write=False)
    page = _page(context, live_app)
    expect(page.locator("[data-role=quarantined] tbody tr")).to_have_count(2)
    expect(page.locator("[data-role=q-release]")).to_have_count(0)
    expect(page.locator("[data-role=q-no-write-key]")).to_be_visible()


def test_nothing_in_quarantine_says_so_and_where_one_starts(context, live_app, fake_pce):
    _setup(live_app, fake_pce)
    page = _page(context, live_app)
    empty = page.locator("[data-role=empty-state]")
    expect(empty).to_contain_text("No host is in quarantine.")
    expect(page.locator("[data-role=page-conclusion]")).to_have_count(0)
    empty.locator("a").click()
    expect(page.locator("[data-role=alerts-home]")).to_be_visible()


def test_the_quarantine_page_works_in_basic_mode(context, live_app, fake_pce):
    _quarantined(live_app, fake_pce)
    s = live_app.ctx.settings
    s.update(s.current().revision, lambda d: d["collection"].update(mode="lightweight"))
    page = _page(context, live_app)
    expect(page.locator("[data-role=quarantined] tbody tr")).to_have_count(2)
