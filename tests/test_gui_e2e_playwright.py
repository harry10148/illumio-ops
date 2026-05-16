"""End-to-end browser tests against a running illumio-ops GUI.

These tests drive a real (headless) Chromium through the auth flow and
each top-level tab, asserting that:

  1. Every tab loads without a JS exception.
  2. The rendered DOM contains no raw i18n keys (``gui_*``, ``rpt_*``,
     ``rule_*``, ``event_group_*``, ``rs_*``, etc.) — every key must
     resolve before reaching the user.
  3. When ``settings.language`` is ``zh_TW`` the dashboard's KPI strip
     contains Chinese text (i.e. the language switch propagates through
     the snapshot retranslate path landed in PR #24).

The suite is **env-gated**: unless ``ILLUMIO_OPS_E2E_BASE_URL`` is set
the whole module is skipped, so unit-test CI doesn't have to spin up a
real daemon. To run locally or on a staging host::

    pip install --user playwright && playwright install chromium
    ILLUMIO_OPS_E2E_BASE_URL=https://<host>:5001 \
    ILLUMIO_OPS_E2E_USER=<user> \
    ILLUMIO_OPS_E2E_PASSWORD=<password> \
    pytest tests/test_gui_e2e_playwright.py -v

The TARGET server must be reachable and accept the supplied credentials.
"""
from __future__ import annotations

import json
import os
import re
import time

import pytest

# ---------------------------------------------------------------------------
# Environment gating — skip the whole module when E2E is not configured.
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("ILLUMIO_OPS_E2E_BASE_URL")
USERNAME = os.environ.get("ILLUMIO_OPS_E2E_USER", "illumio")
PASSWORD = os.environ.get("ILLUMIO_OPS_E2E_PASSWORD", "illumio")

if not BASE_URL:
    pytest.skip(
        "Set ILLUMIO_OPS_E2E_BASE_URL (and optionally _USER/_PASSWORD) to enable "
        "GUI end-to-end tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    pytest.skip("playwright not installed; run `pip install playwright`.",
                allow_module_level=True)


# ---------------------------------------------------------------------------
# Patterns flagged as i18n leakage.
#
# Includes ONLY strict-prefix UI keys with no humanization fallback. Excluded
# on purpose:
#   - ``login_*`` — overlaps with PCE event_ids like ``login_proxy_ldap_config.*``
#     which are stored data, not i18n keys.
#   - ``event_*`` — overlaps with bare PCE event_ids like ``event_settings.update``.
#   - ``rule_*`` — too generic; PCE has ``rule_set.create`` etc. We rely on
#     the report-level test_report_i18n_leakage.py to cover ``rule_*`` surfaces.
# ---------------------------------------------------------------------------

_RAW_KEY_RE = re.compile(
    r"(?:^|[\s>])("
    r"rpt_|gui_|rs_|cli_|menu_|settings_|alert_|sched_|wgs_|webhook_|"
    r"mail_|line_|metric_|trigger_|filter_|step_|select_|confirm_|"
    r"pill_|daemon_|report_|pd_|event_group_"
    r")[a-z][a-z0-9_]{2,}"
)

# The 4 tabs we walk through. Each tab's data-args value matches the click
# handler in src/templates/index.html.
_TABS = ["dashboard", "events", "rules", "reports", "rule-scheduler",
         "integrations", "settings"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def playwright_browser():
    """Module-scoped chromium so we don't re-spawn for every test."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="module")
def _logged_in_context(playwright_browser):
    """Module-scoped browser context with one authenticated session.

    Per-test contexts would burn through the ``5 per minute`` rate limit on
    /api/login almost immediately, so we share the session and just reset
    URL state between tests.
    """
    ctx = playwright_browser.new_context(
        ignore_https_errors=True,
        viewport={"width": 1400, "height": 900},
    )
    pg = ctx.new_page()
    resp = pg.request.post(
        f"{BASE_URL}/api/login",
        data=json.dumps({"username": USERNAME, "password": PASSWORD}),
        headers={"Content-Type": "application/json"},
    )
    j = resp.json()
    assert resp.ok and j.get("ok"), f"login failed: {j}"
    yield ctx, pg
    ctx.close()


@pytest.fixture()
def page(_logged_in_context):
    """Per-test page that returns to root before each test so we get a clean
    starting state without re-authenticating (and without tripping the
    login rate limiter)."""
    _ctx, pg = _logged_in_context
    pg.goto(f"{BASE_URL}/", wait_until="networkidle", timeout=20000)
    time.sleep(0.6)
    yield pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_raw_keys(text: str) -> list[str]:
    out, seen = [], set()
    for m in _RAW_KEY_RE.finditer(text):
        token = m.group(0).strip(" \t\n>")
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _click_tab(page, tab_id: str) -> bool:
    """Click a top-level tab by data-args. Returns True if found."""
    handle = page.query_selector(f'[data-args=\'["{tab_id}"]\']')
    if handle is None:
        return False
    handle.scroll_into_view_if_needed()
    handle.click(timeout=3000)
    time.sleep(0.6)
    return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_login_and_landing_page(page):
    """Login succeeds and the SPA renders its top-level shell."""
    text = page.evaluate("() => document.body.innerText")
    assert text, "body innerText empty — page did not render"
    # The brand line is hard-coded and should always be present.
    assert "Illumio PCE Ops" in text


def test_init_translations_loaded(page):
    """``window._INIT_TRANSLATIONS`` is non-empty (~900 keys at writing)."""
    count = page.evaluate("() => Object.keys(window._INIT_TRANSLATIONS || {}).length")
    assert count >= 500, f"only {count} translations loaded — i18n shim broke?"


@pytest.mark.parametrize("tab_id", _TABS)
def test_tab_clicks_without_raw_key_leak(page, tab_id):
    """Click each main tab; assert no raw i18n keys appear in the rendered text."""
    if not _click_tab(page, tab_id):
        pytest.skip(f"tab '{tab_id}' not in this build")
    text = page.evaluate("() => document.body.innerText")
    leaks = _scan_raw_keys(text)
    # `rule_set` (Illumio object name) is not a leak — it's plain English data
    # in tables. Filter it out explicitly so a single false positive doesn't
    # mask real regressions.
    leaks = [k for k in leaks if k not in {"rule_set", "rule_sets"}]
    assert not leaks, f"raw i18n keys leaked on tab '{tab_id}': {leaks}"


def test_dashboard_kpi_strip_renders_in_current_language(page):
    """Dashboard's KPI strip should contain text in the configured language
    (Chinese chars present in zh_TW; English-only in en). Catches snapshot
    cache-language regressions like the one fixed in PR #24."""
    if not _click_tab(page, "dashboard"):
        pytest.skip("dashboard tab not present")
    # Configured language from API (cheaper than scraping settings.json)
    resp = page.request.get(f"{BASE_URL}/api/settings")
    settings = resp.json()
    lang = (settings.get("settings") or {}).get("language") \
        or (settings.get("config", {}).get("settings", {}) or {}).get("language") \
        or "en"
    # Grab everything near the KPI strip (visible card area).
    text = page.evaluate("() => document.body.innerText")
    if lang == "zh_TW":
        assert re.search(r"[一-鿿]", text), (
            "zh_TW configured but no Chinese characters in dashboard text"
        )
    else:
        # Allow Chinese in things like font fallback names; assert at least
        # one ASCII-only KPI label is present (e.g. "Total Flows" / "Maturity Score").
        ascii_phrases = [
            "Total Flows", "Maturity Score", "Total Connections",
            "Blocked Flows", "Total Data Volume",
        ]
        assert any(p in text for p in ascii_phrases), (
            f"en configured but no canonical English KPI label found in dashboard"
        )


def test_main_api_endpoints_authenticated(page):
    """Smoke-check that core JSON endpoints return 200 inside an authenticated
    session — guards against accidental @login_required regressions."""
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
        r = page.request.get(f"{BASE_URL}{ep}")
        if r.status != 200:
            failures.append((ep, r.status))
    assert not failures, f"non-200 responses: {failures}"
