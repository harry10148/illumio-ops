"""Phase 2A Task 11 — the three remaining legacy e2e suites, migrated onto v2.

## What this replaces

Three env-gated Playwright files that drove the LEGACY GUI and are deleted
with it. All three were gated on ILLUMIO_OPS_E2E_BASE_URL and skipped their
whole module when it was unset, so none of them ever ran in CI; every test
here runs in-process against the real Flask app, on every run.

  tests/test_gui_e2e_playwright.py            5 tests
      login_and_landing_page                  -> test_landing_page_renders
      init_translations_loaded                -> test_translation_catalogue_is_loaded
      tab_clicks_without_raw_key_leak         -> test_no_raw_i18n_key_leaks_on_any_area
      dashboard_kpi_strip_renders_in_current_language
                                              -> test_overview_renders_in_the_configured_language
      main_api_endpoints_authenticated        -> test_core_api_endpoints_answer_inside_a_session

  tests/test_e2e_header_menu.py               3 tests
      menu_opens_and_closes_with_escape       } the legacy "Operations" dropdown became
      menu_closes_on_outside_click            } the v2 user menu (XC-13); its open/close
      stop_item_triggers_confirm              } and Escape behaviour is covered by
                                                tests/test_v2_shell_e2e.py, and the Stop
                                                item moved to #/system/security's confirm
                                                (tests/test_v2_system_e2e.py). What had NO
                                                new owner is the outside-click dismissal,
                                                which is here.

  tests/test_gui_settings_subtab_e2e.py       3 tests
      switch_between_four_settings_subtabs    -> test_system_subroutes_switch
      stab_url_param_deep_link                -> test_system_subroute_deep_link
      save_button_label_updates_when_one_tab_dirty
                                              -> test_save_label_names_the_dirty_section

Assertion counts before/after are in task-11-report.md. The one legacy
assertion with no v2 counterpart is `window._INIT_TRANSLATIONS` having >= 500
keys: v2 has no global translations object at all (core/i18n.mjs keeps the
catalogue module-private and hands it out through t()). The invariant it
protected — "the real catalogue reached the browser, it is not a stub" —
is asserted through i18n.missing() and a real key lookup instead.
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

pytest_plugins = ["tests.v2_e2e_utils"]

# Every route the six-area nav can reach, i.e. what "click each top-level tab"
# means now. Kept explicit rather than derived so a route silently disappearing
# from the shell shows up as a test that stopped covering it.
AREA_ROUTES = [
    "#/home",
    "#/investigate/inbox", "#/investigate/traffic", "#/investigate/workloads", "#/investigate/events",
    "#/policy/alert-rules", "#/policy/rulesets", "#/policy/schedules", "#/policy/ops",
    "#/reports", "#/reports/schedules",
    "#/system/jobs", "#/system/alerting",
    "#/system/pce", "#/system/cache", "#/system/siem", "#/system/tls",
    "#/system/security", "#/system/display", "#/system/channels", "#/system/logs",
]

# Prefixes transcribed from tests/test_gui_e2e_playwright.py's _RAW_KEY_RE,
# unchanged: strict-prefix UI keys with no humanization fallback. login_*,
# event_* and rule_* stay excluded for the reasons that file documented (they
# collide with real PCE event_ids like `login_proxy_ldap_config.*` and
# `rule_set.create`).
#
# WHAT CHANGED, stated rather than buried (Phase 2A finding B3): the legacy
# test searched for these prefixes as SUBSTRINGS of body.innerText. Run
# unchanged against v2 that flags four false positives, all of them real
# product copy — the v2 areas explain themselves far more than the legacy
# tabs did, and their notes quote real identifiers in prose:
#
#   #/system/display     "...the hardcoded literal \"Theme\" (settings.js:448,
#                         no data-i18n); this page uses the existing gui_theme..."
#   #/reports            "...newest per report_type (the filename prefix rules...)"
#   #/reports/schedules "...Every key report_schedules carries is listed..."
#   #/policy/ops       an <code> chip naming the alert_history field
#
# So the match is anchored instead: a LEAKED key is a text node whose ENTIRE
# content is the key, which is exactly what an unresolved t()/tf() renders
# (`el("h2", {text: t("gui_x")})` -> the node's whole text is "gui_x").
# A prefix appearing inside a sentence is prose, not a leak.
#
# This is narrower in one direction, so the tests below pair it with
# i18n.missing() per route — core/i18n.mjs records EVERY key lookup that fell
# through, however the result was rendered — which the legacy test had no
# equivalent of at all. Together they are strictly stronger than the substring
# scan, which in this codebase would have had to be suppressed to stay green.
_RAW_KEY_RE = re.compile(
    r"^("
    r"rpt_|gui_|rs_|cli_|menu_|settings_|alert_|sched_|wgs_|webhook_|"
    r"mail_|line_|metric_|trigger_|filter_|step_|select_|confirm_|"
    r"pill_|daemon_|report_|pd_|event_group_"
    r")[a-z][a-z0-9_]{2,}$"
)

# Returns every text node's trimmed content, so the anchored pattern above can
# be applied per node instead of to one flattened blob.
#
# <code>/<kbd>/.mono nodes are skipped: those are the product's identifier
# chips, which name real payload keys, config keys and job names on purpose
# (areas/reports.mjs's RP-04 lists `partial` / `failed_formats` / `files`;
# areas/alerting.mjs names the `alert_history` field the same way). An
# identifier rendered as an identifier is the feature, not a leak — and a
# LEAKED key never lands in one of these, because every leak comes from a
# t()/tf() call whose result is set as a label's text.
_TEXT_NODES_JS = """() => {
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let n;
  while ((n = walk.nextNode())) {
    const v = (n.nodeValue || '').trim();
    if (!v) continue;
    if (n.parentElement && n.parentElement.closest('code, kbd, pre, .mono')) continue;
    out.push(v);
  }
  return out;
}"""


def _boot(page, base_url, route="#/home"):
    page.goto(base_url + "/" + route)
    # 90s, not the 10s default. app.mjs sets data-booted only after
    # `Promise.all([mountHealth, router.start])`, and router.start() awaits the
    # FIRST route's mount — so a cold load of an area that fetches from the PCE
    # blocks this flag for as long as that fetch takes. Against this harness's
    # unreachable PCE, #/policy/rulesets waits on get_all_rulesets plus a
    # label-cache warm-up, each with its own urllib3 connect-retry budget:
    # measured well past 30s. This is a ceiling on a real wait, not a sleep.
    page.wait_for_selector('body[data-booted="true"]', timeout=90_000)


def _scan_raw_keys(page) -> list[str]:
    seen = []
    for value in page.evaluate(_TEXT_NODES_JS):
        if _RAW_KEY_RE.match(value) and value not in seen:
            seen.append(value)
    return seen


# ── from test_gui_e2e_playwright.py ─────────────────────────────────────────

def test_landing_page_renders(v2_page):
    """Login succeeds and the SPA renders its shell.

    The legacy assertion was the hardcoded brand line "Illumio PCE Ops" in
    body.innerText. The v2 chrome renders the brand as "illumio | ops"
    (shell.mjs), so the check is on the shell's own structure plus that brand.
    """
    page, base_url = v2_page
    _boot(page, base_url)

    text = page.evaluate("() => document.body.innerText")
    assert text, "body innerText empty — page did not render"
    assert page.locator("header.chrome .brand").count() == 1
    assert "illumio" in page.locator("header.chrome .brand").inner_text().lower()
    # The three things that make it a shell and not an error page.
    assert page.locator("#area-root").count() == 1
    assert page.locator('[data-cov="XC-14"] a').count() == 5


def test_translation_catalogue_is_loaded(v2_page):
    """The real catalogue reached the browser.

    Legacy: `Object.keys(window._INIT_TRANSLATIONS).length >= 500`. v2 has no
    such global — core/i18n.mjs keeps the catalogue module-private — so this
    asks the same question through the module's own surface: a real product
    key resolves to its real product value, and nothing the app rendered was
    recorded as missing.
    """
    page, base_url = v2_page
    _boot(page, base_url)

    result = page.evaluate(
        "async () => { const { t, i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { resolved: t('gui_err_unauthorized'), missing: i18n.missing() }; }"
    )
    assert result["resolved"] == "Unauthorized.", result
    assert result["missing"] == [], result["missing"]


@pytest.mark.parametrize("route", AREA_ROUTES)
def test_no_raw_i18n_key_leaks_on_any_area(v2_page, route):
    """Visit every area; no raw i18n key may reach the rendered text.

    The legacy version walked 7 top-level tabs; v2 has 18 routes behind the
    six-area nav, so this covers strictly more surface.
    """
    page, base_url = v2_page
    _boot(page, base_url, route)
    page.wait_for_timeout(2500)

    leaks = _scan_raw_keys(page)
    # `rule_set` (an Illumio object name) is plain English data in tables, not
    # a leaked key — the same explicit carve-out the legacy file had.
    leaks = [k for k in leaks if k not in {"rule_set", "rule_sets"}]
    assert not leaks, f"raw i18n keys leaked on {route}: {leaks}"

    # The other half of the pair (see _RAW_KEY_RE's note): any key that failed
    # to resolve is recorded here whether or not it reached the screen.
    missing = page.evaluate(
        "async () => { const { i18n } = await import('/static/js/v2/core/i18n.mjs'); "
        "return i18n.missing(); }"
    )
    assert missing == [], f"unresolved i18n keys on {route}: {missing}"


def test_overview_renders_in_the_configured_language(v2_page):
    """The overview's text follows settings.language.

    Legacy: scrape the KPI strip for Chinese characters when zh_TW, or for one
    of five canonical English KPI labels otherwise. v2 renders no such fixed
    label set, so the check is against the catalogue: the language the backend
    reports is the language a known key resolves in.
    """
    page, base_url = v2_page
    _boot(page, base_url)

    lang = page.evaluate(
        "async () => { const { api } = await import('/static/js/v2/core/api.mjs'); "
        "return (await api.load('status')).language || 'en'; }"
    )
    # .text_content(), not .inner_text(): the nav label is uppercased by CSS
    # and inner_text() returns the RENDERED text.
    nav_label = page.locator('[data-cov="XC-14"] a[href="#/home"] u').text_content()
    if lang == "zh_TW":
        assert re.search(r"[一-鿿]", nav_label), nav_label
    else:
        assert nav_label == "Home", nav_label


def test_core_api_endpoints_answer_inside_a_session(v2_page):
    """Smoke-check that core JSON endpoints return 200 inside an authenticated
    session — guards against accidental @login_required regressions.

    Same endpoint list as the legacy file, minus none.
    """
    page, base_url = v2_page
    _boot(page, base_url)

    endpoints = [
        "/api/settings",
        "/api/rules",
        "/api/reports",
        "/api/report-schedules",
        "/api/workloads",
        "/api/dashboard/snapshot",
        "/api/event-catalog",
        "/api/rule_scheduler/schedules",
    ]
    failures = []
    for ep in endpoints:
        r = page.request.get(base_url + ep)
        if r.status != 200:
            failures.append((ep, r.status))
    assert not failures, f"non-200 responses: {failures}"


# ── from test_e2e_header_menu.py ────────────────────────────────────────────

def test_user_menu_closes_on_an_outside_click(v2_page):
    """The legacy Operations dropdown's outside-click dismissal, on XC-13.

    Its two siblings (open/close on Escape, and the Stop item raising a
    confirm) have owners already: tests/test_v2_shell_e2e.py and
    tests/test_v2_system_e2e.py's destructive-confirm test. This one had none.
    """
    page, base_url = v2_page
    _boot(page, base_url)

    assert page.locator(".usermenu-pop").count() == 0
    page.click(".userchip")
    page.wait_for_selector(".usermenu-pop")

    # Click well away from the menu — the area body, not the chrome.
    page.locator("#area-root").click(position={"x": 20, "y": 20})
    page.wait_for_selector(".usermenu-pop", state="detached")
    assert page.get_attribute(".userchip", "aria-expanded") == "false"


# ── from test_gui_settings_subtab_e2e.py ────────────────────────────────────
#
# The legacy settings panel had four sub-tabs (pce / channels / display /
# security) behind `?tab=settings&stab=<name>`. v2 replaced them with eight
# first-class routes under #/system, so "switch sub-tab" is now "navigate",
# and the deep link is the hash itself.

def test_system_subroutes_switch(v2_page):
    page, base_url = v2_page
    _boot(page, base_url, "#/system/pce")
    assert page.locator('[data-cov="SY-18"]').count() >= 1

    page.evaluate("location.hash = '#/system/security'")
    page.wait_for_selector('[data-cov="SY-12"]')
    assert page.locator('[data-cov="SY-18"]').count() == 0
    assert "#/system/security" in page.url


def test_system_subroute_deep_link(v2_page):
    """A cold load of a sub-route lands on that sub-route — the v2 form of
    `?tab=settings&stab=channels`."""
    page, base_url = v2_page
    _boot(page, base_url, "#/system/channels")

    page.wait_for_selector('[data-cov="SY-14"]')
    # ...and the nav marks the area it belongs to.
    assert page.locator('[data-cov="XC-14"] a[aria-current]').get_attribute(
        "href"
    ) == "#/system/pce"


def test_save_label_names_the_dirty_section(v2_page):
    """Editing one field marks the form dirty and the save control says so.

    Legacy: type into `#s-rpt-retention` on the display sub-tab and assert
    `#s-save-label`'s text changed AND named the section ("Interface"/"介面").
    v2's docked form (areas/system.mjs's form.track) carries the same idea on
    #/system/display.
    """
    page, base_url = v2_page
    _boot(page, base_url, "#/system/display")
    page.wait_for_selector('[data-cov="SY-13"]')

    # areas/system.mjs's makeForm() renders the docked bar as `.savebar`
    # (`.savedock` is its in-flow placeholder); SY-18 is stamped on the PCE
    # page's bar only, so the class is the portable selector.
    bar = page.locator(".savebar").first
    bar.wait_for(state="attached")
    baseline = bar.inner_text().strip()

    # `report.retention_days` is the direct descendant of the legacy test's
    # `#s-rpt-retention` — the same setting, on the same page, and a REAL
    # tracked field (areas/system.mjs's form.track). Deliberately not the
    # theme/density controls next to it: XC-05 applies those live through
    # theme.mjs and they are not part of the saved form at all, so editing one
    # would leave the bar clean and this test would prove nothing.
    field = page.locator('[data-field="report.retention_days"]')
    field.wait_for(state="visible")
    original = field.input_value()
    field.fill("99" if original != "99" else "98")
    field.dispatch_event("input")

    page.wait_for_function(
        "before => { const el = document.querySelector('.savebar'); "
        "return el && el.innerText.trim() !== before; }",
        arg=baseline,
    )
    after = bar.inner_text().strip()
    assert after != baseline, (baseline, after)
    # ...and the bar reports the dirty state, not just any change: the legacy
    # assertion was that the label NAMES the dirty section.
    assert bar.get_attribute("data-tone") != "neutral", bar.get_attribute("data-tone")
    assert "report.retention_days" in bar.inner_text(), bar.inner_text()

    # Restore, in a finally-equivalent position: nothing is saved (Save is
    # never clicked), but leaving the field edited would leave the shared
    # browser context's page dirty for whatever runs next.
    field.fill(original)
    field.dispatch_event("input")
