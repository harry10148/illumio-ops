"""v3.1 §1 / §5.1 — the shell and page-type gates.

Spec: docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md
(§1 the left-hand navigation shell, §5.1 the two page types plus settings,
§5.4 responsive). Plan: docs/superpowers/plans/2026-09-04-phase3e-workbench.md.

What this file is for, stated plainly: 3B's shell was a top bar with a
six-then-five-area nav and each AREA drawing its own sub-navigation. v3.1
replaces it with one left-hand navigation that owns every sub-item, and gives
every page one head (breadcrumbs, a sentence title, at most one primary
action). Those are structural invariants that no existing suite asserts —
tests/test_v2_shell_e2e.py asserts the topbar's own behaviour, which is
exactly what is being replaced.

Task 1 lands the shell half. The settings-page half (§5.1's `.savebar` on
every settings route) and the `.mono` DOM sweep (§7) arrive with Tasks 5 and
6, alongside the pages they gate.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

# Registers v2_page and the fixture chain it depends on — see
# tests/v2_e2e_utils.py's module docstring for why both this line and the
# importorskip above (in THIS module, not just there) are required, in order.
pytest_plugins = ["tests.v2_e2e_utils"]


# Every non-settings route that renders a page of its own. The settings routes
# are held back for Task 5, which is what gives them their own page type.
ROUTES = [
    "#/home",
    "#/investigate/alerts",
    "#/investigate/traffic",
    "#/investigate/workloads",
    "#/investigate/events",
    "#/policy/alert-rules",
    "#/policy/ops",
    "#/policy/rulesets",
    "#/policy/schedules",
    "#/reports",
    "#/reports/schedules",
]


def _open(page, base_url, route):
    """Land on `route` and wait for the shell and the page head.

    The head is matched by its OWN data-route, not just by tag. Two routes in
    this list differ only in the hash, and `page.goto` to a same-document hash
    does not reload — so a bare `.phead h2` wait is satisfied by the PREVIOUS
    route's head, still in the DOM, and every assertion after it reads the
    wrong page. Waiting for the incoming route's head is what actually proves
    the new area mounted.

    NOT `body[data-booted="true"]` either: that flag is set once, after the
    first router.start() resolves, and never cleared on a hash change. It says
    nothing about the route being visited now.
    """
    page.goto(base_url + "/" + route)
    page.wait_for_selector(".sidenav", timeout=20000)
    page.wait_for_selector('.workarea .phead[data-route="%s"] h2' % route, timeout=30000)


# ── §1 · the shell ──────────────────────────────────────────────────────────

def test_shell_is_a_left_nav_with_the_five_areas_and_no_top_bar(v2_page):
    """The five areas are direct children of the nav; the top bar is gone.

    `> a` and not ` a`: the sub-items are links too, so a descendant count
    would pass with the areas missing entirely.
    """
    page, base_url = v2_page
    _open(page, base_url, "#/home")

    assert page.locator(".sidenav").count() == 1
    assert page.locator(".topbar, .areanav, .rail-host").count() == 0
    assert page.locator('.sidenav > a[href^="#/"]').count() == 5
    assert page.locator('.sidenav a[aria-current="page"][href="#/home"]').count() == 1


def test_current_area_expands_its_children_only(v2_page):
    """One area's sub-items at a time — the nav is not a sitemap."""
    page, base_url = v2_page
    _open(page, base_url, "#/policy/rulesets")

    assert page.locator('.sidenav .sub a[href="#/policy/rulesets"][aria-current="page"]').count() == 1
    assert page.locator('.sidenav .sub a[href^="#/system/"]').count() == 0
    # Exactly one link is THE current page anywhere in the nav: the area link
    # marks itself as an ancestor (aria-current="true"), not as the page.
    assert page.locator('.sidenav a[aria-current="page"]').count() == 1


def test_the_shell_carries_its_three_coverage_anchors(v2_page):
    """SH-01 nav, SH-02 user menu, SH-03 the command-palette entry (§7)."""
    page, base_url = v2_page
    _open(page, base_url, "#/home")

    for anchor in ("SH-01", "SH-02", "SH-03"):
        assert page.locator('.sidenav [data-cov="%s"], .sidenav[data-cov="%s"]'
                            % (anchor, anchor)).count() == 1, anchor


# ── §5.1 · the page head ────────────────────────────────────────────────────

def test_every_page_has_a_sentence_title_and_at_most_one_primary_action(v2_page):
    page, base_url = v2_page
    for route in ROUTES:
        _open(page, base_url, route)
        assert page.locator(".workarea .phead h2").count() == 1, route
        assert page.locator(".workarea .phead .btn.primary").count() <= 1, route


# ── §5.4 · responsive ───────────────────────────────────────────────────────

def test_nothing_clips_at_800(v2_page):
    """3B Task 7's lesson: the nav may never cut a label off at any width."""
    page, base_url = v2_page
    page.set_viewport_size({"width": 800, "height": 700})
    _open(page, base_url, "#/reports")

    over = page.evaluate(
        "Array.from(document.querySelectorAll('.sidenav a, .phead h2'))"
        ".filter(e => e.scrollWidth > e.clientWidth + 1).length"
    )
    assert over == 0


# ── §5.2 · no route reaches the screen ──────────────────────────────────────

def test_no_visible_text_is_a_route(v2_page):
    """The half of §5.2 that a source lint cannot see.

    tests/test_gui_copy_lint.py catches a route written as a literal piece of
    text. It cannot catch one COMPOSED at runtime — `t("gui_health_goto") + " "
    + route` was how 21 buttons and every command-palette entry printed an
    address — because no regex over source tells a route variable from any
    other string. The rendered page does tell, so this asks it directly.

    body.innerText, deliberately: it is what an operator can actually read, so
    a hash inside an href, a title attribute or a hidden surface does not count.
    """
    page, base_url = v2_page
    offenders = []
    for route in ROUTES:
        _open(page, base_url, route)
        # The head is synchronous, the body is not — and here the BODY is the
        # subject, so reading straight after _open would let a page that has
        # not painted its content yet pass for lack of anything to read. Wait
        # for the network to go quiet instead: every area's copy arrives with
        # (or right after) its own loads, which against the harness's closed
        # port fail slowly, with retry backoff.
        try:
            page.wait_for_load_state("networkidle", timeout=90000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        text = page.evaluate("() => document.body.innerText")
        for line in text.splitlines():
            if "#/" in line:
                offenders.append((route, line.strip()))
    assert offenders == [], (
        "these routes print a hash route at the operator (spec §5.2):\n  "
        + "\n  ".join("%s: %s" % pair for pair in offenders[:20])
    )


def test_the_page_head_is_actually_styled(v2_page):
    """The head must be STYLED, not merely present.

    This is here because of a real regression: a Task 3 edit truncated
    components.css from a marker to end-of-file and took the whole page-head
    block with it. Every gate stayed green — the colour and spacing lints
    count tokens rather than rules, and the structural checks above only ask
    whether `.phead h2` exists. The page shipped with an unstyled head and
    breadcrumbs run together as "Home/Investigate/Alerts", and only a
    screenshot caught it.

    What it asserts is deliberately NOT "the title is big and bold": an
    unstyled `<h2>` is big and bold by browser default, so that assertion
    passes with the stylesheet gone — measured, not assumed. It asserts the
    layout properties that ONLY this stylesheet supplies: the head is a
    column, its title row is a spaced-out flex row, and the breadcrumb trail
    lays its parts out with a real gap. Each of those is `block` / `0px`
    without the rules.
    """
    page, base_url = v2_page
    _open(page, base_url, "#/investigate/alerts")

    def styles(selector):
        return page.evaluate(
            "sel => { const n = document.querySelector(sel); if (!n) return null;"
            " const s = getComputedStyle(n);"
            " return {display: s.display, direction: s.flexDirection,"
            "         justify: s.justifyContent, gap: parseFloat(s.columnGap) || 0}; }",
            selector,
        )

    head = styles(".workarea .phead")
    assert head and head["display"] == "flex" and head["direction"] == "column", head
    row = styles(".workarea .phead .phead-main")
    assert row and row["display"] == "flex" and row["justify"] == "space-between", row
    crumbs = styles(".workarea .phead .crumbs")
    assert crumbs and crumbs["display"] == "flex" and crumbs["gap"] > 0, crumbs
