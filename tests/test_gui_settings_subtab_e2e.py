"""Sub-tab smoke test — switch between 4 sub-tabs and verify deep-link via ?stab=.

Env-gated identically to tests/test_gui_e2e_playwright.py:
  ILLUMIO_OPS_E2E_BASE_URL=https://172.16.15.106:5001
  ILLUMIO_OPS_E2E_USER=illumio
  ILLUMIO_OPS_E2E_PASSWORD=...

If the env var is unset, the whole module is skipped.
"""
from __future__ import annotations

import json
import os
import time

import pytest


BASE_URL = os.environ.get("ILLUMIO_OPS_E2E_BASE_URL")
USERNAME = os.environ.get("ILLUMIO_OPS_E2E_USER", "illumio")
PASSWORD = os.environ.get("ILLUMIO_OPS_E2E_PASSWORD", "illumio")

if not BASE_URL:
    pytest.skip(
        "Set ILLUMIO_OPS_E2E_BASE_URL (and optionally _USER/_PASSWORD) to enable "
        "settings sub-tab GUI end-to-end tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    pytest.skip("playwright not installed; run `pip install playwright`.",
                allow_module_level=True)


@pytest.fixture(scope="module")
def _logged_in_page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
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
        yield pg
        ctx.close()
        browser.close()


def test_switch_between_four_settings_subtabs(_logged_in_page):
    page = _logged_in_page
    page.goto(f"{BASE_URL}/?tab=settings", wait_until="networkidle", timeout=20000)
    page.wait_for_selector("#p-settings.active", timeout=5000)
    time.sleep(0.5)  # allow loadSettings() to finish injecting panels

    # Default sub-tab = pce
    expect(page.locator("#settings-pce")).to_have_class("s-subpanel active")

    # Click "Security" sub-tab
    page.click("#sbtn-security")
    expect(page.locator("#settings-security")).to_have_class("s-subpanel active")
    assert "stab=security" in page.url, f"URL missing stab param: {page.url}"


def test_stab_url_param_deep_link(_logged_in_page):
    page = _logged_in_page
    page.goto(f"{BASE_URL}/?tab=settings&stab=channels",
              wait_until="networkidle", timeout=20000)
    page.wait_for_selector("#settings-channels.active", timeout=5000)
    expect(page.locator("#settings-channels")).to_have_class("s-subpanel active")
    expect(page.locator("#sbtn-channels")).to_have_class("sub-nav-btn active")


def test_save_button_label_updates_when_one_tab_dirty(_logged_in_page):
    page = _logged_in_page
    page.goto(f"{BASE_URL}/?tab=settings&stab=display",
              wait_until="networkidle", timeout=20000)
    page.wait_for_selector("#settings-display.active", timeout=5000)
    page.wait_for_selector("#s-rpt-retention", timeout=5000)

    baseline = (page.text_content("#s-save-label") or "").strip()

    page.fill("#s-rpt-retention", "99")
    page.dispatch_event("#s-rpt-retention", "input")
    time.sleep(0.2)

    updated = (page.text_content("#s-save-label") or "").strip()
    assert updated != baseline, (
        f"Save label did not update after dirty event "
        f"(baseline={baseline!r}, after={updated!r})"
    )
    assert (
        "Interface" in updated or "介面" in updated
    ), f"Save label should name the dirty section, got {updated!r}"
