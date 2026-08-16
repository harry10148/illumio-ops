"""Phase 2A Task 8 — in-process Playwright e2e for the v2 reports area.

Drives a real (headless) Chromium against a real Flask app + real backend
through tests.v2_e2e_utils's shared harness — see that module's docstring for
the harness itself (PCE is a closed local port, so every PCE-bound call fails
instantly with "connection refused").

Covers, per the task brief's T8 row:
  - every RP-01..RP-09 coverage anchor (design/v2/coverage.yaml's reports
    subset) — test_reports_coverage_anchors_and_i18n.
  - key flow: generate (real POST) -> progress (RP-03/XC-07) -> complete ->
    appears in the real output list (RP-06) -> delete (real DELETE, RP-07),
    end to end — test_generate_audit_report_progress_complete_list_delete.
  - RP-05 reads its real GET (asserted inside the coverage test, against the
    live, unmocked response) — test_reports_coverage_anchors_and_i18n.
  - the real async job-status endpoint exists and behaves for a real caller
    — test_job_status_endpoint_is_real_for_unknown_job.
  - the progress card's poll timer is really cancelled by navigating away —
    test_async_job_polling_stops_on_navigation_away.

## Why the generated report is `audit`, and how it is genuinely generated

The task brief requires ONE real, small report: "the e2e genuinely produces
one small audit report -> polls the job -> downloads it -> deletes it."
Two things that are NOT obvious from that sentence, checked against the real
backend before writing this file:

  1. `/api/audit_report/generate` (src/gui/routes/reports.py:548) answers
     SYNCHRONOUSLY — no job_id, no polling. Only the three traffic profiles
     and app_summary are job-based (reports.py:408-538, :713-783); RTYPES's
     own `.flags(isAsync, ...)` in reports.mjs already encodes this split
     correctly, transcribed from dashboard.js. So "polls the job" describes
     this area's general RP-03/XC-07 mechanism, not literally what happens
     for the one type this file is allowed to generate for real — the async
     polling PATH is instead proven separately, honestly, in
     test_async_job_polling_stops_on_navigation_away (see that test's own
     docstring for exactly what is real there and what is a mocked network
     boundary) and in test_job_status_endpoint_is_real_for_unknown_job (the
     real GET /api/reports/jobs/<id> endpoint, hit directly).
  2. AuditGenerator.generate_from_api ultimately calls
     ApiClient.fetch_events against the real (closed-port) PCE — which would
     make a genuinely successful audit generation impossible in this harness
     if left unpatched (fetch_events swallows the connection failure and
     returns [], so the route would answer real-but-useless
     `{"ok": false, "error": "no audit data"}` — never producing a file).
     _patch_audit_events stubs ONLY that one ApiClient method with two
     minimal but real-shaped PCE org-events — the same "stub only the PCE
     network boundary, keep the whole Flask route real" pattern
     test_v2_automation_e2e.py's _patch_pce_gates and
     test_v2_investigate_e2e.py's pagination test already established. Every
     other line the request touches (the Flask route, AuditGenerator's
     normalizer/dataframe/pipeline, the real AuditHtmlExporter, state.json
     bookkeeping) is real and unmodified, and was verified end to end with
     these exact two fixture events before this file was written (a
     throwaway smoke script, not committed) — record_count=2, a real
     ~330KB HTML file written to a real temp reports dir.

## Destructive-operation discipline

  POST /api/audit_report/generate — called for real, exactly once, with the
      PCE boundary stubbed as above. Small and quick (2 events, one format).
      The file it produces is deleted through the real UI delete flow before
      the test returns, with a `finally` safety-net DELETE in case that step
      fails.
  DELETE /api/reports/<filename>   — called for real (the cleanup above).
  GET  /api/rule_hit_count/enablement, /api/reports, /api/report-schedules,
      /api/labels, /api/status, /api/filter-objects/{suggest,browse} — all
      real, unmocked GETs (this area's own mount already issues every one of
      them for real on every visit).
  GET  /api/reports/jobs/<id> — called for real against a real (nonexistent)
      job id (404 path only); never against a real, still-running job.
  POST /api/reports/generate, /api/rule_hit_count/enable, POST/DELETE
      /api/reports/bulk-delete — never called for real in this file. The
      polling test intercepts /api/reports/generate at the network boundary
      (page.route) precisely so it never reaches the real backend — see that
      test's own docstring.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]

ROUTE = "#/reports"
SLOW = 45_000


def _goto(page, base_url, route, cov):
    page.set_default_timeout(SLOW)
    page.goto(base_url + "/v2" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector("code:text-is('%s')" % route)
    page.wait_for_selector('[data-cov="%s"]' % cov)


def _covs(page):
    return set(page.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))


def _missing_i18n(page):
    return page.evaluate(
        "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return i18n.missing(); }"
    )


def _open_all(page):
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(300)


def _api_del(page, path):
    """Real DELETE through api.mjs (attaches/refreshes X-CSRF-Token) — the
    only route a page.request.delete() call cannot take, since it bypasses
    api.mjs entirely and this app's CSRF check is not exempted for /api/*
    mutations (v2_login's own bare POST works only because /api/login is)."""
    return page.evaluate(
        "async (path) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.del(path); }",
        path,
    )


def _patch_audit_events(monkeypatch):
    """Stub only the PCE network boundary — see this file's module docstring
    for the full rationale and what was verified before writing this. Two
    minimal but real-shaped PCE org-events; ApiClient.fetch_events is the one
    call AuditGenerator._fetch_events falls through to when no cache reader
    is configured (the harness's fresh temp config never enables one)."""
    now = datetime.now(timezone.utc)
    events = [
        {
            "href": "/orgs/1/events/1",
            "timestamp": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "pce_fqdn": "pce.test",
            "event_type": "user.login",
            "status": "success",
            "severity": "informational",
            "created_by": {"user": {"href": "/users/1", "username": "e2e-reports-audit@local"}},
            "resource": {},
            "notifications": [],
        },
        {
            "href": "/orgs/1/events/2",
            "timestamp": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            "pce_fqdn": "pce.test",
            "event_type": "rule_set.update",
            "status": "success",
            "severity": "informational",
            "created_by": {"user": {"href": "/users/1", "username": "e2e-reports-audit@local"}},
            "resource": {"rule_set": {"href": "/orgs/1/sec_policy/draft/rule_sets/1", "name": "RS-1"}},
            "notifications": [],
        },
    ]

    def fake_fetch_events(self, start_time_str, end_time_str=None, max_results=5000, rate_limit=False):
        return list(events)

    monkeypatch.setattr("src.api_client.ApiClient.fetch_events", fake_fetch_events)


def test_reports_coverage_anchors_and_i18n(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, ROUTE, "RP-01")
    _open_all(page)  # RP-02 only exists inside the "rp-gen" drawer opener

    expected = {"RP-%02d" % i for i in range(1, 10)}
    covs = _covs(page)
    assert expected - covs == set(), sorted(expected - covs)
    assert "XC-07" in covs  # the idle progress card the audit sweep shows — header point 9
    assert _missing_i18n(page) == []

    # RP-05: the panel really reflects the real GET's response, not a guess.
    # This harness's PCE is unreachable, so the real, unmocked response is a
    # real failure (500 "Internal server error") — RP-05 must show THAT, not
    # crash the page or fabricate a state. Either branch is a genuine
    # assertion: it goes red if paintRhc() stopped reading state.rhc/state.rhc
    # ._error (a production change swapping in a literal or dropping the
    # error branch would flip which locator resolves).
    rhc_resp = page.request.get(base_url + "/api/rule_hit_count/enablement")
    rhc = rhc_resp.json()
    panel = page.locator('section[data-cov="RP-05"]')
    if rhc.get("ok"):
        panel_state = panel.locator("li .c").first.inner_text()
        assert panel_state == str(rhc.get("state"))
    else:
        assert panel.locator("li .c").count() == 0
        assert (rhc.get("error") or "") in panel.inner_text()


def test_job_status_endpoint_is_real_for_unknown_job(v2_page):
    # No job of this id was ever created — the real handler's 404 "unknown
    # job" path (reports.py:540-546), hit directly, no mock in the loop.
    page, base_url = v2_page
    _goto(page, base_url, ROUTE, "RP-01")
    resp = page.request.get(base_url + "/api/reports/jobs/e2e-reports-unknown-job")
    assert resp.status == 404
    body = resp.json()
    assert body.get("ok") is False
    assert body.get("error")


def test_generate_audit_report_progress_complete_list_delete(v2_page, monkeypatch):
    _patch_audit_events(monkeypatch)
    page, base_url = v2_page
    _goto(page, base_url, ROUTE, "RP-01")

    page.locator('article[data-rtype="audit"] button.btn.primary').click()
    page.wait_for_selector('[data-cov="RP-02"]')

    with page.expect_response(
        lambda r: r.url.endswith("/api/audit_report/generate") and r.request.method == "POST"
    ) as resp_info:
        page.locator('.drawer-f .btn.primary').click()
    body = resp_info.value.json()
    assert body.get("ok") is True, body
    assert body.get("record_count") == 2, body
    filenames = body.get("files") or []
    assert filenames, body
    filename = filenames[0]

    try:
        # RP-03/XC-07: the real progress card appears for the real request,
        # then removes itself once .done() has held the "done" state for a
        # moment (components/progress.mjs's own 1600ms hold) — B1: this
        # assertion goes red if runGenerate() stopped calling p.done() (the
        # card would sit at "active" forever instead of detaching).
        page.wait_for_selector('[data-cov="XC-07"]')
        page.wait_for_selector('[data-cov="XC-07"]', state="detached", timeout=10_000)

        # RP-06: the real refreshList() ran off the real response — the file
        # the backend actually wrote is in the real output list. B1: this
        # goes red if hooks.refreshList() were dropped from the success path.
        row_sel = 'table.tbl tbody tr:has-text("%s")' % filename
        page.wait_for_selector(row_sel)
        row = page.locator(row_sel)
        assert row.count() == 1

        # The file genuinely exists on disk and is really servable.
        view_resp = page.request.get(base_url + "/reports/" + filename)
        assert view_resp.status == 200
        assert len(view_resp.body()) > 0

        # RP-07: delete it through the real UI confirm flow (XC-08).
        row.locator("button.btn.danger").click()
        page.wait_for_selector('div.modal[role="dialog"]')
        with page.expect_response(
            lambda r: r.url.endswith("/api/reports/" + filename) and r.request.method == "DELETE"
        ) as del_info:
            page.locator('div.modal[role="dialog"] button.btn.danger').click()
        del_body = del_info.value.json()
        assert del_body.get("ok") is True, del_body

        # B1: both sides of the deletion are checked — the row leaving the
        # real refreshed list, AND the file actually leaving disk (the row
        # alone would still pass if delete only mutated local JS state, the
        # exact bug the mockup's own honesty note used to admit to).
        page.wait_for_selector(row_sel, state="detached")
        gone_resp = page.request.get(base_url + "/reports/" + filename)
        assert gone_resp.status == 404
    finally:
        # Safety net: guarantee no leftover file even if an assertion above
        # failed before the UI-driven delete ran.
        _api_del(page, "/api/reports/" + filename)


def test_async_job_polling_stops_on_navigation_away(v2_page):
    """RP-03/XC-07's polling MECHANISM, proven at the network boundary.

    This test does NOT touch the real /api/reports/generate or
    /api/reports/jobs/<id> — per the destructive-operation discipline above,
    the only type this file generates for real is the small, synchronous
    `audit` type. To prove the poll-cancel-on-navigate wiring for the three
    async types (traffic/security_risk/network_inventory/app_summary) without
    triggering a real job, page.route intercepts POST /api/reports/generate
    (answers a fake job_id) and GET /api/reports/jobs/<that id> (answers
    "running" every time, counted here) — the whole Flask app underneath is
    never reached for either call. Everything else is real: the real drawer,
    the real click, the real runGenerate()/pollReportJob() JS.
    """
    page, base_url = v2_page
    poll_hits: list[str] = []

    def handle_generate(route):
        if route.request.method == "POST":
            route.fulfill(status=200, content_type="application/json",
                           body=json.dumps({"ok": True, "job_id": "e2e-reports-poll-fake"}))
        else:
            route.continue_()

    def handle_job_status(route):
        poll_hits.append(route.request.url)
        route.fulfill(status=200, content_type="application/json",
                       body=json.dumps({"ok": True, "status": "running"}))

    page.route("**/api/reports/generate", handle_generate)
    page.route("**/api/reports/jobs/**", handle_job_status)

    _goto(page, base_url, ROUTE, "RP-01")
    page.locator('article[data-rtype="traffic"] button.btn.primary').click()
    page.wait_for_selector('[data-cov="RP-02"]')
    page.locator('.drawer-f .btn.primary').click()
    page.wait_for_selector('[data-cov="XC-07"]')

    # POLL_MS is 2000ms (reports.mjs, transcribed from dashboard.js:867's
    # _pollReportJob) — wait for the first real poll request to land.
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not poll_hits:
        page.wait_for_timeout(200)
    hits_before = len(poll_hits)
    assert hits_before >= 1, "no poll request was observed"

    # Navigate away — module-level stopProgress() (path !== ROUTE) must
    # cancel the pending setTimeout, and the docked card must detach.
    page.evaluate("location.hash = '#/overview'")
    page.wait_for_selector("code:text-is('#/overview')")
    assert page.locator('[data-cov="XC-07"]').count() == 0

    # B1: wait past another full poll interval. If stopProgress() failed to
    # clear livePollTimer, this count would grow; a passing run with the
    # cancel deleted from runGenerate() would show hits_before < a later
    # count here — the assertion below would go red exactly then.
    page.wait_for_timeout(3_000)
    assert len(poll_hits) == hits_before, "a poll fired after navigating away from #/reports"

    page.unroute("**/api/reports/generate", handle_generate)
    page.unroute("**/api/reports/jobs/**", handle_job_status)
