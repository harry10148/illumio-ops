"""End-to-end: Operations dropdown opens/closes (Esc + outside-click) and
the Stop menu item dispatches a confirm() dialog.

Env-gated: set ILLUMIO_OPS_E2E_BASE_URL to a deployed instance to enable.
"""
from __future__ import annotations

import os
import pytest


BASE_URL = os.environ.get("ILLUMIO_OPS_E2E_BASE_URL", "")
USERNAME = os.environ.get("ILLUMIO_OPS_E2E_USER", "illumio")
PASSWORD = os.environ.get("ILLUMIO_OPS_E2E_PASSWORD", "illumio")

if not BASE_URL:
    pytest.skip(
        "Set ILLUMIO_OPS_E2E_BASE_URL (and optionally _USER/_PASSWORD) to enable "
        "GUI end-to-end tests.",
        allow_module_level=True,
    )

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    pytest.skip("playwright not installed; run `pip install playwright`.",
                allow_module_level=True)


def _login(page) -> None:
    page.goto(BASE_URL + "/login", wait_until="domcontentloaded")
    page.fill("input[name=username], input#username", USERNAME)
    page.fill("input[name=password], input#password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle", timeout=20000)


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(ignore_https_errors=True)
        pg = ctx.new_page()
        _login(pg)
        pg.wait_for_selector("#hdr-menu-btn", timeout=10000)
        yield pg
        browser.close()


def test_menu_opens_and_closes_with_escape(page) -> None:
    panel = page.locator("#hdr-menu-panel")
    # initially hidden
    assert panel.evaluate("el => el.hasAttribute('hidden')")
    page.click("#hdr-menu-btn")
    assert not panel.evaluate("el => el.hasAttribute('hidden')")
    page.keyboard.press("Escape")
    assert panel.evaluate("el => el.hasAttribute('hidden')")


def test_menu_closes_on_outside_click(page) -> None:
    panel = page.locator("#hdr-menu-panel")
    page.click("#hdr-menu-btn")
    assert not panel.evaluate("el => el.hasAttribute('hidden')")
    # click on the main heading area to dismiss
    page.click("h1")
    assert panel.evaluate("el => el.hasAttribute('hidden')")


def test_stop_item_triggers_confirm(page) -> None:
    confirms: list[str] = []
    page.on("dialog", lambda d: (confirms.append(d.message), d.dismiss()))
    page.click("#hdr-menu-btn")
    page.click('button.menu-item.danger[data-action="stopGui"]')
    assert confirms, "expected a confirm() dialog when clicking Stop"
    text = confirms[0]
    assert "stop" in text.lower() or "停止" in text, (
        f"confirm message should mention stop / 停止, got: {text!r}"
    )
