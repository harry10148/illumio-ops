"""Reports in a browser (P5a Tasks 8–9): generate, wait, download, land on a linked report, schedule and run."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from illumio_ops.services.reports import generate
from tests.e2e.conftest import sign_in

SHOTS = Path(__file__).resolve().parents[2] / "tmp" / "v6-p5-verification"


def _reports(page, base):
    sign_in(page, base)
    page.goto(base + "/reports")
    page.wait_for_selector("[data-role=report-catalog]")


def test_generate_wait_download(context, live_app):
    page = context.new_page()
    _reports(page, live_app.url)
    entry = page.locator("[data-report-type=unmanaged_endpoints]")
    entry.get_by_role("button", name="Generate…").click()
    form = page.locator("[data-role=generate-form]")
    form.locator("select[name=lookback_days]").select_option("14")
    form.locator("select[name=lang]").select_option("zh_TW")
    form.get_by_role("button", name="Generate", exact=True).click()
    row = page.locator("[data-role=report-list] tbody tr").first
    expect(row).to_have_attribute("data-status", "queued")
    generate.run_queued(live_app.ctx)  # the reports job, run here instead of by the scheduler
    expect(row).to_have_attribute("data-status", "done", timeout=10_000)  # the page polls while one is queued
    with page.expect_download() as dl:
        row.get_by_role("link", name="HTML").click()
    text = Path(dl.value.path()).read_text(encoding="utf-8")
    assert "非受管端點" in text and "rpt_" not in text
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / "reports-1280.png"), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(SHOTS / "reports-390.png"), full_page=True)


def test_linked_report_is_marked(context, live_app):
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.registry import ReportParams
    rid = generate.enqueue(live_app.ctx, ReportParams(report_type=ReportType.NEW_CONNECTIONS), trigger="manual",
                           schedule_id=None, now=datetime.now(UTC))
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(f"{live_app.url}/reports?id={rid}")
    expect(page.locator(f"[data-report-id='{rid}']")).to_have_attribute("data-highlight", "true")


def test_lightweight_mode_flow_reports_available(context, live_app):
    """Lightweight mode pulls a flow report's period from the PCE when it is made (spec §6.4, 2026-10-29)."""
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="lightweight"))
    page = context.new_page()
    _reports(page, live_app.url)
    entry = page.locator("[data-report-type=lateral_posture]")
    expect(entry).to_have_attribute("data-available", "true")
    expect(entry.get_by_role("button", name="Generate…")).to_be_enabled()


def test_schedule_create_and_run_now(context, live_app):
    page = context.new_page()
    _reports(page, live_app.url)
    page.get_by_role("tab", name="Schedules").click()
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Daily lateral")
    editor.locator("select[name=frequency]").select_option("daily")
    editor.get_by_role("button", name="Save").click()
    row = page.locator("[data-role=schedule-list] tbody tr").first
    expect(row).to_contain_text("Daily lateral")
    expect(row).to_contain_text("Every day at 08:00")
    row.get_by_role("button", name="Run now").click()
    page.wait_for_url("**/reports?id=*")
    marked = page.locator("[data-highlight=true]")
    expect(marked).to_contain_text("Daily lateral")
    assert [s.name for s in live_app.ctx.settings.current().reports.schedules] == ["Daily lateral"]


def test_editing_a_schedule_cannot_switch_the_editor_target(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/reports?tab=schedules")
    page.wait_for_selector("[data-role=schedules]")
    for name in ("Schedule A", "Schedule B"):
        page.get_by_role("button", name="Add a schedule").click()
        editor = page.locator("[data-role=schedule-editor]")
        editor.locator("input[name=name]").fill(name)
        editor.locator("select[name=frequency]").select_option("daily")
        editor.get_by_role("button", name="Save").click()
        expect(page.locator(f"[data-role=schedule-list] tr:has-text('{name}')")).to_be_visible()
    row_a = page.locator("[data-role=schedule-list] tr:has-text('Schedule A')")
    row_b = page.locator("[data-role=schedule-list] tr:has-text('Schedule B')")
    row_b.get_by_role("button", name="Delete").click()  # a pending confirmation...
    expect(row_b.locator("[data-role=schedule-delete-confirm]")).to_be_visible()
    row_a.get_by_role("button", name="Edit").click()  # ...is dropped when the editor opens
    expect(page.locator("[data-role=schedule-delete-confirm]")).to_have_count(0)
    editor = page.locator("[data-role=schedule-editor]")
    expect(editor.locator("input[name=name]")).to_have_value("Schedule A")
    expect(row_b.get_by_role("button", name="Edit")).to_be_disabled()
    editor.locator("input[name=name]").fill("Schedule A2")
    editor.get_by_role("button", name="Save").click()
    expect(editor).to_have_count(0)  # saved: the editor closes only on success
    schedules = live_app.ctx.settings.current().reports.schedules
    assert {s.name for s in schedules} == {"Schedule A2", "Schedule B"}


def test_report_single_delete_requires_confirmation(context, live_app):
    ids = _made(live_app)
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/reports?tab=produced")
    row = page.locator(f"[data-report-id='{ids[0]}']")
    requests = []
    page.on("request", lambda request: requests.append(request) if request.method == "DELETE" else None)
    row.get_by_role("button", name="Delete").click()
    expect(row.locator("[data-role=report-delete-confirm]")).to_be_visible()
    assert requests == []
    row.locator("[data-role=report-delete-confirm]").click()
    expect(page.locator(f"[data-report-id='{ids[0]}']")).to_have_count(0)
    assert len(requests) == 1


def test_schedule_errors_are_never_dropped(context, live_app):
    """6.16.2: an error naming a field the editor shows goes next to that field; any other error (no field, or one
    with no place on the form, such as a rejected recipient) stays at the bottom, so it is never lost."""
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/reports?tab=schedules")
    page.wait_for_selector("[data-role=schedules]")
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Error check")
    answer = {"field": "schedule.recipients.0"}

    def refuse(route):
        if route.request.method != "POST":
            route.continue_()
            return
        route.fulfill(status=400, content_type="application/json", body=json.dumps({
            "ok": False, "data": None, "error": {"code": "invalid_input", "message_key": "err_invalid_input",
                                                  "params": {}, "field": answer["field"]}}))

    page.route("**/api/report-schedules", refuse)
    editor.get_by_role("button", name="Save").click()
    expect(editor.locator(".form-error")).to_have_text("Some fields are not valid.")
    answer["field"] = "schedule.lookback_days"
    editor.get_by_role("button", name="Save").click()
    expect(editor.locator('.field-error[data-field="schedule.lookback_days"]')).to_have_text("Some fields are not valid.")
    expect(editor.locator(".form-error")).to_have_count(0)
    answer["field"] = "schedule.name"
    editor.get_by_role("button", name="Save").click()
    expect(editor.locator('.field-error[data-field="schedule.name"]')).to_have_text("Some fields are not valid.")
    expect(editor.locator(".form-error")).to_have_count(0)


def test_schedule_single_delete_requires_confirmation(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/reports?tab=schedules")
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Delete check")
    editor.locator("select[name=frequency]").select_option("daily")
    editor.get_by_role("button", name="Save").click()
    row = page.locator("[data-role=schedule-list] tr:has-text('Delete check')")
    requests = []
    page.on("request", lambda request: requests.append(request) if request.method == "DELETE" else None)
    row.get_by_role("button", name="Delete").click()
    expect(row.locator("[data-role=schedule-delete-confirm]")).to_be_visible()
    assert requests == []
    row.locator("[data-role=schedule-delete-confirm]").click()
    expect(row).to_have_count(0)
    assert len(requests) == 1


def _finance_inventory(ctx):
    from illumio_ops.store.flowdb import labels, workloads
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/f1", hostname="f1", name=None, managed=1, enforcement_mode="full",
            visibility_level=None, os_id=None, ven_version=None, ven_href=None,
            label_set=labels.label_set_id(conn, (("app", "Finance"), ("env", "Prod"))), online=1, risk_exposure=None,
            risk_percent=None, risk_updated_at=None, fetched_at="x")])
        conn.commit()


def test_app_summary_needs_an_app(context, live_app):
    _finance_inventory(live_app.ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    entry = page.locator("[data-report-type=app_summary]")
    entry.get_by_role("button", name="Generate…").click()
    form = page.locator("[data-role=generate-form]")
    go = form.get_by_role("button", name="Generate", exact=True)
    expect(go).to_be_disabled()  # no app chosen yet
    form.locator("select[name=filter_app]").select_option("Finance")
    go.click()
    row = page.locator("[data-role=report-list] tbody tr").first
    expect(row).to_have_attribute("data-status", "queued")
    generate.run_queued(live_app.ctx)
    expect(row).to_have_attribute("data-status", "done", timeout=10_000)
    with page.expect_download() as dl:
        row.get_by_role("link", name="HTML").click()
    assert "App summary: Finance" in Path(dl.value.path()).read_text(encoding="utf-8")


def test_the_report_filter_starts_from_the_loaded_labels_and_holds_back_a_bad_condition(context, live_app):
    """Review 2026-11-06: the condition editor was mounted before its choices arrived, so its label key stayed empty
    and offered no values; and a condition that did not parse (443/tcpp) let the report be generated without it."""
    _finance_inventory(live_app.ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    entry = page.locator("[data-report-type=traffic]")
    entry.get_by_role("button", name="Generate…").click()
    form = page.locator("[data-role=generate-form]")
    form.locator("[data-role=report-filter] summary").first.click()  # the filter is folded until it holds something
    dst = form.locator("[data-side=dst]")
    expect(dst.locator("select[name=dst_label_key]")).not_to_have_value("")
    dst.locator("select[name=dst_label_key]").select_option("app")
    expect(dst.locator("select[name=dst_label_value] option", has_text="Finance")).to_have_count(1)
    go = form.get_by_role("button", name="Generate", exact=True)
    form.locator("input[name=ports]").fill("443/tcpp")
    form.locator("input[name=ports]").blur()
    expect(go).to_be_disabled()
    form.locator("input[name=ports]").fill("443")
    form.locator("input[name=ports]").blur()
    expect(go).to_be_enabled()


def test_schedule_with_filter(context, live_app):
    _finance_inventory(live_app.ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    page.get_by_role("tab", name="Schedules").click()
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Finance traffic")
    editor.locator("select[name=report_type]").select_option("traffic")
    editor.locator("[data-role=report-filter] summary").first.click()  # folded until it holds something
    dst = editor.locator("[data-side=dst]")
    dst.locator("select[name=dst_label_key]").select_option("app")
    dst.locator("select[name=dst_label_value]").select_option("Finance")
    dst.get_by_role("button", name="Add label").click()
    editor.locator("input[name=ports]").fill("443")
    editor.locator("input[name=ports]").blur()
    editor.get_by_text("Exclusions").click()
    editor.locator("input[name=src_exclude_ips]").fill("10.9.0.0/16")
    editor.locator("input[name=src_exclude_ips]").blur()
    editor.get_by_role("button", name="Save").click()
    row = page.locator("[data-role=schedule-list] tbody tr").first
    expect(row.locator("[data-role=schedule-filter]")).to_have_text(
        "Destination: app=Finance; Source is not: 10.9.0.0/16; Port: 443/TCP")
    saved = live_app.ctx.settings.current().reports.schedules[0]
    assert saved.filter is not None and saved.filter.dst.labels[0].values == ("Finance",)
    assert [p.port for p in saved.filter.ports] == [443] and saved.filter.src_exclude.ips == ("10.9.0.0/16",)


def test_editing_a_schedule_keeps_filter_fields_the_picker_does_not_show(context, live_app):
    _finance_inventory(live_app.ctx)
    ctx = live_app.ctx
    sched = {"id": "a" * 32, "name": "Finance 443", "enabled": True, "report_type": "traffic", "lookback_days": 7,
             "frequency": "daily", "day_of_week": None, "day_of_month": None, "hour": 8, "minute": 0,
             "formats": ["html"], "email": False, "recipients": [], "lang": None, "keep": 30,
             "filter": {"dst": {"labels": [{"key": "app", "values": ["Finance"]}]}, "ports": [{"port": 443, "proto": 6}],
                        "src_exclude": {"ips": ["10.9.0.0/16"]}}}
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"]["schedules"].append(sched))
    page = context.new_page()
    _reports(page, live_app.url)
    page.get_by_role("tab", name="Schedules").click()
    page.locator("[data-role=schedule-list] tbody tr").first.get_by_role("button", name="Edit").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Finance 443 renamed")
    editor.get_by_role("button", name="Save").click()
    expect(page.locator("[data-role=schedule-list] tbody tr").first).to_contain_text("Finance 443 renamed")
    saved = ctx.settings.current().reports.schedules[0].filter
    assert saved is not None and [p.port for p in saved.ports] == [443] and saved.src_exclude.ips == ("10.9.0.0/16",)
    assert saved.dst.labels[0].values == ("Finance",)


def test_schedule_lookback_stays_within_the_type(context, live_app):
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"]["retention"].update(
        flow_days=7, baseline_days=7))
    page = context.new_page()
    _reports(page, live_app.url)
    page.get_by_role("tab", name="Schedules").click()
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Short retention")
    editor.locator("select[name=report_type]").select_option("traffic")
    editor.get_by_role("button", name="Save").click()
    expect(page.locator("[data-role=schedule-list] tbody tr").first).to_contain_text("Short retention")
    # past the kept 7 days the period is pulled on demand, so the usual week is offered (spec §6.4)
    assert ctx.settings.current().reports.schedules[0].lookback_days == 7


def test_audit_in_lightweight_mode(context, live_app):
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.events import upsert_events
    from tests.services.reports.test_audit import event
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="lightweight"))
    yesterday = datetime.now(UTC) - timedelta(days=1)
    with ctx.flows().connect() as conn:
        upsert_events(conn, [event("sec_policy.create", yesterday, user="alice")], origin=DataOrigin.INGEST,
                      now=datetime.now(UTC))
        conn.commit()
    page = context.new_page()
    _reports(page, live_app.url)
    entry = page.locator("[data-report-type=audit]")
    expect(entry).to_have_attribute("data-available", "true")
    expect(page.locator("[data-report-type=traffic]")).to_have_attribute("data-available", "true")
    entry.get_by_role("button", name="Generate…").click()
    page.locator("[data-role=generate-form]").get_by_role("button", name="Generate", exact=True).click()
    row = page.locator("[data-role=report-list] tbody tr").first
    expect(row).to_have_attribute("data-status", "queued")
    generate.run_queued(live_app.ctx)
    expect(row).to_have_attribute("data-status", "done", timeout=10_000)
    with page.expect_download() as dl:
        row.get_by_role("link", name="HTML").click()
    assert "Policy provisions" in Path(dl.value.path()).read_text(encoding="utf-8")


# ── the reports page (UI redesign samples 07, 08) ───────────────────────────

COMMON = ["weekly_overview", "security_risk", "ven_status", "new_connections", "audit"]


@pytest.mark.parametrize("width,columns", [(1440, (3, 4)), (820, (1, 2))])
def test_templates_are_the_common_ones_then_the_rest(browser, live_app, width, columns):
    """UI redesign spec §9.1 (stage 3a): two parts — the common templates, then the ones by topic — each a grid of
    cards; what used to head a column is a small tag on each card."""
    from tests.e2e import ui_rules
    from tests.e2e.conftest import no_horizontal_overflow
    ctx = browser.new_context(locale="en-US", viewport={"width": width, "height": 900})
    page = ctx.new_page()
    _reports(page, live_app.url)
    tiers = page.locator("[data-role=report-catalog] > [data-tier]")
    assert [tiers.nth(i).get_attribute("data-tier") for i in range(tiers.count())] == ["common", "topic"]
    assert [h.strip() for h in page.locator("[data-role=report-catalog] [data-tier] > h2").all_text_contents()] == [
        "Common", "By topic"]
    common = page.locator("[data-tier=common] .rpt-card")
    assert [common.nth(i).get_attribute("data-report-type") for i in range(common.count())] == COMMON
    topic = page.locator("[data-tier=topic] .rpt-card")
    kinds = [topic.nth(i).get_attribute("data-report-type") for i in range(topic.count())]
    # Rule Hit Count has no card since it became a chapter of policy usage; the detections report is by topic.
    assert "rule_hit_count" not in kinds and "policy_usage" in kinds
    assert "detections" in kinds
    assert not set(kinds) & set(COMMON) and len(kinds) + len(COMMON) == 17
    cards = page.locator("[data-role=report-catalog] .rpt-card")
    tags = page.locator("[data-role=report-catalog] .rpt-card [data-role=rpt-group]")
    assert tags.count() == cards.count() == 17
    detection_card = page.locator('[data-report-type="detections"]')
    assert detection_card.locator("strong").inner_text() == "Detections and alerts"
    assert "Stored detections" in detection_card.inner_text()
    assert set(tags.all_text_contents()) == {"Security assessment", "Traffic analysis", "Policy", "Operations and audit"}
    assert page.locator("[data-report-type=audit] [data-role=rpt-group]").inner_text() == "Operations and audit"
    # cards of one row share a top: the widest row of each part is as many columns as the width allows
    for tier, n in (("common", 5), ("topic", 12)):
        tops = page.evaluate(
            "(t) => [...document.querySelectorAll(`[data-tier=${t}] .rpt-card`)].map((c) => Math.round(c.getBoundingClientRect().top))",
            tier)
        widest = max(tops.count(t) for t in set(tops))
        assert len(tops) == n and columns[0] <= widest <= columns[1], (tier, width, tops)
    assert no_horizontal_overflow(page)
    assert ui_rules.violations(page) == {}
    ctx.close()


def test_traffic_card_explains_on_demand_without_mode_label(context, live_app):
    page = context.new_page()
    _reports(page, live_app.url)
    cards = page.locator("[data-role=report-catalog] .rpt-card")
    card = page.locator("[data-report-type=traffic]")
    expect(card).to_contain_text("Queries the PCE when made; slower")
    assert all("Basic mode" not in text for text in cards.all_text_contents())


def test_recent_shows_conclusion(context, live_app):
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.registry import ReportParams
    generate.enqueue(live_app.ctx, ReportParams(report_type=ReportType.UNMANAGED_ENDPOINTS), trigger="manual",
                     schedule_id=None, now=datetime.now(UTC))
    generate.run_queued(live_app.ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    cell = page.locator("[data-role=report-list] [data-role=report-conclusion]").first
    expect(cell).to_contain_text("Unmanaged addresses:")


def test_schedules_tab_holds_the_settings(context, live_app):
    page = context.new_page()
    sign_in(page, live_app.url)
    page.goto(live_app.url + "/system/reports")
    page.wait_for_url("**/reports?tab=schedules")
    expect(page.locator("[data-role=report-settings]")).to_have_count(1)


def test_reports_no_overflow_760(narrow_context, live_app):
    from tests.e2e.conftest import no_horizontal_overflow
    page = narrow_context.new_page()
    _reports(page, live_app.url)
    assert no_horizontal_overflow(page)


def _made(live_app, n=1):
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.registry import ReportParams
    ids = [generate.enqueue(live_app.ctx, ReportParams(report_type=ReportType.UNMANAGED_ENDPOINTS), trigger="manual",
                            schedule_id=None, now=datetime.now(UTC)) for _ in range(n)]
    generate.run_queued(live_app.ctx)
    return ids


def test_report_period_is_read_in_the_display_zone(browser, live_app):
    """6.17.0: the list reads a report's period (stored in UTC) in the display zone, as the report itself does, not
    in the browser's zone and not as the UTC date."""
    from zoneinfo import ZoneInfo

    from illumio_ops.domain.report import period_text
    from illumio_ops.services.reports import views
    context = browser.new_context(locale="en-US", timezone_id="America/New_York")
    try:
        page = context.new_page()
        sign_in(page, live_app.url)
        page.goto(f"{live_app.url}/system/display")
        page.locator("input[name=timezone]").fill("Asia/Taipei")
        with page.expect_response(lambda response: response.url.endswith("/api/auth/me") and response.status == 200):
            page.get_by_role("button", name="Save").click()
        ids = _made(live_app)
        item = views.get_report(live_app.ctx, ids[0])
        assert item is not None
        expected = period_text(item.period_start, item.period_end, ZoneInfo("Asia/Taipei"))
        page.goto(f"{live_app.url}/reports?tab=produced")
        expect(page.locator(f"[data-report-id='{ids[0]}']")).to_contain_text(expected)
    finally:
        context.close()


def test_open_report_in_browser_sandboxed(context, live_app):
    """5.x opened an HTML report in the browser: here in a new tab, its own script running, sealed off from the
    console (no session cookie, no API)."""
    _made(live_app)
    page = context.new_page()
    _reports(page, live_app.url)
    row = page.locator("[data-role=report-list] tbody tr").first
    with context.expect_page() as opened:
        row.locator("[data-role=report-open]").click()
    report = opened.value
    report.wait_for_load_state()
    assert "/reports/view/" in report.url
    expect(report.locator("header.cover h1")).to_have_count(1)
    assert report.evaluate("typeof sortTable") == "function"  # the report's inline table script ran
    said = []
    report.on("console", lambda m: said.append(m.text))
    report.locator(".print-btn").click()
    report.wait_for_timeout(300)
    assert not [m for m in said if "sandboxed" in m]  # allow-modals: printing is not refused
    # an opaque origin: reading the console's cookies throws
    assert report.evaluate("(() => { try { return document.cookie; } catch (e) { return e.name; } })()") == "SecurityError"
    reached = report.evaluate("fetch('/api/reports').then(() => 'reached', () => 'blocked')")
    assert reached == "blocked"


def test_bulk_delete_from_the_list(context, live_app):
    ids = _made(live_app, 3)
    page = context.new_page()
    _reports(page, live_app.url)
    for rid in ids[:2]:
        page.locator(f"input[name=pick-{rid}]").check()
    page.locator("[data-role=bulk-delete]").click()
    page.locator("[data-role=bulk-delete-confirm]").click()
    expect(page.locator("[data-role=bulk-outcome]")).to_contain_text("Deleted 2")
    expect(page.locator("[data-role=report-list] tbody tr")).to_have_count(1)
    expect(page.locator(f"[data-report-id='{ids[2]}']")).to_have_count(1)


def test_a_host_named_in_a_report_leads_to_its_page(context, live_app):
    """Stage 3a: a host in a report table is a link to the console's host page, at the part the table is about. The
    report opens sealed off from the console (no cookie of its own); the link still lands signed in."""
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.registry import ReportParams
    from tests.services.reports.test_ven_status import _inventory, host
    ctx = live_app.ctx
    _inventory(ctx, [host("db"), host("web")], read_at=datetime.now(UTC))
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["reports"].update(gui_external_url=live_app.url))
    generate.enqueue(ctx, ReportParams(report_type=ReportType.VEN_STATUS), trigger="manual", schedule_id=None,
                     now=datetime.now(UTC))
    generate.run_queued(ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    row = page.locator("[data-role=report-list] tbody tr").first
    with context.expect_page() as opened:
        row.locator("[data-role=report-open]").click()
    report = opened.value
    report.wait_for_load_state()
    link = report.locator("a[data-role=host-link]").first
    expect(link).to_have_text("db")
    assert link.get_attribute("href") == f"{live_app.url}/hosts?key=%2Forgs%2F1%2Fworkloads%2Fdb#status"
    link.click()
    report.wait_for_url("**/hosts?key=*")
    expect(report.locator("h1")).to_have_text("db")
    assert report.url == f"{live_app.url}/hosts?key=%2Forgs%2F1%2Fworkloads%2Fdb#status"
    expect(report.locator("#status")).to_be_in_viewport()


def test_generate_settings_open_in_a_full_width_panel_after_the_cards_row(context, live_app):
    """6.15.1 on .106: the settings opened inside a 260px card and the filter's fields spread onto the next card."""
    page = context.new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    _reports(page, live_app.url)
    card = page.locator("[data-report-type=traffic]")
    card.get_by_role("button", name="Generate…").click()
    panel = page.locator("[data-role=generate-panel][data-for=traffic]")
    expect(panel).to_be_visible()
    expect(card).to_have_attribute("data-open", "true")
    geo = panel.evaluate("""(p) => { const g = p.closest('.rpt-grid').getBoundingClientRect(), r = p.getBoundingClientRect();
        const c = document.querySelector('[data-report-type=traffic]').getBoundingClientRect();
        const row = [...p.closest('.rpt-grid').querySelectorAll('.rpt-card')].map((e) => e.getBoundingClientRect())
          .filter((b) => Math.abs(b.top - c.top) < 2);
        return {full: Math.abs(r.width - g.width) < 2, below: row.every((b) => r.top >= b.bottom),
                page: document.documentElement.scrollWidth <= document.documentElement.clientWidth}; }""")
    assert geo == {"full": True, "below": True, "page": True}
    # the clicked card is marked in the accent colour, the others are not; the panel title reads as a title
    look = panel.evaluate("""(p) => {
        const probe = document.createElement('i'); probe.style.color = 'var(--accent)'; document.body.append(probe);
        const accent = getComputedStyle(probe).color; probe.remove();
        const mark = (e) => { const s = getComputedStyle(e);
          return (s.outlineStyle !== 'none' && s.outlineColor === accent) || s.boxShadow.includes(accent); };
        const others = [...document.querySelectorAll('.rpt-card:not([data-open=true])')];
        const h = getComputedStyle(p.querySelector('h3'));
        return {open: mark(document.querySelector('[data-report-type=traffic]')), others: others.some(mark),
                size: parseFloat(h.fontSize) >= 17, upper: h.textTransform}; }""")
    assert look == {"open": True, "others": False, "size": True, "upper": "none"}
    # the optional filter is folded; period, language and formats come first
    assert not panel.locator("[data-role=report-filter] details").first.evaluate("(d) => d.open")
    expect(panel.locator("select[name=lookback_days]")).to_be_visible()
    panel.get_by_role("button", name="Close").click()
    expect(panel).to_have_count(0)


def test_a_produced_report_is_titled_by_its_kind_and_when_it_was_made(context, live_app):
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.registry import ReportParams
    generate.enqueue(live_app.ctx, ReportParams(report_type=ReportType.UNMANAGED_ENDPOINTS), trigger="manual",
                     schedule_id=None, now=datetime.now(UTC))
    generate.run_queued(live_app.ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    row = page.locator("[data-role=report-list] tbody tr").first
    expect(row.locator("[data-role=report-title]")).to_have_text("Unmanaged endpoints")
    expect(row.locator("[data-role=report-made]")).to_contain_text("Made ")
    expect(row.locator("[data-role=report-conclusion]")).to_contain_text("Unmanaged addresses:")
    assert row.locator(".badge").evaluate("(b) => b.getBoundingClientRect().height < 2 * parseFloat(getComputedStyle(b).lineHeight) + 8")


# ── 6.16.0: calendar months, how long the last one took, what a restart left ──

def test_a_monthly_schedule_can_cover_the_previous_whole_month(context, live_app):
    from datetime import UTC, datetime, timedelta

    from illumio_ops.store import reports as store
    page = context.new_page()
    _reports(page, live_app.url)
    page.get_by_role("tab", name="Schedules").click()
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    period = editor.locator("select[name=lookback_days]")
    expect(period.locator("option[value=previous_month]")).to_have_count(0)  # a weekly schedule: days only
    editor.locator("input[name=name]").fill("Monthly audit")
    editor.locator("select[name=report_type]").select_option("audit")
    editor.locator("select[name=frequency]").select_option("monthly")
    period.select_option("previous_month")
    editor.locator("select[name=frequency]").select_option("weekly")  # no longer monthly: back to a number of days
    expect(period).not_to_have_value("previous_month")
    editor.locator("select[name=frequency]").select_option("monthly")
    period.select_option("previous_month")
    editor.get_by_role("button", name="Save").click()
    row = page.locator("[data-role=schedule-list] tbody tr").first
    expect(row).to_contain_text("The previous whole month")
    (saved,) = live_app.ctx.settings.current().reports.schedules
    assert (saved.period, saved.frequency) == ("previous_month", "monthly")
    row.get_by_role("button", name="Run now").click()
    page.wait_for_url("**/reports?id=*")
    with live_app.ctx.db() as conn:
        made = store.list_reports(conn, limit=1, offset=0)[0][0]
    tz = live_app.ctx.settings.current().display.zone()
    first, after = made.period_start.astimezone(tz), made.period_end.astimezone(tz)
    last_month = (datetime.now(UTC).astimezone(tz).date().replace(day=1) - timedelta(days=1)).replace(day=1)
    assert first.date() == last_month and (first.day, after.day) == (1, 1) and (after - first).days in (28, 29, 30, 31)
    assert made.error_key is None


def test_the_generate_panel_says_how_long_the_last_one_took(context, live_app):
    from datetime import UTC, datetime, timedelta

    from illumio_ops.domain.values import ReportStatus
    from illumio_ops.store import reports as store
    now = datetime.now(UTC)
    with live_app.ctx.db() as conn:
        for kind, seconds in (("policy_usage", 1449), ("traffic", 29)):
            rid = store.insert(conn, report_type=kind, params_json="{}", status=ReportStatus.QUEUED, trigger="manual",
                               schedule_id=None, pce_label="p", period_start=now - timedelta(days=30), period_end=now,
                               created_at=now)
            conn.execute("UPDATE reports SET status = 'done', started_at = ?, finished_at = ? WHERE id = ?",
                         ((now - timedelta(seconds=seconds)).isoformat(), now.isoformat(), rid))
        conn.commit()
    page = context.new_page()
    page.set_viewport_size({"width": 1440, "height": 900})
    _reports(page, live_app.url)
    page.locator("[data-report-type=policy_usage]").get_by_role("button", name="Generate…").click()
    said = page.locator("[data-role=generate-panel][data-for=policy_usage] [data-role=last-took]")
    expect(said).to_have_text("The last one (30 days) took 24 minutes to make.")
    page.locator("[data-report-type=traffic]").get_by_role("button", name="Generate…").click()
    panel = page.locator("[data-role=generate-panel][data-for=traffic]")
    expect(panel).to_be_visible()
    expect(panel.locator("[data-role=last-took]")).to_have_count(0)  # seconds: nothing worth saying


def test_an_email_a_restart_interrupted_says_so_and_the_page_stops_waiting(context, live_app):
    from datetime import UTC, datetime

    from illumio_ops.domain.values import ReportType
    from illumio_ops.services.reports.registry import ReportParams
    from illumio_ops.store import reports as store
    ctx = live_app.ctx
    rid = generate.enqueue(ctx, ReportParams(report_type=ReportType.UNMANAGED_ENDPOINTS), trigger="manual",
                           schedule_id=None, now=datetime.now(UTC))
    generate.run_queued(ctx)
    with ctx.db() as conn:
        store.set_email(conn, rid, status="sending", detail=None)
    generate.recover(ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    expect(page.locator("[data-role=report-list]")).to_contain_text("Not known: the service stopped while sending")
