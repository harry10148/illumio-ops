"""Phase 2A Task 4 — in-process Playwright e2e for the v2 overview area.

Drives a real (headless) Chromium against a real Flask app + real backend
(no snapshots, no mocks) through tests.v2_e2e_utils's shared harness — see
that module's docstring for the harness itself.

Covers:
  - every OV-01..OV-16 coverage anchor (design/v2/coverage.yaml's overview
    subset) is present in the DOM after window.__openAllForAudit() on
    #/overview.
  - the OV-04 custom-query CRUD round trip through the REAL
    POST/DELETE /api/dashboard/queries endpoints, driven by real UI clicks
    (button clicks + form fill, not an api.post()/api.del() bypass): create
    a query -> it appears in the list -> a page reload proves the create
    reached the backend -> edit-open shows the saved value -> delete
    (through the real confirm-modal flow) -> it disappears -> a second
    reload proves the delete reached the backend too.
  - the posture-detail drawer (OV-02) opens and Escape closes it.
  - a "go to" header button (present on every read-only card) navigates to
    another area — URL hash and mounted content both change.
  - S2 teardown: navigating away from #/overview closes a drawer this area
    left open. drawer.mjs/modal.mjs have no per-area scoping of their own
    (closeAll() is global), so this is the only externally observable proof
    that mountOverview()'s router.onChange teardown actually ran.

Not covered here: OV-05's chart.rankedBars() ResizeObserver teardown. This
test environment's PCE is unconfigured/unreachable, and dashboard.py's
api_dashboard_top10 lets query_flows() run its real (slow, ~6s here) DNS
failure before returning {ok:false}, so a created query's top10 refresh
resolves with an empty result and OV-05 never actually renders a chart to
observe teardown of (see cardTop10()'s `if (!top.ok || !data.length)` empty
branch in areas/overview.mjs). The chart handle IS captured and destroyed
(buildBoard's repaint-time cleanup and mountOverview's teardown callback,
both in areas/overview.mjs) — verified by code reading, not by this suite.
"""
from __future__ import annotations

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


def _goto_overview(page, base_url):
    page.goto(base_url + "/v2#/overview")
    page.wait_for_selector('body[data-booted="true"]')


def _labels(page):
    """Resolve the exact catalogue strings the test needs to click on —
    language-independent (asks the real ui_translations catalogue via t(),
    never hardcodes English/Chinese text)."""
    return page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { "
        "add: t('gui_add_query_widget'), "
        "edit: t('gui_edit_query_widget'), "
        "confirm: t('gui_confirm'), "
        "posture: t('gui_ov_posture_score_label') "
        "}; }"
    )


def test_overview_coverage_anchors_present(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    page.evaluate("window.__openAllForAudit ? window.__openAllForAudit() : null")
    page.wait_for_timeout(200)

    found = set(page.eval_on_selector_all("[data-cov]", "els => els.map(e => e.dataset.cov)"))
    expected = {"OV-%02d" % i for i in range(1, 17)}
    missing = expected - found
    assert missing == set(), f"missing coverage anchors: {sorted(missing)}"


def test_custom_query_create_appears_edit_delete_round_trip(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)
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
            page.goto(base_url + "/v2#/overview")
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
            page2.goto(base_url + "/v2#/overview")
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


def test_posture_drawer_opens_and_closes(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)
    labels = _labels(page)

    # A fresh test config has no posture score yet (dashboard.py's
    # _overview_posture requires real analysis history), so OV-02's "Detail"
    # header button does not render — buildBoard()'s openPostureDetail()
    # opener is still registered unconditionally though (drawer.registerAudit
    # "ov-posture-detail" in mountOverview), the same real code path a click
    # would use once posture data exists. Reached here the same way the
    # coverage gate reaches it.
    page.evaluate("window.__openAllForAudit()")
    posture_drawer = page.locator(f'aside.drawer[aria-label="{labels["posture"]}"]')
    posture_drawer.wait_for(state="visible")
    assert posture_drawer.count() == 1

    # __openAllForAudit() may have opened more than one dialog (the "add
    # query" opener is also registered); dom.mjs's dismissible() stack means
    # Escape closes the topmost first, not necessarily the posture one. Press
    # until this SPECIFIC drawer is confirmed gone rather than assume order.
    for _ in range(6):
        if posture_drawer.count() == 0:
            break
        page.keyboard.press("Escape")
        page.wait_for_timeout(50)
    assert posture_drawer.count() == 0


def test_goto_link_navigates_to_another_area(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    # OV-01's header carries exactly one "go to" button (withGoto, no
    # withAction on that card), pointing at #/system/pce.
    page.locator('section[data-cov="OV-01"] .hact button.goto').click()
    page.wait_for_selector("code:text-is('#/system/pce')")
    assert page.evaluate("location.hash") == "#/system/pce"


def test_teardown_closes_drawer_on_navigate_away(v2_page):
    """S2 acceptance: leaving #/overview must not strand an open drawer.
    Fails against a mountOverview() with no router.onChange teardown (the
    drawer would still be in the DOM after the hash change below)."""
    page, base_url = v2_page
    _goto_overview(page, base_url)
    labels = _labels(page)

    page.locator('section[data-cov="OV-04"]').get_by_role(
        "button", name=labels["add"], exact=True
    ).click()
    drawer = page.locator("aside.drawer")
    drawer.wait_for(state="visible")
    assert drawer.count() == 1

    page.evaluate("location.hash = '#/reports'")
    page.wait_for_selector("code:text-is('#/reports')")

    assert page.locator("aside.drawer").count() == 0
