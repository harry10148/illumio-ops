"""Phase 2A Task 2 — in-process Playwright e2e for the v2 core layer.

Drives a real (headless) Chromium against a real Flask app + real backend
(no snapshots, no mocks) through tests.v2_e2e_utils's shared harness — see
that module's docstring for why this harness had to be built and why it
lives there rather than inline here.

Covers exactly the brief's Step 2 acceptance list:
  - #/overview shows the health rail; #/reports does not (XC-01 scope, T2's
    syncRail wiring in app.mjs).
  - hash routing switches the mounted area without a page reload.
  - theme AND density persist across a reload (theme.mjs + app.mjs's
    initDisplay()).
  - api.load("status") reaches the DOM with a real daemon field (the running
    app's own version string, not a fixture literal).
  - the CSRF-aware POST/GET/DELETE round trip against a real endpoint
    (/api/dashboard/queries): create -> list shows it -> delete -> list
    doesn't.
  - i18n's real backend contract: a real catalogue key (one of the ~1400
    gui_/sched_/status_/error_/pd_ keys already in src/i18n_en.json /
    src/i18n_zh_TW.json, served through GET /api/ui_translations) actually
    resolves through t(), and a known-absent key lands in i18n.missing().
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

    # The placeholder body must degrade through tf()'s fallback, not leak
    # the raw, unresolved i18n key onto the screen (review finding: tf() had
    # no fallback path, so every placeholder area rendered the literal
    # string "gui_shell_wip_body" until this task's key lands in Tasks 4-9).
    wip_text = page.locator("section.wip").inner_text()
    assert "gui_shell_wip_body" not in wip_text
    assert "#/reports" in wip_text

    # And switching back re-attaches it (detach-not-destroy semantics).
    page.evaluate("location.hash = '#/overview'")
    page.wait_for_selector("#health-rail")
    assert __version__ in page.locator("#health-rail").inner_text()


def test_theme_and_density_persist_across_reload(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("document.documentElement.dataset.density") == "cozy"

    page.evaluate(
        "async () => { const { theme, density } = await import('/static/js/v2/core/theme.mjs'); "
        "theme.set('light'); density.set('compact'); }"
    )
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("document.documentElement.dataset.density") == "compact"

    page.reload()
    page.wait_for_selector('body[data-booted="true"]')
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("document.documentElement.dataset.density") == "compact"


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


def test_i18n_resolves_real_catalogue_key_and_tracks_missing_keys(v2_page):
    """The one thing this task actually changed in i18n: t()/tf() now read
    from GET /api/ui_translations instead of a captured snapshot. Assert
    that against the real endpoint, not just that the plumbing doesn't
    throw — a 404'd/reshaped/missing route must fail this test.
    """
    page, base_url = v2_page
    _goto_overview(page, base_url)

    result = page.evaluate(
        "async () => { const { t, i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { "
        "resolved: t('gui_err_unauthorized'), "
        "fallback: t('gui_this_key_does_not_exist_anywhere', 'fallback-text'), "
        "missing: i18n.missing() "
        "}; }"
    )
    # gui_err_unauthorized is the live 401 error string (src/gui/__init__.py's
    # security_check hook uses it directly) — a real key already in
    # src/i18n_en.json, served through _ui_translation_dict's gui_ whitelist.
    # Asserting the exact product text (not just "is truthy") catches a
    # reshaped response (e.g. {ok, data: {...}} instead of a flat map) that a
    # weaker assertion would miss.
    assert result["resolved"] == "Unauthorized."
    # A key that will never exist must degrade to its fallback...
    assert result["fallback"] == "fallback-text"
    # ...and be recorded as backlog, not swallowed.
    assert "gui_this_key_does_not_exist_anywhere" in result["missing"]


def test_i18n_init_failure_is_logged_not_silent(v2_page):
    """initI18n() swallows a catalogue load failure into catalogue=null so
    the app can still boot with fallbacks — but that must be loud, not
    silent. Simulates the failure directly (no route to break) and asserts
    the console.warn this review requested actually fires.
    """
    page, base_url = v2_page
    _goto_overview(page, base_url)

    warned = page.evaluate(
        "async () => { "
        "const mod = await import('/static/js/v2/core/i18n.mjs'); "
        "const { api } = await import('/static/js/v2/core/api.mjs'); "
        # api.load() caches successes — the page's own boot already loaded
        # ui_translations once, so it must be invalidated or this call would
        # just return the cached success and never see the simulated failure.
        "api.invalidate('ui_translations'); "
        "let warned = false; "
        "const orig = console.warn; "
        "console.warn = (...args) => { warned = true; orig(...args); }; "
        "const origFetch = window.fetch; "
        "window.fetch = () => Promise.reject(new Error('simulated network failure')); "
        "try { await mod.initI18n(); } finally { "
        "window.fetch = origFetch; console.warn = orig; "
        "} "
        "return warned; "
        "}"
    )
    assert warned is True
