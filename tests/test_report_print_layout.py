"""Print-layout invariants, restated against the v2 shell.

These used to read ``report_css.BASE_CSS`` and ``cover_page.build_cover_page()``.
Both are gone (Task 6 of the Phase 2B reskin); the requirements they encoded are
not, so each one is re-anchored on ``report_shell.SHELL_CSS`` and on the cover
``build_shell_document()`` actually renders. Where a requirement genuinely
stopped existing — the legacy print-only second cover — the case is deleted with
the reason stated on the replacement, not silently dropped.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from src.report.exporters.html_exporter import HtmlExporter
from src.report.exporters.report_shell import (
    SHELL_CSS, ShellCover, ShellSection, build_shell_document)

SCREEN_CSS, PRINT_CSS = SHELL_CSS.split("@media print")[0:2]

# Containers a whole page (or more) tall. If any of them ever says
# "do not break inside me", the printer pushes it whole to the next sheet and
# leaves the previous one mostly blank.
PAGE_SIZED_CONTAINERS = (".sheet", ".doc", ".chapter", ".exec", ".appendix")


def _rules_for(css: str, selector: str) -> list[str]:
    """Every rule block whose selector list contains ``selector`` exactly."""
    out = []
    for m in re.finditer(r"([^{}/]+)\{([^}]*)\}", css):
        parts = [s.strip() for s in m.group(1).split(",")]
        if selector in parts:
            out.append(m.group(2))
    return out


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

def test_page_sized_containers_do_not_forbid_breaking():
    """Was ``test_card_no_longer_has_page_break_inside_avoid``.

    The old shell had learned this on ``.card``; the v2 shell has no ``.card``,
    so the invariant is restated on the containers that are actually page-sized.
    ``break-inside: avoid`` is legitimate and present on the small units
    (``.finding-card``, ``.report-table-panel``, ``.mat-row``, ``.sev-box``,
    ``figure.chart-static``, ``.toc li``, table rows) — the defect is putting it
    on something a page tall.
    """
    offenders = {
        sel: body
        for sel in PAGE_SIZED_CONTAINERS
        for body in _rules_for(PRINT_CSS, sel) + _rules_for(SCREEN_CSS, sel)
        if "break-inside: avoid" in body or "page-break-inside: avoid" in body
    }
    assert offenders == {}, f"page-sized containers refusing to break: {offenders}"


def test_chapters_start_on_a_new_page():
    assert "break-before: page" in "".join(_rules_for(PRINT_CSS, ".chapter"))


def test_cover_and_exec_and_toc_each_own_their_page():
    """The v2 replacement for the legacy ``.report-cover`` print-only block.

    The old shell emitted a second, full-page ``<section class="report-cover">``
    that was ``display: none`` on screen and ``display: flex`` in print — three
    of the deleted cases (``test_cover_page_css_present``,
    ``test_cover_hidden_in_screen``, ``test_cover_visible_in_print``) only
    described that mechanism. The v2 shell has one cover, shown in both media,
    and it claims its page with ``break-after`` instead.
    """
    for sel in (".cover", ".exec", ".toc"):
        assert "break-after: page" in "".join(_rules_for(PRINT_CSS, sel)), sel


def test_chapter_headings_are_not_orphaned_at_the_foot_of_a_page():
    assert "break-after: avoid" in "".join(_rules_for(PRINT_CSS, ".chapter-head"))


# --------------------------------------------------------------------------
# Tables in print
# --------------------------------------------------------------------------

def test_thead_repeats_on_every_printed_page():
    assert "display: table-header-group" in \
        "".join(_rules_for(PRINT_CSS, ".report-table thead"))


def test_table_rows_are_not_split_across_pages():
    assert "break-inside: avoid" in \
        "".join(_rules_for(PRINT_CSS, ".report-table tbody tr"))


def test_wide_tables_shrink_their_type_in_print():
    """Was ``font-size: 7.5pt`` on ``.report-table-panel--wide``; the v2 shell
    ships 6.5pt. The requirement is that wide tables get *smaller* type than
    body copy, not one particular value.

    C2: the first rewrite compared against a hardcoded ``9.0``, which is the
    body size only for as long as nobody edits ``--fs-ui``. Measured: setting
    ``--fs-ui`` to ``5pt`` makes the 6.5pt wide table *larger* than body copy
    and the hardcoded form still passed. Both sides are read out of the print
    block now, so the comparison is between the two values that actually meet
    on the page.
    """
    body = "".join(_rules_for(PRINT_CSS, ".report-table-panel--wide .report-table"))
    m = re.search(r"font-size:\s*([\d.]+)pt", body)
    assert m, f"wide tables declare no print font-size: {body!r}"
    wide_pt = float(m.group(1))

    # Read straight out of the print block rather than through _rules_for:
    # PRINT_CSS still carries @media's own opening brace, so a rule splitter
    # swallows the :root override that redeclares the size tokens in pt.
    body_sizes = re.findall(r"--fs-ui:\s*([\d.]+)pt", PRINT_CSS)
    assert len(body_sizes) == 1, (
        f"expected exactly one print --fs-ui declaration, found {body_sizes}")
    body_pt = float(body_sizes[0])

    assert wide_pt < body_pt, (
        f"wide-table print type {wide_pt}pt is not smaller than body copy "
        f"({body_pt}pt) — a wide table set larger than the text around it is "
        f"the opposite of the fit-more-columns intent")


def test_wide_table_hint_is_hidden_in_print():
    """``wide_table_attrs`` emits a ``.table-hint`` paragraph on every wide
    table, but it is an on-screen scroll affordance, not report content — it
    tells the reader the table scrolls sideways, which is meaningless on paper.
    """
    assert ".table-hint { display: none; }" in PRINT_CSS
    assert ".table-hint { display: none; }" not in SCREEN_CSS


def test_print_table_cells_break_words_rather_than_clip():
    """Ordinary cells use ``break-word`` (``anywhere`` splits numbers), and the
    long-text column inside a wide table is the one allowed ``anywhere``."""
    assert "overflow-wrap: break-word" in \
        "".join(_rules_for(PRINT_CSS, ".report-table tbody td"))
    assert "overflow-wrap: anywhere" in \
        "".join(_rules_for(PRINT_CSS,
                           ".report-table-panel--wide .report-table td.col-long"))


def test_collapsed_long_cells_still_print_their_full_text():
    """CLAUDE.md's silent-truncation rule, in its print form: a collapsed
    ``<details>`` hides its content through ``::details-content``, so without
    this the full text never reaches the PDF text layer at all."""
    assert ".cell-long::details-content { content-visibility: visible; }" in PRINT_CSS
    assert "display: block" in \
        "".join(_rules_for(PRINT_CSS, ".cell-long > .cell-long-full"))


def test_three_column_layout_drops_to_two_in_print():
    """A4 portrait leaves the third column too narrow for its table's
    min-content, and the panel clips the overflow — measured: "966,315" printed
    as "966,31"."""
    body = "".join(_rules_for(PRINT_CSS, ".tri-grid"))
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in body


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def test_chart_frames_neither_split_nor_overflow_their_column():
    """Was ``.chart-container { page-break-inside: avoid; overflow: hidden }``.

    The v2 charts are server-rendered SVG rather than a JS canvas, so the
    bleeding is prevented by constraining the SVG instead of clipping the box;
    the "do not split a chart across a page break" half is unchanged.
    """
    assert "break-inside: avoid" in \
        "".join(_rules_for(PRINT_CSS, "figure.chart-static") +
                _rules_for(SCREEN_CSS, "figure.chart-static"))
    svg = "".join(_rules_for(SCREEN_CSS, "figure.chart-static svg"))
    assert "max-width: 100%" in svg and "width: 100%" in svg


def test_screen_td_breaks_long_words():
    """Screen layout must break long words in table cells to prevent horizontal
    scrolling on narrow viewports (URLs, hostnames, etc.)."""
    assert "overflow-wrap: break-word" in \
        "".join(_rules_for(SCREEN_CSS, ".report-table tbody td"))


# --------------------------------------------------------------------------
# The cover the shell renders
# --------------------------------------------------------------------------

def _cover_doc(**kw) -> str:
    return build_shell_document(
        lang=kw.pop("lang", "en"),
        cover=ShellCover(**kw),
        sections=[ShellSection(id="s", title="S", html="<p>body</p>")],
    )


def test_cover_carries_title_pce_and_org():
    html = _cover_doc(
        title="Traffic Security Report", doc_title="Traffic Security Report",
        type_label="Security Risk",
        meta={"Date range": "2026-04-01 – 2026-05-11",
              "PCE": "pce.example.com", "Organization": "Acme Corp"},
    )
    cover = BeautifulSoup(html, "html.parser").select_one('header.cover[data-shell="cover"]')
    assert cover is not None
    assert cover.select_one("h1").get_text() == "Traffic Security Report"
    text = cover.get_text(" ", strip=True)
    for expected in ("pce.example.com", "Acme Corp", "2026-04-01 – 2026-05-11"):
        assert expected in text, expected


def test_cover_renders_zh_tw():
    html = _cover_doc(lang="zh_TW", title="流量安全報告", doc_title="流量安全報告",
                      type_label="", meta={"產生時間": "2026-05-11 09:00"})
    cover = BeautifulSoup(html, "html.parser").select_one("header.cover")
    text = cover.get_text(" ", strip=True)
    assert "流量安全報告" in text and "產生時間" in text


def test_cover_omits_the_blocks_it_has_no_data_for():
    """The legacy cover emitted 📅 / 🖥 rows for empty values; the shell drops the
    whole element instead of printing an empty label."""
    soup = BeautifulSoup(
        _cover_doc(title="Test", doc_title="Test", type_label=""), "html.parser")
    cover = soup.select_one("header.cover")
    assert cover.select_one(".cover-meta") is None
    assert cover.select_one(".cover-badges") is None
    assert cover.select_one(".cover-eyebrow") is None
    assert cover.select_one(".cover-kicker") is None
    assert cover.select_one("h1") is not None


# --------------------------------------------------------------------------
# End to end through a real exporter
# --------------------------------------------------------------------------

def _minimal_results() -> dict:
    return {k: {} for k in [
        "mod01", "mod02", "mod03", "mod04", "mod05", "mod06",
        "mod07", "mod08", "mod09", "mod11", "mod12",
        "mod13", "mod14", "mod15",
    ]}


def test_html_exporter_renders_exactly_one_cover():
    """The old assertion here was ``'class="report-cover' not in html``. That
    string cannot appear anywhere now that ``cover_page.py`` is deleted, so it
    would be permanently true and guard nothing. The requirement it stood for —
    the reader gets one cover page, not two — is counted directly instead.
    """
    exp = HtmlExporter(
        _minimal_results(),
        pce_url="pce.test", org_name="TestOrg",
        date_range=("2026-01-01", "2026-05-01"), lang="en",
    )
    html = exp.build()
    soup = BeautifulSoup(html, "html.parser")
    covers = soup.select('header.cover[data-shell="cover"]')
    assert len(covers) == 1, f"expected exactly one cover, found {len(covers)}"
    # Nothing else in the document may claim a full page ahead of the content.
    assert len(soup.select("h1")) == 1
    # PCE and organisation are asserted per PLACE, not once against the whole
    # document. The cover and the appendix's "Generation parameters" render the
    # same ``ShellCover.meta`` dict, so `"pce.test" in html` cannot tell the two
    # apart: measured, with the appendix emitting no meta block and the cover
    # keeping its own, the document-wide form is GREEN and the two below are
    # RED. (The reverse direction is NOT a hole -- one source, so dropping it
    # takes both renderings with it and the document-wide form does go red.)
    cover_meta = covers[0].select_one("dl.cover-meta").get_text(" ", strip=True)
    assert "pce.test" in cover_meta, cover_meta
    assert "TestOrg" in cover_meta, cover_meta
    appendix = soup.select_one("section.appendix").get_text(" ", strip=True)
    assert "pce.test" in appendix and "TestOrg" in appendix, appendix


def test_html_exporter_data_report_title():
    exp = HtmlExporter(_minimal_results(), lang="en")
    html = exp.build()
    assert 'data-report-title="' in html
    assert 'data-report-title=""' not in html
