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

    NOT `body[data-booted="true"]`: that flag is set after router.start()
    resolves, i.e. after the mounted area's own loads finish, and several
    routes here drive PCE-bound endpoints that take tens of seconds to fail
    against the harness's closed port. The shell and the head are both built
    synchronously, before any await — which is the property this file is
    asserting in the first place.
    """
    page.goto(base_url + "/" + route)
    page.wait_for_selector(".sidenav", timeout=20000)
    page.wait_for_selector(".workarea .phead h2", timeout=20000)


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
