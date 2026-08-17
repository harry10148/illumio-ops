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

Instead, both /api/filter-objects routes are fulfilled locally with a small
fixture corpus (Playwright's page.route, the same "stub only the network
boundary" pattern tests/test_v2_investigate_e2e.py already uses for
GET /api/workloads). See _stub_object_corpus below for exactly what that stub
does and does not stand in for.

## The live-query scenarios (2026-08-17)

The bar was wired to two captured payloads: one category had rows, the other
four said "type to search" forever, typing filtered the captured page instead
of asking the server, and the category counts came from that page's own total.
It now queries the endpoints per keystroke and per category. The scenarios
below the original ten cover that wiring at the network boundary — the request
that goes out, the debounce that keeps it to one per burst, the states for
"cannot browse this category" and "could not reach the PCE" — because a
screen that renders is not evidence that anything was asked.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

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
        "transmission: t('gui_fb_cat_transmission'), add: t('gui_add'), "
        "iplists: t('gui_fb_cat_iplist'), workloads: t('gui_fb_cat_workload'), "
        "label_groups: t('gui_fb_cat_label_group'), search_only: t('gui_fb_search_only'), "
        "retry: t('gui_fb_retry'), no_match: t('gui_fb_no_match'), "
        "loading: t('gui_fb_loading') }; }"
    )


# ── fixture corpus ──────────────────────────────────────────────────────────

FIXTURE_SERVICES = [
    {"name": "HTTP-8080", "href": "/orgs/1/sec_policy/active/services/1", "summary": "8080/tcp"},
    {"name": "HTTPS-8443", "href": "/orgs/1/sec_policy/active/services/2", "summary": "8443/tcp"},
]
FIXTURE_LABELS = [
    {"name": "role=web", "href": "/orgs/1/labels/1", "key": "role", "value": "web"},
    {"name": "role=db", "href": "/orgs/1/labels/2", "key": "role", "value": "db"},
    {"name": "env=prod", "href": "/orgs/1/labels/3", "key": "env", "value": "prod"},
]
FIXTURE_LABEL_GROUPS = [
    {"name": "WebTier-Group", "href": "/orgs/1/sec_policy/active/label_groups/1"},
    {"name": "DBTier-Group", "href": "/orgs/1/sec_policy/active/label_groups/2"},
]
FIXTURE_IPLISTS = [
    {"name": "Corp-Networks", "href": "/orgs/1/sec_policy/active/ip_lists/1",
     "summary": "10.0.0.0/8, 192.168.0.0/16"},
]
# workloads have NO browse endpoint at all — suggest is their only access path
# (filter_objects.py:66-67 answers type=workload with browseable:false), so this
# corpus is deliberately reachable by search only.
FIXTURE_WORKLOADS = [
    {"name": "web-01", "href": "/orgs/1/workloads/w1", "hostname": "web-01.corp", "ip": "10.1.1.4"},
    {"name": "web-02", "href": "/orgs/1/workloads/w2", "hostname": "web-02.corp", "ip": "10.1.1.5"},
]
FIXTURE = {
    "label": FIXTURE_LABELS,
    "label_group": FIXTURE_LABEL_GROUPS,
    "iplist": FIXTURE_IPLISTS,
    "service": FIXTURE_SERVICES,
    "workload": FIXTURE_WORKLOADS,
}
BROWSEABLE = ("label", "label_group", "iplist", "service")

# A collection longer than one browse page, for the paging scenario. Named so it
# matches none of the search queries the other scenarios type, so switching it
# on cannot change what they see.
BIG_LABELS = [
    {"name": f"tier{n:02d}=z", "href": f"/orgs/1/labels/b{n}", "key": f"tier{n:02d}", "value": "z"}
    for n in range(45)
]


def _stub_object_corpus(page):
    """Fulfil the two object-source reads locally, per request.

    The bar asks the server for what it needs, when it needs it
    (filter-bar.mjs's setFilterBarQuery, over core/filter-objects.mjs):

      GET /api/filter-objects/suggest?q=&types=&limit=   per keystroke, debounced
      GET /api/filter-objects/browse?type=&offset=&limit= per category opened
      GET /api/filter-objects/browse?type=_totals        once per bar

    So the stub answers per request rather than handing over one fixed page,
    and it reproduces the shapes the real route actually returns — including
    the two that are easy to mistake for data: `type=workload` answers
    browseable:false with an empty list, and a category the PCE could not
    reach answers `error: "pce_unreachable"` INSIDE a 200.

    Named honestly, per Phase 2A finding B2: what is stubbed is the OBJECT
    SOURCE — the PCE side of these two routes. Everything downstream is real:
    the debounce, the per-(category, query) cache, the paging, the category
    counts, the loading/error/retry states, the object-browser drawer, pill
    creation, the zone model, _objfbSerialize and the real POST
    /api/quarantine/search that carries the result. A test that claimed to
    verify the backend's own browse pagination would be overclaiming; none do.

    Returns a control dict the caller can mutate and read:
      fail_browse   {cat, ...}  -> answer those browse calls with a 502
      fail_suggest  {cat, ...}  -> mark those categories `error` inside a 200
      fail_totals   bool        -> answer type=_totals with a 502
      big_label_corpus bool     -> serve BIG_LABELS from browse, for paging
      hold_browse   {cat, ...}  -> do not answer those browse calls yet; the
                                   answer is parked in `held` for the test to
                                   release, which is how the in-flight state
                                   becomes observable instead of a race
      held         [callable]   -> release a parked answer by calling it
      browse_calls / suggest_calls -> the requests that actually arrived
    """
    ctl = {
        "fail_browse": set(),
        "fail_suggest": set(),
        "fail_totals": False,
        "big_label_corpus": False,
        "hold_browse": set(),
        "held": [],
        "browse_calls": [],
        "suggest_calls": [],
    }

    def _args(route):
        return parse_qs(urlparse(route.request.url).query)

    def _json(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))

    def browse(route):
        args = _args(route)
        btype = (args.get("type") or [""])[0]
        offset = int((args.get("offset") or ["0"])[0])
        limit = int((args.get("limit") or ["20"])[0])
        ctl["browse_calls"].append((btype, offset, limit))

        def answer():
            if btype == "_totals":
                if ctl["fail_totals"]:
                    _json(route, {"ok": False, "error": "pce_unreachable"}, status=502)
                    return
                _json(route, {"ok": True, "totals": {c: len(FIXTURE[c]) for c in BROWSEABLE}})
                return
            if btype == "workload":
                _json(route, {"ok": True, "browseable": False, "items": [], "total": None})
                return
            if btype not in BROWSEABLE:
                _json(route, {"ok": False, "error": "unknown_type"}, status=400)
                return
            if btype in ctl["fail_browse"]:
                _json(route, {"ok": False, "error": "pce_unreachable"}, status=502)
                return
            rows = BIG_LABELS if (btype == "label" and ctl["big_label_corpus"]) else FIXTURE[btype]
            page_rows = rows[offset:offset + limit]
            body = {"ok": True, "items": page_rows, "total": len(rows),
                    "truncated": offset + limit < len(rows)}
            if btype == "label":
                body["groups"] = [{"key": "role", "count": 2}, {"key": "env", "count": 1}]
            _json(route, body)

        if btype in ctl["hold_browse"]:
            ctl["held"].append(answer)
            return
        answer()

    def suggest(route):
        args = _args(route)
        q = (args.get("q") or [""])[0].lower()
        types = [ty for ty in (args.get("types") or [""])[0].split(",") if ty]
        ctl["suggest_calls"].append((q, tuple(types)))
        results = {}
        for ty in types:
            if ty in ctl["fail_suggest"]:
                results[ty] = {"items": [], "truncated": False, "error": "pce_unreachable"}
                continue
            hits = [r for r in FIXTURE.get(ty, []) if q in r["name"].lower()]
            results[ty] = {"items": hits, "truncated": False}
        _json(route, {"ok": True, "results": results})

    page.route("**/api/filter-objects/browse*", browse)
    page.route("**/api/filter-objects/suggest*", suggest)
    return ctl


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
    # .fb-dd-txt is the object's NAME; the row also carries a type code chip and
    # (for a service) its ports, and reading the row's whole text would let the
    # assertion below pass on the type code alone.
    name = first.locator(".fb-dd-txt").inner_text().strip()
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


# ── live queries · the wiring itself ────────────────────────────────────────
#
# Everything below asserts at the network boundary — WHICH request went out,
# with which parameters, and how many. A dropdown full of rows proves nothing
# about that: the bug these cover shipped with a full dropdown (one captured
# page of labels, filtered in the browser, for every category and every
# keystroke).

def _query_args(request):
    return parse_qs(urlparse(request.url).query)


def test_typing_issues_a_suggest_request_for_this_zones_categories(v2_page):
    page, base_url = v2_page
    _stub_object_corpus(page)
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    with page.expect_request(
        lambda r: "/api/filter-objects/suggest" in r.url and r.method == "GET"
    ) as info:
        inp.fill("role")
    args = _query_args(info.value)

    assert args.get("q") == ["role"], args
    # The Source zone's suggestable categories, and only those: `service` lives
    # in the Service column and `ip` has no suggest endpoint at all
    # (_objfbZoneCats ∩ _OBJFB_SUGGEST_CATS). A wider request would put service
    # rows under Source; a narrower one would hide a category the pane offers.
    assert set(args["types"][0].split(",")) == {"label", "label_group", "iplist", "workload"}, args

    # ...and the answer is what the list shows: two of the three fixture labels
    # match "role", and nothing in the other three categories does.
    page.wait_for_selector(f'{FB} .fb-dd-item[data-cat="label"]')
    assert page.locator(f'{FB} .fb-dd-item[data-cat="label"]').count() == 2
    assert page.locator(f"{FB} .fb-dd-item:not([data-cat='label'])").count() == 0


def test_typing_a_burst_costs_one_suggest_request(v2_page):
    """The debounce. Four characters inside the 250 ms window = one request."""
    page, base_url = v2_page
    ctl = _stub_object_corpus(page)
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    inp.press_sequentially("role", delay=40)
    page.wait_for_selector(f'{FB} .fb-dd-item[data-cat="label"]')
    # Wait past the debounce window again before counting, so this cannot pass
    # merely by looking before a per-character burst finished arriving.
    page.wait_for_timeout(600)

    assert [call[0] for call in ctl["suggest_calls"]] == ["role"], ctl["suggest_calls"]

    # Retyping the same query asks nothing more: the (category, query) answers
    # are cached for the life of the bar.
    inp.fill("")
    inp.fill("role")
    page.wait_for_timeout(600)
    assert [call[0] for call in ctl["suggest_calls"]] == ["role"], ctl["suggest_calls"]


def test_selecting_a_non_label_category_browses_it_from_the_server(v2_page):
    page, base_url = v2_page
    _stub_object_corpus(page)
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    with page.expect_request(
        lambda r: "/api/filter-objects/browse" in r.url and "type=iplist" in r.url
    ):
        page.locator(f"{_zone('src')} .fb-cat-item").filter(
            has_text=labels["iplists"]
        ).first.click()

    row = page.locator(f'{_zone("src")} .fb-dd-item[data-cat="iplist"]').first
    row.wait_for(state="visible")
    assert "Corp-Networks" in row.inner_text()
    # The row carries what only an IP list carries — its ranges. Before this
    # wiring every scope but Labels could only ever say "type to search",
    # because the one captured payload held labels.
    assert "10.0.0.0/8" in row.locator(".fb-dd-sub").inner_text()

    row.click()
    pill = page.locator(f"{_zone('src')} .fb-pill").first
    pill.wait_for(state="visible")
    assert "Corp-Networks" in pill.inner_text()


def test_workload_category_says_search_only_instead_of_an_empty_list(v2_page):
    """browseable:false is a property of the category, not an outage — and not
    zero rows. Workloads have no browse endpoint (filter_objects.py:66-67)."""
    page, base_url = v2_page
    _stub_object_corpus(page)
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    page.locator(f"{_zone('src')} .fb-cat-item").filter(
        has_text=labels["workloads"]
    ).first.click()

    note = page.locator(f"{_zone('src')} .fb-dd-note").filter(
        has_text=labels["search_only"]
    ).first
    note.wait_for(state="visible")
    assert page.locator(f"{_zone('src')} .fb-dd-item").count() == 0
    assert page.locator(f"{_zone('src')} .fb-dd-empty").count() == 0

    # ...and the category IS reachable — by searching it.
    inp.fill("web")
    row = page.locator(f'{_zone("src")} .fb-dd-item[data-cat="workload"]').first
    row.wait_for(state="visible")
    assert "web-01" in row.inner_text()
    # a workload states its hostname/address, which is its own kind of detail
    assert "10.1.1.4" in row.locator(".fb-dd-sub").inner_text()


def test_the_object_browser_says_search_only_without_an_empty_table(v2_page):
    """XC-04 reads the same two endpoints, so it inherits the same rule: a
    category that cannot be listed says so, and does NOT get the table's own
    "no data available" card underneath saying the opposite."""
    page, base_url = v2_page
    _stub_object_corpus(page)
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    page.locator(f"{_zone('src')} .fb-cat-item").filter(
        has_text=labels["browse_all"]
    ).first.click()
    browser = page.locator('[data-cov="XC-04"]')
    browser.wait_for(state="visible")
    page.wait_for_selector('[data-cov="XC-04"] input[type="checkbox"]')

    browser.locator(".chips button").filter(has_text=labels["workloads"]).first.click()
    page.locator('[data-cov="XC-04"] .note').filter(
        has_text=labels["search_only"]
    ).first.wait_for(state="visible")
    assert browser.locator("table.tbl").count() == 0
    assert browser.locator(".empty").count() == 0

    # ...and searching the category does reach it
    browser.locator("input.field").fill("web")
    page.wait_for_selector('[data-cov="XC-04"] tbody tr')
    assert browser.locator("tbody tr").count() == 2
    assert "10.1.1.4" in browser.locator("tbody tr").first.inner_text()


def test_a_category_being_loaded_says_so_while_the_request_is_in_flight(v2_page):
    """The in-flight state, made observable by parking the response: opening a
    category must not look like an empty category while its page is on the way."""
    page, base_url = v2_page
    ctl = _stub_object_corpus(page)
    ctl["hold_browse"].add("service")
    labels = _open_filter_drawer(page, base_url)

    svc = _zone_input(page, "svc")
    svc.click()
    page.wait_for_selector(f"{_zone('svc')} .fb-cat-item")
    page.locator(f"{_zone('svc')} .fb-cat-item").filter(
        has_text=labels["services"]
    ).first.click()

    loading = page.locator(f"{_zone('svc')} .fb-dd-note").filter(has_text=labels["loading"]).first
    loading.wait_for(state="visible")
    assert page.locator(f"{_zone('svc')} .fb-dd-item").count() == 0
    assert page.locator(f"{_zone('svc')} .fb-dd-empty").count() == 0

    assert ctl["held"], "the browse request never arrived"
    ctl["held"].pop()()
    page.wait_for_selector(f'{_zone("svc")} .fb-dd-item[data-cat="service"]')
    assert page.locator(f"{_zone('svc')} .fb-dd-note").filter(
        has_text=labels["loading"]
    ).count() == 0


def test_a_category_the_pce_could_not_answer_shows_an_error_and_a_retry(v2_page):
    """The 200-with-per-category-error shape: an unreachable PCE fails the
    cached categories while the live workload lookup still answers. The failing
    one must be NAMED, offer a retry, and never be reported as "no match"."""
    page, base_url = v2_page
    ctl = _stub_object_corpus(page)
    ctl["fail_suggest"].add("label")
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("role")

    err = page.locator(f"{FB} .fb-dd-err").first
    err.wait_for(state="visible")
    assert labels["labels"] in err.inner_text(), err.inner_text()
    assert page.locator(f'{FB} .fb-dd-item[data-cat="label"]').count() == 0
    # the failure is NOT dressed up as an empty result
    assert page.locator(f"{FB} .fb-dd-empty").count() == 0

    ctl["fail_suggest"].clear()
    with page.expect_request(lambda r: "/api/filter-objects/suggest" in r.url):
        err.locator(".fb-dd-retry").click()
    page.wait_for_selector(f'{FB} .fb-dd-item[data-cat="label"]')
    assert page.locator(f"{FB} .fb-dd-err").count() == 0


def test_a_failed_browse_shows_an_error_and_a_retry(v2_page):
    """The other failure shape: a 502 {ok:false} for the whole request."""
    page, base_url = v2_page
    ctl = _stub_object_corpus(page)
    ctl["fail_browse"].add("iplist")
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    page.locator(f"{_zone('src')} .fb-cat-item").filter(
        has_text=labels["iplists"]
    ).first.click()

    err = page.locator(f"{_zone('src')} .fb-dd-err").first
    err.wait_for(state="visible")
    assert page.locator(f'{_zone("src")} .fb-dd-item').count() == 0
    assert labels["no_match"] not in page.locator(f"{_zone('src')} .fb-dd-body").inner_text()

    ctl["fail_browse"].clear()
    with page.expect_request(
        lambda r: "/api/filter-objects/browse" in r.url and "type=iplist" in r.url
    ):
        err.locator(".fb-dd-retry").click()
    page.wait_for_selector(f'{_zone("src")} .fb-dd-item[data-cat="iplist"]')
    assert page.locator(f"{_zone('src')} .fb-dd-err").count() == 0


def test_category_counts_come_from_the_totals_query(v2_page):
    page, base_url = v2_page
    _stub_object_corpus(page)
    labels = _open_filter_drawer(page, base_url)

    with page.expect_request(lambda r: "type=_totals" in r.url):
        _zone_input(page, "src").click()

    row = page.locator(f"{_zone('src')} .fb-cat-item").filter(has_text=labels["iplists"]).first
    count = row.locator(".fb-cnt")
    count.wait_for(state="visible")
    assert count.inner_text().strip() == "1", row.inner_text()
    label_row = page.locator(f"{_zone('src')} .fb-cat-item").filter(has_text=labels["labels"]).first
    assert label_row.locator(".fb-cnt").inner_text().strip() == "3", label_row.inner_text()


def test_a_failed_totals_query_shows_no_count_rather_than_zero(v2_page):
    """A count is decoration; a WRONG count is a claim. "Failure rendered as a
    healthy zero" is a mistake this project has shipped more than once."""
    page, base_url = v2_page
    ctl = _stub_object_corpus(page)
    ctl["fail_totals"] = True
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    page.wait_for_selector(f"{_zone('src')} .fb-cat-item")
    page.wait_for_timeout(400)   # let the failed totals response land
    assert page.locator(f"{_zone('src')} .fb-cat-item .fb-cnt").count() == 0
    # the categories themselves are still offered, and still work
    page.locator(f"{_zone('src')} .fb-cat-item").filter(
        has_text=labels["labels"]
    ).first.click()
    page.wait_for_selector(f'{_zone("src")} .fb-dd-item[data-cat="label"]')


def test_each_candidate_row_states_its_own_type(v2_page):
    """Reported symptom 4: the object types all looked the same. Every candidate
    row carries its category as a data attribute AND a distinct type code."""
    page, base_url = v2_page
    _stub_object_corpus(page)
    _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    inp.fill("e")            # matches every fixture category in this zone
    page.wait_for_selector(f'{FB} .fb-dd-item[data-cat="workload"]')

    codes = page.eval_on_selector_all(
        f"{FB} .fb-dd-item",
        "els => els.map(e => [e.dataset.cat, e.querySelector('.fb-cat').textContent])",
    )
    by_cat = dict(codes)
    assert by_cat.get("label") == "LBL", codes
    assert by_cat.get("label_group") == "LGR", codes
    assert by_cat.get("iplist") == "IPL", codes
    assert by_cat.get("workload") == "WKL", codes
    assert len(set(by_cat.values())) == 4, codes


def test_browse_pages_with_load_more(v2_page):
    """`total` greater than what is held offers a load-more, and it asks for the
    NEXT offset rather than re-reading page one."""
    page, base_url = v2_page
    ctl = _stub_object_corpus(page)
    ctl["big_label_corpus"] = True
    labels = _open_filter_drawer(page, base_url)

    inp = _zone_input(page, "src")
    inp.click()
    page.locator(f"{_zone('src')} .fb-cat-item").filter(has_text=labels["labels"]).first.click()
    page.wait_for_selector(f'{_zone("src")} .fb-dd-item[data-cat="label"]')
    assert [c for c in ctl["browse_calls"] if c[0] == "label"] == [("label", 0, 20)]
    assert page.locator(f'{_zone("src")} .fb-dd-item[data-cat="label"]').count() == 20

    more = page.locator(f"{_zone('src')} .fb-dd-more").first
    assert "20" in more.inner_text() and "45" in more.inner_text(), more.inner_text()
    with page.expect_request(
        lambda r: "type=label" in r.url and "offset=20" in r.url
    ):
        more.click()
    page.wait_for_function(
        "() => document.querySelectorAll('[data-cov=\"XC-03\"] .fb-dd-item[data-cat=\"label\"]').length === 40"
    )
    assert [c for c in ctl["browse_calls"] if c[0] == "label"] == [("label", 0, 20), ("label", 20, 20)]
