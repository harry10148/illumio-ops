"""Phase 2A Task 4 — in-process Playwright e2e for the v2 overview area.

Drives a real (headless) Chromium against a real Flask app + real backend
(no snapshots, no mocks) through tests.v2_e2e_utils's shared harness — see
that module's docstring for the harness itself.

Covers:
  - every OV-01..OV-16 coverage anchor (design/v2/coverage.yaml's overview
    subset) is present in the DOM after window.__openAllForAudit() on
    #/home.
  - the OV-04 custom-query CRUD round trip through the REAL
    POST/DELETE /api/dashboard/queries endpoints, driven by real UI clicks
    (button clicks + form fill, not an api.post()/api.del() bypass): create
    a query -> it appears in the list -> a page reload proves the create
    reached the backend -> edit-open shows the saved value -> delete
    (through the real confirm-modal flow) -> it disappears -> a second
    reload proves the delete reached the backend too.
  - the recent-alerts list's "see all" link navigates to another area — URL
    hash and mounted content both change.
  - S2 teardown: navigating away from #/home closes a drawer this area
    left open. drawer.mjs/modal.mjs have no per-area scoping of their own
    (closeAll() is global), so this is the only externally observable proof
    that mountOverview()'s router.onChange teardown actually ran.

Not covered here: OV-05's chart.rankedBars() ResizeObserver teardown. This
test environment's PCE is unreachable by construction (build_v2_app points
api.url at a closed local port — see tests/v2_e2e_utils.py's
_closed_local_port docstring, Task 5b), and dashboard.py's
api_dashboard_top10 lets query_flows() run its real (fast, connection-refused)
failure before returning {ok:false}, so a created query's top10 refresh
resolves with an empty result and OV-05 never actually renders a chart to
observe teardown of (see cardTop10()'s `if (!top.ok || !data.length)` empty
branch in areas/overview.mjs). The chart handle IS captured and destroyed
(buildBoard's repaint-time cleanup and mountOverview's teardown callback,
both in areas/overview.mjs) — verified by code reading, not by this suite.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]

# Plain functions/classes (not fixtures) from the shared harness, imported
# directly so the legacy-query regression test below can seed
# settings.dashboard_queries BEFORE the server starts — v2_page/v2_server
# give no hook for that.
from tests.v2_e2e_utils import build_v2_app, _LiveServer, v2_login  # noqa: E402


HOME = "#/home"
TRAFFIC = "#/investigate/traffic"   # OV-04 / OV-05 live here in v3
PCE = "#/system/pce"                # OV-01 / OV-12
SIEM = "#/system/siem"              # OV-10 / OV-16


# The first card each page paints once its snapshots are in — waiting on the
# route alone races the async load (the area head lands before the data).
FIRST_ANCHOR = {HOME: "HM-02", TRAFFIC: "OV-04", PCE: "OV-01", SIEM: "OV-10", "#/reports": "OV-03",
                "#/system/tls": "OV-14", "#/system/channels": "OV-15"}


def _goto(page, base_url, route=HOME, cov=None):
    page.set_default_timeout(30000)
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector('[data-route="%s"]' % route)
    first = cov or FIRST_ANCHOR.get(route)
    if first:
        page.wait_for_selector('[data-cov="%s"]' % first)


def _goto_overview(page, base_url):
    _goto(page, base_url, HOME)


def _labels(page):
    """Resolve the exact catalogue strings the test needs to click on —
    language-independent (asks the real ui_translations catalogue via t(),
    never hardcodes English/Chinese text)."""
    return page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { "
        "add: t('gui_add_query_widget'), "
        "edit: t('gui_edit_query_widget'), "
        "confirm: t('gui_confirm') "
        "}; }"
    )


def _health_labels(page):
    return page.evaluate(
        "async () => { const { t, tf } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { auth: t('gui_health_pce_auth_failed'), "
        "unreachable: t('gui_health_pce_unreachable'), "
        "degraded: tf('gui_health_pce_reported_status', { status: 'degraded' }), "
        "critical: tf('gui_health_pce_reported_status', { status: 'critical' }), "
        "provider: t('gui_saas_status_link') }; }"
    )


def _route_health_snapshots(page, *, pce_stats, pipeline,
                            deployment_type="saas", health_probe="noop"):
    """Serve complete, controlled health snapshots through the real UI loads."""
    status = {
        "version": "e2e",
        "api_url": "https://api.e2e.invalid",
        "rules_count": 1,
        "health_check": True,
        "language": "en",
        "theme": "dark",
        "timezone": "UTC",
        "cooldowns": [],
        "event_watermark": "2026-08-30T00:00:00Z",
        "event_overflow": {},
        "unknown_events": {},
        "event_parser_stats": {},
        "event_parser_samples": [],
        "pce_stats": pce_stats,
        "throttle_state": {},
        "dispatch_history": [],
        "alert_channels": [],
        "event_timeline": [],
        "deployment_type": deployment_type,
        "health_probe": health_probe,
    }
    if deployment_type == "saas":
        status["provider_status_url"] = "https://status.illumio.com/posts/dashboard"
    overview = {
        "as_of": "2026-08-30T00:05:00Z",
        "ven": {"verdict": "unknown"},
        "blocked": {"verdict": "unknown"},
        "pipeline": pipeline,
        "alerts": {"verdict": "ok", "recent": []},
        "os_dist": [],
        "enforcement": {},
        "posture": {"verdict": "unknown"},
        "job_health": [],
        "data_integrity": [],
        "tls": {"enabled": False, "days_remaining": None, "expiring_soon": False},
    }

    def serve_status(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(status))

    def serve_overview(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(overview))

    page.route("**/api/status", serve_status)
    page.route("**/api/dashboard/overview", serve_overview)


def _pce_stats(*, health_status="ok", health_category="ok", failures=0,
               event_poll_status="ok", last_error="", last_error_status=None):
    return {
        "health_status": health_status,
        "health_category": health_category,
        "health_probe": "noop",
        "deployment_type": "saas",
        "event_poll_status": event_poll_status,
        "consecutive_failures": failures,
        "last_health_check": "2026-08-30T00:04:00Z",
        "last_success": "2026-08-30T00:04:00Z",
        "last_event_poll": "2026-08-30T00:03:00Z",
        "last_error": last_error,
        "last_error_status": (
            "401" if health_category == "auth_failed" else ""
        ) if last_error_status is None else last_error_status,
        "last_error_stage": "health" if health_category != "ok" else "",
        "last_batch_total": 12,
        "last_batch_unknown": 0,
    }


def _pipeline(*, verdict="ok", event_status="ok", traffic_status="ok"):
    return {
        "verdict": verdict,
        "cache_lag": [
            {"source": "events", "lag_s": 30, "level": "ok", "last_status": event_status},
            {"source": "traffic", "lag_s": 45, "level": "ok", "last_status": traffic_status},
        ],
        "siem_success_1h": 100.0,
        "dlq": 0,
        "siem_idle": False,
    }


def test_overview_coverage_anchors_present(v2_page):
    """v3: the overview board is gone; its surviving cards live on the pages
    below (design/v3/coverage.yaml), and #/home carries the five new cards."""
    page, base_url = v2_page
    placement = {
        HOME: {"HM-00", "HM-01", "HM-02", "HM-03", "HM-05", "HM-06"},
        TRAFFIC: {"OV-04", "OV-05"},
        "#/reports": {"OV-03", "OV-06", "OV-07", "OV-08"},
        PCE: {"OV-01", "OV-12"},
        SIEM: {"OV-10", "OV-16"},
        "#/system/tls": {"OV-14"},
        "#/system/channels": {"OV-15"},
    }
    for route, expected in placement.items():
        _goto(page, base_url, route)
        page.evaluate("window.__openAllForAudit ? window.__openAllForAudit() : null")
        page.wait_for_timeout(300)
        found = set(page.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))
        missing = expected - found
        assert missing == set(), f"{route}: missing coverage anchors: {sorted(missing)}"


def test_auth_failure_is_credentials_reason_not_generic_unreachable(v2_page):
    page, base_url = v2_page
    _route_health_snapshots(
        page,
        pce_stats=_pce_stats(
            health_status="error",
            health_category="auth_failed",
            failures=1,
            last_error="sensitive-response-body-must-not-render",
        ),
        pipeline=_pipeline(),
    )
    _goto(page, base_url, HOME)
    labels = _health_labels(page)

    pce_lamp = page.locator('[data-cov="HM-02"] details.lamp').nth(1)
    assert pce_lamp.get_attribute("data-tone") == "crit"
    pce_lamp.locator("summary").click()
    reasons = pce_lamp.locator(".lamp-why").inner_text()
    assert labels["auth"] in reasons
    assert labels["unreachable"] not in reasons
    assert "sensitive-response-body-must-not-render" not in reasons

    _goto(page, base_url, PCE)

    system_text = page.locator('section[data-cov="OV-01"]').text_content()
    assert labels["auth"] in system_text
    assert labels["unreachable"] not in system_text
    assert "sensitive-response-body-must-not-render" not in system_text


def test_noop_success_keeps_api_green_while_failed_ingestor_keeps_pipeline_red(v2_page):
    page, base_url = v2_page
    _route_health_snapshots(
        page,
        pce_stats=_pce_stats(event_poll_status="error"),
        pipeline=_pipeline(verdict="error", event_status="error"),
    )
    _goto(page, base_url, HOME)

    lamps = page.locator('[data-cov="HM-02"] details.lamp')
    assert lamps.nth(1).get_attribute("data-tone") == "ok"
    assert lamps.nth(3).get_attribute("data-tone") == "crit"
    _goto(page, base_url, PCE)
    assert page.locator('section[data-cov="OV-01"]').get_attribute("data-tone") == "ok"
    _goto(page, base_url, SIEM)
    assert page.locator('section[data-cov="OV-10"]').get_attribute("data-tone") == "crit"

    pipeline_text = page.locator('section[data-cov="OV-10"]').text_content()
    assert "events" in pipeline_text and "error" in pipeline_text
    assert "traffic" in pipeline_text and "ok" in pipeline_text


def test_healthy_saas_identifies_noop_provider_and_both_ingest_freshness_rows(v2_page):
    page, base_url = v2_page
    _route_health_snapshots(
        page,
        pce_stats=_pce_stats(),
        pipeline=_pipeline(),
    )
    _goto(page, base_url, HOME)
    labels = _health_labels(page)

    pce_lamp = page.locator('[data-cov="HM-02"] details.lamp').nth(1)
    assert pce_lamp.get_attribute("data-tone") == "ok"
    pce_lamp.locator("summary").click()
    reasons = pce_lamp.locator(".lamp-why").inner_text()
    assert "SaaS" in reasons
    assert "noop" in reasons

    _goto(page, base_url, PCE)

    system = page.locator('section[data-cov="OV-01"]')
    assert "SaaS" in system.text_content()
    assert "noop" in system.text_content()
    provider = system.locator('a[href="https://status.illumio.com/posts/dashboard"]')
    assert provider.text_content() == labels["provider"]
    assert provider.get_attribute("href") == "https://status.illumio.com/posts/dashboard"
    assert provider.get_attribute("target") == "_blank"
    assert provider.get_attribute("rel") == "noopener noreferrer"

    _goto(page, base_url, SIEM)
    pipeline_text = page.locator('section[data-cov="OV-10"]').text_content()
    assert "events" in pipeline_text and "ok" in pipeline_text
    assert "traffic" in pipeline_text and "ok" in pipeline_text


@pytest.mark.parametrize(
    ("category", "expected_tone"),
    [("degraded", "warn"), ("critical", "crit")],
)
def test_on_prem_health_body_category_and_probe_chain_render_consistently(
    v2_page, category, expected_tone,
):
    page, base_url = v2_page
    _route_health_snapshots(
        page,
        pce_stats=_pce_stats(
            health_status="error",
            health_category=category,
            failures=1,
            last_error_status="200",
        ),
        pipeline=_pipeline(),
        deployment_type="on_prem",
        health_probe="noop+health+node_available",
    )
    _goto(page, base_url, HOME)
    labels = _health_labels(page)
    expected_reason = labels[category]
    expected_probe = "/noop + /health + /node_available"

    pce_lamp = page.locator('[data-cov="HM-02"] details.lamp').nth(1)
    assert pce_lamp.get_attribute("data-tone") == expected_tone
    pce_lamp.locator("summary").click()
    reasons = pce_lamp.locator(".lamp-why").inner_text()
    assert expected_reason in reasons
    assert expected_probe in reasons
    assert "HTTP 200" not in reasons

    _goto(page, base_url, PCE)

    system = page.locator('section[data-cov="OV-01"]')
    system_text = system.text_content()
    assert system.get_attribute("data-tone") == expected_tone
    assert expected_reason in system_text
    assert expected_probe in system_text
    assert "HTTP 200" not in system_text


def test_custom_query_create_appears_edit_delete_round_trip(v2_page):
    page, base_url = v2_page
    _goto(page, base_url, TRAFFIC)
    labels = _labels(page)
    query_name = "e2e-overview-query"

    panel = page.locator('section[data-cov="OV-04"]')
    assert panel.locator("li").filter(has_text=query_name).count() == 0

    # Create: real click on the header action, real form fill, real Save click.
    panel.get_by_role("button", name=labels["add"], exact=True).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    drawer.locator('input[data-field="name"]').fill(query_name)
    drawer.locator(".drawer-f button.btn.primary").click()
    page.wait_for_selector("aside.drawer", state="detached")

    row = panel.locator("li").filter(has_text=query_name)
    assert row.count() == 1

    # Reload — proves the create really reached the backend (POST
    # /api/dashboard/queries), not just a locally-mutated copy the way the
    # frozen mockup this area was ported from behaved.
    page.reload()
    page.wait_for_selector('body[data-booted="true"]')
    panel = page.locator('section[data-cov="OV-04"]')
    row = panel.locator("li").filter(has_text=query_name)
    assert row.count() == 1

    # Edit-open shows the value the backend actually stored.
    row.get_by_role("button", name=labels["edit"], exact=True).click()
    edit_drawer = page.locator("aside.drawer")
    edit_drawer.wait_for(state="visible")
    assert edit_drawer.locator('input[data-field="name"]').input_value() == query_name

    # Delete, through the real confirm-modal flow (drawer's own danger
    # button -> modal.confirm -> DELETE /api/dashboard/queries/<idx>).
    edit_drawer.locator(".drawer-f button.btn.danger").click()
    modal = page.locator(".modal")
    modal.wait_for(state="visible")
    modal.get_by_role("button", name=labels["confirm"], exact=True).click()
    page.wait_for_selector("aside.drawer", state="detached")
    page.wait_for_selector(".modal", state="detached")

    panel = page.locator('section[data-cov="OV-04"]')
    assert panel.locator("li").filter(has_text=query_name).count() == 0

    # Reload again — proves the delete really reached the backend too.
    page.reload()
    page.wait_for_selector('body[data-booted="true"]')
    panel = page.locator('section[data-cov="OV-04"]')
    assert panel.locator("li").filter(has_text=query_name).count() == 0


def test_legacy_scalar_query_edit_preserves_filters_on_save(v2_context, temp_config_file):
    """Review finding (Important 1): a query saved before Phase 4b
    (dashboard.py:548-558's `else` branch — src_label/dst_label/src_ip_in/
    dst_ip_in singular/scalar keys, not the post-Phase-4b
    src_labels/dst_labels/... plural whitelist) had its filters silently
    dropped by the FIRST Save through this drawer, even a Save that only
    renamed the query — buildSavePayload() forwarded none of the legacy
    keys, so an empty `filters` dict reached the backend.

    This does not use the v2_page fixture: it needs to seed
    settings.dashboard_queries with a legacy-shaped entry BEFORE the server
    starts, which v2_page (already logged in, already serving) has no hook
    for.
    """
    app, cm = build_v2_app(temp_config_file)
    with cm.write_lock:
        cm.load()
        cm.config.setdefault("settings", {})["dashboard_queries"] = [{
            "name": "legacy-e2e-query",
            "rank_by": "count",
            "pd": 3,
            "port": None, "proto": None, "ex_port": None,
            "src_label": "role=web",
            "dst_label": "role=db",
            "src_ip_in": "10.0.0.0/8",
            "dst_ip_in": None,
            "ex_src_label": None, "ex_dst_label": None,
            "ex_src_ip": None, "ex_dst_ip": None,
        }]
        cm.save()

    server = _LiveServer(app)
    server.start()
    try:
        base_url = server.base_url
        v2_login(v2_context, base_url)
        labels = None
        page = v2_context.new_page()
        page.set_default_timeout(10_000)
        try:
            page.goto(base_url + "/" + TRAFFIC)
            page.wait_for_selector('body[data-booted="true"]')

            panel = page.locator('section[data-cov="OV-04"]')
            row = panel.locator("li").filter(has_text="legacy-e2e-query")
            assert row.count() == 1

            labels = _labels(page)
            row.get_by_role("button", name=labels["edit"], exact=True).click()
            drawer = page.locator("aside.drawer")
            drawer.wait_for(state="visible")

            # Rename only — every other field left exactly as loaded. The
            # legacy fields render as plain inputs (no i18n key of their own
            # before this fix's fieldLabel() extension, which is itself
            # covered by the i18n.missing() check further down).
            drawer.locator('input[data-field="name"]').fill("legacy-e2e-query-renamed")
            drawer.locator(".drawer-f button.btn.primary").click()
            page.wait_for_selector("aside.drawer", state="detached")

            # i18n.missing() must stay empty even after opening a legacy
            # query's edit drawer (brief S4) — fieldLabel()'s raw t(key)
            # fallback for an untranslated field name would have added
            # "src_label" etc. to it.
            missing = page.evaluate(
                "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
                "return i18n.missing(); }"
            )
            assert missing == [], missing
        finally:
            page.close()

        # Re-read from the real backend (not the DOM) — the regression is
        # server-side data loss, so the proof has to be server-side too.
        page2 = v2_context.new_page()
        page2.set_default_timeout(10_000)
        try:
            page2.goto(base_url + "/" + TRAFFIC)
            page2.wait_for_selector('body[data-booted="true"]')
            queries = page2.evaluate(
                "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
                "return api.load('dashboard_queries'); }"
            )
        finally:
            page2.close()
    finally:
        server.stop()

    match = [q for q in queries if q.get("name") == "legacy-e2e-query-renamed"]
    assert len(match) == 1, queries
    saved = match[0]
    # The legacy singular keys migrate to their plural whitelisted name (the
    # backend's dict-branch always writes back in that shape once `filters`
    # is a dict at all) — the point is that the VALUES survive a save that
    # only touched the name, in whichever shape, not that the old key names
    # persist unchanged.
    assert saved.get("src_labels") == ["role=web"], saved
    assert saved.get("dst_labels") == ["role=db"], saved
    assert saved.get("src_ip_in") == "10.0.0.0/8", saved


def test_goto_link_navigates_to_another_area(v2_page):
    """HM-01's "see all" leaves the home page for the alert list (v3.1).

    3B put a "Go to <route>" button in every card header; §5.2 took those out,
    so the list's own secondary link is the affordance being asserted.
    """
    page, base_url = v2_page
    _goto(page, base_url, HOME)
    assert page.locator('section[data-cov="HM-01"]').count() == 1, "the list must render"
    page.locator('section[data-cov="HM-01"] a.seeall').click()
    page.wait_for_selector('[data-route="#/investigate/alerts"]')
    assert page.evaluate("location.hash") == "#/investigate/alerts"


def test_teardown_closes_drawer_on_navigate_away(v2_page):
    """S2 acceptance: leaving #/home must not strand an open drawer.
    Fails against a mountOverview() with no router.onChange teardown (the
    drawer would still be in the DOM after the hash change below)."""
    page, base_url = v2_page
    _goto(page, base_url, TRAFFIC)
    labels = _labels(page)

    page.locator('section[data-cov="OV-04"]').get_by_role(
        "button", name=labels["add"], exact=True
    ).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    assert drawer.count() == 1

    page.evaluate("location.hash = '#/reports'")
    page.wait_for_selector('[data-route="#/reports"]')

    assert page.locator("aside.drawer").count() == 0


def test_home_palette_commands_drop_on_navigate_away(v2_page):
    """S2: the two route-scoped palette commands mountHome registers before
    its first await (home:alerts, home:traffic) must be gone after navigating
    away — even when the page's own loads failed (home tolerates a broken
    snapshot and still paints, so this is checked under a 500 on /api/status)."""
    page, base_url = v2_page

    def bad_payload(route):
        route.fulfill(status=500, content_type="application/json", body='{"ok": false}')
    page.route("**/api/status", bad_payload)
    try:
        _goto(page, base_url, HOME)
        page.evaluate("location.hash = '#/reports'")
        page.wait_for_selector('[data-route="#/reports"]')
        ids = page.evaluate(
            "async () => { const { palette } = await import('/static/js/v2/components/palette.mjs'); "
            "return palette.list().map(c => c.id); }"
        )
    finally:
        page.unroute("**/api/status", bad_payload)
    assert [i for i in ids if i.startswith("ov:") or i.startswith("home:")] == [], ids

def test_home_headline_counts_open_alerts_and_alert_rows_deep_link(v2_page, _isolate_alert_store):
    """HM-00/HM-01: the headline number is /api/alerts counts.new and each row
    links to that alert's page (spec §2; v3.1 replaced the inbox route)."""
    from src.alerts.store import AlertStore
    st = AlertStore(_isolate_alert_store)
    a = st.insert(fired_at="2026-09-04T01:00:00Z", type="traffic", rule_id="t1", rule_name="SSH in",
                  severity="warning", summary="SSH in · 24", criteria="port 22", payload={}, dispatch=[])
    st.insert(fired_at="2026-09-04T01:01:00Z", type="event", rule_id="18", rule_name="Login failed",
              severity="critical", summary="Login failed · x", criteria="", payload={}, dispatch=[])
    st.close()
    page, base_url = v2_page
    page.reload()
    _goto(page, base_url, HOME)
    page.wait_for_selector('[data-cov="HM-01"] a.lrow')
    assert "2" in page.locator('[data-cov="HM-00"]').text_content()
    rows = page.locator('[data-cov="HM-01"] a.lrow')
    assert rows.count() == 2
    # critical sorts first
    assert "Login failed" in rows.nth(0).text_content()
    assert rows.nth(1).get_attribute("href") == "#/investigate/alerts?id=%d" % a


def test_home_survives_alerts_api_failure(v2_page):
    """HM-01 shows the error inline; the rest of the page still renders."""
    page, base_url = v2_page
    page.route("**/api/alerts?*", lambda r: r.fulfill(status=500, content_type="application/json", body='{"ok": false, "error": "boom"}'))
    _goto(page, base_url, HOME)
    page.wait_for_selector('[data-cov="HM-02"]')
    for cov in ("HM-01", "HM-02", "HM-03", "HM-05"):
        assert page.locator('[data-cov="%s"]' % cov).count() == 1, cov
    assert page.locator('[data-cov="HM-01"]').get_attribute("data-tone") == "warn"
    page.unroute("**/api/alerts?*")


def test_the_home_dashboard_strip_reads_four_instruments_and_each_one_leads_somewhere(v2_page):
    """HM-06: the four KPI cells the operator asked to have back on the home
    page — VEN health, flagged flows, the ingest pipeline, alerts fired in 24h.

    Three things are asserted, and the third is the one worth stating: a cell
    must be a LINK. A dashboard number with no way through to the page that
    explains it is where an operator's investigation stops, and this page's
    whole job is to start one. The hrefs are checked against the four areas
    that own those figures rather than against a hard-coded list of strings,
    so moving a route does not silently unhook a card.

    No stub: the harness's PCE is a closed port and the cache is off, so this
    exercises the branch where the panels come back `no_cache`/`unknown` —
    which is exactly the branch that must not print a zero as if it were a
    measurement. The values are therefore asserted to be non-empty, not to be
    any particular number.
    """
    page, base_url = v2_page
    _goto(page, base_url, HOME)
    page.wait_for_selector('.home .kpirow[data-cov="HM-06"]', timeout=30000)

    cells = page.locator('.kpirow[data-cov="HM-06"] .kpicell')
    assert cells.count() == 4, cells.count()

    for i in range(4):
        cell = cells.nth(i)
        label = cell.locator(".k").inner_text().strip()
        value = cell.locator(".v").inner_text().strip()
        assert label, f"cell {i} has no label"
        assert value, f"cell {i} ({label}) has no value"

    hrefs = page.eval_on_selector_all(
        '.kpirow[data-cov="HM-06"] a.kpicell', "els => els.map(e => e.getAttribute('href'))"
    )
    assert len(hrefs) == 4, f"a KPI cell is not a link: {hrefs}"
    assert hrefs == ["#/system/pce", "#/investigate/traffic",
                     "#/system/cache", "#/investigate/alerts"], hrefs


def test_a_failing_rule_schedule_is_marked_on_the_home_card(v2_page):
    """HM-03: a schedule whose last run errored is visibly not fine.

    3B carried `tone: s.last_result === "error" ? "warn" : "info"` on the rule
    START row; Phase 3E rewrote the card as a sideCard and dropped the tone
    with it, so a failed schedule read exactly like a healthy one. The
    schedules page still has the full status — but if the home page is where
    an operator looks first, a row that cannot say "this one failed" is worse
    than no row, because it answers the question wrongly rather than not at
    all.

    Two rows are served and both are asserted, so a change that tones every
    row the same way fails as loudly as one that tones none.
    """
    page, base_url = v2_page
    schedules = [
        {"id": 1, "name": "nightly-block", "start": "08:00", "action": "block",
         "live_enabled": True, "last_result": "error"},
        {"id": 2, "name": "morning-allow", "start": "09:00", "action": "allow",
         "live_enabled": True, "last_result": "ok"},
    ]
    page.route("**/api/rule_scheduler/schedules",
               lambda r: r.fulfill(status=200, content_type="application/json",
                                   body=json.dumps(schedules)))
    _goto(page, base_url, HOME)
    page.wait_for_selector('[data-cov="HM-03"] .sched li', timeout=30000)

    tones = page.eval_on_selector_all(
        '[data-cov="HM-03"] .sched li',
        "els => els.map(e => [e.textContent.trim(), e.getAttribute('data-tone')])",
    )
    failing = [t for txt, t in tones if "nightly-block" in txt]
    healthy = [t for txt, t in tones if "morning-allow" in txt]
    assert failing == ["warn"], tones
    assert healthy == ["info"], tones


def test_the_home_ruleset_count_asks_for_one_row_not_the_whole_list(v2_page):
    """HM-05 needs `total`, not the rulesets — so it must say so on the wire.

    The call passed `{page: 1, size: 1}`, but GET_MAP's `rs_rulesets` was a
    fixed path string, so both were dropped and the home page pulled the
    entire ruleset list (each item costing a per-ruleset schedule lookup on
    the server) to read one number off it. The parameters were not wrong —
    they were not connected.
    """
    page, base_url = v2_page
    with page.expect_request(
        lambda r: "/api/rule_scheduler/rulesets" in r.url
    ) as info:
        _goto(page, base_url, HOME)
    url = info.value.url
    assert "size=1" in url, url
    assert "page=1" in url, url
