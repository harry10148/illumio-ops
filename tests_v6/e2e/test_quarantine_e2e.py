"""Quarantine in a browser (P6d): the levels with the policy that refers to each, the hosts' last week of traffic, the
Label put on only after a level without policy is acknowledged, the result per host and the record on the host page."""
from playwright.sync_api import expect

from illumio_ops.store.flowdb import workloads
from tests_v6.domain.test_quarantine import LAB_SET, MILD, MOD, SEV
from tests_v6.e2e.conftest import sign_in

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
