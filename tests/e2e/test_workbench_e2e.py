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
from tests.e2e.conftest import sign_in
from tests.services.reports.test_findings import flow

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
    page.get_by_role("button", name="Events", exact=True).click()  # the mode, not the page's purpose line that names events
    page.wait_for_selector("[data-dim=event_type]")
    assert page.locator("[data-dim=dst_host]").count() == 0


def test_one_query_per_change(context, live_app):
    """Lab acceptance 2026-10-30: every change sent the query twice (writing the address gave react-router a new
    setSearchParams, which re-ran the effect). One click, one query."""
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    runs = []
    page.on("request", lambda r: runs.append(r.url) if r.url.endswith("/api/workbench/run") else None)
    page.goto(f"{live_app.url}/investigate?alert={alert_id}")
    page.locator("[data-dim=dst_host] .wb-dim-row").first.wait_for()
    page.wait_for_timeout(1500)
    before = len(runs)
    page.locator("[data-dim=dst_host] .wb-dim-row", has_text="db").click()
    page.wait_for_selector("[data-chip^='dst:h:']")
    page.wait_for_timeout(1500)
    assert len(runs) - before == 1


def test_late_answer_does_not_replace_newer(context, live_app):
    """Final review #2: the first query answers after the narrowed one; the page keeps the narrowed answer."""
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    held = []

    def hold_first(route):
        if not held:
            held.append(route)
        else:
            route.continue_()
    page.route("**/api/workbench/run", hold_first)
    page.goto(f"{live_app.url}/investigate?alert={alert_id}")
    page.locator("[data-dim=dst_host] .wb-dim-row", has_text="db").click()
    expect(page.locator("[data-role=wb-detail] tbody tr")).to_have_count(3)
    held[0].continue_()
    page.wait_for_timeout(1500)
    expect(page.locator("[data-role=wb-detail] tbody tr")).to_have_count(3)


def test_service_pick_narrows_to_it(context, live_app):
    """Final review #6: a picked service narrows to exactly that port (the process and event-host picks are covered
    by the filter and workbench service tests)."""
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate?alert={alert_id}")
    page.locator("[data-dim=service] .wb-dim-row", has_text="445").click()
    expect(page.locator("[data-role=wb-detail] tbody tr")).to_have_count(1)
    assert page.locator("[data-dim=service] .wb-dim-row[data-chosen=true]").count() == 1


# ── the investigation page (UI redesign spec §4.3, §5.1) ────────────────────

def _ranking(page, live_app, alert_id, group_1):
    page.goto(f"{live_app.url}/alerts/{alert_id}")
    page.click("[data-role=open-workbench]")
    page.wait_for_selector("[data-role=wb-detail]")
    page.click("role=tab[name=/Ranking|排名/]")
    page.select_option("select[name=group_0]", "src_host")
    page.select_option("select[name=group_1]", group_1)
    page.wait_for_selector("[data-role=wb-ranking] tr td:nth-child(3)")


def test_from_alert_back_link(context, live_app):
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{alert_id}")
    page.click("[data-role=open-workbench]")
    link = page.locator("[data-role=back-to-alert]")
    expect(link).to_have_text(f"← Back to alert #{alert_id}")
    assert link.get_attribute("href") == f"/alerts/{alert_id}"


def test_peer_precedent_column_states(context, live_app):
    from datetime import timedelta

    from illumio_ops.store.flowdb import ingest_state
    alert_id = _seed(live_app)
    now = datetime.now(UTC)
    with live_app.ctx.flows().connect() as conn:  # a complete baseline, so the column is computed
        ingest_state.add_coverage(conn, "traffic", now - timedelta(days=40), now)
        ingest_state.mark_started(conn, "traffic", now)
        ingest_state.mark_ok(conn, "traffic", now, watermark=now, rows=1)
        conn.commit()
    page = context.new_page()
    sign_in(page, live_app.url)
    _ranking(page, live_app, alert_id, "service")
    expect(page.locator("[data-role=peer-note]")).to_contain_text("source host and destination host")
    expect(page.locator("[data-role=peer-head]")).to_have_count(0)
    page.select_option("select[name=group_1]", "dst_host")
    expect(page.locator("[data-role=peer-head]")).to_have_text("Peer precedent (any port)")
    cells = page.locator("[data-role=peer-cell]")
    expect(cells.first).to_be_visible()
    assert "Source in no peer group" in page.inner_text("[data-role=wb-ranking]")  # the test hosts carry no labels


def test_coverage_sentence(context, live_app):
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{alert_id}")
    page.click("[data-role=open-workbench]")
    expect(page.locator("[data-role=field-coverage]")).to_contain_text("carry the initiating process")


def test_workbench_no_overflow_760(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    alert_id = _seed(live_app)
    page = narrow_context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/alerts/{alert_id}")
    page.click("[data-role=open-workbench]")
    page.wait_for_selector("[data-role=wb-detail]")
    assert no_horizontal_overflow(page)


def test_a_pick_keeps_the_label_group_a_side_holds(context, live_app):
    """5.x parity 2026-11-06: an alert's evidence can name a label group; narrowing that side by a host keeps it."""
    from illumio_ops.domain.filter import EndpointFilter
    from illumio_ops.store.flowdb import policy_objects
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="full"))
    group = "/orgs/1/sec_policy/active/label_groups/dev"
    with ctx.flows().connect() as conn:
        upsert_flows(conn, [flow(src="adm", dst="db", port=3389), flow(src="bak", dst="web", port=443)],
                     origin=DataOrigin.INGEST, now=END)
        policy_objects.replace_label_groups(conn, [policy_objects.LabelGroupRow(group, "Dev estate", "env", ("Dev",))],
                                            at=END)
        conn.commit()
    seg = FlowSegment(filter=FlowCondition(dst=EndpointFilter(label_groups=(group,))).within(START, END),
                      view=SegmentView.DETAIL, limit=50)
    now = datetime.now(UTC)
    t = Trigger(rule_id="c" * 32, rule_type=AlertRuleType.TRAFFIC, subject_key="x", severity=Severity.HIGH,
                first_seen=now, last_seen=now, late=False, message_key="alert_system_disk_low",
                params={"free": "1", "warn": "2"}, facts={}, evidence=seg, confidence=Confidence())
    pce = ctx.settings.current().pce
    with ctx.db() as conn:
        alert_id = store.insert_alert(conn, pce_url=pce.url, org_id=pce.org_id, rule_name="Dev", pack_key=None,
                                      trigger=t, at=now, channels=[], hold=None)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/investigate?alert={alert_id}")
    page.wait_for_selector("[data-role=wb-detail]")
    expect(page.locator(f"[data-chip='dst:g:{group}']")).to_contain_text("Dev estate")
    dst = page.locator("[data-dim=dst_host]")
    dst.locator(".wb-dim-row", has_text="db").click()
    page.wait_for_selector("[data-chip^='dst:h:']")
    expect(page.locator(f"[data-chip='dst:g:{group}']")).to_contain_text("Dev estate")
    expect(page.locator("[data-role=wb-detail] tbody tr")).to_have_count(1)


def test_archived_period_says_it_came_from_the_archive(context, live_app):
    """6.5.0 B1: an answer read from the archive says so — which days were read and which the archive lacks —
    in place of the "read from the PCE" line."""
    alert_id = _seed(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)

    def with_archive(route):
        answer = route.fetch()
        body = answer.json()
        body["data"]["pulled"] = {
            "source": "archive", "start": "2026-09-20T00:00:00Z", "end": "2026-09-23T00:00:00Z", "rows": 1234,
            "capped": False, "unread_from": None, "truncated_windows": 0, "read_at": "2026-10-30T12:00:00Z",
            "archive_days": 2, "archive_first": "2026-09-20", "archive_last": "2026-09-22",
            "missing_days": ["2026-09-21"], "unreadable": 0}
        route.fulfill(response=answer, json=body)
    page.route("**/api/workbench/run", with_archive)
    page.goto(f"{live_app.url}/alerts/{alert_id}")
    page.click("[data-role=open-workbench]")
    note = page.locator("[data-role=pulled][data-source=archive]")
    note.wait_for()
    text = note.inner_text()
    assert "read from the archive, not from the PCE" in text and "2026-09-20 to 2026-09-22" in text
    assert "1,234 rows" in text
    assert "no file for these 1 day(s)" in note.locator("[data-role=archive-missing]").inner_text()
    assert "2026-09-21" in note.locator("[data-role=archive-missing]").inner_text()
