"""Phase 2A Task 2 — in-process Playwright e2e for the v2 core layer.

Drives a real (headless) Chromium against a real Flask app + real backend
(no snapshots, no mocks) through tests.v2_e2e_utils's shared harness — see
that module's docstring for why this harness had to be built and why it
lives there rather than inline here.

Covers exactly the brief's Step 2 acceptance list:
  - #/overview shows the health rail; #/reports does not (XC-01 scope, T2's
    syncRail wiring in app.mjs).
  - hash routing switches the mounted area without a page reload.
  - theme persists across a reload (theme.mjs + app.mjs's initDisplay()).
  - api.load("status") reaches the DOM with a real daemon field (the running
    app's own version string, not a fixture literal).
  - the CSRF-aware POST/GET/DELETE round trip against a real endpoint
    (/api/dashboard/queries): create -> list shows it -> delete -> list
    doesn't.
  - i18n.missing() runs without throwing (the bridge is allowed a non-empty
    backlog at this stage — keys land per area in Tasks 4-9).
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from src import __version__  # noqa: E402

# Registers v2_page and the fixture chain it depends on (v2_context, v2_server,
# v2_app, the session-scoped browser) from the shared harness. A plain
# `from tests.v2_e2e_utils import v2_page` is not enough — pytest only
# resolves a fixture's *own* dependencies via conftest.py or this module's
# plugin registration, not via a second module's globals. Tasks 3-10 should
# do the same in their own test_v2_<area>_e2e.py.
pytest_plugins = ["tests.v2_e2e_utils"]


def _goto_overview(page, base_url):
    page.goto(base_url + "/v2#/overview")
    page.wait_for_selector('body[data-booted="true"]')


def test_v2_boots_with_no_console_errors(v2_page):
    page, base_url = v2_page
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

    _goto_overview(page, base_url)

    assert errors == []


def test_health_rail_only_on_overview(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    # #/overview: health rail present, carrying a REAL daemon field.
    rail = page.locator("#health-rail")
    assert rail.count() == 1
    rail_text = rail.inner_text()
    assert __version__ in rail_text

    # Client-side hash switch (no reload) to #/reports: rail must detach.
    page.evaluate("location.hash = '#/reports'")
    page.wait_for_selector("code:text-is('#/reports')")
    assert page.locator("#health-rail").count() == 0

    # And switching back re-attaches it (detach-not-destroy semantics).
    page.evaluate("location.hash = '#/overview'")
    page.wait_for_selector("#health-rail")
    assert __version__ in page.locator("#health-rail").inner_text()


def test_theme_persists_across_reload(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    assert page.evaluate("document.documentElement.dataset.theme") == "dark"

    page.evaluate(
        "async () => { const { theme } = await import('/static/js/v2/core/theme.mjs'); "
        "theme.set('light'); }"
    )
    assert page.evaluate("document.documentElement.dataset.theme") == "light"

    page.reload()
    page.wait_for_selector('body[data-booted="true"]')
    assert page.evaluate("document.documentElement.dataset.theme") == "light"


def test_dashboard_query_post_get_delete_round_trip(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    before = page.evaluate(
        "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.load('dashboard_queries'); }"
    )
    assert all(q.get("name") != "e2e-core-query" for q in before)

    created = page.evaluate(
        "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.post('/api/dashboard/queries', "
        "{name: 'e2e-core-query', rank_by: 'bandwidth', pd: 3, mins: 1440}); }"
    )
    assert created.get("ok") is True

    after_create = page.evaluate(
        "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "api.invalidate('dashboard_queries'); return api.load('dashboard_queries'); }"
    )
    names_after_create = [q.get("name") for q in after_create]
    assert "e2e-core-query" in names_after_create
    idx = names_after_create.index("e2e-core-query")

    deleted = page.evaluate(
        "async (idx) => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return api.del('/api/dashboard/queries/' + idx); }",
        idx,
    )
    assert deleted.get("ok") is True

    after_delete = page.evaluate(
        "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "api.invalidate('dashboard_queries'); return api.load('dashboard_queries'); }"
    )
    assert all(q.get("name") != "e2e-core-query" for q in after_delete)


def test_i18n_missing_mechanism_does_not_throw(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    missing = page.evaluate(
        "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return i18n.missing(); }"
    )
    # T2 only builds the bridge — keys land per area in Tasks 4-9, so a
    # non-empty backlog is expected. The mechanism must simply not throw and
    # must produce a real array.
    assert isinstance(missing, list)
