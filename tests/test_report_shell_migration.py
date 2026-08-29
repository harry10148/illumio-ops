"""Old→new conservation and structure gate for the v2 report-shell migration.

Every report type that has been moved onto ``build_shell_document`` is listed in
``MIGRATED``; the whole module is parametrised over it, so Tasks 4 and 5 add a
type by appending one string and one baseline JSON — nothing here needs
restructuring.

WHAT THIS FILE CAN AND CANNOT SEE
=================================
``conservation.py``'s module docstring is the authority; the short version is
that an empty conservation result proves only "every text node of the old
document is findable somewhere in the new one". It is blind to pairing, order,
position, chart content, strings under four characters, and duplicated text.
The count assertions below (``table_count`` / ``chart_count``) close "a whole
table or chart vanished", and
``test_known_cell_still_sits_under_its_own_column`` closes the one failure shape
this particular migration can realistically produce — a table whose header row
survives while the columns underneath it are re-mapped. Everything else is
covered by each type's own exporter tests and by the page-by-page check on real
output.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from bs4 import BeautifulSoup

from src.i18n import t
from tests.report_shell.conservation import (
    conservation_text,
    label_value_preserved,
    norm,
)
from tests.report_shell.fixtures import BUILDERS

BASELINES = pathlib.Path(__file__).parent / "report_shell" / "baselines"

# Tasks 4 and 5 append their report types here (one string + one baseline file
# in tests/report_shell/baselines/ is the whole change).
MIGRATED = ["traffic", "security_risk", "network_inventory"]

# Old-side text with no successor in the v2 shell. Every entry carries its own
# reason; batch-adding entries to make a red run green is what this list exists
# to prevent.
_WALL_CLOCK_COVER = norm("2026-08-30 05:08")
# cover_page.build_cover_page() printed ``datetime.now()`` at render time. The
# call is removed (A9), and a wall-clock value could not be conserved anyway:
# the baseline froze the capture minute, so the string is unreachable from any
# later run, migrated or not. The report's real generation timestamp
# (mod12.generated_at) is conserved and asserted by the cover-meta path.

_FOOTER_WITH_DATE = norm("Illumio PCE Ops Traffic Flow Report · 2026-08-30")
# The footer is ``rpt_tr_footer + " · " + date.today()``. The i18n half is
# conserved (it moves into the appendix colophon) and is asserted separately by
# test_footer_text_survives_into_the_appendix; only the date half moves with the
# calendar, so this leaf goes red the day after the baseline was captured
# regardless of what the migration did.

_LEGACY_COVER_BRAND = norm("Illumio Operations")
# The eyebrow of the deleted print-only cover — vendor branding chrome, not
# report content. The v2 cover's eyebrow carries the report type label instead
# (which the legacy cover showed in .cover-title/.cover-type), so the type label
# stays in the text layer while this brand line has no successor. The screen
# cover's other brand line, "Illumio PCE Ops", needs no entry: it survives as a
# substring of the conserved footer text.

_COMMON_ALLOWLIST = frozenset({
    _WALL_CLOCK_COVER,
    _FOOTER_WITH_DATE,
    _LEGACY_COVER_BRAND,
})

ALLOWLIST: dict[str, frozenset[str]] = {
    "traffic": _COMMON_ALLOWLIST,
    "security_risk": _COMMON_ALLOWLIST,
    "network_inventory": _COMMON_ALLOWLIST,
}

# One cell value per type that must still sit under its own column heading.
# (report_type, cell value, expected column heading text)
KNOWN_CELLS: dict[str, tuple[str, str]] = {
    "traffic": ("tcp-prts-alfa", "Protocol"),
    "security_risk": ("Policy Coverage", "Metric"),
    "network_inventory": ("tcp-unmg-alfa", "Protocol"),
}


def _baseline(rtype: str) -> dict:
    return json.loads((BASELINES / f"{rtype}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("rtype", MIGRATED)
def test_conservation_against_baseline(rtype):
    base = _baseline(rtype)
    html = BUILDERS[rtype]()
    _, flat = conservation_text(html)
    allow = ALLOWLIST.get(rtype, frozenset())
    lost = [text for text in base["leaves"]
            if text not in allow and not label_value_preserved(text, flat)]
    assert lost == [], f"{rtype} 遺失 {len(lost)} 段內容: {lost[:10]}"


@pytest.mark.parametrize("rtype", MIGRATED)
def test_table_and_chart_counts_conserved(rtype):
    base = _baseline(rtype)
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    assert len(soup.select("table.report-table")) == base["table_count"]
    assert len(soup.select("figure.chart-static")) == base["chart_count"]


@pytest.mark.parametrize("rtype", MIGRATED)
def test_new_shell_structure(rtype):
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    assert soup.select_one("div.sheet > div.doc")
    assert soup.select_one("header.cover h1")
    toc = [a["href"].lstrip("#") for a in soup.select("nav.toc ol a")]
    body_ids = [s["id"] for s in
                soup.select("section.exec[id], div.chapters > section.chapter")]
    # A chapter that quietly stops rendering blows up here rather than just
    # disappearing from the document (prototype lesson, reskin_report 417-424).
    assert toc == body_ids
    assert soup.select_one("div.report-shell") is None    # old shell container
    assert soup.select_one("aside.report-toc") is None    # old sidebar nav
    assert 'class="print-btn"' in str(soup)


@pytest.mark.parametrize("rtype", MIGRATED)
def test_legacy_cover_page_is_not_emitted(rtype):
    """A9: the call to build_cover_page() is gone, not merely unrendered.

    ``.report-cover.print-only`` becomes ``display: block`` in print, so a
    leftover call would add a second cover page to every PDF while the screen
    view looked fine.
    """
    html = BUILDERS[rtype]()
    assert 'class="report-cover' not in html
    assert 'report-cover-block' not in html


@pytest.mark.parametrize("rtype", MIGRATED)
def test_footer_text_survives_into_the_appendix(rtype):
    """Pairs with the ``_FOOTER_WITH_DATE`` allowlist entry.

    The exempted leaf is the footer *plus that day's date*. Without this the
    exemption would also cover the footer text itself disappearing.
    """
    _, flat = conservation_text(BUILDERS[rtype]())
    assert norm(t("rpt_tr_footer", lang="en")) in flat


@pytest.mark.parametrize("rtype", MIGRATED)
def test_known_cell_still_sits_under_its_own_column(rtype):
    """The failure shape conservation cannot see: header kept, data re-mapped.

    Conservation is a set-membership check, so a table whose columns are
    shuffled underneath an intact header row passes it silently. This walks from
    the cell back up to its own ``<th>``.
    """
    value, expected_heading = KNOWN_CELLS[rtype]
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    for cell in soup.select("table.report-table td"):
        if cell.get_text(strip=True) != value:
            continue
        row = cell.find_parent("tr")
        index = row.find_all("td").index(cell)
        headings = cell.find_parent("table").select("thead th")
        assert headings[index].get_text(strip=True) == expected_heading
        return
    pytest.fail(f"{rtype}: 找不到儲存格 {value!r}，欄位對齊不變量無法驗證")


@pytest.mark.parametrize("rtype", MIGRATED)
def test_grade_colour_comes_from_data_tone_not_inline_style(rtype):
    """A1: no grade-coloured element carries an inline colour any more."""
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    for element in soup.select(".score-hero, .score-num, .grade-chip, .grade-hero"):
        style = element.get("style", "")
        assert "color" not in style, f"{rtype}: {element.name} 仍帶 inline 色碼 {style!r}"
        toned = element if element.get("data-tone") else element.find_parent(
            attrs={"data-tone": True})
        assert toned is not None, f"{rtype}: {element} 沒有任何 data-tone 祖先"
