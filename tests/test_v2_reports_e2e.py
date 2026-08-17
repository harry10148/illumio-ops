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
  POST /api/reports/generate, /api/rule_hit_count/enable — never reach the
      real backend. The polling test intercepts /api/reports/generate at the
      network boundary (page.route) precisely so it never runs; the
      rule-hit-count enable path is exercised the same way, for its payload
      and the panel's repaint only (enabling rule-hit counting really does
      mutate the connected PCE's configuration). Both tests' own docstrings
      state what they do and do not prove.
  POST /api/reports/bulk-delete — called FOR REAL, exactly once, and only
      ever against the three fixture files this file's own
      v2_reports_dir_app fixture wrote into a private tmp_path output
      directory. Nothing outside that directory is reachable, and it dies
      with the test (test_bulk_delete_really_removes_the_selected_files).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from playwright.sync_api import expect  # noqa: E402

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]

# The per-file app fixture below needs the harness's own building blocks,
# same as tests/test_v2_login_e2e.py does for its logged-out page.
from tests.v2_e2e_utils import (  # noqa: E402
    _LiveServer,
    build_v2_app,
    v2_login,
)

ROUTE = "#/reports"
SLOW = 45_000


def _goto(page, base_url, route, cov):
    page.set_default_timeout(SLOW)
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector('[data-route="%s"]' % route)
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


def test_gen_drawer_explanation_collapses_but_payload_preview_stays_visible(v2_page):
    """Density spec R2/R5 (docs/superpowers/specs/2026-08-17-ui-density-spec.md):
    the drawer's per-field explanations (date format/reset, label source, the
    data-source gate, ...) fold into one closed <details.disclose>. The "what
    actually gets sent" section (RO fields + the raw payload preview)
    deliberately does NOT — same call investigate.mjs's filtersDrawer already
    made for its own payload preview: the drawer only opens on demand, so
    this is already one click off the page's default screen, and it is the
    one place an operator can see exactly what 產生 is about to send.

    A closed <details> still renders its own <summary> (that's the toggle) —
    the proof of real collapse is that every OTHER child stays empty until
    opened, same idea as test_v2_automation_e2e.py's table-disclosure
    assertion, adapted for a disclosure whose content isn't a single nested
    locator. Opening the real <summary> then reveals the real content.
    """
    page, base_url = v2_page
    _goto(page, base_url, ROUTE, "RP-01")

    page.locator('article[data-rtype="audit"] button.btn.primary').click()
    drawer_body = page.locator('[data-cov="RP-02"]')
    drawer_body.wait_for()

    # The payload preview is real and visible without opening anything —
    # repaint() is the single function that builds both this preview and the
    # request body runGenerate() actually POSTs, so it cannot drift.
    assert "/api/audit_report/generate" in drawer_body.locator(".codepane").inner_text()

    details_all = drawer_body.locator("details.disclose")
    assert details_all.count() == 1, details_all.count()
    explain_details = details_all.first
    assert explain_details.get_attribute("open") is None
    assert explain_details.evaluate(
        "el => Array.from(el.children)"
        ".filter(c => c.tagName !== 'SUMMARY')"
        ".every(c => c.innerText.trim() === '')"
    ), explain_details.inner_text()
    explain_details.locator("summary").click()
    # audit's own two explanations: the ISO/raw date-format note and the
    # sticky-defaults note (gui_rp_date_iso|raw / gui_rp_date_sticky).
    assert explain_details.inner_text().strip() != ""


def test_aside_documentation_panels_collapse_by_default(v2_page):
    """RP-03/RP-04 are pure documentation — no live status to lead with, so
    R1 has nothing to put first — so each panel's ENTIRE body is one
    disclosure rather than one note per paragraph. Same collapse proof as
    above (every non-<summary> child is empty while closed); opening RP-03's
    reveals the real poll interval/deadline (transcribed from dashboard.js's
    _pollReportJob, reports.mjs's POLL_MS/POLL_DEADLINE_MS)."""
    page, base_url = v2_page
    _goto(page, base_url, ROUTE, "RP-01")

    for cov in ("RP-03", "RP-04"):
        panel = page.locator('section[data-cov="%s"]' % cov)
        details = panel.locator("details.disclose")
        assert details.count() == 1, cov
        assert details.get_attribute("open") is None
        assert details.evaluate(
            "el => Array.from(el.children)"
            ".filter(c => c.tagName !== 'SUMMARY')"
            ".every(c => c.innerText.trim() === '')"
        ), (cov, details.inner_text())

    prog_details = page.locator('section[data-cov="RP-03"] details.disclose')
    prog_details.locator("summary").click()
    body = prog_details.inner_text()
    assert "2" in body and "30" in body, body


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


def test_postform_recovers_from_a_stale_csrf_token(v2_page):
    """Task 8 review, Important finding: reports.mjs's CSV-source generate
    sends its multipart body through api.mjs's `api.postForm()`, which must
    share `rawRequest()`'s real CSRF-refresh-and-retry — the same recovery
    every post()/put()/del() write in the app already gets. The first cut of
    postForm() was a hand-rolled duplicate with NO retry: a stale token was a
    dead end (an opaque `{ok:false, error:"Bad Request"}` the operator could
    not recover from short of reloading).

    Proven directly against api.mjs (not through the UI's file-input widget,
    which would only add Playwright mechanics without changing what's being
    tested): deliberately corrupt the page's CSRF token, then call
    api.postForm() against the real rule_hit_count CSV endpoint. A CSV with
    a header row and no data rows is real, cheap, and produces no artifact —
    reports.py's generate_from_csv path never reaches gen.export() (so never
    writes a file) whether it answers a clean "no data" or a caught internal
    error; either way this test only cares that the REQUEST recovered from
    the stale token and reached the real backend for real, not that the
    business logic succeeded.
    """
    page, base_url = v2_page
    _goto(page, base_url, ROUTE, "RP-01")

    page.evaluate(
        "document.querySelector('meta[name=\"csrf-token\"]').setAttribute('content', 'e2e-stale-token')"
    )

    result = page.evaluate(
        "async () => {"
        "  const { api } = await import('/static/js/v2/core/api.mjs');"
        "  const fd = new FormData();"
        "  fd.append('source', 'csv');"
        "  fd.append('format', 'html');"
        "  fd.append('lang', 'en');"
        "  fd.append('file', new File(['col_a,col_b\\n'], 'e2e-stale-token.csv', {type: 'text/csv'}));"
        "  return api.postForm('/api/rule_hit_count_report/generate', fd);"
        "}"
    )
    assert result is not None
    # B1: this is exactly what the pre-fix duplicate returned verbatim — the
    # server's real 400 {code:"csrf_error", ...} body, un-retried. A retry
    # that actually ran lands on a real (non-CSRF) answer instead.
    assert result.get("code") != "csrf_error", result
    assert "ok" in result, result


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
    page.wait_for_selector('[data-route="#/overview"]')
    assert page.locator('[data-cov="XC-07"]').count() == 0

    # B1: wait past another full poll interval. If stopProgress() failed to
    # clear livePollTimer, this count would grow; a passing run with the
    # cancel deleted from runGenerate() would show hits_before < a later
    # count here — the assertion below would go red exactly then.
    page.wait_for_timeout(3_000)
    assert len(poll_hits) == hits_before, "a poll fired after navigating away from #/reports"

    page.unroute("**/api/reports/generate", handle_generate)
    page.unroute("**/api/reports/jobs/**", handle_job_status)


def test_rule_hit_count_enable_sends_lang_and_repaints_from_a_stubbed_success(v2_page):
    """RP-05's enable path, which no test had ever invoked.

    WHAT THIS PROVES: the confirm's OK really issues POST
    /api/rule_hit_count/enable carrying the area's report language, and a 200
    makes the panel RE-READ /api/rule_hit_count/enablement and repaint itself
    from that response (rather than assuming the new state or leaving the
    stale one on screen).

    WHAT THIS DOES NOT PROVE: anything about the PCE. Both the POST and the
    enablement GET are fulfilled at the network boundary, so reports.py never
    runs and no PCE-side reporting setting is changed — enabling rule-hit
    counting really does mutate the connected PCE's configuration, so it stays
    on this file's never-for-real list. The two response shapes used here are
    the ones the real endpoints document; nothing here asserts they are
    correct.
    """
    page, base_url = v2_page
    enablement_state = {"value": "disabled"}
    posted: list[dict] = []

    def enablement(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "ok": True,
            "state": enablement_state["value"],
            "pce_report_enabled": enablement_state["value"] == "enabled",
            "ven_scopes_enabled": enablement_state["value"] == "enabled",
            "detail": "e2e-rhc-%s" % enablement_state["value"],
        }))

    def enable(route):
        posted.append(route.request.post_data_json)
        enablement_state["value"] = "enabled"
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

    page.route("**/api/rule_hit_count/enablement", enablement)
    page.route("**/api/rule_hit_count/enable", enable)
    try:
        _goto(page, base_url, ROUTE, "RP-05")
        panel = page.locator('section[data-cov="RP-05"]')
        # The stub puts the panel in its real "disabled" rendering, which is
        # the only state that offers the enable control.
        assert panel.locator("li .c").first.inner_text() == "disabled"

        lang = page.locator('select[data-field="lang"]').input_value()
        panel.locator("button.btn.danger").click()
        modal = page.locator('div.modal[role="dialog"]')
        modal.wait_for(state="visible")
        modal.locator("button.btn.danger").click()

        page.wait_for_function(
            "() => document.querySelector('section[data-cov=RP-05] li .c')"
            ".textContent === 'enabled'",
            timeout=SLOW,
        )
        assert posted == [{"lang": lang}], posted
        assert "e2e-rhc-enabled" in panel.inner_text()
    finally:
        page.unroute("**/api/rule_hit_count/enable", enable)
        page.unroute("**/api/rule_hit_count/enablement", enablement)


# ── the traffic-family filename disambiguation ──────────────────────────────
#
# RESTORED GUARD (Task 11 review, Important 1). The legacy owner of this
# behaviour was tests/test_gui_report_split_and_alert_rename.py::
# test_last_run_map_disambiguates_traffic_family_by_filename, which grepped
# src/static/js/dashboard.js for the two filename prefixes. That file was
# deleted with the legacy frontend, and Task 11's first pass claimed the v2
# owner was this module — it was not: nothing here asserted either prefix.
#
# The behaviour is very much alive, at src/static/js/v2/areas/reports.mjs's
# derivedType(). It matters because the metadata sidecar hardcodes
# report_type="traffic" for ALL THREE traffic-family reports
# (report_generator.py), so security_risk / network_inventory / traffic are
# separable ONLY by their filename prefix — and the two specific prefixes
# must be tested BEFORE the bare dated pattern, since
# "Illumio_Traffic_Report_" is a strict prefix of both. A regression there
# silently collapses three report families into one on the RP-01 catalogue.
#
# This replacement is a truth test, not a string grep: it seeds three REAL
# report files with REAL sidecars that all say "traffic" into a real output
# directory, loads the real page, and reads the three cards' own counts and
# timestamps back out of the DOM. If derivedType() stopped honouring the
# prefixes, traffic would show 3 files and the other two would show 0.

TRAFFIC_FAMILY_FILES = [
    # (filename, expected data-rtype, mtime)
    # mtimes a whole DAY apart, not seconds: lastStamp() renders
    # stamp(...).slice(0, 16), i.e. minute resolution in local time, so
    # closely-spaced fixtures could collapse to the same string and make the
    # "three distinct stamps" assertion below pass or fail on the clock.
    ("Illumio_Traffic_Report_SecurityRisk_2026-08-01.html", "security_risk", 1_760_000_000),
    ("Illumio_Traffic_Report_NetworkInventory_2026-08-02.html", "network_inventory", 1_760_086_400),
    ("Illumio_Traffic_Report_2026-08-03.html", "traffic", 1_760_172_800),
]


@pytest.fixture
def v2_reports_dir_app(temp_config_file, tmp_path):
    """A real app whose report.output_dir is a private directory seeded with
    the three traffic-family files, each with a sidecar hardcoding "traffic".

    Its own app rather than the shared v2_app because report.output_dir
    defaults to the repository's `reports/` directory — writing fixtures
    there would not be isolated. Same shape as test_v2_login_e2e.py's
    per-file app fixtures.
    """
    out = tmp_path / "reports-out"
    out.mkdir()
    for name, _rtype, mtime in TRAFFIC_FAMILY_FILES:
        report = out / name
        report.write_text("<html><body>e2e fixture</body></html>", encoding="utf-8")
        # The sidecar the real generator writes: report_type is "traffic" for
        # every member of the family. This is the whole point of the test.
        (out / (name + ".metadata.json")).write_text(
            json.dumps({"report_type": "traffic"}), encoding="utf-8"
        )
        os.utime(report, (mtime, mtime))

    app, cm = build_v2_app(temp_config_file)
    cm.config["report"] = dict(cm.config.get("report", {}))
    cm.config["report"]["output_dir"] = str(out)
    cm.save()
    return app


@pytest.fixture
def v2_reports_dir_page(_v2_browser, v2_reports_dir_app):
    server = _LiveServer(v2_reports_dir_app)
    server.start()
    ctx = _v2_browser.new_context(ignore_https_errors=True)
    try:
        v2_login(ctx, server.base_url)
        page = ctx.new_page()
        page.set_default_timeout(SLOW)
        try:
            yield page, server.base_url
        finally:
            # See v2_e2e_utils.py's v2_page fixture for why this is a plain
            # close() rather than the thread-bounded one Task 6 added and
            # Task 12a removed: the hang it defended against was fixed at
            # its actual root cause (97af78c8), and running Playwright's
            # sync API off-thread is itself invalid.
            page.close()
    finally:
        ctx.close()
        server.stop()


def test_traffic_family_is_split_by_filename_not_by_the_sidecar(v2_reports_dir_page):
    page, base_url = v2_reports_dir_page
    _goto(page, base_url, ROUTE, "RP-01")

    def card(rtype):
        return page.locator('article.rpcard[data-rtype="%s"]' % rtype)

    # Every family member is counted under ITS OWN card, not lumped under
    # traffic — even though all three sidecars say "traffic".
    for _name, rtype, _mtime in TRAFFIC_FAMILY_FILES:
        c = card(rtype)
        assert c.count() == 1, rtype
        assert "1" in c.locator(".rpcard-last .n").inner_text(), (
            rtype, c.locator(".rpcard-last .n").inner_text()
        )

    # ...and each card's "last produced" stamp is its OWN file's mtime, so a
    # rule that merely counted correctly but mapped the newest file to every
    # card would still fail here.
    stamps = {
        rtype: card(rtype).locator(".rpcard-last .v").inner_text()
        for _n, rtype, _m in TRAFFIC_FAMILY_FILES
    }
    assert len(set(stamps.values())) == 3, stamps
    # The bare dated file is the newest of the three (mtime ...300), so the
    # traffic card must hold the latest of the three stamps.
    assert stamps["traffic"] == max(stamps.values()), stamps


def test_bulk_delete_really_removes_the_selected_files(v2_reports_dir_page):
    """RP-06/RP-07's bulk delete, end to end against the real backend — no
    interception anywhere in this test.

    Safe to run for real because every file it deletes is one this test's own
    fixture created, in a private tmp_path output directory
    (v2_reports_dir_app): nothing outside the fixture can be reached, and the
    directory dies with the test.

    WHAT THIS PROVES: selecting rows really fills the bulk bar, its confirm's
    OK really issues ONE POST /api/reports/bulk-delete carrying every selected
    filename, the real handler really removes the real files (they stop being
    servable), and the UI really re-reads the list from the server afterwards
    instead of patching rows out locally.
    """
    page, base_url = v2_reports_dir_page
    _goto(page, base_url, ROUTE, "RP-06")

    names = [name for name, _rtype, _mtime in TRAFFIC_FAMILY_FILES]
    for name in names:
        # Each file really is servable before the delete — otherwise the
        # 404 assertions below would prove nothing.
        assert page.request.get(base_url + "/reports/" + name).status == 200, name

    rows = page.locator('section[data-cov="RP-06"] table.tbl tbody tr')
    expect(rows).to_have_count(len(names))
    boxes = page.locator('section[data-cov="RP-06"] table.tbl tbody input[type="checkbox"]')
    for i in range(boxes.count()):
        boxes.nth(i).check()

    bar = page.locator(".floatbar")
    bar.wait_for(state="visible")
    assert bar.locator("b").inner_text() == str(len(names))

    with page.expect_response(
        lambda r: r.url.endswith("/api/reports/bulk-delete") and r.request.method == "POST"
    ) as info:
        bar.locator("button.btn.danger").click()
        modal = page.locator('div.modal[role="dialog"]')
        modal.wait_for(state="visible")
        modal.locator("button.btn.danger").click()

    body = info.value.json()
    assert body.get("ok") is True, body
    assert body.get("deleted") == len(names), body
    assert not (body.get("errors") or []), body
    sent = info.value.request.post_data_json
    assert sorted(sent["filenames"]) == sorted(names), sent

    # Both halves: the files really left disk, and the real refreshed list
    # really no longer shows them (a local-only row removal would still pass
    # the second check on its own — hence the first).
    for name in names:
        assert page.request.get(base_url + "/reports/" + name).status == 404, name
    expect(page.locator('section[data-cov="RP-06"] table.tbl tbody tr')).to_have_count(0)


def test_specific_traffic_prefixes_are_matched_before_the_bare_dated_one(v2_reports_dir_page):
    """The ordering half of derivedType(), on its own.

    "Illumio_Traffic_Report_" is a strict prefix of both
    "Illumio_Traffic_Report_SecurityRisk_" and
    "..._NetworkInventory_". If the bare dated pattern were tested first, or
    if the specific tests were dropped, both specific families would land on
    the traffic card and this count would be 3.
    """
    page, base_url = v2_reports_dir_page
    _goto(page, base_url, ROUTE, "RP-01")

    traffic_files = page.locator(
        'article.rpcard[data-rtype="traffic"] .rpcard-last .n'
    ).inner_text()
    assert "3" not in traffic_files, (
        "all three traffic-family reports collapsed onto the traffic card — "
        "derivedType() stopped honouring the filename prefixes: %s" % traffic_files
    )
    for rtype in ("security_risk", "network_inventory"):
        assert page.locator(
            'article.rpcard[data-rtype="%s"] .rpcard-last .v' % rtype
        ).inner_text() != "\u2014", rtype
