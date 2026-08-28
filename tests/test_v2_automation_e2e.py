"""Phase 2A Task 7 — in-process Playwright e2e for the v2 automation area.

Drives a real (headless) Chromium against a real Flask app + real backend
through tests.v2_e2e_utils's shared harness — see that module's docstring for
the harness itself.

Covers, per the task brief's T7 row:
  - every AU-01..AU-13 coverage anchor (design/v2/coverage.yaml's automation
    subset), split across the three sub-routes that own them.
  - key flow 1: the rule-scheduler two-level drawer's pre-check message is
    the REAL backend response (test_ruleset_drawer_precheck_is_real_backend_
    error), not a client-side guess.
  - key flow 2: creating real one-time 2027 rule schedules, reconciling them
    against the real GET /api/rule_scheduler/schedules list, watching the
    timeline render three real lanes, then deleting them through the real
    UI confirm flow (test_rule_schedule_crud_reconciles_list_and_timeline).
  - report-schedule CRUD (create -> list -> toggle -> delete) using the
    `traffic` report type from the legacy whitelist — NOT `audit_summary`.
    See "Plan correction" below.
  - AU-13 binds to the real GET /api/dashboard/overview (test_jobs_view_
    binds_to_dashboard_overview).
  - AU-09 "立即檢查" against the real POST /api/rule_scheduler/check, run
    only while the ScheduleDB is empty (test_immediate_check_...).
  - S2 teardown across all three sub-routes.
  - S4: i18n.missing() is empty on each of the three routes.

## Plan correction (already ruled on)

The brief's original T7 row named `audit_summary` as the report type to
exercise for the report-schedule CRUD round trip, to demonstrate bug #2's
pre-fix behaviour. That correction was reverted before this file was
written: `audit_summary` is outside the legacy report-type whitelist and
its pre-fix behaviour is 2D's fix to make, not this task's regression to
assert against. Every report-schedule test below uses `traffic`, which is
in the whitelist REPORT_TYPES already carries.

## Destructive-operation discipline

  POST /api/rule_scheduler/schedules         — called for real, several
      times, but ONLY with `type: one_time` and `expire_at` in 2027. Every
      schedule this file creates is deleted before the test that created it
      returns (via the real UI confirm flow or, in `finally`, via the real
      delete endpoint as a safety net).
  POST /api/rule_scheduler/schedules/delete  — called for real; this is the
      cleanup path itself, never destructive in the sense this note exists
      to flag.
  POST /api/rule_scheduler/check             — called for real exactly once
      (test_immediate_check_runs_real_endpoint_when_no_schedules_exist),
      and ONLY in a test that creates no schedule of its own — and that test
      takes `schedule_free_db` (below), which truncates the real
      rule_schedules.json to `{}` for its duration and restores it after.
      (The store is resolved from the source tree via _resolve_config_dir(),
      NOT from the function-scoped `temp_config_file`, so "every test starts
      empty" was never true.) engine.check() therefore iterates zero stored
      entries and issues no PCE write regardless of whether the PCE gates
      below happen to be reachable.
  POST /api/report-schedules/<id>/run        — NEVER called. The button is
      wired to the real endpoint (AU-12 requires it to exist), but no test
      here clicks it — it starts a real background thread that runs a real
      report.
  POST /api/report-schedules/<id>/toggle     — called for real. It flips a
      boolean in config.json; no PCE call, no file produced.

## The one deterministic seam in this file, and why

rule_scheduler.py's create route (rs_schedule_create) gates on three real
PCE calls (has_draft_changes / get_provision_state / update_rule_note)
before it will store anything — and this harness's PCE is an unreachable
closed port (tests/v2_e2e_utils.py), which makes get_provision_state always
answer 'unknown' and the route always answer 502, for ANY href.
`test_ruleset_drawer_precheck_is_real_backend_error` exercises exactly that
real, unmodified fail-closed path (a different real gate — href-required —
fires first, deterministically, before the PCE calls even run).
`test_rule_schedule_crud_reconciles_list_and_timeline` instead needs the
POST to actually succeed so there is something real to reconcile against
the list, so it monkeypatches those three ApiClient methods only — the same
"stub only the PCE network boundary, keep the whole Flask route real"
pattern test_v2_investigate_e2e.py's pagination test already established
for ApiClient.fetch_events_strict. Every other endpoint this file touches
(GET rulesets/schedules/status/logs, report-schedule CRUD, dashboard
overview) runs against the real, un-patched app.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from playwright.sync_api import expect  # noqa: E402

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]

R_RULES = "#/automation/rules"
R_REPORTS = "#/automation/reports"
R_JOBS = "#/automation/jobs"
SLOW = 45_000


@pytest.fixture
def schedule_free_db():
    """Give the test an empty ScheduleDB it owns, then put the file back.

    The rule-scheduler routes resolve their store as
    ``_resolve_config_dir()/rule_schedules.json`` — anchored off the source
    tree, NOT off the function-scoped ``temp_config_file``. Tests that need a
    schedule-free store therefore cannot just assert they got one: on any
    checkout where a real (or previously leaked) schedule is sitting in that
    file they go red through no fault of the code under test. Reproduced
    2026-08-28: 3 leftover entries in the main checkout, both dependent tests
    red there, green in a clean worktree.

    So create the condition instead of hoping for it: truncate the store to
    ``{}`` on setup and restore the byte-for-byte original on teardown (a
    developer's own schedules are real data, not test scratch).
    """
    from src.gui._helpers import _resolve_config_dir

    db_path = os.path.join(_resolve_config_dir(), "rule_schedules.json")
    saved = None
    if os.path.exists(db_path):
        with open(db_path, "r", encoding="utf-8") as f:
            saved = f.read()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with open(db_path, "w", encoding="utf-8") as f:
        f.write("{}")
    try:
        yield db_path
    finally:
        if saved is None:
            try:
                os.remove(db_path)
            except OSError:
                pass
        else:
            with open(db_path, "w", encoding="utf-8") as f:
                f.write(saved)


def _goto(page, base_url, route, cov):
    page.set_default_timeout(SLOW)
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector('[data-route="%s"]' % route)
    page.wait_for_selector('[data-cov="%s"]' % cov)


def _navigate(page, route, cov):
    page.evaluate("location.hash = '%s'" % route)
    page.wait_for_selector('[data-route="%s"]' % route)
    page.wait_for_selector('[data-cov="%s"]' % cov)


def _labels(page):
    keys = [
        "gui_rs_schedule_title", "gui_save", "gui_cancel", "gui_confirm", "gui_close",
        "gui_rs_delete_selected", "gui_rs_run_check", "gui_sched_add", "gui_sched_edit",
        "gui_sched_disable", "gui_sched_enable", "gui_delete", "gui_rs_col_edit",
    ]
    return page.evaluate(
        "async (keys) => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "const out = {}; keys.forEach(k => { out[k] = t(k); }); return out; }",
        keys,
    )


def _covs(page):
    return set(page.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))


def _missing_i18n(page):
    return page.evaluate(
        "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return i18n.missing(); }"
    )


def _palette_routes(page):
    return page.evaluate(
        "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "return palette.list().map(c => c.route || null); }"
    )


def _open_all(page):
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(250)


# Same rationale as test_v2_alerting_e2e.py: POST/PUT/DELETE here is
# CSRF-protected, and api.mjs is what actually attaches/refreshes the
# X-CSRF-Token header. A page must already be on the app's origin for the
# dynamic import to resolve, so these only run after a real _goto().
def _api_post(page, path, body):
    return page.evaluate(
        "async (args) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.post(args[0], args[1]); }",
        [path, body],
    )


def _api_get(page, path):
    return page.evaluate(
        "async (path) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.get(path); }",
        path,
    )


def _api_del(page, path):
    return page.evaluate(
        "async (path) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.del(path); }",
        path,
    )


def _fake_ruleset():
    base = "/orgs/1/sec_policy/draft/rule_sets/900099"
    return {
        "href": base,
        "name": "e2e-au-coverage-ruleset",
        "enabled": True,
        "update_type": None,
        "sec_rules": [{
            "href": base + "/sec_rules/1",
            "enabled": True,
            "description": "e2e-au-coverage-rule",
            "update_type": None,
            "destinations": [], "consumers": [], "providers": [], "ingress_services": [],
        }],
        "rules": [],
        "deny_rules": [],
    }


def _patch_fake_ruleset(monkeypatch):
    """AU-03/04 have no audit opener (they are plain page content, not a
    drawer/modal) and this harness's PCE is unreachable, so without a
    monkeypatch the ruleset browser is always empty and AU-04 (the rule
    search panel, which only renders once a real ruleset row is selected)
    can never appear. Same "stub only the PCE network boundary" pattern as
    _patch_pce_gates — get_all_rulesets/get_ruleset_by_id are the two calls
    rs_rulesets/rs_ruleset_detail make; every route/rendering path around
    them stays real."""
    rs = _fake_ruleset()

    def fake_get_all_rulesets(self, force_refresh=False, raise_on_error=False):
        return [rs]

    def fake_get_ruleset_by_id(self, rs_id):
        return rs if str(rs_id) == "900099" else None

    monkeypatch.setattr("src.api_client.ApiClient.get_all_rulesets", fake_get_all_rulesets)
    monkeypatch.setattr("src.api_client.ApiClient.get_ruleset_by_id", fake_get_ruleset_by_id)
    # rs_rulesets/rs_ruleset_detail both best-effort call update_label_cache()
    # first (rule_scheduler.py:106-108, :195-197); against an unreachable PCE
    # that is ~25s of urllib3 connect-retry per call, twice, before AU-04 even
    # renders — a real but irrelevant network stall this test is not about.
    monkeypatch.setattr("src.api_client.ApiClient.update_label_cache", lambda self, silent=False, force_refresh=True: False)


def _patch_pce_gates(monkeypatch):
    """Stub only the PCE network boundary the rule-scheduler CREATE route
    gates on, so the real Flask route logic (validation, ScheduleDB.put,
    the note-write success path) runs for real. See this file's header."""
    monkeypatch.setattr("src.api_client.ApiClient.has_draft_changes", lambda self, href: False)
    monkeypatch.setattr("src.api_client.ApiClient.get_provision_state", lambda self, href: "active")
    monkeypatch.setattr(
        "src.api_client.ApiClient.update_rule_note",
        lambda self, href, note, remove=False: True,
    )


def test_rules_coverage_anchors_and_i18n(v2_page, monkeypatch):
    # AU-04 (the rule-search panel) only renders once a real ruleset row is
    # selected, and it has no audit opener (it is plain page content, not a
    # drawer) — see _patch_fake_ruleset's docstring.
    _patch_fake_ruleset(monkeypatch)
    page, base_url = v2_page
    _goto(page, base_url, R_RULES, "AU-01")
    page.locator('section[data-cov="AU-03"] table.tbl tbody tr').first.click()
    page.wait_for_selector('[data-cov="AU-04"]')
    _open_all(page)

    expected = {"AU-%02d" % i for i in range(1, 11)}
    assert expected - _covs(page) == set()
    assert _missing_i18n(page) == []


def test_reports_coverage_anchors_and_i18n(v2_page):
    # AU-12 (the row action buttons) only render once a real report schedule
    # exists, and it has no audit opener — seed one through the real POST,
    # reload so the mount picks it up, then clean up.
    page, base_url = v2_page
    _goto(page, base_url, R_REPORTS, "AU-11")
    created = _api_post(page, "/api/report-schedules", {
        "name": "e2e-au-coverage-report", "report_type": "traffic", "schedule_type": "weekly",
        "day_of_week": "monday", "hour": 8, "minute": 0, "timezone": "local",
        "lookback_days": 7, "max_reports": 30, "format": ["html"], "email_report": False,
        "email_recipients": [], "cron_expr": "", "enabled": True,
    })
    assert created and created.get("ok") is True, created
    sid = created["schedule"]["id"]
    try:
        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector('[data-route="%s"]' % R_REPORTS)
        page.wait_for_selector('[data-cov="AU-11"]')
        _open_all(page)

        assert {"AU-11", "AU-12"} - _covs(page) == set()
        assert _missing_i18n(page) == []
    finally:
        _api_del(page, "/api/report-schedules/%d" % sid)


def test_jobs_coverage_anchors_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_JOBS, "AU-13")

    assert "AU-13" in _covs(page)
    assert _missing_i18n(page) == []


def test_jobs_view_binds_to_dashboard_overview(v2_page):
    """AU-13 binds to the real payload, and opens on its conclusion.

    The density spec (R1/R3) makes this page answer "is anything wrong with the
    schedules" before it shows any evidence: the headline names the failing
    jobs, and the 14-row table ships collapsed. Both halves are asserted here —
    the binding, so the numbers stay real, and the collapse, so a later change
    that re-expands the table by default cannot pass unnoticed.
    """
    page, base_url = v2_page
    _goto(page, base_url, R_JOBS, "AU-13")

    overview = _api_get(page, "/api/dashboard/overview")
    jobs = overview.get("job_health") or []
    bad = [j for j in jobs if j.get("level") != "ok"]
    ok_count = len(jobs) - len(bad)

    panel = page.locator('section[data-cov="AU-13"]')
    expected = page.evaluate(
        "async (args) => { const { tf } = await import('/static/js/v2/core/i18n.mjs'); "
        "return args[2] ? tf('gui_au_jobs_attention', { n: args[2] }) "
        "               : tf('gui_health_jobs_ok', { ok: args[0], total: args[1] }); }",
        [ok_count, len(jobs), len(bad)],
    )
    assert panel.locator(".meta").inner_text() == expected

    # The conclusion: failing jobs are named without opening anything, capped
    # so that a mostly-broken fleet does not regrow the table this replaced.
    # The cap is mirrored from automation.mjs's HEADLINE_MAX.
    headline_max = 5
    headline = panel.locator(".badlist")
    if bad:
        assert headline.count() == 1
        shown = headline.inner_text()
        for j in bad[:headline_max]:
            assert j["job_id"] in shown, (j["job_id"], shown)
        assert len(headline.locator(".idc").all()) == min(len(bad), headline_max)
        if len(bad) > headline_max:
            overflow = page.evaluate(
                "async (n) => { const { tf } = await import('/static/js/v2/core/i18n.mjs'); "
                "return tf('gui_au_jobs_more', { n }); }",
                len(bad) - headline_max,
            )
            assert overflow in panel.inner_text()
    else:
        assert headline.count() == 0

    # The evidence: present and complete, but folded away. inner_text() on a
    # closed <details> is "" — which is itself the proof that it really is
    # collapsed rather than merely styled small.
    details = panel.locator("details.disclose").first
    assert details.get_attribute("open") is None
    rows = page.locator("table.tbl tbody tr")
    assert rows.count() == len(jobs)
    assert page.locator("table.tbl tbody").inner_text() == ""

    # ...and opening it the way an operator would reveals the real rows.
    details.locator("summary").click()
    if jobs:
        body = page.locator("table.tbl tbody").inner_text()
        assert jobs[0]["job_id"] in body, body


def test_ruleset_drawer_precheck_is_real_backend_error(v2_page):
    """AU-05/AU-07 key flow: the drawer's pre-check message is whatever the
    real POST /api/rule_scheduler/schedules answered, not a client guess.
    No rulesets exist (this harness's PCE is unreachable), so the audit
    opener's own fallback (`state.rulesets[0] || {}`) opens the drawer with
    an empty target — href="" — and rule_scheduler.py:308-309's real,
    unmodified `if not href: return _err("href required", 400)` fires
    before any PCE call is even attempted."""
    page, base_url = v2_page
    _goto(page, base_url, R_RULES, "AU-01")

    page.evaluate(
        "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "palette.list().find(c => c.id === 'au:sched-rs').run(); }"
    )
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    assert drawer.locator('[data-cov="AU-05"]').count() == 1
    # AU-07: the one-time fields exist in the drawer regardless of which
    # radio is selected (style.display, not [hidden] — see the module's
    # own comment on why).
    assert drawer.locator('[data-cov="AU-07"] input[data-field="expire_at"]').count() == 1

    drawer.locator('input[type="radio"][value="one_time"]').check()
    drawer.locator('input[data-field="expire_at"]').fill("2027-01-01T00:00")

    with page.expect_response(
        lambda r: r.url.endswith("/api/rule_scheduler/schedules") and r.request.method == "POST"
    ) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    assert info.value.status == 400
    body = info.value.json()
    assert body["ok"] is False
    assert body["error"] == "href required"

    # The drawer stays open (onSave returned false) and shows that exact
    # real backend text.
    drawer.wait_for(state="visible")
    err = drawer.locator('[data-cov="AU-05"] p.note[data-tone="crit"]')
    assert err.inner_text() == "href required"


def test_rule_schedule_crud_reconciles_list_and_timeline(v2_page, monkeypatch, schedule_free_db):
    """AU-08/AU-02 key flow: create three real one-time 2027 schedules
    (one ruleset-level, two rule-level — the dual-target model), reconcile
    them against the real GET list, watch the timeline render three real
    lanes, then delete all three through the real UI confirm flow.

    The ruleset-level schedule (the flagship two-level-drawer flow) is
    created through the real UI form — opened via the same `au:sched-rs`
    palette command as test_ruleset_drawer_precheck_is_real_backend_error,
    fields filled, Save clicked — and the request scheduleBody() actually
    emits is asserted against the real outgoing POST body, so a wrong key
    name or a dropped field in that mapping goes red. `_patch_fake_ruleset`
    gives the ruleset browser one real row so the drawer's target is a
    genuine href instead of the empty-target fallback the precheck test
    deliberately exercises. The two rule-level schedules are still created
    directly through the real endpoint (same as before) — this task's row
    only requires one drawer-driven success case, and duplicating the UI
    path three times would not cover anything new.

    `schedule_free_db` is what makes the row counts below (3, then 0) mean
    "the three this test created" rather than "whatever the checkout's
    rule_schedules.json happened to hold plus three"."""
    _patch_pce_gates(monkeypatch)
    _patch_fake_ruleset(monkeypatch)
    page, base_url = v2_page
    _goto(page, base_url, R_RULES, "AU-01")

    base_href = "/orgs/1/sec_policy/draft/rule_sets/900099"  # the fake ruleset's own href
    created = []

    # ── the drawer-driven ruleset-level schedule ────────────────────────
    ruleset_name = "e2e-au-ruleset-ui"
    page.evaluate(
        "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "palette.list().find(c => c.id === 'au:sched-rs').run(); }"
    )
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="detail_name"]').fill(ruleset_name)
    drawer.locator('input[type="radio"][value="one_time"]').check()
    drawer.locator('input[data-field="expire_at"]').fill("2027-06-01T08:00")

    with page.expect_request(
        lambda r: r.url.endswith("/api/rule_scheduler/schedules") and r.method == "POST"
    ) as create_req:
        drawer.locator(".drawer-f button.btn.primary").click()
    body = create_req.value.post_data_json
    assert body == {
        "href": base_href,
        "type": "one_time",
        "name": ruleset_name,
        "detail_name": ruleset_name,
        "is_ruleset": True,
        "detail_rs": "e2e-au-coverage-ruleset",
        "detail_src": "All",
        "detail_dst": "All",
        "detail_svc": "All",
        "expire_at": "2027-06-01T08:00",
        "timezone": "local",
    }, body
    page.wait_for_selector("aside.drawer", state="detached")
    created.append(base_href)

    targets = [
        (base_href + "/sec_rules/1", False, "e2e-au-rule-allow", "2027-06-02T08:00"),
        (base_href + "/deny_rules/1", False, "e2e-au-rule-deny", "2027-06-03T08:00"),
    ]
    try:
        for href, is_ruleset, name, expire_at in targets:
            result = _api_post(page, "/api/rule_scheduler/schedules", {
                "href": href, "type": "one_time", "expire_at": expire_at,
                "name": name, "detail_name": name, "is_ruleset": is_ruleset,
            })
            assert result and result.get("ok") is True, result
            created.append(href)

        page.reload()
        page.wait_for_selector('body[data-booted="true"]')
        page.wait_for_selector('[data-route="%s"]' % R_RULES)
        page.wait_for_selector('[data-cov="AU-01"]')

        sched_panel = page.locator('section[data-cov="AU-08"]')
        assert sched_panel.locator("tbody tr").count() == 3
        for href in created:
            assert sched_panel.locator('[data-sched-id="%s"]' % href).count() == 1

        tl_panel = page.locator('section[data-cov="AU-02"]')
        assert tl_panel.locator(".tl-lane[data-sched-kind]").count() == 3
        assert tl_panel.locator('.tl-lane[data-sched-kind="ruleset"]').count() == 1
        assert tl_panel.locator('.tl-lane[data-sched-kind="rule"]').count() == 2

        labels = _labels(page)
        sched_panel.get_by_role("button", name=labels["gui_rs_delete_selected"], exact=True).click()
        confirm = page.locator(".modal")
        confirm.wait_for(state="visible")
        assert confirm.locator("ul.impact li").count() >= 1
        with page.expect_request(
            lambda r: r.url.endswith("/api/rule_scheduler/schedules/delete") and r.method == "POST"
        ) as delete_req:
            confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
        assert sorted(delete_req.value.post_data_json["hrefs"]) == sorted(created)
        page.wait_for_selector(".modal", state="detached")

        sched_panel = page.locator('section[data-cov="AU-08"]')
        assert sched_panel.locator("tbody tr").count() == 0
        created = []  # deleted through the real UI flow; nothing left for the finally block
    finally:
        for href in created:
            _api_post(page, "/api/rule_scheduler/schedules/delete", {"hrefs": [href]})


def test_immediate_check_runs_real_endpoint_when_no_schedules_exist(v2_page, schedule_free_db):
    """AU-09: the button POSTs the real /api/rule_scheduler/check. Safe here
    because `schedule_free_db` truncates the real store to `{}` for the
    duration of this test and this test creates no schedule of its own — so
    engine.check() has nothing to toggle regardless of PCE reachability.
    (The store is NOT derived from the function-scoped temp_config_file; it is
    resolved from the source tree, which is why the fixture has to exist.)"""
    page, base_url = v2_page
    _goto(page, base_url, R_RULES, "AU-01")

    existing = _api_get(page, "/api/rule_scheduler/schedules")
    assert existing == [], "this test requires a schedule-free ScheduleDB"

    labels = _labels(page)
    panel = page.locator('section[data-cov="AU-09"]')
    with page.expect_response(
        lambda r: r.url.endswith("/api/rule_scheduler/check") and r.request.method == "POST"
    ) as info:
        panel.get_by_role("button", name=labels["gui_rs_run_check"], exact=True).click()
    assert info.value.status == 200
    body = info.value.json()
    assert body["ok"] is True
    assert isinstance(body["logs"], list)
    page.wait_for_selector('section[data-cov="AU-09"] pre.codepane')


def test_report_schedule_crud_round_trip(v2_page):
    """AU-11/AU-12: create -> list -> toggle -> delete, using `traffic`
    (the legacy whitelist type), never `audit_summary` — see this file's
    header for why."""
    page, base_url = v2_page
    _goto(page, base_url, R_REPORTS, "AU-11")
    labels = _labels(page)
    name = "e2e-au-report-traffic"

    panel = page.locator('section[data-cov="AU-11"]')
    panel.get_by_role("button", name=labels["gui_sched_add"], exact=True).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill(name)
    assert drawer.locator('select[data-field="report_type"]').input_value() == "traffic"

    with page.expect_request(
        lambda r: r.url.endswith("/api/report-schedules") and r.method == "POST"
    ) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    body = info.value.post_data_json
    assert body["report_type"] == "traffic"
    page.wait_for_selector("aside.drawer", state="detached")

    row = panel.locator("tbody tr").filter(has_text=name)
    assert row.count() == 1

    with page.expect_request(
        lambda r: "/api/report-schedules/" in r.url and r.url.endswith("/toggle") and r.method == "POST"
    ):
        row.get_by_role("button", name=labels["gui_sched_disable"], exact=True).click()
    page.wait_for_selector('.toast[data-tone="ok"]')

    row = panel.locator("tbody tr").filter(has_text=name)
    row.get_by_role("button", name=labels["gui_delete"], exact=True).click()
    confirm = page.locator(".modal")
    confirm.wait_for(state="visible")
    with page.expect_request(
        lambda r: "/api/report-schedules/" in r.url and r.method == "DELETE"
    ):
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    page.wait_for_selector(".modal", state="detached")
    assert panel.locator("tbody tr").filter(has_text=name).count() == 0


def test_rule_search_note_describes_this_screens_own_search(v2_page, monkeypatch):
    """Task 12d F3: AU-04's note has to describe what AU-04 does.

    It had been rewritten to promise that the search "runs over every ruleset
    on the PCE and returns hits across the whole policy" — the behaviour of
    GET /api/rule_scheduler/rules/search, an endpoint this screen never calls.
    paintRules() filters state.detail.rules, i.e. the rules of the ONE ruleset
    selected in AU-03 (automation.mjs, ruleMatches()).

    Lesson C4 — the copy is checked against the layer that actually produces
    the behaviour: the search box is driven for real below and asserted to
    issue no search request at all, while the hit line changes. RED against
    the pre-fix catalogue on the forbidden-phrase assertions."""
    from src.i18n import get_messages

    _patch_fake_ruleset(monkeypatch)
    page, base_url = v2_page
    _goto(page, base_url, R_RULES, "AU-01")
    page.locator('section[data-cov="AU-03"] table.tbl tbody tr').first.click()
    page.wait_for_selector('[data-cov="AU-04"]')

    panel = page.locator('[data-cov="AU-04"]')
    # Two p.note in this panel: the live hit line first, the static note last.
    note_text = panel.locator("p.note").last.inner_text()
    for lie in ("every ruleset", "across", "whole policy", "PCE"):
        assert lie.lower() not in note_text.lower(), note_text
    zh_note = get_messages("zh_TW")["gui_au_search_note"]
    for lie in ("全量", "跨", "整個"):
        assert lie not in zh_note, zh_note

    searched = []
    page.on("request", lambda r: searched.append(r.url) if "search" in r.url else None)
    hits = panel.locator("p.note").first
    box = panel.locator("input.field")

    box.fill("zzz-no-such-rule")
    expect(hits).to_contain_text("0 of 1")
    box.fill("1")  # the fake ruleset's only rule id — scope defaults to "id"
    expect(hits).to_contain_text("1 of 1")
    assert searched == [], searched


def test_teardown_closes_surfaces_clears_callbacks_and_palette(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_RULES, "AU-01")

    page.evaluate(
        "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
        "palette.list().find(c => c.id === 'au:sched-rs').run(); }"
    )
    page.locator("aside.drawer").wait_for(state="visible")
    assert "#/automation/rules" in _palette_routes(page)

    _navigate(page, R_REPORTS, "AU-11")
    assert page.locator("aside.drawer").count() == 0
    assert "#/automation/rules" not in _palette_routes(page)

    _open_all(page)
    assert page.locator("aside.drawer").count() >= 1
    _navigate(page, R_JOBS, "AU-13")
    assert page.locator("aside.drawer").count() == 0
    assert all(route != R_REPORTS for route in _palette_routes(page))
