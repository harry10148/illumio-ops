"""Phase 2A Task 3 — in-process Playwright e2e for the v2 component layer.

Drives a real (headless) Chromium against a real Flask app through
tests.v2_e2e_utils's shared harness (see that module's docstring) and imports
the ported component modules directly via dynamic `import()`, the same
pattern test_v2_core_e2e.py uses for the core layer — Task 3 does not wire
these components into app.mjs's chrome (that is Tasks 4-9's job), so there is
no in-app surface to click through yet.

Covers exactly the brief's Step 2 acceptance list:
  - drawer focus trap: Tab does not escape the drawer, Esc closes it, and
    focus returns to the element that opened it.
  - table column-width drag (the resize grip in table.mjs's headCell()).
  - modal.confirm({onOk: undefined}) does not throw a TypeError when its OK
    button is clicked — a real defect in design/v2/mockup/js/components/
    modal.mjs's `await o.onOk()` call, ported forward and only fixed here.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

# Registers v2_page and its fixture chain — see tests/v2_e2e_utils.py's
# docstring for why both this line and the importorskip above (in that exact
# order) are required.
pytest_plugins = ["tests.v2_e2e_utils"]


def _goto_overview(page, base_url):
    page.goto(base_url + "/v2#/overview")
    page.wait_for_selector('body[data-booted="true"]')


def _open_test_drawer(page):
    """Mount a drawer with a real opener button + two body inputs, and
    return the ids Python needs to drive the rest of the test with real
    Playwright keyboard/mouse input (not further page.evaluate calls) —
    driving Tab through page.evaluate would not exercise the browser's own
    focus/keydown event delivery the way a real trap has to survive.
    """
    return page.evaluate(
        "async () => {"
        "  const { drawer } = await import('/static/js/v2/components/drawer.mjs');"
        "  const { el } = await import('/static/js/v2/core/dom.mjs');"
        "  const opener = document.createElement('button');"
        "  opener.id = 'test-opener';"
        "  opener.textContent = 'open';"
        "  document.body.appendChild(opener);"
        "  opener.focus();"
        "  const inputA = el('input', { type: 'text', id: 'fa' });"
        "  const inputB = el('input', { type: 'text', id: 'fb' });"
        "  const body = el('div', null, inputA, inputB);"
        "  const handle = drawer.open({ title: 'Test drawer', body: body });"
        "  window.__testHandle = handle;"
        "  handle.el.id = 'test-drawer';"
        "  return {"
        "    ariaModal: handle.el.getAttribute('aria-modal'),"
        "    activeId: document.activeElement && document.activeElement.id,"
        "  };"
        "}"
    )


def test_drawer_is_aria_modal_and_traps_initial_focus(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    result = _open_test_drawer(page)
    # aria-modal="true" (was "false" in the mockup — brief item 1).
    assert result["ariaModal"] == "true"
    # Opening moves focus into the panel (the close button is the first
    # focusable element: header -> h2 -> spacer -> closeButton) rather than
    # leaving it on the opener.
    assert result["activeId"] != "test-opener"
    assert page.evaluate("document.getElementById('test-drawer').contains(document.activeElement)")


def test_drawer_focus_trap_tab_does_not_escape(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)
    _open_test_drawer(page)

    focusables = page.evaluate(
        "Array.from(document.getElementById('test-drawer')"
        ".querySelectorAll('a[href],button:not([disabled]),input:not([disabled])'))"
        ".map(n => n.id || n.tagName)"
    )
    assert len(focusables) >= 2, focusables

    # Tab exactly len(focusables) times: a real trap wraps back to the first
    # focusable. Without the trap, the browser's native tab order would leave
    # the drawer entirely (there is nothing else focusable after it in the
    # DOM except #test-opener, appended earlier) — so landing anywhere other
    # than the first item, or on #test-opener, is the escape this guards.
    for _ in range(len(focusables)):
        page.keyboard.press("Tab")
    ended_on_first = page.evaluate(
        "document.activeElement === document.getElementById('test-drawer')"
        ".querySelectorAll('a[href],button:not([disabled]),input:not([disabled])')[0]"
    )
    assert ended_on_first
    assert page.evaluate("document.activeElement.id") != "test-opener"

    # And Shift+Tab from the first item wraps to the LAST item, not out to
    # #test-opener (which precedes the drawer in DOM order).
    page.keyboard.press("Shift+Tab")
    ended_on_last = page.evaluate(
        "(() => { const items = document.getElementById('test-drawer')"
        ".querySelectorAll('a[href],button:not([disabled]),input:not([disabled])');"
        "return document.activeElement === items[items.length - 1]; })()"
    )
    assert ended_on_last
    assert page.evaluate("document.activeElement.id") != "test-opener"


def test_drawer_esc_closes_and_restores_focus_to_opener(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)
    _open_test_drawer(page)

    assert page.evaluate("document.getElementById('test-drawer') !== null")
    page.keyboard.press("Escape")
    assert page.evaluate("document.getElementById('test-drawer') === null")
    # Focus returns to the opener that had it before the drawer opened.
    assert page.evaluate("document.activeElement.id") == "test-opener"


def test_drawer_destroy_and_onclose_hook_run_on_any_close_path(v2_page):
    """Teardown contract: handle.destroy() is close()'s alias, and a callback
    registered via handle.onClose() fires exactly once when the drawer goes
    away — the shape Tasks 4-9 use to tear down a FilterBar mounted inside a
    drawer (opener calls fb.destroy() from onClose)."""
    page, base_url = v2_page
    _goto_overview(page, base_url)

    result = page.evaluate(
        "async () => {"
        "  const { drawer } = await import('/static/js/v2/components/drawer.mjs');"
        "  const { el } = await import('/static/js/v2/core/dom.mjs');"
        "  let closed = 0;"
        "  const handle = drawer.open({ title: 'x', body: el('div') });"
        "  handle.onClose(() => { closed += 1; });"
        "  const hasDestroy = typeof handle.destroy === 'function';"
        "  handle.destroy();"
        "  const stillInDom = document.body.contains(handle.el);"
        "  handle.destroy();"  # idempotent: must not double-fire onClose
        "  return { hasDestroy: hasDestroy, closed: closed, stillInDom: stillInDom };"
        "}"
    )
    assert result["hasDestroy"] is True
    assert result["stillInDom"] is False
    assert result["closed"] == 1


def test_table_column_resize_drag_changes_width(v2_page):
    page, base_url = v2_page
    _goto_overview(page, base_url)

    page.evaluate(
        "async () => {"
        "  const { table, col } = await import('/static/js/v2/components/table.mjs');"
        "  const { el } = await import('/static/js/v2/core/dom.mjs');"
        "  const host = el('div', { id: 'test-table' });"
        "  document.body.appendChild(host);"
        "  const columns = [col('a', 'A', { width: 120 }), col('b', 'B', { width: 120 })];"
        "  table.render(host, { columns: columns, rows: [{ a: '1', b: '2' }], page: 0 });"
        "}"
    )
    grip = page.locator("#test-table .tbl-grip").first
    grip.wait_for(state="visible")
    box = grip.bounding_box()
    before_width = page.evaluate(
        "document.querySelector('#test-table col').style.width"
    )

    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 80, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()

    after_width = page.evaluate(
        "document.querySelector('#test-table col').style.width"
    )
    assert after_width != before_width, (before_width, after_width)
    # Width grew by roughly the drag delta (clamped to a 48px minimum, per
    # table.mjs's headCell() grip handler).
    before_px = int(before_width.replace("px", ""))
    after_px = int(after_width.replace("px", ""))
    assert after_px >= before_px + 60, (before_px, after_px)


def test_modal_confirm_with_onok_omitted_does_not_throw(v2_page):
    """Phase 1 review finding: modal.confirm({onOk: undefined})'s OK button
    called `await o.onOk()` unconditionally and threw a TypeError. Clicking
    OK with no onOk must close the modal cleanly instead."""
    page, base_url = v2_page
    _goto_overview(page, base_url)

    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.evaluate(
        "async () => {"
        "  const { modal } = await import('/static/js/v2/components/modal.mjs');"
        "  const handle = modal.confirm({ title: 'Delete?', impact: ['1 thing'] });"
        "  handle.el.id = 'test-modal';"
        "}"
    )
    page.locator("#test-modal .btn.danger").click()
    page.wait_for_function("document.getElementById('test-modal') === null")

    assert errors == []


def test_modal_is_aria_modal_and_traps_focus(v2_page):
    """Brief item 1 names drawer AND modal for aria-modal + focus trap; the
    drawer tests above exercise dom.mjs's shared trapFocus() thoroughly, so
    this only needs to confirm modal.mjs actually wires the same utility in
    (not a stub aria attribute with no behaviour behind it)."""
    page, base_url = v2_page
    _goto_overview(page, base_url)

    result = page.evaluate(
        "async () => {"
        "  const { modal } = await import('/static/js/v2/components/modal.mjs');"
        "  const opener = document.createElement('button');"
        "  opener.id = 'modal-opener';"
        "  document.body.appendChild(opener);"
        "  opener.focus();"
        "  const handle = modal.confirm({ title: 'Delete?', impact: ['1 thing'] });"
        "  handle.el.id = 'test-modal-2';"
        "  return { ariaModal: handle.el.getAttribute('aria-modal') };"
        "}"
    )
    assert result["ariaModal"] == "true"
    assert page.evaluate("document.getElementById('test-modal-2').contains(document.activeElement)")

    focusables = page.evaluate(
        "Array.from(document.getElementById('test-modal-2')"
        ".querySelectorAll('button:not([disabled])')).length"
    )
    assert focusables >= 2
    for _ in range(focusables):
        page.keyboard.press("Tab")
    assert page.evaluate("document.getElementById('test-modal-2').contains(document.activeElement)")
    assert page.evaluate("document.activeElement.id") != "modal-opener"

    page.keyboard.press("Escape")
    assert page.evaluate("document.getElementById('test-modal-2') === null")
    assert page.evaluate("document.activeElement.id") == "modal-opener"
