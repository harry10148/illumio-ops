"""Dashboard story surfaces — live browser check.

Phase 2A Task 11 removed this file's three static tests. They asserted the
LEGACY src/templates/index.html's story-card markup
(`id="d-top-actions-grid"`, `id="d-detailed-kpis"`, the
`story-card--health/traffic/risk` classes, and the two `<details>` wrappers
around `snap-findings-body` / `d-detailed-kpis`). That template is gone; the
v2 overview board is a different shape and is covered by
tests/test_v2_overview_e2e.py, which drives the real app in-process rather
than grepping a template.

The live-browser test below is unchanged in intent and is migrated onto the
v2 DOM: it still answers "do the overview's story surfaces reach the DOM
against a REAL deployed appliance", which is the one thing the in-process
suite cannot answer. It stays env-gated on ILLUMIO_OPS_E2E_BASE_URL.
"""
import os

import pytest


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
            page.fill('[data-cov="LG-01"] input[data-field="username"]', user)
            page.fill('[data-cov="LG-01"] input[data-field="password"]', password)
            page.click('[data-cov="LG-01"] button.btn.primary')
            # Wait for the URL to leave /login, NOT for body[data-booted].
            # login.mjs:309 sets data-booted on the login page itself, so that
            # condition is already true at the moment of the click and cannot
            # distinguish "signed in" from "still on the form" — the navigation
            # below then raced the login POST and landed back on /login#/overview.
            page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
            page.goto(base + "/#/overview")
            page.wait_for_selector('body[data-booted="true"]', timeout=20000)
            # The overview's own anchors, in place of the legacy story-card
            # classes: the posture/score card, the top-actions region and the
            # health rail all have to reach the DOM regardless of data state.
            for cov in ("OV-02", "OV-03", "XC-01"):
                assert page.locator(f'[data-cov="{cov}"]').count() >= 1, f"missing {cov}"
        finally:
            browser.close()
