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
    page.goto(base_url + "/#/overview")
    page.wait_for_selector('body[data-booted="true"]')


def test_v2_boots_with_no_console_errors(v2_page):
    page, base_url = v2_page
    errors = []  # (text, location_url) pairs
    page.on("pageerror", lambda exc: errors.append((str(exc), "")))
    page.on(
        "console",
        lambda msg: errors.append((msg.text, (msg.location or {}).get("url", "")))
        if msg.type == "error" else None,
    )

    _goto_overview(page, base_url)

    # Task 4: #/overview now mounts the real board (areas/overview.mjs),
    # which loads 14 live endpoints. One of them, GET /api/events/viewer,
    # genuinely reaches the PCE and 502s under this fixture's config
    # (build_v2_app points api.url at a closed local port — see
    # tests/v2_e2e_utils.py's _closed_local_port docstring, Task 5b — so the
    # connection is refused instantly and always) — an ordinary operational
    # condition, not a bug; the area is
    # specifically built to survive exactly this and still render the other
    # 15 cards (areas/overview.mjs's loadOne()/loadAll()). The unavoidable
    # byproduct is exactly two known console entries neither this fixture
    # nor overview.mjs can suppress:
    #   1. The browser's OWN network-failure log. Its .text is a generic
    #      "Failed to load resource: ... 502 (BAD GATEWAY)" with NO endpoint
    #      named at all (verified directly) — the failed request's URL only
    #      shows up in the console message's .location.url, not its .text.
    #   2. overview.mjs's own loadOne() diagnostic console.error(), whose
    #      .text DOES name the endpoint ("[overview] events_viewer failed to
    #      load ... /api/events/viewer ..."), but whose .location points at
    #      the overview.mjs source line that logged it, not at the failed
    #      resource.
    #
    # Review finding (Important 2): an earlier version of this filter
    # excluded "events/viewer" OR "502" independently, freestanding, in
    # .text alone — by De Morgan that tolerates ANY error containing "502"
    # regardless of endpoint, and ANY error mentioning "events/viewer"
    # regardless of status. A same-message co-occurrence check (both
    # substrings in .text) was the suggested tightening, but .text alone
    # can't express it for entry 1 (no endpoint in its text at all) — hence
    # checking .location.url for that one and .text for the other, matching
    # exactly the two known messages and nothing broader.
    def is_expected(text, location_url):
        if "events/viewer" in location_url and "502" in text:
            return True
        return "events/viewer" in text and "502" in text

    unexpected = [t for t, u in errors if not is_expected(t, u)]
    assert unexpected == [], errors


def test_health_rail_only_on_overview(v2_page):
    """XC-01's route scoping, against the REAL five-light healthbar.

    Task 11 replaced app.mjs's Task-2 stand-in rail (a #health-rail div
    holding two /api/status fields) with components/healthbar.mjs, so the
    selector moved from `#health-rail` to the component's own XC-01 anchor
    and the "real daemon field reaches the DOM" assertion moved to the user
    menu, which applyStatus() fills from the same /api/status payload. The
    attach/detach behaviour under test is unchanged, and so is the number of
    things asserted — see task-11-report.md.
    """
    page, base_url = v2_page
    _goto_overview(page, base_url)

    # #/overview: the real rail is present, with all five lights.
    rail = page.locator('.rail-host [data-cov="XC-01"]')
    assert rail.count() == 1
    assert rail.locator(".rail-slot").count() == 5

    # ...and the same /api/status snapshot that fed it reached the user menu,
    # carrying a REAL daemon field (the running app's own version string, not
    # a fixture literal). This is where the Task-2 rail's __version__ check
    # lives now. The menu's <dl> only exists while the popover is open, so
    # open it the way an operator would.
    page.click(".userchip")
    assert __version__ in page.locator(".usermenu-pop dd").nth(1).inner_text()
    page.keyboard.press("Escape")

    # Mark the live rail node so the re-attach assertion below can prove it is
    # the SAME node coming back, not a rebuilt one.
    page.evaluate(
        "document.querySelector('.rail-host [data-cov=\"XC-01\"]')"
        ".setAttribute('data-e2e-marker', 'rail-1')"
    )

    # Client-side hash switch (no reload) to #/system: rail must detach.
    # (#/system is the last route still on mountPlaceholder — it is an area
    # landing path with no page of its own, by design.)
    page.evaluate("location.hash = '#/system'")
    page.wait_for_selector("code:text-is('#/system')")
    assert page.locator('.rail-host [data-cov="XC-01"]').count() == 0

    # The placeholder body must degrade through tf()'s fallback, not leak
    # the raw, unresolved i18n key onto the screen (review finding: tf() had
    # no fallback path, so every placeholder area rendered the literal
    # string "gui_shell_wip_body" until this task's key lands in Tasks 4-9).
    wip_text = page.locator("section.wip").inner_text()
    assert "gui_shell_wip_body" not in wip_text
    assert "#/system" in wip_text

    # And switching back re-attaches THE SAME node (detach-not-destroy
    # semantics): healthbar.render() runs once at boot off one pair of
    # snapshot loads, so a marker that survived the round trip is the proof
    # the rail is moved rather than rebuilt (a rebuild would also refetch).
    page.evaluate("location.hash = '#/overview'")
    page.wait_for_selector('.rail-host [data-cov="XC-01"]')
    assert page.locator('.rail-host [data-cov="XC-01"]').get_attribute("data-e2e-marker") == "rail-1"
    assert page.locator('.rail-host [data-cov="XC-01"] .rail-slot').count() == 5


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


# ══════════════════════════ Task 12d — leaks the core layer used to allow ════

def test_detaching_the_health_rail_releases_its_popover(v2_page):
    """F5: syncRail detaches the rail without calling its destroy().

    An open light popover holds two capture-phase document listeners and an
    entry on core/dom.mjs's shared dismiss stack (dismissible()). Detaching
    the rail hides the popover but keeps both: the stale entry stays TOPMOST
    of the stack, so the next Escape anywhere in the app is eaten by its
    stopImmediatePropagation() before any live surface can see it.

    RED against the pre-fix app.mjs: the popover is still open when the rail
    comes back (aria-expanded="true", .rail-pop still in it), and the Escape
    probe below never fires."""
    page, base_url = v2_page
    _goto_overview(page, base_url)

    cell = page.locator('.rail-host [data-cov="XC-01"] .rail-cell').first
    cell.click()
    assert cell.get_attribute("aria-expanded") == "true"
    assert page.locator(".rail-host .rail-pop").count() == 1

    # Away and back: the rail is detached, then re-attached (the same node —
    # test_health_rail_only_on_overview proves the identity).
    page.evaluate("location.hash = '#/reports'")
    page.wait_for_selector("code:text-is('#/reports')")
    page.evaluate("location.hash = '#/overview'")
    page.wait_for_selector('.rail-host [data-cov="XC-01"]')

    assert page.locator('.rail-host .rail-cell[aria-expanded="true"]').count() == 0
    assert page.locator(".rail-host .rail-pop").count() == 0

    # ...and the dismiss stack is clear: a listener registered NOW, i.e. after
    # any stale one, still sees Escape. Same node (document), same capture
    # phase, later registration — exactly what stopImmediatePropagation()
    # would block.
    page.evaluate(
        "() => { window.__escSeen = 0; document.addEventListener('keydown', "
        "e => { if (e.key === 'Escape') window.__escSeen++; }, true); }"
    )
    page.keyboard.press("Escape")
    assert page.evaluate("() => window.__escSeen") == 1


def test_api_does_not_throw_on_a_transport_failure(v2_page):
    """F7: api.mjs's "post/put/del never throw" contract has to hold for the
    transport layer too, not just for HTTP statuses.

    A connection dropped mid-flight (or DNS failure, or an aborted request)
    made fetch() itself reject, and rawRequest() let that reject straight
    through — so every caller written to the documented contract (nobody but
    login.mjs wraps these in try/catch) got an unhandled rejection instead of
    a result, and any progress state it was holding was never cleared.

    RED against the pre-fix api.mjs: post() rejects, so `threw` is True."""
    page, base_url = v2_page
    _goto_overview(page, base_url)

    def kill(route):
        route.abort("connectionfailed")

    page.route("**/api/dashboard/queries", kill)
    try:
        result = page.evaluate(
            "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
            "const out = {}; "
            "try { out.post = await api.post('/api/dashboard/queries', {}); } "
            "catch (e) { out.threw = String(e); } "
            # load()/get() keep their own contract (throw, so the error-card
            # retry path still works) — a transport failure must land there
            # too, not escape as some other shape.
            "try { await api.get('/api/dashboard/queries'); out.getThrew = false; } "
            "catch (e) { out.getThrew = true; } "
            "return out; }"
        )
    finally:
        page.unroute("**/api/dashboard/queries", kill)

    assert "threw" not in result, result
    assert result["post"]["ok"] is False, result
    assert result["post"]["error"], result
    assert result["getThrew"] is True, result
