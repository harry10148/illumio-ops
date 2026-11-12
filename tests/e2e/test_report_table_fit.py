"""Rendered report tables at screen width (2026-10-29, readiness on lab): a table whose long-text columns are
together wider than the page kept every column at its one-line width and scrolled, so the last column — the
rules to write — was past the right edge. Long text wraps instead; only a wide table (many columns) scrolls."""
import math
import re
import shutil
import subprocess
from datetime import UTC

import pytest

from illumio_ops.domain.report import Column, Finding, Kpi, Section, TableBlock
from illumio_ops.domain.values import Language, Severity
from illumio_ops.i18n import translate
from illumio_ops.services.reports.render_html import render_html
from tests.services.reports.conftest import make_doc, table

# A4 portrait less the report's page margins (report_shell.css @page: 15mm 13mm 14mm), in CSS px: what a printed
# page really has. Print media at the full 794px hid a table that was 100px too wide for the paper.
PAPER_W, PAPER_H = 695, 1013

LONG = "38 points (F): the most is lost on “From the app itself” — 4.9% of the connections, 1 of its 20 points. " * 2
LINKS = "Endpoint → 5353/UDP (809 connections); Endpoint → 7000/TCP (279 connections); Web → 443/TCP (156) " * 2


def _overflow(context, html, width):
    page = context.new_page()
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(html)
    page.wait_for_timeout(300)
    return page.evaluate("""() => [...document.querySelectorAll('.report-table-wrap')]
        .map(w => w.scrollWidth - w.clientWidth)""")


def test_long_text_columns_wrap_to_the_page(context):
    rows = [("Endpoint (WIFI)", LONG, LINKS), ("DemoApp (Server)", LONG, LINKS)]
    doc = make_doc(sections=(Section(id="next", title="What to do first", intro="",
                                     blocks=(table(rows, cols=3),)),))
    for width in (1280, 768):
        assert _overflow(context, render_html(doc, tz=UTC), width) == [0], width


def test_print_media_no_overflow(context):
    """UI redesign spec §8: printed on A4 (≈ 794 CSS px wide), the first page and a long table stay inside the page."""
    from illumio_ops.domain.report import Finding
    from illumio_ops.domain.values import Severity
    rows = [(f"host-{i}", LONG, LINKS) for i in range(40)]
    doc = make_doc(findings=(Finding(severity=Severity.HIGH, title="Open RDP " * 6, why=LINKS, action=LONG),),
                   sections=(Section(id="next", title="What to do first", intro="", blocks=(table(rows, cols=3),)),)
                   ).model_copy(update={"conclusion": LONG})
    page = context.new_page()
    page.set_viewport_size({"width": 794, "height": 1123})
    page.emulate_media(media="print")
    page.set_content(render_html(doc, tz=UTC))
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")


# ── stage 3a Task 6: paper lists ten rows, cards are never split, the lead numbers stay level ──────────────

def _page(context, html, *, width, media):
    page = context.new_page()
    page.set_viewport_size({"width": width, "height": 1000})
    page.emulate_media(media=media)
    page.set_content(html)
    page.wait_for_timeout(300)
    return page


VISIBLE = "e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }"


def test_paper_lists_the_first_ten_rows_and_says_so(context):
    doc = make_doc(sections=(Section(id="hosts", title="Hosts", blocks=(table([(f"host-{i:02d}", i) for i in range(30)]),)),))
    html = render_html(doc, tz=UTC)

    def seen(media):
        page = _page(context, html, width=PAPER_W, media=media)
        rows = page.evaluate(f"[...document.querySelectorAll('tbody tr')].filter({VISIBLE}).map(r => r.cells[0].innerText)")
        said = page.evaluate(f"[...document.querySelectorAll('[data-role=print-capped]')].filter({VISIBLE})"
                             ".map(e => e.innerText)")
        page.close()
        return rows, said
    rows, said = seen("print")
    assert rows == [f"host-{i:02d}" for i in range(10)]
    assert said == ["Print lists the first 10 rows of 30; every row is in the XLSX sheet “Hosts”."]
    rows, said = seen("screen")
    assert len(rows) == 30 and said == []


def test_paper_lists_the_first_ten_rows_by_place_not_by_the_rows_own_number(context):
    doc = make_doc(sections=(Section(id="hosts", title="Hosts", blocks=(table([(f"host-{i:02d}", i) for i in range(30)]),)),))
    page = _page(context, render_html(doc, tz=UTC), width=1280, media="screen")
    # The shell's own sort (report_table.js sortTable re-appends the rows in their new order), called directly:
    # v6's tables do not carry data-interactive="true", so no header click is wired to it today.
    page.evaluate("() => { const t = document.querySelector('table.report-table'); sortTable(t, 1); sortTable(t, 1); }")
    page.emulate_media(media="print")
    rows = page.evaluate(f"[...document.querySelectorAll('tbody tr')].filter({VISIBLE}).map(r => r.cells[0].innerText)")
    assert rows == [f"host-{i:02d}" for i in range(29, 19, -1)]


def _pdf_pages(page, tmp_path):
    out = tmp_path / "report.pdf"
    page.pdf(path=str(out), prefer_css_page_size=True, print_background=True)
    text = subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True, check=True).stdout
    pages = [re.sub(r"\s+", "", t) for t in text.split("\f")]
    return pages[:-1] if pages and not pages[-1] else pages


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="reads the printed PDF's pages with poppler's pdftotext")
def test_no_printed_page_splits_a_card_or_stands_empty(context, tmp_path):
    """19 cards of several lines each: in the PDF every card's first and last word are on one page, no page is
    blank or holds a heading alone, and the pages are as many as the content needs."""
    body = "The rule found connections that nothing blocks, on the ports ransomware uses to spread. " * 4
    findings = tuple(Finding(severity=Severity.HIGH, title=f"QZA{i:02d}Z finding", what=body, why=body,
                             action=body + f"QZB{i:02d}Z", action_code=f"code_{i % 7}",
                             action_short="Move the hosts to enforcement.") for i in range(19))
    doc = make_doc(findings=findings, kpis=tuple(Kpi(key=f"k{i}", label=f"Number {i}", value=i, previous=None)
                                                 for i in range(5)),
                   sections=(Section(id="hosts", title="Hosts", blocks=(table([("a", 1)]),)),))
    page = _page(context, render_html(doc, tz=UTC), width=PAPER_W, media="print")
    height = page.evaluate("document.documentElement.scrollHeight")
    pages = _pdf_pages(page, tmp_path)
    for i in range(19):
        first = [n for n, t in enumerate(pages) if f"QZA{i:02d}Zfinding" in t]  # the card (its links say "…Z finding" too)
        last = [n for n, t in enumerate(pages) if f"QZB{i:02d}Z" in t]
        assert last and set(last) <= set(first), f"card {i} starts on {first}, ends on {last}"
    assert all(len(t) > 200 for t in pages[:-1]), [len(t) for t in pages]  # no blank page, no heading alone
    needed = math.ceil(height / PAPER_H)
    assert needed <= len(pages) <= needed + 2, (height, len(pages))  # whole cards leave a little white per page


LONGEST = ("rpt_sec_kpi_pb_flows", "rpt_sec_kpi_allowed_pct", "rpt_sec_kpi_blocked_flows")


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_the_lead_numbers_are_level_at_every_width(context, lang):
    """The three longest names there are, one cell with all four lines and one with two: equal heights anyway."""
    names = [translate(lang, k, {}) for k in LONGEST]
    kpis = (Kpi(key="a", label=names[0], value=7125, previous=9948, better="lower"),
            Kpi(key="b", label=names[1], value=94.6, previous=None, unit="percent", better="higher", note="A note. " * 20),
            Kpi(key="c", label=names[2], value=None, previous=None))
    html = render_html(make_doc(lang=lang, kpis=kpis), tz=UTC)
    for width, media, one_row in ((1440, "screen", True), (820, "screen", False), (PAPER_W, "print", True)):
        page = _page(context, html, width=width, media=media)
        boxes = page.evaluate("[...document.querySelectorAll('[data-role=lead-kpi]')].map(e => {"
                              " const r = e.getBoundingClientRect(); return [r.top, r.height, r.left, r.width]; })")
        assert len(boxes) == 3
        heights = [b[1] for b in boxes]
        assert max(heights) - min(heights) <= 1, (width, media, heights)
        tops = [b[0] for b in boxes]
        if one_row:
            assert max(tops) - min(tops) <= 1 and boxes[0][2] < boxes[1][2] < boxes[2][2], (width, media, boxes)
            widths = [b[3] for b in boxes]
            assert max(widths) - min(widths) <= 1, (width, media, widths)
        else:  # a narrow screen stacks them
            assert tops[0] < tops[1] < tops[2] and len({b[2] for b in boxes}) == 1, (width, boxes)
        # every word of every cell is inside its cell, and the page does not scroll sideways
        assert page.evaluate("[...document.querySelectorAll('[data-role=lead-kpi], [data-role=lead-kpi] *')]"
                             ".every(e => e.scrollWidth <= e.clientWidth + 1)"), (width, media)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), (width, media)
        page.close()


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_the_longest_names_fit_the_page_and_the_paper(context, lang):
    """The cells and column names that grew when a decision and a mode got plain words (stage 3a Task 5): a
    readiness scores table (four share columns and the modes cell), a table whose columns are the four modes, and a
    cell holding a decision's name. On screen a table may scroll inside its panel; nothing is cut and the page
    itself never scrolls sideways; on paper every table is inside the page."""
    def t(key, **params):
        return translate(lang, key, {k: str(v) for k, v in params.items()})
    modes = [t(k) for k in ("term_mode_full", "term_mode_selective", "term_mode_visibility_only", "term_mode_idle")]
    cell = t("rpt_rdy_modes", full_word=modes[0], full=12, selective_word=modes[1], selective=3,
             visibility_word=modes[2], visibility=140, idle_word=modes[3], idle=7)
    assert lang is not Language.EN or len(cell) > 100
    scores = TableBlock(
        title="Scores", columns=(Column(key="app", label="App (environment)"),
                                 *(Column(key=f"s{i}", label=f"Share of basis {i}") for i in range(4)),
                                 Column(key="hosts", label="Hosts enforced", kind="number"),
                                 Column(key="modes", label="Host modes")),
        rows=tuple((f"CoreServices-{i} (Production)", "12.5%", "100.0%", "4.9%", "66.7%", i, cell) for i in range(4)),
        total_rows=4, empty_text="-")
    by_mode = TableBlock(title="Modes", columns=(Column(key="os", label="OS"),
                                                 *(Column(key=f"m{i}", label=m, kind="number") for i, m in enumerate(modes))),
                         rows=(("Windows", 1, 2, 3, 4), ("Linux", 5, 6, 7, 8)), total_rows=2, empty_text="-")
    decisions = TableBlock(title="Decisions", columns=(Column(key="decision", label="Decision"),
                                                       Column(key="n", label="Connections", kind="number"),
                                                       Column(key="note", label="Note")),
                           rows=tuple((t(k), 7125, LONG) for k in ("term_decision_potentially_blocked",
                                                                   "term_decision_allowed", "term_decision_blocked")),
                           total_rows=3, empty_text="-")
    html = render_html(make_doc(lang=lang, sections=(Section(id="s", title="S", blocks=(scores, by_mode, decisions)),)),
                       tz=UTC)
    for width, media in ((1440, "screen"), (820, "screen"), (PAPER_W, "print")):
        page = _page(context, html, width=width, media=media)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), (width, media)
        cut = page.evaluate("""() => [...document.querySelectorAll('.chapter *')].filter(e => {
            const cs = getComputedStyle(e);
            return e.scrollWidth > e.clientWidth + 1 && cs.display !== 'inline' && cs.overflowX !== 'visible'
                && cs.overflowX !== 'auto' && cs.overflowX !== 'scroll'; }).map(e => e.className || e.tagName)""")
        assert cut == [], (width, media, cut)
        if media == "print":
            right = page.evaluate("Math.max(...[...document.querySelectorAll('table.report-table')]"
                                  ".map(e => e.getBoundingClientRect().right))")
            assert right <= width + 0.5, right
        page.close()
