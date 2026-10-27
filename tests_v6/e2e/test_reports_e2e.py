"""Reports in a browser (P5a Tasks 8–9): generate, wait, download, land on a linked report, schedule and run."""
from pathlib import Path

from playwright.sync_api import expect

from illumio_ops.services.reports import generate
from tests_v6.e2e.conftest import sign_in

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
    form = entry.locator("[data-role=generate-form]")
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


def test_events_only_mode_greys_out_with_reason(context, live_app):
    ctx = live_app.ctx
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["collection"].update(mode="events_only"))
    page = context.new_page()
    _reports(page, live_app.url)
    entry = page.locator("[data-report-type=lateral_posture]")
    expect(entry).to_have_attribute("data-available", "false")
    expect(entry.get_by_role("button", name="Generate…")).to_be_disabled()
    expect(entry.locator("[data-role=unavailable]")).to_contain_text("events only")


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
    form = entry.locator("[data-role=generate-form]")
    go = form.get_by_role("button", name="Generate", exact=True)
    expect(go).to_be_disabled()  # no app chosen yet
    form.locator("select[name=filter_value]").select_option("Finance")
    go.click()
    row = page.locator("[data-role=report-list] tbody tr").first
    expect(row).to_have_attribute("data-status", "queued")
    generate.run_queued(live_app.ctx)
    expect(row).to_have_attribute("data-status", "done", timeout=10_000)
    with page.expect_download() as dl:
        row.get_by_role("link", name="HTML").click()
    assert "App summary: Finance" in Path(dl.value.path()).read_text(encoding="utf-8")


def test_schedule_with_filter(context, live_app):
    _finance_inventory(live_app.ctx)
    page = context.new_page()
    _reports(page, live_app.url)
    page.get_by_role("tab", name="Schedules").click()
    page.get_by_role("button", name="Add a schedule").click()
    editor = page.locator("[data-role=schedule-editor]")
    editor.locator("input[name=name]").fill("Finance traffic")
    editor.locator("select[name=report_type]").select_option("traffic")
    editor.get_by_role("button", name="Add a condition").click()
    editor.locator("select[name=filter_value]").select_option("Finance")
    editor.get_by_role("button", name="Save").click()
    row = page.locator("[data-role=schedule-list] tbody tr").first
    expect(row.locator("[data-role=schedule-filter]")).to_have_text("app = Finance")
    saved = live_app.ctx.settings.current().reports.schedules[0]
    assert saved.filter is not None and saved.filter.dst.labels[0].values == ("Finance",)


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
