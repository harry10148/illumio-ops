"""End-to-end browser tests for the PCE-style filter bar service/port pills.

Scenario coverage (feat/port-service-filter Task 13; migrated to the v2
zone-model DOM and extended with v2-specific scenarios by FilterBar v2 Plan B
Task 6):

  1. Traffic Analyzer filter modal: click empty input → category list (with
     object totals) → click Services → grouped browse list → "Load more"
     grows the list → picking an item becomes a pill.
  2. Manual port token ``443/tcp`` (typed in the Service zone) → "Add Port"
     candidate → Enter turns it into a pill → clicking the pill opens a
     popover WITHOUT the direction row but WITH a working include/exclude
     toggle.
  3. Dropdown footer "Browse all…" → object browser modal → Labels tab →
     tick 2 rows → Add → 2 pills appear in the bar.
  4. Manual IP/CIDR regression: ``10.0.0.0/24`` (typed in the Source zone) →
     "Add IP/CIDR" candidate → Enter turns it into a pill.
  5. Submitting the query POSTs /api/quarantine/search with ``services`` and
     ``ports`` keys in the JSON payload.
  6-10. v2 zone-model scenarios: three-column layout + collapsed exclusion
     row, AND/OR mode toggle migrating pills between columns, source/
     destination swap, the Service column's numeric three-way (both/tcp/udp)
     candidate guidance, and Transmission being a destination-only category.

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

v2 DOM notes (see src/static/js/filter-bar.js): every FilterBar instance now
renders 4-6 "zones" (``.objfb-col[data-zone='<col>:<neg>']`` for
col ∈ src|dst|any|svc and neg ∈ false|true), each with its own
``.objfb-input``/``.objfb-dd`` — so any locator that used to be
``f"{FB} .objfb-input"`` must now be scoped to a zone or Playwright's strict
mode raises on the multiple matches. Manual port tokens (dirless category)
are only recognized when typed in the Service zone; manual IP/CIDR tokens
are only recognized in a non-Service zone. The is-not exclusion row is
collapsed by default. Category browsing moved from a top "chip" row to a
persistent right-hand column (``.objfb-dd-catlist .objfb-cat-item``) that is
zone-scoped (e.g. only the Service zone offers the Services category; only
Destination/merged-any offers Transmission).
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


def _zone(col="src", neg="false"):
    return f"{FB} .objfb-col[data-zone='{col}:{neg}']"


def _zone_input(page, col="src", neg="false"):
    return page.locator(f"{_zone(col, neg)} .objfb-input")


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

    Returns the Source zone's text input as a Playwright locator (re-resolved
    on every action, so it survives re-renders instead of going stale like a
    snapshotted ElementHandle would). Other zones must be obtained via
    ``_zone_input`` explicitly — v2 has one input per zone.
    """
    tab = page.locator('[data-args=\'["traffic-workload"]\']')
    tab.click(timeout=10000)
    btn = page.locator("[data-action='openQtFiltersModal']")
    btn.click(timeout=10000)
    page.wait_for_selector("#modal-qt-filters.show", state="visible", timeout=10000)
    inp = _zone_input(page, "src")
    inp.wait_for(state="visible", timeout=10000)
    return inp


def _pill_count(page) -> int:
    return page.locator(f"{FB} .objfb-pill").count()


def _open_service_browse(page):
    """Focus the Service zone's empty input → click the Services category
    item in the zone's category column → wait for the grouped browse list.
    Skips (not fails) when the PCE has no services, but fails loudly when
    the browse endpoint itself errors.

    Services only live in the Service zone (spec §3.1/_objfbZoneCats), so
    this always targets ``_zone('svc')`` regardless of which zone is
    currently focused.
    """
    svc_inp = _zone_input(page, "svc")
    svc_inp.click()
    page.wait_for_selector(
        f"{_zone('svc')} .objfb-dd.open .objfb-cat-item", state="visible", timeout=10000)
    # data-args is a JSON array like ["objfb-1","service"] — match the quoted
    # value so "service" doesn't also match the "winservice" category item.
    page.locator(
        f"{_zone('svc')} .objfb-dd-catlist .objfb-cat-item[data-args*='\"service\"']"
    ).click()
    try:
        page.wait_for_selector(f"{_zone('svc')} .objfb-dd-item", state="visible", timeout=15000)
    except PWTimeout:
        assert page.locator(
            f"{_zone('svc')} .objfb-dd [data-i18n='gui_fb_browse_error']").count() == 0, \
            "filter-objects browse endpoint returned an error"
        pytest.skip("target PCE object cache has no services to browse")


# ---------------------------------------------------------------------------
# Scenario 1 — category list (with totals) → Services browse → load more →
#              pick becomes a (direction-less) pill, landing in the Service
#              zone
# ---------------------------------------------------------------------------

def test_filter_modal_service_browse_to_pill(page):
    _open_traffic_filter_modal(page)
    svc_inp = _zone_input(page, "svc")
    svc_inp.click()

    # Empty input ⇒ right-hand category list. The Service zone only offers
    # service/port/process/winservice (label/iplist/workload/ip/transmission
    # live in the Source/Destination zones instead — _objfbZoneCats).
    page.wait_for_selector(
        f"{_zone('svc')} .objfb-dd.open .objfb-cat-item", state="visible", timeout=10000)
    cats = page.locator(f"{_zone('svc')} .objfb-dd-catlist .objfb-cat-item")
    # "Search All Categories" header + 4 categories + "Browse all…" footer.
    assert cats.count() == 6, f"expected 6 cat-list entries, got {cats.count()}"

    # Totals arrive async from /api/filter-objects/browse?type=_totals and
    # re-render the category list with a "(N)" count suffix.
    cnt = page.locator(f"{_zone('svc')} .objfb-chip-cnt").first
    cnt.wait_for(state="visible", timeout=15000)
    cnt_text = cnt.inner_text()
    assert re.search(r"\(\d+\)", cnt_text), f"chip count malformed: {cnt_text!r}"

    _open_service_browse(page)

    # "Load more" pagination (only rendered when total > page size).
    items = page.locator(f"{_zone('svc')} .objfb-dd-item")
    n0 = items.count()
    more = page.locator(f"{_zone('svc')} .objfb-dd-more[data-i18n='gui_fb_load_more']")
    if more.count() > 0:
        more.click()
        page.wait_for_function(
            "n => document.querySelectorAll("
            "\"#qt-filter-bar .objfb-col[data-zone='svc:false'] .objfb-dd-item\""
            ").length > n",
            arg=n0, timeout=15000)

    # Pick the first service → pill (service pills are direction-less and
    # land in the Service zone).
    first = page.locator(f"{_zone('svc')} .objfb-dd-item").first
    item_name = first.inner_text().split(" — ")[0].strip()
    first.click()
    pill = page.locator(f"{_zone('svc')} .objfb-pill").first
    pill.wait_for(state="visible", timeout=10000)
    assert item_name in pill.inner_text()
    # v2 has no `.objfb-pill-dir` class — direction-less pills are proven by
    # zone placement instead: the pill locator above is already scoped to
    # `_zone('svc')`, which only exists for direction-less categories.


# ---------------------------------------------------------------------------
# Scenario 2 — manual port token (Service zone) → pill → popover: no
#              direction row, exclude toggle works
# ---------------------------------------------------------------------------

def test_manual_port_token_pill_and_popover(page):
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "svc")
    inp.click()
    inp.fill("443/tcp")

    # Synchronous candidate rendering — "Add Port" group header appears
    # without waiting for the debounced suggest round-trip.
    page.wait_for_selector(
        f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_port']",
        state="visible", timeout=10000)
    inp.press("Enter")

    pill = page.locator(f"{_zone('svc')} .objfb-pill").first
    pill.wait_for(state="visible", timeout=10000)
    assert "443/tcp" in pill.inner_text()
    # v2 has no `.objfb-pill-dir` class — direction-less pills are proven by
    # zone placement instead: the pill locator above is already scoped to
    # `_zone('svc')`, which only exists for direction-less categories.

    # Open the edit popover by clicking the pill body.
    pill.locator(".objfb-pill-txt").click()
    page.wait_for_selector(f"{FB} .objfb-pop.open", state="visible", timeout=10000)

    # Direction-less category ⇒ no src/dst segment in the popover…
    dir_btns = page.locator(f"{FB} .objfb-pop [data-i18n^='gui_fb_dir_']")
    assert dir_btns.count() == 0, "port pill popover must not render a direction row"
    # …but the include/exclude toggle is present and functional.
    page.locator(f"{FB} .objfb-pop .objfb-pop-btn-danger").click()
    page.wait_for_selector(
        f"{_zone('svc', 'true')} .objfb-pill.objfb-excl", state="visible", timeout=10000)
    txt = page.locator(f"{_zone('svc', 'true')} .objfb-pill .objfb-pill-txt").first.inner_text()
    assert txt.startswith("!"), f"excluded pill text should start with '!': {txt!r}"


# ---------------------------------------------------------------------------
# Scenario 3 — "Browse all…" → object browser modal → Labels tab → tick 2 →
#              Add → 2 pills
# ---------------------------------------------------------------------------

def test_browse_all_modal_labels_multi_add(page):
    inp = _open_traffic_filter_modal(page)
    inp.click()
    page.wait_for_selector(
        f"{_zone('src')} .objfb-dd.open .objfb-cat-item", state="visible", timeout=10000)
    # "Browse all…" is now the persistent category column's footer entry
    # (v1's top "chip row" dropdown-more button is gone in v2).
    page.locator(
        f"{_zone('src')} .objfb-dd-catlist .objfb-cat-item[data-i18n='gui_fb_browse_all']"
    ).click()
    page.wait_for_selector("#modal-obj-browser.show", state="visible", timeout=10000)

    # Switch to the Labels tab explicitly (it is also the default).
    page.wait_for_selector("#ob-body .ob-tab", state="visible", timeout=10000)
    page.locator("#ob-body .ob-tab[data-i18n='gui_fb_cat_label']").click()
    try:
        page.wait_for_selector(
            "#ob-table .ob-row input[type=checkbox]", state="attached", timeout=15000)
    except PWTimeout:
        assert page.locator(
            "#ob-table [data-i18n='gui_fb_browse_error']").count() == 0, \
            "filter-objects browse endpoint returned an error"
        pytest.skip("target PCE object cache has no labels to browse")

    boxes = page.locator("#ob-table .ob-row input[type=checkbox]")
    if boxes.count() < 2:
        pytest.skip("fewer than 2 labels on target PCE")
    boxes.nth(0).check()
    boxes.nth(1).check()

    page.locator("#ob-add-btn").click()
    # closeModal() drops the .show class — the selector stops matching.
    page.wait_for_selector("#modal-obj-browser.show", state="detached", timeout=10000)
    assert _pill_count(page) == 2, \
        f"expected 2 label pills after multi-add, got {_pill_count(page)}"


# ---------------------------------------------------------------------------
# Scenario 4 — manual IP/CIDR regression (Source zone; IP/CIDR is not
#              recognized in the Service zone)
# ---------------------------------------------------------------------------

def test_manual_ip_cidr_pill(page):
    inp = _open_traffic_filter_modal(page)
    inp.click()
    inp.fill("10.0.0.0/24")
    page.wait_for_selector(
        f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_ipcidr']",
        state="visible", timeout=10000)
    inp.press("Enter")
    pill = page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    assert "10.0.0.0/24" in pill.inner_text()


# ---------------------------------------------------------------------------
# Scenario 5 — submitted query payload carries services/ports keys
# ---------------------------------------------------------------------------

def test_query_payload_contains_services_and_ports(page):
    _open_traffic_filter_modal(page)

    # Port pill via manual token (Service zone only — dirless category).
    svc_inp = _zone_input(page, "svc")
    svc_inp.click()
    svc_inp.fill("443/tcp")
    page.wait_for_selector(
        f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_port']",
        state="visible", timeout=10000)
    svc_inp.press("Enter")
    page.wait_for_selector(f"{_zone('svc')} .objfb-pill", state="visible", timeout=10000)

    # Service pill via the Services category browse (input was cleared after
    # the pick, so the dropdown is back on the category list).
    _open_service_browse(page)
    page.locator(f"{_zone('svc')} .objfb-dd-item").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('#qt-filter-bar .objfb-pill').length === 2",
        timeout=10000)

    # Apply & Query fires POST /api/quarantine/search with the serialized
    # filter dict merged into the payload.
    with page.expect_request(
        lambda r: "/api/quarantine/search" in r.url and r.method == "POST",
        timeout=15000,
    ) as req_info:
        page.locator("#modal-qt-filters [data-action='applyQtFilters']").click()
    payload = req_info.value.post_data_json

    assert payload.get("ports") == ["443/tcp"], \
        f"payload 'ports' wrong: {payload.get('ports')!r}"
    services = payload.get("services")
    assert isinstance(services, list) and services, \
        f"payload 'services' missing/empty: {services!r}"


# ---------------------------------------------------------------------------
# Scenario 6-10 — v2 zone-model scenarios (FilterBar v2 Plan B)
# ---------------------------------------------------------------------------

def test_v2_three_column_layout_and_excl_collapse(page):
    _open_traffic_filter_modal(page)
    for col in ("src", "dst", "svc"):
        assert page.locator(_zone(col)).count() == 1, f"include column {col} missing"
    # is-not 排除列預設收合（spec §3.1）
    assert not page.locator(_zone("src", "true")).is_visible()
    page.locator(f"{FB} .objfb-excl-toggle").click()
    page.wait_for_selector(_zone("src", "true"), state="visible", timeout=10000)


def test_v2_mode_toggle_migrates_pills(page):
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.1")
    page.wait_for_selector(f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_ipcidr']",
                           state="visible", timeout=10000)
    inp.press("Enter")
    page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    page.locator(f"{FB} .objfb-mode").first.click()   # AND → OR
    page.wait_for_selector(f"{_zone('any')} .objfb-pill", state="visible", timeout=10000)
    assert "OR" in page.locator(f"{FB} .objfb-mode").first.inner_text()
    page.locator(f"{FB} .objfb-mode").first.click()   # OR → AND：回 Source 欄 + 提示
    page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    assert page.locator(f"{FB} .objfb-hint[data-i18n='gui_fb_moved_any_src']").is_visible()


def test_v2_swap_moves_pill_between_columns(page):
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.2")
    page.wait_for_selector(f"{FB} .objfb-dd-hdr[data-i18n='gui_fb_add_ipcidr']",
                           state="visible", timeout=10000)
    inp.press("Enter")
    page.wait_for_selector(f"{_zone('src')} .objfb-pill", state="visible", timeout=10000)
    page.locator(f"{FB} .objfb-swap").first.click()
    page.wait_for_selector(f"{_zone('dst')} .objfb-pill", state="visible", timeout=10000)
    assert page.locator(f"{_zone('src')} .objfb-pill").count() == 0


def test_v2_service_column_three_way_candidates(page):
    """spec §3.2：輸入 443 → 兩者（預設）/tcp/udp 三選一；Enter 取預設成 443 (TCP+UDP) pill。"""
    _open_traffic_filter_modal(page)
    inp = _zone_input(page, "svc")
    inp.click()
    inp.fill("443")
    page.wait_for_selector(f"{FB} .objfb-dd-tag-both", state="visible", timeout=10000)
    items = page.locator(f"{FB} .objfb-dd-main .objfb-dd-item")
    texts = " | ".join(items.all_inner_texts())
    assert "443/tcp" in texts and "443/udp" in texts
    inp.press("Enter")
    pill = page.locator(f"{_zone('svc')} .objfb-pill").first
    pill.wait_for(state="visible", timeout=10000)
    assert "443 (TCP+UDP)" in pill.inner_text()


def test_v2_transmission_category_only_in_destination(page):
    _open_traffic_filter_modal(page)
    _zone_input(page, "dst").click()
    page.wait_for_selector(f"{_zone('dst')} .objfb-dd.open", state="visible", timeout=10000)
    dst_cats = " | ".join(page.locator(f"{_zone('dst')} .objfb-cat-item").all_inner_texts())
    assert "Transmission" in dst_cats or "傳輸型態" in dst_cats
    _zone_input(page, "src").click()
    page.wait_for_selector(f"{_zone('src')} .objfb-dd.open", state="visible", timeout=10000)
    src_cats = " | ".join(page.locator(f"{_zone('src')} .objfb-cat-item").all_inner_texts())
    assert "Transmission" not in src_cats and "傳輸型態" not in src_cats
