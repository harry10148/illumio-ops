"""Phase 2A Task 11 — in-process Playwright e2e for the v2 shell (chrome).

Drives a real (headless) Chromium against a real Flask app + real backend
through tests.v2_e2e_utils's shared harness — see that module's docstring for
the harness itself.

The shell is what Task 11 added: src/static/js/v2/shell.mjs, mounted by
app.mjs into src/templates/index.html's `#shell`. Before this task the
whole chrome was a bare rail host, so nothing here had any coverage at all.
It owns the four cross-cutting coverage anchors that live outside every area
(design/v2/coverage.yaml):

  XC-02  the Cmd/Ctrl+K command palette — opens on the shortcut and on the
         topbar button, filters, runs a command, closes on Escape.
  XC-13  the topbar user menu — opens, carries the real appliance identity
         from /api/status, and its two segmented controls really switch
         theme and density.
  XC-14  the six-area nav — highlights the area the URL hash names, on a
         cold load of a deep route as well as after in-page navigation.
  LG-03  sign-out — a real POST /logout that lands back on /login and
         leaves the session actually dead.

XC-01 (the health rail) is covered by tests/test_v2_core_e2e.py, which owns
the attach/detach-by-route behaviour around it.

Destructive-operation discipline: the only state-changing call in this file
is POST /logout, and it runs on the harness's throwaway per-test config with
its own browser context. Nothing here touches the PCE.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from src import __version__  # noqa: E402

# Registers v2_page and the fixture chain it depends on — see
# tests/v2_e2e_utils.py's module docstring for why both this line and the
# importorskip above (in THIS module, not just there) are required, in order.
pytest_plugins = ["tests.v2_e2e_utils"]

from tests.v2_e2e_utils import v2_login  # noqa: E402


def _boot(page, base_url, route="#/overview"):
    page.goto(base_url + "/" + route)
    page.wait_for_selector('body[data-booted="true"]')


def _labels(page):
    """The real product strings for the keys this file asserts on.

    Read from the app's own catalogue rather than hardcoded, for the same
    reason every other v2 e2e file does it: the fixture's language is a
    config value, and a hardcoded English literal would silently stop
    testing anything the day that default changes.
    """
    return page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { logout: t('gui_logout'), area: t('gui_cmd_group_area'), "
        "reports: t('gui_nav_reports'), theme: t('gui_cmd_theme') }; }"
    )


# ── XC-14 · the six-area nav ────────────────────────────────────────────────

def test_nav_marks_the_area_named_by_a_cold_deep_link(v2_page):
    """A cold load of a sub-route highlights its AREA, not just its own path.

    This is the half of XC-14 that a click-driven test cannot reach: the
    highlight has to be derived from the URL at boot (shell.mjs's
    router.onChange fires during router.start()), not set as a side effect
    of the click that navigated.
    """
    page, base_url = v2_page
    _boot(page, base_url, "#/system/siem")

    nav = page.locator('[data-cov="XC-14"]')
    assert nav.count() == 1
    current = nav.locator("a[aria-current]")
    assert current.count() == 1
    # #/system/siem is a SUB-route; the highlighted link is the area's
    # landing route, which is a different href.
    assert current.get_attribute("href") == "#/system/pce"


def test_nav_highlight_follows_in_page_navigation(v2_page):
    page, base_url = v2_page
    _boot(page, base_url)

    nav = page.locator('[data-cov="XC-14"]')
    assert nav.locator("a[aria-current]").get_attribute("href") == "#/overview"

    page.click('[data-cov="XC-14"] a[href="#/reports"]')
    page.wait_for_function(
        "() => document.querySelector('[data-cov=\"XC-14\"] a[aria-current]')"
        ".getAttribute('href') === '#/reports'"
    )
    # Exactly one link is ever current — a highlight that is added but never
    # removed would leave two.
    assert nav.locator("a[aria-current]").count() == 1


# ── XC-13 · the topbar user menu ────────────────────────────────────────────

def test_user_menu_opens_with_the_real_appliance_identity(v2_page):
    """The menu's <dl> is filled from the SAME /api/status load that feeds the
    health rail (app.mjs's mountHealth -> shell.mjs's applyStatus)."""
    page, base_url = v2_page
    _boot(page, base_url)

    assert page.locator('[data-cov="XC-13"]').count() == 1
    assert page.locator(".usermenu-pop").count() == 0
    assert page.get_attribute(".userchip", "aria-expanded") == "false"

    page.click(".userchip")
    pop = page.locator(".usermenu-pop")
    pop.wait_for(state="visible")
    assert page.get_attribute(".userchip", "aria-expanded") == "true"

    # The running app's own version string, not a fixture literal.
    assert pop.locator("dd").nth(1).inner_text() == "v" + __version__
    # The PCE target the harness configured (a closed local port — see
    # v2_e2e_utils._closed_local_port), with the scheme stripped.
    api_url = page.evaluate(
        "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return (await api.load('status')).api_url; }"
    )
    assert pop.locator("dd").nth(0).inner_text() == api_url.replace("http://", "")

    page.keyboard.press("Escape")
    page.wait_for_selector(".usermenu-pop", state="detached")
    assert page.get_attribute(".userchip", "aria-expanded") == "false"


def test_status_marks_legacy_config_as_on_prem_with_full_probe_chain(v2_context, v2_server):
    """The harness config has no deployment_type, exercising the legacy default."""
    v2_login(v2_context, v2_server)
    resp = v2_context.request.get(v2_server + "/api/status")

    assert resp.ok, resp.text()
    body = resp.json()
    assert body["deployment_type"] == "on_prem"
    assert body["health_probe"] == "noop+health+node_available"
    assert "provider_status_url" not in body


def test_user_menu_segmented_controls_switch_theme_and_density(v2_page):
    """XC-13's two segmented controls are the same theme.mjs/density API the
    #/system/display page writes — proven by reading <html>'s dataset."""
    page, base_url = v2_page
    _boot(page, base_url)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("document.documentElement.dataset.density") == "cozy"

    page.click(".userchip")
    page.wait_for_selector(".usermenu-pop")
    # First .seg is theme, second is density (shell.mjs builds them in that
    # order); the second button in each is the non-default value.
    page.locator(".usermenu-pop .seg").nth(0).locator("button").nth(1).click()
    page.locator(".usermenu-pop .seg").nth(1).locator("button").nth(1).click()

    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    assert page.evaluate("document.documentElement.dataset.density") == "compact"
    # ...and the controls reflect the state they just set (onDisplayChange).
    assert (
        page.locator(".usermenu-pop .seg").nth(0).locator("button").nth(1)
        .get_attribute("aria-pressed") == "true"
    )

    # Restore, so this test cannot leak a changed preference into the shared
    # browser context's localStorage for whatever runs next.
    page.evaluate(
        "async () => { const { theme, density } = "
        "await import('/static/js/v2/core/theme.mjs'); "
        "theme.set('dark'); density.set('cozy'); }"
    )


# theme.mjs keeps its subscriber Set module-private, so this counts live
# listeners by their observable effect instead: onDisplayChange's emit() calls
# `fn(theme.get(), density.get())` once PER LISTENER, and each live
# segmented() control's own sync() calls theme.get()/density.get() again. So
# the number of theme.get() calls triggered by ONE emit is a monotonic
# function of how many subscribers are alive. The absolute number is an
# implementation detail; that it does not GROW across open/close cycles is
# the invariant.
_COUNT_GETS_DURING_ONE_EMIT = """async () => {
  const m = await import('/static/js/v2/core/theme.mjs');
  const orig = m.theme.get;
  let n = 0;
  m.theme.get = function () { n++; return orig.call(this); };
  try { m.density.set(m.density.get()); } finally { m.theme.get = orig; }
  return n;
}"""


def test_user_menu_reopen_does_not_accumulate_display_listeners(v2_page):
    """Closing the menu must unsubscribe its segmented controls.

    shell.mjs's segmented() subscribes to onDisplayChange while it is on
    screen. If close() dropped the popover without unsubscribing, every
    open/close cycle would leave two more live listeners behind, each
    writing to a node that is no longer in the document — forever.
    """
    page, base_url = v2_page
    _boot(page, base_url)

    baseline = page.evaluate(_COUNT_GETS_DURING_ONE_EMIT)

    # While the menu is OPEN the count must rise — otherwise the probe is
    # measuring nothing and the "no growth" assertion below is decoration.
    page.click(".userchip")
    page.wait_for_selector(".usermenu-pop")
    assert page.evaluate(_COUNT_GETS_DURING_ONE_EMIT) > baseline
    page.keyboard.press("Escape")
    page.wait_for_selector(".usermenu-pop", state="detached")

    for _ in range(3):
        page.click(".userchip")
        page.wait_for_selector(".usermenu-pop")
        page.keyboard.press("Escape")
        page.wait_for_selector(".usermenu-pop", state="detached")

    assert page.evaluate(_COUNT_GETS_DURING_ONE_EMIT) == baseline
    # ...and nothing is left in the document either.
    assert page.locator(".usermenu-pop").count() == 0
    assert page.locator(".usermenu .seg").count() == 0


# ── XC-02 · the command palette ─────────────────────────────────────────────

def test_palette_exists_hidden_from_boot_and_opens_on_the_shortcut(v2_page):
    page, base_url = v2_page
    _boot(page, base_url)

    wrap = page.locator('[data-cov="XC-02"]')
    assert wrap.count() == 1
    assert wrap.is_hidden()

    page.keyboard.press("Control+k")
    wrap.wait_for(state="visible")
    # Seeded by shell.mjs's seedPalette(): the six area jumps, each labelled
    # with its landing route, all present before the user types anything.
    # (The list also holds whatever route-scoped commands the mounted area
    # registered, so this checks the six by name rather than by total count.)
    texts = page.locator('[data-cov="XC-02"] li[role="option"]').all_inner_texts()
    for route in ("#/overview", "#/investigate/traffic", "#/alerting/rules",
                  "#/automation/rules", "#/reports", "#/system/pce"):
        assert any(route in txt for txt in texts), (route, texts)

    page.keyboard.press("Escape")
    wrap.wait_for(state="hidden")


def test_palette_button_filters_and_runs_a_command(v2_page):
    page, base_url = v2_page
    _boot(page, base_url)
    labels = _labels(page)

    page.click(".kbd-btn")
    wrap = page.locator('[data-cov="XC-02"]')
    wrap.wait_for(state="visible")

    page.fill('[data-cov="XC-02"] input', labels["reports"])
    options = page.locator('[data-cov="XC-02"] li[role="option"]')
    # An exact substring hit scores below every fuzzy one (palette.mjs's
    # score()), so the area jump must sort to the top.
    page.wait_for_function(
        "() => { const el = document.querySelector("
        "'[data-cov=\"XC-02\"] li[role=\"option\"]'); "
        "return el && el.textContent.indexOf('#/reports') >= 0; }"
    )
    assert labels["reports"] in options.first.inner_text()
    # .text_content(), not .inner_text(): the group chip is uppercased by
    # CSS (text-transform), and inner_text() returns the RENDERED text.
    assert options.first.locator(".grp").text_content() == labels["area"]

    page.keyboard.press("Enter")
    # Running a command closes the palette AND actually navigates.
    wrap.wait_for(state="hidden")
    page.wait_for_function("() => location.hash === '#/reports'")


def test_palette_display_command_toggles_the_theme_for_real(v2_page):
    page, base_url = v2_page
    _boot(page, base_url)
    labels = _labels(page)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"

    page.keyboard.press("Control+k")
    page.locator('[data-cov="XC-02"]').wait_for(state="visible")
    page.fill('[data-cov="XC-02"] input', labels["theme"])
    page.wait_for_function(
        "label => { const el = document.querySelector("
        "'[data-cov=\"XC-02\"] li[role=\"option\"]'); "
        "return el && el.textContent.indexOf(label) >= 0; }",
        arg=labels["theme"],
    )
    page.keyboard.press("Enter")

    assert page.evaluate("document.documentElement.dataset.theme") == "light"
    page.evaluate(
        "async () => { const { theme } = "
        "await import('/static/js/v2/core/theme.mjs'); theme.set('dark'); }"
    )


def test_palette_is_not_opened_by_the_audit_hook(v2_page):
    """__openAllForAudit() must NOT leave the palette's full-screen scrim up.

    XC-02 is in the DOM from boot (hidden), so the coverage gate — which
    collects [data-cov] with querySelectorAll, visibility-blind — sees it
    without anything being opened. Opening it puts a z-index:100 scrim over
    the whole app, which swallowed clicks in two existing area suites. This
    asserts the deliberate absence of that opener (palette.mjs's install()).
    """
    page, base_url = v2_page
    _boot(page, base_url)

    page.evaluate("window.__openAllForAudit()")
    assert page.locator('[data-cov="XC-02"]').is_hidden()
    # The anchor is still collectable while hidden — the property the gate
    # actually depends on.
    assert page.evaluate(
        "document.querySelectorAll('[data-cov=\"XC-02\"]').length"
    ) == 1


# ── LG-03 · sign-out ────────────────────────────────────────────────────────

def test_sign_out_ends_the_session_for_real(v2_context, v2_server):
    """The sign-out form really POSTs /logout, lands on /login, and the
    session is genuinely gone afterwards.

    Uses its own context/page rather than the shared v2_page so killing the
    session cannot affect any other test in this file.
    """
    v2_login(v2_context, v2_server)
    page = v2_context.new_page()
    page.set_default_timeout(10_000)
    try:
        _boot(page, v2_server)

        page.click(".userchip")
        page.wait_for_selector(".usermenu-pop")
        form = page.locator('[data-cov="LG-03"]')
        assert form.count() == 1
        # A real form post — not a fetch: auth.py's logout() answers 302, and
        # the CSRF token flask-wtf checks comes from the hidden field.
        assert form.get_attribute("method").lower() == "post"
        assert form.get_attribute("action") == "/logout"
        assert form.locator('input[name="csrf_token"]').get_attribute("value")

        page.click('[data-cov="LG-03"] button[type="submit"]')
        page.wait_for_url(v2_server + "/login")
        assert page.locator("#login-root").count() == 1

        # The session is really dead: an authenticated-only API call now 401s
        # instead of returning data.
        resp = v2_context.request.get(v2_server + "/api/status")
        assert resp.status == 401, resp.text()
    finally:
        page.close()


def test_sign_out_survives_a_csrf_token_refresh_before_submit(v2_context, v2_server):
    """Finding 2 (security): sign-out must not silently fail after the app's
    CSRF token moves on.

    The form used to snapshot the token into its hidden field when the user
    menu was BUILT. core/api.mjs refreshes that token whenever the server
    rejects one (rawRequest()'s csrf_error refresh-and-retry), so the form
    could be left carrying a value the server no longer accepts. POST /logout
    then answers a JSON 400 — src/gui/__init__.py's CSRFError handler treats
    /logout like /api/*, so there is no redirect and no flash — and
    `logout_user()`/`session.clear()` NEVER RUN. The operator sees a JSON blob
    (or, with the menu closing over it, nothing at all) and believes they have
    signed out while the session is still live.

    Reproduced the way the real failure arrives — the hidden field holding a
    token the server rejects while api.mjs's own token is current:

      1. the page's meta token is corrupted (the state a tab left open across
         a server restart, or any token the server has stopped accepting, is
         in);
      2. the user menu is opened, so the form snapshots THAT value;
      3. a real api.post() runs and drives api.mjs's genuine
         refresh-and-retry, which repairs the meta tag — and only the meta tag.

    The POST chosen for step 3 is a DLQ replay against a destination name no
    configuration contains, so the request is real (it must be, or api.mjs's
    refresh path never runs) and its effect is a proven no-op: {requeued: 0}.

    What goes red without the fix: step 5's assertion that the browser reached
    /login, and step 6's — the session is still alive and /api/status still
    serves. Its own context, so a dead session cannot affect other tests.
    """
    v2_login(v2_context, v2_server)
    page = v2_context.new_page()
    page.set_default_timeout(10_000)
    try:
        _boot(page, v2_server)

        page.evaluate(
            "document.querySelector('meta[name=\"csrf-token\"]')"
            ".setAttribute('content', 'e2e-stale-logout-token')"
        )
        page.click(".userchip")
        page.wait_for_selector(".usermenu-pop")
        stale = page.locator('[data-cov="LG-03"] input[name="csrf_token"]').input_value()
        assert stale == "e2e-stale-logout-token", stale

        replayed = page.evaluate(
            "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
            "return api.post('/api/siem/dlq/replay', "
            "{dest: 'e2e-shell-no-such-dest', limit: 1}); }"
        )
        assert replayed == {"status": "ok", "requeued": 0}, replayed
        # api.mjs really did refresh: the meta tag no longer holds the corrupt
        # value. Without this the test could pass for the wrong reason.
        assert page.evaluate(
            "document.querySelector('meta[name=\"csrf-token\"]').getAttribute('content')"
        ) != "e2e-stale-logout-token"

        page.click('[data-cov="LG-03"] button[type="submit"]')
        page.wait_for_url(v2_server + "/login")
        assert page.locator("#login-root").count() == 1

        resp = v2_context.request.get(v2_server + "/api/status")
        assert resp.status == 401, resp.text()
    finally:
        page.close()


def test_sign_out_button_carries_the_real_product_label(v2_page):
    """C1: the control is localized through the catalogue, not hardcoded."""
    page, base_url = v2_page
    _boot(page, base_url)
    labels = _labels(page)

    page.click(".userchip")
    page.wait_for_selector(".usermenu-pop")
    assert (
        page.locator('[data-cov="LG-03"] button[type="submit"]').inner_text()
        == labels["logout"]
    )
    assert labels["logout"] not in ("", "gui_logout")
