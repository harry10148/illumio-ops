"""Phase 2A Task 11 — the FilterBar scenarios, migrated onto the v2 GUI.

## What this replaces

tests/test_gui_e2e_filterbar_playwright.py drove the LEGACY GUI's traffic
filter modal (`#qt-filter-bar`, `.objfb-*` DOM) through ten scenarios. That
GUI is gone. The bar itself is not: src/static/js/v2/components/filter-bar.mjs
is the same serialization core (proven key-for-key equal to the frozen mockup
by tests/design_v2/test_filterbar_semantics.py) behind a reskinned DOM —
`.objfb-col[data-zone=...]` became `[data-zone=...]` inside `[data-cov="XC-03"]`,
`.objfb-pill` became `.fb-pill`, and so on. All ten scenarios are carried over
here against that DOM, one test each, same order, same names where the name
still describes the thing.

## One thing that changed for the better

The legacy file was env-gated on ILLUMIO_OPS_E2E_BASE_URL and skipped its
whole module when unset — i.e. it never ran in CI, only against a staging
appliance someone remembered to point it at. This runs in-process on
tests.v2_e2e_utils's real Flask app, every time.

## Where the object corpus comes from, and what that does and does not prove

Four of the ten scenarios need PCE-sourced objects (services, labels) to
exist. The legacy file `pytest.skip`ped those when the target appliance's
object cache was empty. This harness's PCE is deliberately unreachable, so
they would skip every time — which is the same as deleting them.

Instead, GET /api/filter-objects/browse is fulfilled locally with a small
fixture corpus (Playwright's page.route, the same "stub only the network
boundary" pattern tests/test_v2_investigate_e2e.py already uses for
GET /api/workloads). Named honestly, per Phase 2A finding B2: what is stubbed
is the OBJECT SOURCE. Everything downstream is real — the corpus load, the
category column, the browse list, the object-browser drawer, pill creation,
the zone model, _objfbSerialize, and the real POST /api/quarantine/search
that carries the result. A test that says it verifies the backend's browse
pagination would be overclaiming; none of these do.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

pytest_plugins = ["tests.v2_e2e_utils"]

R_TRAFFIC = "#/investigate/traffic"

# The bar lives inside the advanced-filters drawer, anchored at XC-03.
FB = 'aside.drawer [data-cov="XC-03"]'


def _zone(col: str = "src", neg: str = "false") -> str:
    return f'{FB} [data-zone="{col}:{neg}"]'


def _zone_input(page, col: str = "src", neg: str = "false"):
    return page.locator(f"{_zone(col, neg)} input.fb-input")


def _labels(page):
    return page.evaluate(
        "async () => { const { t } = await import('/static/js/v2/core/i18n.mjs'); "
        "return { filters: t('gui_filter_settings'), browse_all: t('gui_fb_browse_all'), "
        "services: t('gui_fb_cat_service'), labels: t('gui_fb_cat_label'), "
        "transmission: t('gui_fb_cat_transmission'), add: t('gui_add') }; }"
    )


# ── fixture corpus ──────────────────────────────────────────────────────────

FIXTURE_SERVICES = [
    {"name": "HTTP-8080", "href": "/orgs/1/sec_policy/active/services/1", "detail": "8080/tcp"},
    {"name": "HTTPS-8443", "href": "/orgs/1/sec_policy/active/services/2", "detail": "8443/tcp"},
]
FIXTURE_LABELS = [
    {"name": "role=web", "href": "/orgs/1/labels/1", "detail": "role"},
    {"name": "role=db", "href": "/orgs/1/labels/2", "detail": "role"},
    {"name": "env=prod", "href": "/orgs/1/labels/3", "detail": "env"},
]


def _stub_object_corpus(page):
    """Fulfil the two object-source reads locally.

    The bar's corpus is loaded ONCE per mount from two snapshots, not per
    category on demand (filter-bar.mjs's setFilterBarSnapshots):

      fb_browse   GET /api/filter-objects/browse   {groups, items}
      fb_suggest  GET /api/filter-objects/suggest  {ok, results: {<cat>: {items}}}

    Note what this makes possible that the shipped app cannot do without a
    live PCE, and why the legacy scenarios needed a real appliance:
    filter-bar.mjs's own header records that only `label` was ever capturable,
    so a serviceless install genuinely reports "type to search" for the
    Service column. The suggest half below is what puts services in reach —
    which is exactly the object source this module's docstring says is
    stubbed, and nothing more.
    """
    def browse(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "groups": [{"key": "role", "count": 2}, {"key": "env", "count": 1}],
                "items": FIXTURE_LABELS,
                "total": len(FIXTURE_LABELS),
            }),
        )

    def suggest(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"ok": True, "results": {
                "label": {"items": FIXTURE_LABELS, "truncated": False},
                "service": {"items": FIXTURE_SERVICES, "truncated": False},
            }}),
        )

    page.route("**/api/filter-objects/browse*", browse)
    page.route("**/api/filter-objects/suggest*", suggest)


# ── navigation ──────────────────────────────────────────────────────────────

def _open_filter_drawer(page, base_url):
    """Traffic view -> "Filter settings" -> the advanced-filters drawer.

    The legacy counterpart was tab click -> openQtFiltersModal -> #modal-qt-filters.
    """
    page.goto(base_url + "/" + R_TRAFFIC)
    page.wait_for_selector('body[data-booted="true"]')
    page.wait_for_selector('[data-cov="IV-01"]')
    labels = _labels(page)
    page.locator('section[data-cov="IV-01"]').get_by_role(
        "button", name=labels["filters"], exact=True
    ).click()
    page.wait_for_selector(FB)
    return labels


# ── scenario 1 · category list -> service browse -> pill ────────────────────

def test_filter_drawer_service_browse_to_pill(v2_page):
    page, base_url = v2_page
    _stub_object_corpus(page)
    _open_filter_drawer(page, base_url)

    svc = _zone_input(page, "svc")
    svc.click()
    page.wait_for_selector(f"{_zone('svc')} .fb-cat-item")

    # The Service zone offers only the direction-less categories; label /
    # iplist / workload / ip / transmission live in src/dst instead
    # (_objfbZoneCats). The legacy assertion was a count of 6 entries in a
    # differently-shaped list; the invariant kept is the zone scoping itself.
    svc_cats = " | ".join(page.locator(f"{_zone('svc')} .fb-cat-item").all_inner_texts())
    assert "label" not in svc_cats.lower()

    page.locator(f"{_zone('svc')} .fb-cat-item").filter(
        has_text=_labels(page)["services"]
    ).first.click()
    page.wait_for_selector(f"{_zone('svc')} .fb-dd-item")

    first = page.locator(f"{_zone('svc')} .fb-dd-item").first
    name = first.inner_text().split("\n")[0].strip()
    first.click()

    pill = page.locator(f"{_zone('svc')} .fb-pill").first
    pill.wait_for(state="visible")
    assert name in pill.inner_text()
    # Direction-less pills are proven by zone placement: the locator above is
    # scoped to the svc zone, which only exists for direction-less categories.


# ── scenario 2 · manual port token -> pill -> popover ───────────────────────

def test_manual_port_token_pill_and_popover(v2_page):
    page, base_url = v2_page
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "svc")
    inp.click()
    inp.fill("443/tcp")
    # Candidates render synchronously — no debounced round trip needed.
    page.wait_for_selector(f"{FB} .fb-dd-item")
    inp.press("Enter")

    pill = page.locator(f"{_zone('svc')} .fb-pill").first
    pill.wait_for(state="visible")
    assert "443/tcp" in pill.inner_text()

    pill.locator(".fb-pill-txt").click()
    page.wait_for_selector(f"{FB} .fb-pop")

    # A direction-less category renders no src/dst segment in the popover...
    pop = page.locator(f"{FB} .fb-pop")
    assert pop.locator(".fb-seg").count() == 0 or "src" not in pop.inner_text().lower()
    # ...but the include/exclude toggle is there and works.
    pop.locator(".fb-seg-btn.danger, button.danger").first.click()
    page.wait_for_selector(f"{_zone('svc', 'true')} .fb-pill")
    txt = page.locator(f"{_zone('svc', 'true')} .fb-pill .fb-pill-txt").first.inner_text()
    assert txt.startswith("!"), txt


# ── scenario 3 · browse-all -> object browser -> multi-add ──────────────────

def test_browse_all_object_browser_labels_multi_add(v2_page):
    page, base_url = v2_page
    _stub_object_corpus(page)
    labels = _open_filter_drawer(page, base_url)

    src = _zone_input(page, "src")
    src.click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    page.locator(f"{_zone('src')} .fb-cat-item").filter(
        has_text=labels["browse_all"]
    ).first.click()

    # XC-04 — in v2 the object browser is a drawer, not a modal.
    browser = page.locator('[data-cov="XC-04"]')
    browser.wait_for(state="visible")

    boxes = browser.locator('input[type="checkbox"]')
    boxes.first.wait_for(state="visible")
    assert boxes.count() >= 2, boxes.count()
    boxes.nth(0).check()
    boxes.nth(1).check()

    # The browser is a drawer stacked on top of the filters drawer, and its
    # save button lives in the drawer FOOTER, outside the XC-04 body — so
    # target the newest drawer's footer, not the anchor's subtree.
    page.locator("aside.drawer .drawer-f button.btn.primary").last.click()
    page.wait_for_function(
        "() => document.querySelectorAll('[data-cov=\"XC-03\"] .fb-pill').length === 2"
    )


# ── scenario 4 · manual IP/CIDR ─────────────────────────────────────────────

def test_manual_ip_cidr_pill(v2_page):
    page, base_url = v2_page
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.0/24")
    page.wait_for_selector(f"{FB} .fb-dd-item")
    inp.press("Enter")

    pill = page.locator(f"{_zone('src')} .fb-pill").first
    pill.wait_for(state="visible")
    assert "10.0.0.0/24" in pill.inner_text()


# ── scenario 5 · the submitted payload carries services and ports ───────────

def test_query_payload_contains_services_and_ports(v2_page):
    page, base_url = v2_page
    _stub_object_corpus(page)
    labels = _open_filter_drawer(page, base_url)

    svc = _zone_input(page, "svc")
    svc.click()
    svc.fill("443/tcp")
    page.wait_for_selector(f"{FB} .fb-dd-item")
    svc.press("Enter")
    page.wait_for_selector(f"{_zone('svc')} .fb-pill")

    svc.click()
    page.locator(f"{_zone('svc')} .fb-cat-item").filter(
        has_text=labels["services"]
    ).first.click()
    page.wait_for_selector(f"{_zone('svc')} .fb-dd-item")
    page.locator(f"{_zone('svc')} .fb-dd-item").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('[data-cov=\"XC-03\"] .fb-pill').length === 2"
    )

    with page.expect_request(
        lambda r: "/api/quarantine/search" in r.url and r.method == "POST"
    ) as info:
        page.locator("aside.drawer .drawer-f button.btn.primary").click()
    payload = info.value.post_data_json

    assert payload.get("ports") == ["443/tcp"], payload.get("ports")
    services = payload.get("services")
    assert isinstance(services, list) and services, services


# ── scenarios 6-10 · the v2 zone model ──────────────────────────────────────

def test_three_column_layout_and_exclusion_row_collapsed(v2_page):
    page, base_url = v2_page
    _open_filter_drawer(page, base_url)

    for col in ("src", "dst", "svc"):
        assert page.locator(_zone(col)).count() == 1, col
    # The is-not row is collapsed by default (spec §3.1).
    assert not page.locator(_zone("src", "true")).is_visible()
    page.locator(f"{FB} .fb-excl").first.click()
    page.wait_for_selector(_zone("src", "true"), state="visible")


def test_mode_toggle_migrates_pills_between_and_and_or(v2_page):
    page, base_url = v2_page
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.1")
    page.wait_for_selector(f"{FB} .fb-dd-item")
    inp.press("Enter")
    page.wait_for_selector(f"{_zone('src')} .fb-pill")

    page.locator(f"{FB} .fb-mode").first.click()      # AND -> OR
    page.wait_for_selector(f"{_zone('any')} .fb-pill")
    assert "OR" in page.locator(f"{FB} .fb-mode").first.inner_text()

    page.locator(f"{FB} .fb-mode").first.click()      # OR -> AND, back to src
    page.wait_for_selector(f"{_zone('src')} .fb-pill")
    assert page.locator(f"{FB} .fb-hint").count() >= 1


def test_swap_moves_a_pill_between_columns(v2_page):
    page, base_url = v2_page
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("10.0.0.2")
    page.wait_for_selector(f"{FB} .fb-dd-item")
    inp.press("Enter")
    page.wait_for_selector(f"{_zone('src')} .fb-pill")

    page.locator(f"{FB} .fb-swap").first.click()
    page.wait_for_selector(f"{_zone('dst')} .fb-pill")
    assert page.locator(f"{_zone('src')} .fb-pill").count() == 0


def test_service_column_offers_the_three_way_port_candidates(v2_page):
    """spec §3.2: typing 443 offers both / tcp / udp; Enter takes the default."""
    page, base_url = v2_page
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "svc")
    inp.click()
    inp.fill("443")
    page.wait_for_selector(f"{FB} .fb-dd-item")
    texts = " | ".join(page.locator(f"{FB} .fb-dd-item").all_inner_texts())
    assert "443/tcp" in texts and "443/udp" in texts, texts

    inp.press("Enter")
    pill = page.locator(f"{_zone('svc')} .fb-pill").first
    pill.wait_for(state="visible")
    assert "443" in pill.inner_text()
    # The default candidate is the protocol-agnostic one, so the committed
    # pill must NOT have collapsed onto a single protocol.
    assert "/tcp" not in pill.inner_text() and "/udp" not in pill.inner_text()


def test_transmission_category_is_destination_only(v2_page):
    page, base_url = v2_page
    labels = _open_filter_drawer(page, base_url)

    _zone_input(page, "dst").click()
    page.wait_for_selector(f"{_zone('dst')} .fb-cat-item")
    dst_cats = " | ".join(page.locator(f"{_zone('dst')} .fb-cat-item").all_inner_texts())
    assert labels["transmission"] in dst_cats, dst_cats

    _zone_input(page, "src").click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    src_cats = " | ".join(page.locator(f"{_zone('src')} .fb-cat-item").all_inner_texts())
    assert labels["transmission"] not in src_cats, src_cats
