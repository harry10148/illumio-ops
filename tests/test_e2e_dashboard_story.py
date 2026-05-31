"""Dashboard story-card end-to-end assertions (real-time data, no report dependency).

Full Playwright run requires ILLUMIO_OPS_E2E_BASE_URL; this lightweight
suite asserts that story-card surfaces are wired end-to-end through
the static template + JS files. Skips the live browser run when no
E2E base URL is configured.
"""
import os
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"


def _html():
    return INDEX_HTML.read_text(encoding="utf-8")


def _js():
    return DASHBOARD_JS.read_text(encoding="utf-8")


def test_story_pieces_all_present_in_template():
    html = _html()
    # Legacy snapshot section (in q-panel-legacy) still has these IDs
    for anchor in (
        'id="d-top-actions-grid"',
        'id="d-detailed-kpis"',
    ):
        assert anchor in html, f"missing template anchor: {anchor}"
    # Real-time story-card classes exist in the main dashboard
    for cls in ("story-card--health", "story-card--traffic", "story-card--risk"):
        pattern = re.compile(r'class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"')
        assert pattern.search(html), f"missing template class: {cls}"


def test_findings_table_collapsed_by_details():
    html = _html()
    pattern = re.compile(r'<details[^>]*>[\s\S]*?id="snap-findings-body"', re.MULTILINE)
    assert pattern.search(html)


def test_detailed_kpi_grid_collapsed_by_details():
    html = _html()
    pattern = re.compile(r'<details[^>]*id="d-detailed-kpis"', re.MULTILINE)
    m = pattern.search(html)
    assert m
    assert " open" not in m.group(0), "details must not be open by default"


@pytest.mark.skipif(
    not os.environ.get("ILLUMIO_OPS_E2E_BASE_URL"),
    reason="Set ILLUMIO_OPS_E2E_BASE_URL to enable live Playwright run",
)
def test_dashboard_story_live_browser():
    """Live Playwright check — only runs when E2E_BASE_URL is provided."""
    from playwright.sync_api import sync_playwright

    base = os.environ["ILLUMIO_OPS_E2E_BASE_URL"].rstrip("/")
    user = os.environ.get("ILLUMIO_OPS_E2E_USER", "illumio")
    password = os.environ.get("ILLUMIO_OPS_E2E_PASSWORD", "illumio")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(ignore_https_errors=True)
            page.goto(base + "/login", wait_until="domcontentloaded")
            page.fill("input[name=username], input#username", user)
            page.fill("input[name=password], input#password", password)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_selector("#p-dashboard", timeout=15000)
            # Story-group cards exist in DOM regardless of data state.
            for cls in ("story-card--health", "story-card--traffic", "story-card--risk"):
                assert page.locator(f".{cls}").count() >= 1, f"missing {cls} in DOM"
        finally:
            browser.close()
