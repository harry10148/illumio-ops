"""Phase 2A Task 5 — in-process Playwright e2e for the v2 investigate area.

Drives a real (headless) Chromium against a real Flask app + real backend
through tests.v2_e2e_utils's shared harness — see that module's docstring for
the harness itself.

Covers, per the task brief's T5 row:
  - every IV-01..IV-15 coverage anchor (design/v2/coverage.yaml's investigate
    subset), split across the three sub-routes that own them, plus the
    cross-cutting anchors this area carries (XC-03/04/08/09/11/12).
  - key flow 1: add a FilterBar pill -> run the query -> the pill reaches the
    real POST /api/quarantine/search body and the KPI strip moves through its
    real loading state to the figures of the result.
  - key flow 2: the event catalogue's three-level cascade (category -> group
    -> event type, all from the real GET /api/event-catalog) and load-more
    (real Flask offset paging against GET /api/events/viewer; only the PCE
    fetch is replaced with deterministic in-process data).
  - the destructive endpoints, wired and exercised WITHOUT performing the
    destructive act — see "Destructive-operation discipline" below.
  - S2 teardown across all three sub-routes.
  - S4: i18n.missing() is empty on each of the three routes.

## Destructive-operation discipline

Nothing in this file quarantines, lifts, accelerates or backfills anything.
Exactly what each destructive endpoint sees:

  POST /api/quarantine/apply     — called once, with a workload href that does
      not exist. The route reaches the PCE for the Quarantine label map first
      (actions.py:317-324); this environment's PCE is unreachable by design,
      so it answers {ok:false, "Failed to fetch Mild labels."} having issued
      no workload update at all. The test asserts that error path.
  POST /api/quarantine/lift      — same, with the same nonexistent href.
  POST /api/workloads/accelerate — called once with an EMPTY target list, so
      actions.py:479-483 refuses it before any PCE call.
  POST /api/cache/backfill       — called once with no start date, so
      pce_cache/web.py:57-58 answers 400 "missing since" before any PCE call
      and before touching the cache DB.
  POST /api/quarantine/bulk_apply — never reaches the backend. Exercised for
      its payload and the UI's success reaction ONLY, against a success
      response fulfilled at the network boundary (page.route), so actions.py
      never runs and no workload is quarantined —
      test_bulk_quarantine_sends_the_right_payload_and_reacts_to_a_stubbed_success,
      whose docstring states exactly what it does and does not prove.

## The deterministic seams in this file, and why

`_stub_workload_list` intercepts GET /api/workloads only. The workload LIST is
a precondition, not the thing under test, and it cannot be satisfied here —
workloads come from the unreachable PCE — so the table is empty and the
row-level Isolate / Lift buttons never render. The destructive POSTs remain
real in the error-path tests. The acceleration and lift result-shape tests
intercept those POSTs with synthetic responses, so no PCE write is possible;
they test frontend accounting only. The pagination test keeps the HTTP call
on the real Flask route and monkeypatches only ApiClient.fetch_events_strict
inside that live app, so the route's filtering, sorting, offset slicing and
has_more calculation all execute. IV-15 still runs against the unmodified
backend and observes its deliberate 502.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]

R_TRAFFIC = "#/investigate/traffic"
R_WORKLOADS = "#/investigate/workloads"
R_EVENTS = "#/investigate/events"

# A workload href that is well-formed (actions.py's _is_workload_href only
# looks for "/workloads/") but cannot exist on any PCE.
FAKE_HREF = "/orgs/1/workloads/e2e-nonexistent-0000-0000-000000000000"

# Several endpoints on these routes reach the unreachable PCE (build_v2_app
# points api.url at a closed local port — see tests/v2_e2e_utils.py's
# _closed_local_port docstring, Task 5b) and some chain multiple PCE round
# trips (e.g. quarantine label-map lookup before the actual write) before
# giving up, so the harness's 10s default is still too tight for anything
# that waits on one. Kept generous rather than tuned to the fast-fail path's
# now-small measured latency, on purpose — this budget also has to cover
# real browser/CI scheduling jitter, not just the PCE round trip itself.
SLOW = 45_000


# A selector that only exists once the route's mount has run to completion.
# The route breadcrumb <code> alone is not enough: every mount appends it
# BEFORE its first await, so waiting on it can race a still-loading mount.
MOUNTED = {
    R_TRAFFIC: ".kpirow",
    R_WORKLOADS: 'section[data-cov="IV-08"]',
    R_EVENTS: 'section[data-cov="IV-13"]',
}


def _goto(page, base_url, route):
    page.set_default_timeout(SLOW)
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector('[data-route="%s"]' % route)
    page.wait_for_selector(MOUNTED[route])


def _navigate(page, route):
    """Hash-navigate within the SPA and wait for the new mount to finish."""
    page.evaluate("location.hash = '%s'" % route)
    page.wait_for_selector('[data-route="%s"]' % route)
    page.wait_for_selector(MOUNTED[route])


def _labels(page):
    """Resolve the exact catalogue strings the test clicks on — language
    independent (asks the real ui_translations catalogue through t(), never
    hardcodes English or Chinese text)."""
    keys = [
        "gui_filter_settings", "gui_cb_title", "gui_query_flow", "gui_find",
        "gui_save", "gui_confirm", "gui_btn_isolate", "gui_lift_quarantine",
        "gui_accel_modal_title", "gui_q_title", "gui_category", "gui_ev_type_group",
        "gui_event_type", "gui_refresh", "gui_load_more", "gui_search",
        "gui_accel_bulk_btn", "gui_q_apply",
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


def _stub_workload_list(page, workloads, calls=None):
    """Fulfil GET /api/workloads locally. See this module's docstring."""
    def handler(route):
        if calls is not None:
            calls.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "data": workloads, "truncated": False}),
        )

    page.route("**/api/workloads?*", handler)


def _fake_workload(quarantined=False, managed=True, href=FAKE_HREF, name="e2e-fake-workload"):
    labels = [{"key": "Quarantine", "value": "Mild"}] if quarantined else []
    return {
        "href": href,
        "name": name,
        "hostname": "e2e-fake-host",
        "online": True,
        "managed": managed,
        "labels": labels,
        "interfaces": [{"name": "eth0", "address": "10.99.0.1"}],
        "enforcement_mode": "visibility_only",
    }


# ── coverage anchors ────────────────────────────────────────────────────────

def test_traffic_coverage_anchors_present(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_TRAFFIC)

    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(300)

    found = _covs(page)
    expected = {"IV-0%d" % i for i in range(1, 8)} | {"XC-03", "XC-04", "XC-09", "XC-11", "XC-12"}
    assert expected - found == set(), sorted(expected - found)


def test_traffic_empty_state_is_quiet_before_first_query(v2_page):
    """Density spec R1/R3 for a work page: before any query has run, XC-09
    is the honest "you have not asked yet" prompt, not the full
    why-is-this-empty diagnostic (cache on? window? filter count?) — that
    diagnostic only means something once a query actually ran and matched
    nothing. Pinned separately from the post-query 3-`<li>` assertion in
    test_filter_pill_reaches_query_and_kpis_update, or a later change could
    make the causes list the idle default again with nothing to catch it."""
    page, base_url = v2_page
    _goto(page, base_url, R_TRAFFIC)

    xc09 = page.locator('[data-cov="XC-09"]')
    assert xc09.count() == 1
    assert xc09.locator("li").count() == 0
    labels = _labels(page)
    assert labels["gui_query_flow"]  # sanity: catalogue resolved
    prompt = page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return t('gui_iv_search_prompt'); }"
    )
    assert xc09.inner_text().strip() == prompt.strip() or prompt in xc09.inner_text()

    # The audit probe (handles.probeEmpty) still exercises the real
    # causes-diagnostic renderer even while the page itself is idle — it
    # forces its own copy of the state to phase "done" precisely so an
    # audit pass proves the empty-causes branch works without requiring a
    # real query first.
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(300)
    all_xc09 = page.locator('[data-cov="XC-09"]')
    assert all_xc09.count() == 2
    assert sum(all_xc09.nth(i).locator("li").count() for i in range(2)) == 3


def test_workloads_coverage_anchors_present(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_WORKLOADS)

    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(300)

    found = _covs(page)
    expected = {"IV-08", "IV-09", "IV-10", "IV-11", "IV-12", "XC-08"}
    assert expected - found == set(), sorted(expected - found)


def test_events_coverage_anchors_present(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, R_EVENTS)

    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(300)

    found = _covs(page)
    expected = {"IV-13", "IV-14", "IV-15"}
    assert expected - found == set(), sorted(expected - found)


# ── key flow 1: FilterBar pill -> query -> KPIs ─────────────────────────────

def test_filter_pill_reaches_query_and_kpis_update(v2_page):
    """Add a pill in the advanced-filter drawer, apply it, and prove (a) the
    serialized pill really rides the POST /api/quarantine/search body and
    (b) the KPI strip is bound to the query lifecycle, not static."""
    page, base_url = v2_page
    _goto(page, base_url, R_TRAFFIC)
    labels = _labels(page)

    # Before any query the strip is idle and shows no figures.
    kpis = page.locator(".kpirow")
    assert kpis.get_attribute("data-phase") == "idle"
    assert kpis.locator(".kpicell .v span").first.inner_text() == "—"

    # IV-03: open the advanced filters drawer from the IV-01 panel header.
    page.locator('section[data-cov="IV-01"]').get_by_role(
        "button", name=labels["gui_filter_settings"], exact=True
    ).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")

    # XC-03: type a real label spec into the source zone and commit it. This
    # is filter-bar.mjs's own keyboard path (_objfbKeydown's Enter branch),
    # not an injected pill.
    zone = drawer.locator('[data-cov="XC-03"] [data-zone="src:false"] input.fb-input')
    zone.fill("role=web")
    zone.press("Enter")
    assert drawer.locator(".fb-pill").count() == 1

    # Save applies the filters and runs the query.
    with page.expect_request(
        lambda r: "/api/quarantine/search" in r.url and r.method == "POST"
    ) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    body = info.value.post_data_json

    # The pill's serialized key (filter-bar.mjs _objfbSerialize) is in the body,
    # alongside the fixed fields quarantine.js:288-292 always sends.
    assert body["src_labels"] == ["role=web"], body
    assert body["mins"] == 60, body
    assert body["sort_by"] == "bandwidth", body
    assert body["source"] == "live", body
    assert body["policy_decision"] == "-1", body

    # Real loading state while the PCE search runs, then the figures of the
    # result — the strip moved, it is not a static placeholder.
    page.wait_for_selector('.kpirow[data-loading="true"]')
    page.wait_for_selector('.kpirow[data-phase="done"]', timeout=SLOW)
    assert page.locator('.kpirow[data-loading="true"]').count() == 0
    assert page.locator(".kpirow .kpicell .v span").first.inner_text() == "0"

    # XC-09: the empty result explains itself instead of shrugging.
    assert page.locator('[data-cov="XC-09"] li').count() == 3


# ── key flow 2: catalogue cascade + load more ───────────────────────────────

def test_event_catalog_three_level_cascade(v2_page):
    """IV-13 against the REAL GET /api/event-catalog: choosing a category
    narrows the group list, and choosing a group narrows the type list — and
    the resulting query really carries those filters."""
    page, base_url = v2_page
    _goto(page, base_url, R_EVENTS)
    labels = _labels(page)

    panel = page.locator('section[data-cov="IV-13"]')
    cat = panel.locator('select[aria-label="%s"]' % labels["gui_category"])
    grp = panel.locator('select[aria-label="%s"]' % labels["gui_ev_type_group"])
    typ = panel.locator('select[aria-label="%s"]' % labels["gui_event_type"])

    groups_all = grp.locator("option").count()
    types_all = typ.locator("option").count()
    assert groups_all > 2 and types_all > 2

    # Pick the second category (the first option is "All categories").
    cat_value = cat.locator("option").nth(1).get_attribute("value")
    assert cat_value
    with page.expect_request(lambda r: "/api/events/viewer" in r.url) as info:
        cat.select_option(cat_value)
    assert "category=" + cat_value.replace(" ", "+") in info.value.url, info.value.url

    grp = panel.locator('select[aria-label="%s"]' % labels["gui_ev_type_group"])
    typ = panel.locator('select[aria-label="%s"]' % labels["gui_event_type"])
    groups_cat = grp.locator("option").count()
    types_cat = typ.locator("option").count()
    assert 1 < groups_cat < groups_all, (groups_cat, groups_all)
    assert 1 < types_cat < types_all, (types_cat, types_all)

    # Pick the second group — the type list must narrow strictly, the category
    # does not. A <= assertion would pass even if this change repopulated the
    # same list and therefore would not prove the cascade.
    grp_value = grp.locator("option").nth(1).get_attribute("value")
    assert grp_value
    with page.expect_request(lambda r: "/api/events/viewer" in r.url) as info2:
        grp.select_option(grp_value)
    assert "type_group=" + grp_value in info2.value.url, info2.value.url

    typ = panel.locator('select[aria-label="%s"]' % labels["gui_event_type"])
    types_grp = typ.locator("option").count()
    assert 1 < types_grp < types_cat, (types_grp, types_cat)
    assert page.locator('select[aria-label="%s"]' % labels["gui_category"]).input_value() == cat_value

    # Select one concrete event type as the final tier and prove that the
    # viewer request carries event_type=, not just the category/group filters.
    type_value = typ.locator("option").nth(1).get_attribute("value")
    assert type_value
    with page.expect_request(lambda r: "/api/events/viewer" in r.url) as info3:
        typ.select_option(type_value)
    query = parse_qs(urlparse(info3.value.url).query)
    assert query.get("event_type") == [type_value], info3.value.url


def test_event_load_more_pages_by_offset(v2_page, v2_app, monkeypatch):
    """IV-14 load-more through the real Flask handler: the button exists
    exactly while the handler says has_more, and it asks for the NEXT offset
    rather than revealing rows it already had. Only the PCE fetch is replaced
    with deterministic data; the route itself is real."""
    page, base_url = v2_page
    seen = []

    def fake_fetch_events_strict(self, start_time_str, end_time_str=None, max_results=5000, event_type=None):
        return [
            {
                "href": "/orgs/1/events/%d" % i,
                "timestamp": "2026-08-14T10:00:%02dZ" % i,
                "event_type": "user.login",
                "status": "success",
                "severity": "info",
                "created_by": {"user": {"username": "admin"}},
                "action": {"api_method": "POST", "api_endpoint": "/api/v2/login"},
            }
            for i in range(30)
        ]

    # This is the real Flask route in the in-process app; replace only its
    # external PCE fetch so the route can deterministically produce 25 + 5.
    monkeypatch.setattr("src.api_client.ApiClient.fetch_events_strict", fake_fetch_events_strict)

    def on_request(request):
        if "/api/events/viewer" in request.url:
            query = parse_qs(urlparse(request.url).query)
            seen.append(int(query.get("offset", ["0"])[0]))

    page.on("request", on_request)
    _goto(page, base_url, R_EVENTS)
    labels = _labels(page)

    page.locator('section[data-cov="IV-13"]').get_by_role(
        "button", name=labels["gui_refresh"], exact=True
    ).click()
    rows = page.locator('.evl tbody tr')
    page.wait_for_function("() => document.querySelectorAll('.evl tbody tr').length === 25")

    more = page.locator('button[data-role="load-more"]')
    assert more.count() == 1
    more.click()
    page.wait_for_function("() => document.querySelectorAll('.evl tbody tr').length === 30")
    assert rows.count() == 30
    assert seen == [0, 25], seen
    # The server said there is no more, so the control is gone — it is driven
    # by summary.has_more, not by a local row count.
    assert page.locator('button[data-role="load-more"]').count() == 0


# ── destructive endpoints: wiring exercised, act not performed ──────────────

def test_quarantine_apply_surfaces_backend_error_for_nonexistent_workload(v2_page):
    page, base_url = v2_page
    _stub_workload_list(page, [_fake_workload()])
    _goto(page, base_url, R_WORKLOADS)
    labels = _labels(page)

    page.locator('section[data-cov="IV-08"]').get_by_role(
        "button", name=labels["gui_find"], exact=True
    ).click()
    row = page.locator("tbody tr").filter(has_text="e2e-fake-workload")
    row.wait_for(state="visible")

    row.get_by_role("button", name=labels["gui_btn_isolate"], exact=True).click()
    drawer = page.locator('aside.drawer[aria-label="%s"]' % labels["gui_q_title"])
    drawer.wait_for(state="visible")
    assert drawer.locator('[data-cov="IV-09"]').count() == 1

    # The confirmation with its impact list must appear before anything is sent.
    drawer.locator(".drawer-f button.btn.primary").click()
    confirm = page.locator(".modal")
    confirm.wait_for(state="visible")
    assert confirm.locator("ul.impact li").count() >= 2

    with page.expect_request(
        lambda r: "/api/quarantine/apply" in r.url and r.method == "POST"
    ) as info:
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    body = info.value.post_data_json
    assert body == {"href": FAKE_HREF, "level": "Mild"}, body

    payload = info.value.response().json()
    assert payload.get("ok") is False, payload
    # Nothing was quarantined: the route failed at the label lookup, before any
    # workload update. The UI must say so rather than claim success.
    page.wait_for_selector('.toast[data-tone="crit"]', timeout=SLOW)


def test_quarantine_lift_surfaces_backend_error_for_nonexistent_workload(v2_page):
    page, base_url = v2_page
    _stub_workload_list(page, [_fake_workload(quarantined=True)])
    _goto(page, base_url, R_WORKLOADS)
    labels = _labels(page)

    page.locator('section[data-cov="IV-08"]').get_by_role(
        "button", name=labels["gui_find"], exact=True
    ).click()
    row = page.locator("tbody tr").filter(has_text="e2e-fake-workload")
    row.wait_for(state="visible")

    # IV-11 only exists on a workload that carries the Quarantine label.
    lift = row.locator('button[data-cov="IV-11"]')
    assert lift.count() == 1
    lift.click()

    confirm = page.locator('.modal[data-cov="XC-08"]')
    confirm.wait_for(state="visible")

    with page.expect_request(
        lambda r: "/api/quarantine/lift" in r.url and r.method == "POST"
    ) as info:
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    assert info.value.post_data_json == {"hrefs": [FAKE_HREF]}, info.value.post_data_json

    payload = info.value.response().json()
    assert payload.get("ok") is False, payload
    page.wait_for_selector('.toast[data-tone="crit"]', timeout=SLOW)


def test_quarantine_lift_reports_partial_results_without_refresh(v2_page):
    """An HTTP-successful lift response can still contain failed and
    not-quarantined targets; those counts are reported separately and the
    stale workload list is not refreshed when success is zero. The POST is
    fulfilled locally, so this never performs a destructive PCE call."""
    page, base_url = v2_page
    workload_calls = []
    _stub_workload_list(page, [_fake_workload(quarantined=True)], workload_calls)
    page.route(
        "**/api/quarantine/lift",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True,
                "results": {"success": 0, "failed": [FAKE_HREF], "not_quarantined": 2},
            }),
        ),
    )
    _goto(page, base_url, R_WORKLOADS)
    labels = _labels(page)

    page.locator('section[data-cov="IV-08"]').get_by_role(
        "button", name=labels["gui_find"], exact=True
    ).click()
    row = page.locator("tbody tr").filter(has_text="e2e-fake-workload")
    row.wait_for(state="visible")
    row.locator('button[data-cov="IV-11"]').click()
    confirm = page.locator('.modal[data-cov="XC-08"]')
    confirm.wait_for(state="visible")
    with page.expect_response(lambda r: "/api/quarantine/lift" in r.url) as response:
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()
    assert response.value.json()["results"] == {
        "success": 0, "failed": [FAKE_HREF], "not_quarantined": 2,
    }

    failed_text = page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return t('gui_lift_failed').replace('{n}', '1'); }"
    )
    not_quarantined_text = page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return t('gui_lift_not_quarantined').replace('{n}', '2'); }"
    )
    page.wait_for_function("() => document.querySelectorAll('.toast[data-tone=warn]').length === 2")
    warnings = page.locator('.toast[data-tone="warn"]').all_inner_texts()
    assert failed_text in warnings
    assert not_quarantined_text in warnings
    page.wait_for_timeout(200)
    assert len(workload_calls) == 1, workload_calls


def test_accelerate_submission_is_rejected_by_backend_validation(v2_page):
    """IV-12 wiring: the form really posts, and the backend really refuses it
    (actions.py:479-483) before any PCE call, because nothing is selected."""
    page, base_url = v2_page
    _goto(page, base_url, R_WORKLOADS)
    labels = _labels(page)

    # With no PCE there are no workload rows, so the row-level and bulk-bar
    # entry points cannot render; the registered opener is the same code path
    # a click would use (the pattern tests/test_v2_overview_e2e.py already
    # uses for OV-02). It also opens the lift-confirm modal on top, whose
    # scrim would swallow the click below — dismiss that first.
    page.evaluate("window.__openAllForAudit()")
    drawer = page.locator('aside.drawer[aria-label="%s"]' % labels["gui_accel_modal_title"])
    drawer.wait_for(state="visible")
    page.locator(".modal").first.wait_for(state="visible")
    page.keyboard.press("Escape")
    page.wait_for_selector(".modal", state="detached")
    assert drawer.locator('[data-cov="IV-12"]').count() == 1

    with page.expect_request(
        lambda r: "/api/workloads/accelerate" in r.url and r.method == "POST"
    ) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    assert info.value.post_data_json == {"hrefs": [], "duration_minutes": 0}

    payload = info.value.response().json()
    assert payload.get("ok") is False, payload
    page.wait_for_selector('.toast[data-tone="crit"]')
    # A rejected submission keeps the drawer open (drawerSpec onSave -> false).
    assert drawer.count() == 1


def test_accelerate_submits_only_managed_targets_and_stops_on_all_failures(v2_page):
    """Acceleration excludes unmanaged selections and does not start a
    persistent countdown when the backend reports success=0/failed=1. The
    destructive POST is fulfilled locally, so no PCE write occurs."""
    page, base_url = v2_page
    managed_href = "/orgs/1/workloads/e2e-managed-0000"
    unmanaged_href = "/orgs/1/workloads/e2e-unmanaged-0000"
    _stub_workload_list(page, [
        _fake_workload(href=managed_href, name="e2e-managed", managed=True),
        _fake_workload(href=unmanaged_href, name="e2e-unmanaged", managed=False),
    ])
    requests = []

    def accelerate(route):
        requests.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "success": 0, "failed": 1, "skipped_invalid": 0}),
        )

    page.route("**/api/workloads/accelerate", accelerate)
    _goto(page, base_url, R_WORKLOADS)
    labels = _labels(page)
    page.locator('section[data-cov="IV-08"]').get_by_role(
        "button", name=labels["gui_find"], exact=True
    ).click()
    page.locator('input[type="checkbox"][aria-label="e2e-managed"]').check()
    page.locator('input[type="checkbox"][aria-label="e2e-unmanaged"]').check()
    bar = page.locator('.floatbar[data-tone="crit"]')
    bar.get_by_role("button", name=labels["gui_accel_bulk_btn"], exact=True).click()
    drawer = page.locator('aside.drawer[aria-label="%s"]' % labels["gui_accel_modal_title"])
    drawer.wait_for(state="visible")
    drawer.locator('input[name="iv-accel"][value="30"]').check()
    drawer.locator(".drawer-f button.btn.primary").click()

    page.wait_for_function("() => document.querySelectorAll('.toast[data-tone=warn]').length >= 1")
    assert requests == [{"hrefs": [managed_href], "duration_minutes": 30}], requests
    assert page.locator('.floatbar[data-tone="ok"]').count() == 0


def test_backfill_submission_is_rejected_by_backend_validation(v2_page):
    """IV-07 wiring: an empty date range really posts and the route really
    answers 400 "missing since" (pce_cache/web.py:57-58) — no backfill runs."""
    page, base_url = v2_page
    _goto(page, base_url, R_TRAFFIC)
    labels = _labels(page)

    page.locator('section[data-cov="IV-01"]').get_by_role(
        "button", name=labels["gui_cb_title"], exact=True
    ).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    assert drawer.locator('[data-cov="IV-07"]').count() == 1

    with page.expect_response(lambda r: "/api/cache/backfill" in r.url) as info:
        drawer.locator(".drawer-f button.btn.primary").click()
    assert info.value.status == 400, info.value.text()
    assert "since" in info.value.text()

    page.wait_for_selector('.toast[data-tone="crit"]')
    assert drawer.count() == 1


# ── successful write paths, asserted at the service boundary ────────────────

def test_bulk_quarantine_sends_the_right_payload_and_reacts_to_a_stubbed_success(v2_page):
    """IV-10's bulk quarantine, the one write path in this area no test had
    ever exercised at all (it was neither called nor stubbed).

    WHAT THIS PROVES: with two workloads selected, the drawer's Save ->
    confirm -> OK chain really issues POST /api/quarantine/bulk_apply with
    exactly {hrefs: [both selected], level: "Mild"} — the many-target route,
    not the single-target one — and the UI reacts to a 200 success by
    reporting the applied count and refreshing the workload list from the
    server (the stale list is not patched locally).

    WHAT THIS DOES NOT PROVE: nothing about the backend. The POST is
    fulfilled at the network boundary, so actions.py's bulk_apply never runs,
    no PCE is contacted and no workload is quarantined anywhere — this is the
    destructive-operation discipline in this file's module docstring, kept
    intact. The response shape used here is transcribed from actions.py's
    documented contract ({ok, results:{success, failed[], skipped_invalid}}),
    not invented, but that contract is asserted nowhere here.
    """
    page, base_url = v2_page
    href_a = "/orgs/1/workloads/e2e-bulk-a-0000"
    href_b = "/orgs/1/workloads/e2e-bulk-b-0000"
    list_calls: list[str] = []
    _stub_workload_list(page, [
        _fake_workload(href=href_a, name="e2e-bulk-a"),
        _fake_workload(href=href_b, name="e2e-bulk-b"),
    ], calls=list_calls)

    posted: list[dict] = []

    def bulk(route):
        posted.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "results": {"success": 2, "failed": [], "skipped_invalid": 0}}),
        )

    page.route("**/api/quarantine/bulk_apply", bulk)
    try:
        _goto(page, base_url, R_WORKLOADS)
        labels = _labels(page)
        page.locator('section[data-cov="IV-08"]').get_by_role(
            "button", name=labels["gui_find"], exact=True
        ).click()
        page.locator('input[type="checkbox"][aria-label="e2e-bulk-a"]').check()
        page.locator('input[type="checkbox"][aria-label="e2e-bulk-b"]').check()
        searches_before = len(list_calls)

        page.locator(".floatbar").get_by_role(
            "button", name=labels["gui_q_apply"], exact=True
        ).click()
        drawer = page.locator("aside.drawer")
        drawer.wait_for(state="visible")
        assert drawer.locator('[data-cov="IV-10"]').count() == 1

        drawer.locator(".drawer-f button.btn.primary").click()
        confirm = page.locator(".modal")
        confirm.wait_for(state="visible")
        assert confirm.locator("ul.impact li").count() >= 2
        confirm.get_by_role("button", name=labels["gui_confirm"], exact=True).click()

        page.wait_for_function("() => document.querySelectorAll('.toast[data-tone=warn]').length >= 1")
        assert posted == [{"hrefs": [href_a, href_b], "level": "Mild"}], posted
        # The success reaction: the applied count is reported...
        assert any("2" in text for text in page.locator('.toast[data-tone="warn"]').all_inner_texts())
        # ...and the list is re-read from the server rather than patched.
        # onQuarantined() -> runSearch() issues a fresh GET /api/workloads;
        # deleting that call from the success path turns this red.
        for _ in range(100):
            if len(list_calls) > searches_before:
                break
            page.wait_for_timeout(100)
        assert len(list_calls) > searches_before, list_calls
    finally:
        page.unroute("**/api/quarantine/bulk_apply", bulk)


# ── S2 teardown ─────────────────────────────────────────────────────────────

def test_teardown_across_all_three_subroutes(v2_page):
    """Leaving any sub-route must destroy mounted components, strand no
    dialog, leave no route-scoped palette command, and clear traffic-only
    audit surfaces before the next route can invoke them."""
    page, base_url = v2_page

    # traffic -> workloads
    _goto(page, base_url, R_TRAFFIC)
    labels = _labels(page)
    assert R_TRAFFIC in _palette_routes(page)
    page.locator('section[data-cov="IV-01"]').get_by_role(
        "button", name=labels["gui_filter_settings"], exact=True
    ).click()
    traffic_drawer = page.locator("aside.drawer")
    traffic_drawer.wait_for(state="visible")
    traffic_fb = traffic_drawer.locator('[data-cov="XC-03"]')
    traffic_fb_id = traffic_fb.get_attribute("data-objfb-id")
    assert traffic_fb_id

    _navigate(page, R_WORKLOADS)
    assert page.locator("aside.drawer").count() == 0
    assert R_TRAFFIC not in _palette_routes(page)
    assert R_WORKLOADS in _palette_routes(page)
    assert page.evaluate(
        "id => window._objfbGetInstance(id)", traffic_fb_id
    ) is None
    # The FilterBar instance being gone is drawer.closeAll()'s doing, not
    # teardown's — a separate module-global callback that filter-bar.mjs calls
    # to open the object browser (setFilterBarBrowser) must also be cleared,
    # or a later area could invoke a closure over this torn-down traffic
    # mount's state.
    assert page.evaluate(
        "async () => { const fb = await import('/static/js/v2/components/filter-bar.mjs'); "
        "return fb._objfbHasBrowser(); }"
    ) is False

    # The audit hook is a page-global entry point, but its route registry must
    # contain only the current mount. Calling it after leaving traffic must not
    # resurrect the departed traffic FilterBar/browser surfaces.
    page.evaluate("window.__openAllForAudit()")
    assert page.locator('[data-cov="XC-03"]').count() == 0
    assert page.locator('[data-cov="XC-04"]').count() == 0

    # workloads -> events, with both a drawer AND a modal left open
    page.evaluate("window.__openAllForAudit()")
    page.locator("aside.drawer").first.wait_for(state="visible")
    page.locator(".modal").first.wait_for(state="visible")

    _navigate(page, R_EVENTS)
    assert page.locator("aside.drawer").count() == 0
    assert page.locator(".modal").count() == 0
    assert R_WORKLOADS not in _palette_routes(page)
    assert R_EVENTS in _palette_routes(page)

    # events -> back to traffic: no command from the events mount survives, and
    # the traffic mount rebuilds cleanly (exactly one KPI strip, not two).
    _navigate(page, R_TRAFFIC)
    assert R_EVENTS not in _palette_routes(page)
    assert page.locator(".kpirow").count() == 1


# ── S4 i18n ─────────────────────────────────────────────────────────────────

def test_i18n_missing_is_empty_on_every_investigate_route(v2_page):
    """i18n.missing() accumulates for the life of the page, so walking all
    three routes (each with every registered surface opened) in one page load
    checks all three at once."""
    page, base_url = v2_page

    _goto(page, base_url, R_TRAFFIC)
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(200)
    assert _missing_i18n(page) == []

    _navigate(page, R_WORKLOADS)
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(200)
    assert _missing_i18n(page) == []

    _navigate(page, R_EVENTS)
    page.evaluate("window.__openAllForAudit()")
    page.wait_for_timeout(200)
    assert _missing_i18n(page) == []


# ── IV-15 shadow compare ────────────────────────────────────────────────────

def test_shadow_compare_binds_to_its_real_endpoint(v2_page):
    """IV-15: the panel is idle until asked, then it really calls
    GET /api/events/shadow_compare with the clamped mins/limit and reports
    what that endpoint answers (here: the PCE fetch failure, verbatim)."""
    page, base_url = v2_page
    _goto(page, base_url, R_EVENTS)
    labels = _labels(page)

    panel = page.locator('section[data-cov="IV-15"]')
    assert panel.count() == 1
    # The five columns this endpoint returns are declared even while empty.
    assert panel.locator("thead th").count() == 5

    with page.expect_request(lambda r: "/api/events/shadow_compare" in r.url) as info:
        panel.get_by_role("button", name=labels["gui_refresh"], exact=True).click()
    assert "mins=60" in info.value.url and "limit=200" in info.value.url, info.value.url

    page.wait_for_selector('section[data-cov="IV-15"] .strip[data-tone="crit"]', timeout=SLOW)
