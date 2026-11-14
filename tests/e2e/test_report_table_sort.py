"""A report table sorts by its column headers, on screen only: a click sorts ascending, the next descending, the
third puts the report's own order back. A number sorts as a number whatever it is printed with (thousands separators,
a percent sign, a unit), a time as a time, anything else as text; a cell without a value is last both ways. Paper
prints the report's order, and its first ten rows, whatever the page was sorted by."""
import re
import shutil
import subprocess
from datetime import UTC

import pytest

from illumio_ops.domain.report import Column, Section, TableBlock
from illumio_ops.domain.values import Language
from illumio_ops.services.reports.render_html import render_html
from tests.services.reports.conftest import make_doc, table

VISIBLE = "e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }"
# name, connections (a number), share (text the builder wrote), volume (text with a unit), last seen (a time), note
ROWS = (("web-10", 1200, "12.5%", "900 KB", "2026-10-22T03:00:00+00:00", "Zulu"),
        ("web-9", 15, "100.0%", "1.5 GB", "2026-10-21T23:00:00.000+00:00", "alpha"),
        ("db-1", None, "—", "—", None, ""),
        ("App-2", 1_000_000, "4.9%", "20 MB", "2026-10-23T00:00:00+00:00", "Bravo"),
        ("cache", 0, "0.0%", "0 B", "2026-10-20T12:00:00+00:00", "charlie"))
COLUMNS = (Column(key="host", label="Host"), Column(key="n", label="Connections", kind="number"),
           Column(key="share", label="Share"), Column(key="volume", label="Volume"),
           Column(key="last", label="Last seen", kind="time"), Column(key="note", label="Note"))
NAMES = [r[0] for r in ROWS]


def _doc(rows=ROWS, columns=COLUMNS, **over):
    block = TableBlock(title="Hosts", columns=columns, rows=tuple(rows), total_rows=over.pop("total", len(rows)),
                       empty_text="none", **over)
    return make_doc(sections=(Section(id="hosts", title="Hosts", blocks=(block,)),))


def _open(context, html, *, width=1280, media="screen"):
    page = context.new_page()
    page.set_viewport_size({"width": width, "height": 1000})
    page.emulate_media(media=media)
    page.set_content(html)
    page.wait_for_timeout(300)
    return page


def _names(page, column=0):
    """The first table's rows as a reader sees them: the given cell of every row that is drawn."""
    return page.evaluate(f"[...document.querySelector('table.report-table').querySelectorAll('tbody tr')]"
                         f".filter({VISIBLE}).map(r => r.cells[{column}].innerText.trim())")


def _aria(page):
    return page.evaluate("[...document.querySelectorAll('table.report-table thead th')].map(th => th.getAttribute('aria-sort'))")


def _click(page, name):
    page.get_by_role("button", name=name, exact=True).click()


def test_a_number_column_sorts_by_the_number_and_a_cell_without_one_is_last(context):
    page = _open(context, render_html(_doc(), tz=UTC))
    assert _names(page) == NAMES and _aria(page) == ["none"] * 6
    assert _names(page, 1) == ["1,200", "15", "", "1,000,000", "0"]  # as printed: separators, and nothing for no value
    _click(page, "Connections")
    assert _names(page) == ["cache", "web-9", "web-10", "App-2", "db-1"]
    assert _aria(page) == ["none", "ascending", "none", "none", "none", "none"]
    _click(page, "Connections")
    assert _names(page) == ["App-2", "web-10", "web-9", "cache", "db-1"]  # the row without a number is still last
    assert _aria(page)[1] == "descending"
    _click(page, "Connections")
    assert _names(page) == NAMES and _aria(page) == ["none"] * 6  # the third click: the report's own order


def test_a_percentage_a_unit_and_a_time_sort_by_their_value(context):
    page = _open(context, render_html(_doc(), tz=UTC))
    _click(page, "Share")
    assert _names(page) == ["cache", "App-2", "web-10", "web-9", "db-1"]  # 0.0% 4.9% 12.5% 100.0%, then "—"
    _click(page, "Volume")
    assert _names(page) == ["cache", "web-10", "App-2", "web-9", "db-1"]  # 0 B, 900 KB, 20 MB, 1.5 GB
    assert _aria(page) == ["none", "none", "none", "ascending", "none", "none"]  # one column at a time
    _click(page, "Volume")
    assert _names(page) == ["web-9", "App-2", "web-10", "cache", "db-1"]
    _click(page, "Last seen")
    assert _names(page) == ["cache", "web-9", "web-10", "App-2", "db-1"]
    _click(page, "Last seen")
    assert _names(page) == ["App-2", "web-10", "web-9", "cache", "db-1"]


def test_a_text_column_sorts_as_a_reader_of_the_language_would(context):
    page = _open(context, render_html(_doc(), tz=UTC))
    _click(page, "Host")
    assert _names(page) == ["App-2", "cache", "db-1", "web-9", "web-10"]  # no capitals first; 9 before 10
    _click(page, "Note")
    assert _names(page, 5) == ["alpha", "Bravo", "charlie", "Zulu", ""]  # the empty cell last
    _click(page, "Note")
    assert _names(page, 5) == ["Zulu", "charlie", "Bravo", "alpha", ""]
    # Traditional Chinese by strokes (乙 is one stroke, 三 and 大 three), not by code point (三 U+4E09 is before 乙 U+4E59)
    zh = _doc(rows=(("大", 1), ("三", 2), ("乙", 3)), columns=COLUMNS[:2]).model_copy(update={"lang": Language.ZH_TW})
    page = _open(context, render_html(zh, tz=UTC))
    page.locator("thead th button").first.click()
    assert _names(page) == ["乙", "三", "大"] and _aria(page) == ["ascending", "none"]


def test_the_header_is_a_button_reached_and_pressed_from_the_keyboard(context):
    page = _open(context, render_html(_doc(), tz=UTC))
    headers = page.locator("table.report-table thead th")
    assert headers.count() == 6 and page.locator("table.report-table thead th > button").count() == 6
    button = page.get_by_role("button", name="Connections", exact=True)
    button.focus()
    page.keyboard.press("Enter")
    assert _aria(page)[1] == "ascending" and _names(page)[0] == "cache"
    page.keyboard.press("Space")
    assert _aria(page)[1] == "descending" and _names(page)[0] == "App-2"
    # what shows the state is drawn, and differs between the three states
    drawn = page.evaluate("""() => [...document.querySelectorAll('table.report-table thead th')].map(th =>
        getComputedStyle(th.querySelector('.sort-indicator'), '::before').content)""")
    assert len(set(drawn)) == 2 and drawn[1] != drawn[0], drawn


@pytest.mark.parametrize("width", [1280, 820])
def test_sorting_changes_no_width_and_wraps_no_header(context, width):
    page = _open(context, render_html(_doc(), tz=UTC), width=width)
    boxes = """() => [document.querySelector('table.report-table'), ...document.querySelectorAll('thead th, thead .th-label')]
        .map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.width), Math.round(r.height)]; })"""
    before = page.evaluate(boxes)
    for name in ("Connections", "Connections", "Note", "Host"):
        _click(page, name)
        assert page.evaluate(boxes) == before, name
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    # the mark of the state is inside its header cell and does not lie over the column's name
    assert page.evaluate("""() => [...document.querySelectorAll('thead th')].every(th => {
        const m = th.querySelector('.sort-indicator').getBoundingClientRect(), l = th.querySelector('.th-label').getBoundingClientRect(),
              c = th.getBoundingClientRect();
        return m.width > 0 && m.left >= l.right - 0.5 && m.right <= c.right + 0.5; })""")


def test_paper_prints_the_reports_order_and_no_button_whatever_was_sorted(context):
    rows = [(f"host-{i:02d}", 100 - i) for i in range(30)]
    page = _open(context, render_html(_doc(rows=rows, columns=COLUMNS[:2]), tz=UTC))
    _click(page, "Connections")
    assert _names(page)[:3] == ["host-29", "host-28", "host-27"] and len(_names(page)) == 30
    page.emulate_media(media="print")
    assert _names(page) == [f"host-{i:02d}" for i in range(10)]  # the same first ten as an unsorted page prints
    assert page.evaluate(f"[...document.querySelectorAll('thead th button, thead .sort-indicator')].filter({VISIBLE}).length") == 0
    assert page.evaluate(f"[...document.querySelectorAll('thead .th-label')].filter({VISIBLE}).map(e => e.textContent)") == ["Host", "Connections"]
    page.emulate_media(media="screen")
    assert _names(page)[:3] == ["host-29", "host-28", "host-27"]  # and the screen is as the reader left it


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="reads the printed PDF's text with poppler's pdftotext")
def test_the_printed_pdf_of_a_sorted_page_is_the_report_in_its_own_order(context, tmp_path):
    rows = [(f"QZ{i:02d}Zhost", 100 - i) for i in range(30)]
    page = _open(context, render_html(_doc(rows=rows, columns=COLUMNS[:2]), tz=UTC), width=695)
    _click(page, "Connections")
    assert _names(page)[0] == "QZ29Zhost"
    out = tmp_path / "sorted.pdf"
    page.emulate_media(media="null")  # no medium is forced: printing itself is what makes the page paper
    assert _names(page)[0] == "QZ29Zhost"
    page.pdf(path=str(out), prefer_css_page_size=True)
    text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True, check=True).stdout
    assert re.findall(r"QZ(\d\d)Zhost", text) == [f"{i:02d}" for i in range(10)]
    assert "Sorting by a column" not in text and "↕" not in text and "▲" not in text


def test_a_cut_table_says_how_many_rows_it_lists_and_that_sorting_orders_only_those(context):
    rows = [(f"host-{i:03d}", i) for i in range(260)]
    html = render_html(_doc(rows=rows, columns=COLUMNS[:2]), tz=UTC)
    page = _open(context, html)
    said = "[...document.querySelectorAll('.chapter p.note')].filter(" + VISIBLE + ").map(e => e.innerText.trim())"
    cut = "200 of 260 rows are listed here; every row is in the XLSX sheet “Hosts”."
    assert page.evaluate(said) == [f"{cut} Sorting by a column orders these 200 rows only."]
    _click(page, "Connections")
    _click(page, "Connections")
    assert _names(page)[0] == "host-199" and len(_names(page)) == 200  # the 200 rows of the page, never the other 60
    page.emulate_media(media="print")  # paper cannot be sorted: it does not speak of sorting
    assert page.evaluate(said) == ["Print lists the first 10 rows of 260; every row is in the XLSX sheet “Hosts”.", cut]


def test_a_table_with_nothing_to_sort_has_no_button(context):
    one_row = table([("only", 1)], title="One row")
    one_column = TableBlock(title="One column", columns=(Column(key="a", label="A"),), rows=(("x",), ("y",)),
                            total_rows=2, empty_text="none")
    empty = table([], title="Empty")
    doc = make_doc(sections=(Section(id="s", title="S", blocks=(one_row, one_column, empty)),))
    page = _open(context, render_html(doc, tz=UTC))
    assert page.locator("table.report-table").count() == 2
    assert page.locator("thead button").count() == 0 and page.locator("thead th[aria-sort]").count() == 0
    assert page.locator(".sort-indicator").count() == 0
