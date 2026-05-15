"""Phase 3.1 Task 7 — integrated story-flow assertions.

Full Playwright run requires ILLUMIO_OPS_E2E_BASE_URL; this lightweight
suite asserts that every Phase 3.1 surface (hero / story-cards / maturity /
top-actions / collapsed KPIs / empty-state) is wired end-to-end through
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
    for anchor in (
        'id="d-hero"',
        'id="d-hero-cta"',
        'class="card story-card story-card--health"',
        'class="card story-card story-card--traffic"',
        'class="card story-card story-card--risk"',
        'id="d-maturity"',
        'id="d-top-actions-grid"',
        'id="d-detailed-kpis"',
    ):
        assert anchor in html, f"missing template anchor: {anchor}"


def test_snapshot_loader_invokes_full_story_pipeline():
    js = _js()
    # all five render hooks called from loadDashboardSnapshot
    block = re.search(r"async function loadDashboardSnapshot[\s\S]*?\n}\n", js)
    assert block, "loadDashboardSnapshot not found"
    body = block.group(0)
    for fn in ("renderHero(", "renderStoryGroups(", "renderMaturity(", "renderTopActions("):
        assert fn in body, f"loadDashboardSnapshot must call {fn}"
    assert "renderHeroEmpty()" in body, "empty-state fallback must be wired"


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

    url = os.environ["ILLUMIO_OPS_E2E_BASE_URL"].rstrip("/") + "/"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(ignore_https_errors=True)
            page.goto(url)
            page.wait_for_selector("#p-dashboard", timeout=15000)
            assert page.is_visible("#d-hero"), "hero block must be visible"
            for cls in ("story-card--health", "story-card--traffic", "story-card--risk"):
                assert page.is_visible(f".{cls}"), f"missing visible {cls}"
            details_open = page.eval_on_selector(
                "#d-detailed-kpis", "el => el.hasAttribute('open')"
            )
            assert details_open is False, "detailed-kpis must default to collapsed"
        finally:
            browser.close()
