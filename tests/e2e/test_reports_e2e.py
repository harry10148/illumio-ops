"""Reports in a browser (P5a Tasks 8–9): generate, wait, download, land on a linked report, schedule and run."""
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
    form = entry.locator("[data-role=generate-form]")
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
        "Destination: app=Finance; Source is not: 10.9.0.0/16; Port: 443/6")
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
    entry.locator("[data-role=generate-form]").get_by_role("button", name="Generate", exact=True).click()
    row = page.locator("[data-role=report-list] tbody tr").first
    expect(row).to_have_attribute("data-status", "queued")
    generate.run_queued(live_app.ctx)
    expect(row).to_have_attribute("data-status", "done", timeout=10_000)
    with page.expect_download() as dl:
        row.get_by_role("link", name="HTML").click()
    assert "Policy provisions" in Path(dl.value.path()).read_text(encoding="utf-8")


# ── the reports page (UI redesign samples 07, 08) ───────────────────────────

COMMON = ["security_risk", "ven_status", "new_connections", "audit"]


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
    assert "rule_hit_count" in kinds and not set(kinds) & set(COMMON) and len(kinds) + len(COMMON) == 16
    cards = page.locator("[data-role=report-catalog] .rpt-card")
    tags = page.locator("[data-role=report-catalog] .rpt-card [data-role=rpt-group]")
    assert tags.count() == cards.count() == 16
    assert set(tags.all_text_contents()) == {"Security assessment", "Traffic analysis", "Policy", "Operations and audit"}
    assert page.locator("[data-report-type=audit] [data-role=rpt-group]").inner_text() == "Operations and audit"
    # cards of one row share a top: the widest row of each part is as many columns as the width allows
    for tier, n in (("common", 4), ("topic", 12)):
        tops = page.evaluate(
            "(t) => [...document.querySelectorAll(`[data-tier=${t}] .rpt-card`)].map((c) => Math.round(c.getBoundingClientRect().top))",
            tier)
        widest = max(tops.count(t) for t in set(tops))
        assert len(tops) == n and columns[0] <= widest <= columns[1], (tier, width, tops)
    assert no_horizontal_overflow(page)
    assert ui_rules.violations(page) == {}
    ctx.close()


def test_traffic_card_not_marked_advanced(context, live_app):
    page = context.new_page()
    _reports(page, live_app.url)
    card = page.locator("[data-report-type=traffic]")
    expect(card).to_contain_text("Basic mode: on demand")
    assert "Advanced mode" not in card.inner_text()


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
