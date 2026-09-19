"""The table panel is as wide as the table it holds, not wider.

``report_shell``'s auto-fit says so in two comments — "the panel itself is
``width: max-content``, so the narrow table gets a tight panel and the empty
space lives OUTSIDE the panel" — and then takes the ``else`` branch that
depends on it: when a table has no ``text`` column there is no slack to
distribute, so the columns keep their natural widths and ``table.style.width``
is pinned to that natural total. If the panel is a full-width block, the
slack the JS deliberately did not spend reappears as a bordered empty region
to the right of a narrow table.

That is what shipped. The legacy shell's ``.report-table-panel`` carried
``width: max-content; max-width: 100%`` (``report_css.py``); the v2 port
brought both comments across and left the rule behind, so from the moment
``97c3bef3`` deleted the legacy CSS every all-narrow-column table has been
sitting in an oversized card. Five call sites build ``--compact`` panels.

These assertions are on the *rendered* geometry, not on the CSS text. A
string search for the declaration would pass the moment the rule exists
anywhere, including under a selector that never matches or a media query that
never applies; only the browser can say whether the panel actually ends where
the table ends. The three cases pull in different directions on purpose:

  * a narrow table's panel must shrink to it,
  * a wide table's panel must NOT shrink — it must stay full width and keep
    the horizontal scroll that makes the overflow reachable,
  * an empty-state panel has no table at all and is centred text; shrinking it
    to fit the words "No data" would turn a full-width card into a chip.
"""
from __future__ import annotations

import concurrent.futures

import pytest

pytest.importorskip("playwright.sync_api", exc_type=ImportError)

from playwright.sync_api import sync_playwright  # noqa: E402

from src.report.exporters.report_shell import (  # noqa: E402
    ShellCover, ShellSection, build_shell_document)

VIEWPORTS = (800, 1280)


def _panel(cls: str, inner: str) -> str:
    return (f'<div class="report-table-panel {cls}">'
            f'<div class="report-table-wrap">{inner}</div></div>')


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                   for r in rows)
    return (f'<table class="report-table"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table>")


# Two short columns and short cells: every column is 'narrow' or 'num' to the
# auto-fit categoriser, so it takes the no-text-column branch. This is the
# exact shape of the VEN report's compatibility chapter.
NARROW = _panel("report-table-panel--compact",
                _table(["Verdict", "Workloads"],
                       [["pass", "0"], ["warn", "0"], ["fail", "0"],
                        ["unknown", "1"]]))

# Enough columns of long text that the natural total exceeds any viewport.
WIDE = _panel("report-table-panel--wide",
              _table([f"Column {i}" for i in range(12)],
                     [[f"a-fairly-long-value-{i}-{j}" for i in range(12)]
                      for j in range(3)]))

EMPTY = ('<div class="report-table-panel report-table-panel--empty">'
         '<span class="empty-marker"></span>'
         '<span class="empty-text">No data</span></div>')

# The traffic reports put compact panels inside a narrow column of a
# multi-column section; at 1280 those columns are ~210px while the tables in
# them want ~250px. A max-width that is a fixed 640px does not clamp to a
# parent narrower than that, so a panel sized by max-content escapes its
# column. These numbers are the measured ones, not invented.
IN_A_NARROW_COLUMN = (
    '<div style="width:210px">'
    + _panel("report-table-panel--compact",
             _table(["Rule", "Hits"],
                    [["a-moderately-long-rule-name-here", "12"],
                     ["another-rule-name-that-is-long", "3"]]))
    + "</div>")


def _document() -> str:
    return build_shell_document(
        lang="en",
        cover=ShellCover(title="Panel width", doc_title="Panel width",
                         type_label="Test"),
        sections=[
            ShellSection(id="narrow", title="Narrow", html=NARROW),
            ShellSection(id="wide", title="Wide", html=WIDE),
            ShellSection(id="empty", title="Empty", html=EMPTY),
            ShellSection(id="column", title="Column", html=IN_A_NARROW_COLUMN),
        ],
    )


def _measure(tmp_path, width: int) -> dict:
    """Drive the browser on a worker thread.

    ``sync_playwright()`` refuses to start while an asyncio loop is running on
    the calling thread, and under ``-n auto`` this file shares an xdist worker
    with tests that leave one behind — the whole file then fails with "you are
    using Playwright Sync API inside the asyncio loop", which looks nothing
    like a layout problem. A fresh thread has no loop of its own. The repo's
    other Playwright tests dodge this by opening playwright in a session
    fixture before anything else runs; this file has no such harness and
    should not need one.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_measure_in_browser, tmp_path, width).result()


def _measure_in_browser(tmp_path, width: int) -> dict:
    path = tmp_path / f"panel-{width}.html"
    path.write_text(_document(), encoding="utf-8")
    js = """
    () => {
      const read = (id) => {
        const sec = document.getElementById(id);
        const panel = sec.querySelector('.report-table-panel');
        const table = panel.querySelector('table.report-table');
        const wrap = panel.querySelector('.report-table-wrap');
        const pr = panel.getBoundingClientRect();
        const parent = panel.parentElement.getBoundingClientRect();
        return {
          panelW: pr.width,
          parentW: parent.width,
          tableW: table ? table.getBoundingClientRect().width : null,
          scrollable: wrap ? wrap.scrollWidth > wrap.clientWidth + 1 : null,
          overflowsParent: pr.right > parent.right + 1,
        };
      };
      return {narrow: read('narrow'), wide: read('wide'), empty: read('empty'),
              column: read('column')};
    }
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000})
        page.goto(path.as_uri())
        page.wait_for_load_state("networkidle")
        # Wait for the thing itself, not for a number of milliseconds. The
        # auto-fit runs on load and writes inline widths, and it marks each
        # table when it is done; a fixed sleep is a race that a loaded machine
        # loses, and losing it silently reads the pre-fit layout. Under the
        # full suite (`-n auto`) that race is lost often enough to turn every
        # case in this file red at once.
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('table.report-table'))"
            ".every(t => t.dataset.autoFitted === 'true')",
            timeout=30_000)
        # And prove the stylesheet is in force before believing any geometry:
        # a document rendered without SHELL_CSS has full-width block panels,
        # which fails these assertions for a reason that has nothing to do
        # with what they are testing.
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector("
            "'.report-table-panel')).borderTopWidth") == "1px", (
            "SHELL_CSS did not apply; the measurements below would be noise")
        out = page.evaluate(js)
        browser.close()
    return out


@pytest.mark.parametrize("width", VIEWPORTS)
def test_a_narrow_table_does_not_sit_in_an_oversized_card(tmp_path, width):
    m = _measure(tmp_path, width)["narrow"]
    assert m["tableW"] is not None
    # Border and rounding only: anything larger is empty bordered space that
    # reads as a rendering fault rather than a small table.
    slack = m["panelW"] - m["tableW"]
    assert slack <= 6, (
        f"panel is {slack:.0f}px wider than its table at {width}px "
        f"(panel={m['panelW']:.0f}, table={m['tableW']:.0f}); the empty space "
        "belongs outside the border, not inside it")


@pytest.mark.parametrize("width", VIEWPORTS)
def test_a_wide_table_keeps_a_full_width_panel_and_its_scroll(tmp_path, width):
    m = _measure(tmp_path, width)["wide"]
    assert m["scrollable"] is True, (
        "the wide table's overflow is unreachable: its wrap does not scroll")
    assert not m["overflowsParent"], "the wide panel spills past its column"
    # max-content would blow the panel out to the table's natural width; the
    # 100% clamp is what keeps it inside the column.
    assert m["panelW"] >= m["parentW"] - 40, (
        f"the wide panel shrank to {m['panelW']:.0f} of {m['parentW']:.0f}px")


@pytest.mark.parametrize("width", VIEWPORTS)
def test_an_empty_state_panel_stays_a_full_width_card(tmp_path, width):
    m = _measure(tmp_path, width)["empty"]
    assert m["tableW"] is None
    assert m["panelW"] >= m["parentW"] - 40, (
        f"the empty-state card shrank to {m['panelW']:.0f} of "
        f"{m['parentW']:.0f}px and reads as a chip, not as a panel")


@pytest.mark.parametrize("width", VIEWPORTS)
def test_a_compact_panel_stays_inside_a_column_narrower_than_its_cap(tmp_path, width):
    """--compact's 640px cap must not out-rank the 100% one.

    `max-width: 640px` on the compact variant overrides the base
    `max-width: 100%` rather than adding to it, so in a column narrower than
    640px the cap stops clamping anything. With the panel sized by
    max-content that is the difference between sitting in the column and
    hanging out of it — which is what the traffic reports' policy section
    does at 1280, where its columns are about 210px wide.
    """
    m = _measure(tmp_path, width)["column"]
    assert not m["overflowsParent"], (
        f"the compact panel is {m['panelW']:.0f}px inside a "
        f"{m['parentW']:.0f}px column at viewport {width}")
