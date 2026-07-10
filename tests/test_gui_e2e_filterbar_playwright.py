"""End-to-end browser tests for the PCE-style filter bar service/port pills.

Scenario coverage (feat/port-service-filter Task 13):

  1. Traffic Analyzer filter modal: click empty input → category chips
     (with object totals) → click Services → grouped browse list →
     "Load more" grows the list → picking an item becomes a pill.
  2. Manual port token ``443/tcp`` → "Add Port" candidate → Enter turns it
     into a pill → clicking the pill opens a popover WITHOUT the direction
     row but WITH a working include/exclude toggle.
  3. Dropdown footer "Browse all…" → object browser modal → Labels tab →
     tick 2 rows → Add → 2 pills appear in the bar.
  4. Manual IP/CIDR regression: ``10.0.0.0/24`` → "Add IP/CIDR" candidate →
     Enter turns it into a pill.
  5. Submitting the query POSTs /api/quarantine/search with ``services``
     and ``ports`` keys in the JSON payload.

The suite is **env-gated** exactly like test_gui_e2e_playwright.py: unless
``ILLUMIO_OPS_E2E_BASE_URL`` is set the whole module is skipped, so unit-test
CI doesn't have to spin up a real daemon. To run locally or on staging::

    pip install --user playwright && playwright install chromium
    ILLUMIO_OPS_E2E_BASE_URL=https://<host>:5001 \
    ILLUMIO_OPS_E2E_USER=<user> \
    ILLUMIO_OPS_E2E_PASSWORD=<password> \
    pytest tests/test_gui_e2e_filterbar_playwright.py -v

Scenarios 1/3/5 need real PCE objects (services / labels) in the daemon's
object cache; when the target has none they skip with an explicit reason
instead of failing, while a broken browse endpoint still fails loudly.
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
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    pytest.skip("playwright not installed; run `pip install playwright`.",
                allow_module_level=True)


# The traffic analyzer filter bar container (see src/templates/index.html,
# #modal-qt-filters) — every selector below is scoped to it so other
# filter-bar instances (reports / scheduler / rules) can't interfere.
FB = "#qt-filter-bar"


# ---------------------------------------------------------------------------
# Fixtures (same shape as test_gui_e2e_playwright.py — shared login session
# to stay under the /api/login rate limit)
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
    """Module-scoped browser context with one authenticated session."""
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
    """Per-test page reset to root so every scenario starts from a fresh
    SPA state (the filter bar instance is created lazily per page load)."""
    _ctx, pg = _logged_in_context
    pg.goto(f"{BASE_URL}/", wait_until="networkidle", timeout=20000)
    time.sleep(0.6)
    yield pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_traffic_filter_modal(page):
    """Navigate: Traffic & Workload tab → Filter Settings → filters modal.

    Returns the filter bar's text input element handle.
    """
    tab = page.wait_for_selector(
        '[data-args=\'["traffic-workload"]\']', state="visible", timeout=10000)
    tab.click()
    btn = page.wait_for_selector(
        "[data-action='openQtFiltersModal']", state="visible", timeout=10000)
    btn.click()
    page.wait_for_selector("#modal-qt-filters.show", state="visible", timeout=10000)
    return page.wait_for_selector(f"{FB} .objfb-input", state="visible", timeout=10000)


def _pill_count(page) -> int:
    return len(page.query_selector_all(f"{FB} .objfb-pill"))


def _open_service_browse(page, inp):
    """Empty-input dropdown → click the Services category chip → wait for the
    grouped browse list. Skips (not fails) when the PCE has no services, but
    fails loudly when the browse endpoint itself errors."""
    inp.click()
    page.wait_for_selector(
        f"{FB} .objfb-dd.open .objfb-cat-btn", state="visible", timeout=10000)
    page.click(f"{FB} .objfb-dd-cats .objfb-cat-btn[data-args*='service']")
    try:
        page.wait_for_selector(f"{FB} .objfb-dd-item", state="visible", timeout=15000)
    except PWTimeout:
        assert page.query_selector(
            f"{FB} .objfb-dd [data-i18n='gui_fb_browse_error']") is None, \
            "filter-objects browse endpoint returned an error"
        pytest.skip("target PCE object cache has no services to browse")


# ---------------------------------------------------------------------------
# Scenario 1 — category chips (with totals) → Services browse → load more →
#              pick becomes a (direction-less) pill
# ---------------------------------------------------------------------------

def test_filter_modal_service_browse_to_pill(page):
    inp = _open_traffic_filter_modal(page)
    inp.click()

    # Empty input ⇒ category chip row (label / label_group / iplist /
    # workload / service — 'ip' and 'port' are manual-only, no chips).
    page.wait_for_selector(
        f"{FB} .objfb-dd.open .objfb-cat-btn", state="visible", timeout=10000)
    chips = page.query_selector_all(f"{FB} .objfb-dd-cats .objfb-cat-btn")
    assert len(chips) == 5, f"expected 5 category chips, got {len(chips)}"

    # Totals arrive async from /api/filter-objects/browse?type=_totals and
    # re-render the chips with a "(N)" count suffix.
    cnt = page.wait_for_selector(
        f"{FB} .objfb-chip-cnt", state="visible", timeout=15000)
    assert re.search(r"\(\d+\)", cnt.inner_text()), \
        f"chip count malformed: {cnt.inner_text()!r}"

    _open_service_browse(page, inp)

    # "Load more" pagination (only rendered when total > page size).
    n0 = len(page.query_selector_all(f"{FB} .objfb-dd-item"))
    more = page.query_selector(f"{FB} .objfb-dd-more[data-i18n='gui_fb_load_more']")
    if more is not None:
        more.click()
        page.wait_for_function(
            "n => document.querySelectorAll('#qt-filter-bar .objfb-dd-item').length > n",
            arg=n0, timeout=15000)

    # Pick the first service → pill (service pills are direction-less).
    first = page.query_selector(f"{FB} .objfb-dd-item")
    item_name = first.inner_text().split(" — ")[0].strip()
    first.click()
    pill = page.wait_for_selector(f"{FB} .objfb-pill", state="visible", timeout=10000)
    assert item_name in pill.inner_text()
    assert pill.query_selector(".objfb-pill-dir") is None, \
        "service pill must not carry a src/dst direction tag"


# ---------------------------------------------------------------------------
# Scenario 2 — manual port token → pill → popover: no direction row,
#              exclude toggle works
# ---------------------------------------------------------------------------

def test_manual_port_token_pill_and_popover(page):
    inp = _open_traffic_filter_modal(page)
    inp.click()
    inp.fill("443/tcp")

    # Synchronous candidate rendering — "Add Port" group header appears
    # without waiting for the debounced suggest round-trip.
    page.wait_for_selector(
        f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_port']",
        state="visible", timeout=10000)
    inp.press("Enter")

    pill = page.wait_for_selector(f"{FB} .objfb-pill", state="visible", timeout=10000)
    assert "443/tcp" in pill.inner_text()
    assert pill.query_selector(".objfb-pill-dir") is None, \
        "port pill must not carry a src/dst direction tag"

    # Open the edit popover by clicking the pill body.
    pill.query_selector(".objfb-pill-txt").click()
    page.wait_for_selector(f"{FB} .objfb-pop.open", state="visible", timeout=10000)

    # Direction-less category ⇒ no src/dst/any segment in the popover…
    dir_btns = page.query_selector_all(f"{FB} .objfb-pop [data-i18n^='gui_fb_dir_']")
    assert not dir_btns, "port pill popover must not render a direction row"
    # …but the include/exclude toggle is present and functional.
    page.click(f"{FB} .objfb-pop .objfb-pop-btn-danger")
    page.wait_for_selector(
        f"{FB} .objfb-pill.objfb-excl", state="visible", timeout=10000)
    txt = page.query_selector(f"{FB} .objfb-pill .objfb-pill-txt").inner_text()
    assert txt.startswith("!"), f"excluded pill text should start with '!': {txt!r}"


# ---------------------------------------------------------------------------
# Scenario 3 — "Browse all…" → object browser modal → Labels tab → tick 2 →
#              Add → 2 pills
# ---------------------------------------------------------------------------

def test_browse_all_modal_labels_multi_add(page):
    inp = _open_traffic_filter_modal(page)
    inp.click()
    page.wait_for_selector(
        f"{FB} .objfb-dd.open .objfb-cat-btn", state="visible", timeout=10000)
    page.click(f"{FB} .objfb-dd-more[data-i18n='gui_fb_browse_all']")
    page.wait_for_selector("#modal-obj-browser.show", state="visible", timeout=10000)

    # Switch to the Labels tab explicitly (it is also the default).
    page.wait_for_selector("#ob-body .ob-tab", state="visible", timeout=10000)
    page.click("#ob-body .ob-tab[data-i18n='gui_fb_cat_label']")
    try:
        page.wait_for_selector(
            "#ob-table .ob-row input[type=checkbox]", state="attached", timeout=15000)
    except PWTimeout:
        assert page.query_selector(
            "#ob-table [data-i18n='gui_fb_browse_error']") is None, \
            "filter-objects browse endpoint returned an error"
        pytest.skip("target PCE object cache has no labels to browse")

    boxes = page.query_selector_all("#ob-table .ob-row input[type=checkbox]")
    if len(boxes) < 2:
        pytest.skip("fewer than 2 labels on target PCE")
    boxes[0].check()
    boxes[1].check()

    page.click("#ob-add-btn")
    # closeModal() drops the .show class — the selector stops matching.
    page.wait_for_selector("#modal-obj-browser.show", state="detached", timeout=10000)
    assert _pill_count(page) == 2, \
        f"expected 2 label pills after multi-add, got {_pill_count(page)}"


# ---------------------------------------------------------------------------
# Scenario 4 — manual IP/CIDR regression
# ---------------------------------------------------------------------------

def test_manual_ip_cidr_pill(page):
    inp = _open_traffic_filter_modal(page)
    inp.click()
    inp.fill("10.0.0.0/24")
    page.wait_for_selector(
        f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_ipcidr']",
        state="visible", timeout=10000)
    inp.press("Enter")
    pill = page.wait_for_selector(f"{FB} .objfb-pill", state="visible", timeout=10000)
    assert "10.0.0.0/24" in pill.inner_text()


# ---------------------------------------------------------------------------
# Scenario 5 — submitted query payload carries services/ports keys
# ---------------------------------------------------------------------------

def test_query_payload_contains_services_and_ports(page):
    inp = _open_traffic_filter_modal(page)

    # Port pill via manual token.
    inp.click()
    inp.fill("443/tcp")
    page.wait_for_selector(
        f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_port']",
        state="visible", timeout=10000)
    inp.press("Enter")
    page.wait_for_selector(f"{FB} .objfb-pill", state="visible", timeout=10000)

    # Service pill via the Services category browse (input was cleared after
    # the pick, so the dropdown is back on the category chip row).
    _open_service_browse(page, inp)
    page.query_selector(f"{FB} .objfb-dd-item").click()
    page.wait_for_function(
        "() => document.querySelectorAll('#qt-filter-bar .objfb-pill').length === 2",
        timeout=10000)

    # Apply & Query fires POST /api/quarantine/search with the serialized
    # filter dict merged into the payload.
    with page.expect_request(
        lambda r: "/api/quarantine/search" in r.url and r.method == "POST",
        timeout=15000,
    ) as req_info:
        page.click("#modal-qt-filters [data-action='applyQtFilters']")
    payload = req_info.value.post_data_json

    assert payload.get("ports") == ["443/tcp"], \
        f"payload 'ports' wrong: {payload.get('ports')!r}"
    services = payload.get("services")
    assert isinstance(services, list) and services, \
        f"payload 'services' missing/empty: {services!r}"
