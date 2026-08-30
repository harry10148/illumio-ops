"""Old→new conservation and structure gate for the v2 report-shell migration.

Every report type that has been moved onto ``build_shell_document`` is listed in
``MIGRATED``; the whole module is parametrised over it, so Tasks 4 and 5 extend
it in place — nothing here needs restructuring. The checklist for adding a type
is on ``MIGRATED`` itself: it is four items, not one, and the two that are easy
to miss are the per-type ``KNOWN_CELLS`` entry and the per-type ``ALLOWLIST``
entry for whatever render-time clock values that type's baseline froze.

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

# Tasks 4 and 5 append their report types here. Adding one needs, at minimum:
#   1. the string below;
#   2. `tests/report_shell/baselines/<type>.json`, captured on PRE-migration
#      code (scripts/capture_report_baselines.py);
#   3. an entry in `KNOWN_CELLS` — the column-alignment invariant is per type
#      and `test_known_cell_still_sits_under_its_own_column` fails loudly
#      without one;
#   4. that type's own `ALLOWLIST` entry for whatever render-time clock values
#      its baseline froze. The cover/footer timestamps below are Task 3's
#      capture date and are NOT reusable — capture yours, write your own
#      reasons.
# Nothing here needs restructuring; every test is parametrised over MIGRATED.
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

_WRONG_EXEC_SUFFIX = norm("Executive Summary — Traffic Report")
# The old exec-summary heading hard-coded t('gui_btn_traffic_report') for all
# three types, so the security-risk and network-inventory reports both titled
# their executive summary "… — Traffic Report". That was wrong, not stylistic
# (fix round 1, F5); the suffix is each type's own label now, and a corrected
# string has no obligation to contain the incorrect one it replaced. Only those
# two types get the exemption — the traffic report's suffix genuinely is
# "Traffic Report" and still matches, which is why `traffic` is absent below.
# test_exec_chapter_names_its_own_report_type is what keeps this honest.

_COMMON_ALLOWLIST = frozenset({
    _WALL_CLOCK_COVER,
    _FOOTER_WITH_DATE,
    _LEGACY_COVER_BRAND,
})

ALLOWLIST: dict[str, frozenset[str]] = {
    "traffic": _COMMON_ALLOWLIST,
    "security_risk": _COMMON_ALLOWLIST | {_WRONG_EXEC_SUFFIX},
    "network_inventory": _COMMON_ALLOWLIST | {_WRONG_EXEC_SUFFIX},
}

# The report-type label each type's executive summary must name (F5).
EXEC_SUFFIX: dict[str, str] = {
    "traffic": "Traffic Report",
    "security_risk": "Security Risk Profile",
    "network_inventory": "Network Inventory",
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


# ---------------------------------------------------------------------------
# Fix round 1 — F2/F3/F4/F5/F6. These are user-visible colours and numbers, so
# each one is asserted on the rendered document, not on a helper's return value.
# ---------------------------------------------------------------------------

def _findings_results(severities):
    """A SecurityRisk input whose findings carry exactly ``severities``."""
    from dataclasses import dataclass, field

    @dataclass
    class _F:
        rule_id: str
        rule_name: str
        severity: str
        severity_rank: int
        category: str = "COVERAGE"
        description: str = "description text"
        recommendation: str = "recommendation text"
        evidence: dict = field(default_factory=dict)

    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    findings = [
        _F(rule_id=f"R{i:03d}", rule_name=f"rule name {i}", severity=sev,
           severity_rank=rank.get(sev, 9))
        for i, sev in enumerate(severities)
    ]
    return {
        "mod01": {"total_flows": 100, "total_mb": 10},
        "mod12": {"kpis": [], "key_findings": [], "maturity_score": 52,
                  "maturity_grade": "D", "maturity_dimensions": {},
                  "generated_at": "2026-05-15 09:00",
                  # An action row whose severity is CRITICAL regardless of what
                  # the findings carry: if it leaked into the chapter marks the
                  # two numbers below would disagree.
                  "action_matrix": [{"action_code": "LOCK_PORTS", "count": 3,
                                     "action": "lock down boundary ports",
                                     "severity": "CRITICAL", "apps": ["web"],
                                     "flow_total": 450}]},
        "findings": findings,
    }


def _security_html(severities):
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
    return SecurityRiskHtmlExporter(_findings_results(severities), lang="en").build()


def test_finding_cards_carry_their_own_tone():
    """F2: a LOW card inside a critical chapter must not be painted crit red.

    ``.finding-card``'s left rule is ``solid var(--mark)``, which resolves from
    the nearest ``[data-tone]`` ancestor — the chapter. Without a tone of its
    own every card in a critical chapter reads as critical.
    """
    soup = BeautifulSoup(_security_html(["CRITICAL", "LOW"]), "html.parser")
    chapter = soup.select_one("section.chapter#findings")
    assert chapter["data-tone"] == "crit"        # the hostile environment
    cards = [(" ".join(c.get("class", [])), c.get("data-tone"))
             for c in soup.select(".finding-card")]
    assert sorted(cards) == [
        ("finding-card sev-CRITICAL", "crit"),
        ("finding-card sev-LOW", "info"),
    ], f"發現卡沒有自己的 tone，會繼承所在章的 crit：{cards}"


def test_severity_summary_boxes_distinguish_critical_from_high():
    """F3: CRITICAL is solid, HIGH is outlined — the rule needs data-sev.

    ``[data-tone="crit"][data-sev="CRITICAL"].badge`` is the only thing keeping
    the two apart; they share the ``crit`` tone.
    """
    soup = BeautifulSoup(_security_html(["CRITICAL", "HIGH"]), "html.parser")
    boxes = soup.select(".sev-summary .sev-box .badge")
    assert boxes, "severity summary rendered no badges"
    by_sev = {b.get("data-sev"): b.get("data-tone") for b in boxes}
    assert by_sev.get("CRITICAL") == "crit"
    assert by_sev.get("HIGH") == "crit"
    # Both tones are crit; only data-sev can separate them, so it must be on
    # every box, not just those two.
    assert all(b.get("data-sev") for b in boxes)


@pytest.mark.parametrize("severities", [
    [],
    ["CRITICAL"],
    ["CRITICAL", "CRITICAL", "LOW"],
    ["HIGH", "MEDIUM", "MEDIUM", "INFO"],
])
def test_chapter_marks_agree_with_the_count_in_the_chapter_heading(severities):
    """F4: the heading's "(n)" and the chapter's mark chips are one tally.

    They used to be two: the heading counted ``findings`` while the marks
    counted every ``data-sev`` in the rendered body, so a table's severity cells
    and the action-matrix rows inflated the chips. ``_findings_results`` puts a
    CRITICAL action row in every case precisely so a regression shows up here.
    """
    soup = BeautifulSoup(_security_html(severities), "html.parser")
    chapter = soup.select_one("section.chapter#findings")
    heading = chapter.select_one(".chapter-title").get_text(strip=True)
    in_heading = int(heading.rsplit("(", 1)[1].rstrip(")"))
    chips = chapter.select(".chapter-marks .mark-chip")
    in_marks = sum(int(chip.get_text(strip=True).rsplit(" ", 1)[1]) for chip in chips)
    assert in_heading == len(severities)
    assert in_marks == in_heading, (
        f"章頭 {heading!r} 印 {in_heading}，章標印 {in_marks}："
        f"{[c.get_text(strip=True) for c in chips]}")


def test_a_severity_table_cell_does_not_tone_the_whole_document():
    """F4, second half: one CRITICAL cell must not dye the cover.

    ``doc_tone`` is "crit if any chapter is crit"; when marks came from the
    rendered markup a single severity cell in an unrelated table reached it.
    """
    soup = BeautifulSoup(_security_html([]), "html.parser")
    # The action matrix (CRITICAL) and its badge are rendered, but there are no
    # findings, so nothing may claim a critical tone.
    assert soup.select_one('td .badge[data-sev="CRITICAL"]') is not None
    assert soup.select_one("header.cover")["data-tone"] != "crit"
    assert [s["data-tone"] for s in soup.select("section.chapter")].count("crit") == 0


@pytest.mark.parametrize("rtype", MIGRATED)
def test_exec_chapter_names_its_own_report_type(rtype):
    """F5: the exec summary must not call every report a Traffic Report.

    Pairs with the ``_WRONG_EXEC_SUFFIX`` allowlist entry: that exemption drops
    the old (incorrect) string, and this is what proves a correct one replaced
    it rather than nothing at all.
    """
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    exec_section = soup.select_one("section.exec#exec-summary")
    title = exec_section.select_one("h2").get_text(strip=True)
    assert title == f"Executive Summary \u2014 {EXEC_SUFFIX[rtype]}"
    # …and the block must not print its own heading a second time.
    assert exec_section.select_one(".exec-summary h2") is None


@pytest.mark.parametrize("rtype", MIGRATED)
def test_table_of_contents_has_no_duplicate_titles(rtype):
    """F5: two chapters called "Executive Summary" in a row is a naming bug."""
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    labels = [el.get_text(strip=True) for el in soup.select("nav.toc ol li .toc-label")]
    assert labels, "目錄沒有任何項目"
    duplicates = {label for label in labels if labels.count(label) > 1}
    assert not duplicates, f"{rtype}: 目錄有重複章名 {sorted(duplicates)}"


@pytest.mark.parametrize("rtype", MIGRATED)
def test_cover_does_not_print_the_same_label_twice(rtype):
    """F6: eyebrow and profile badge were the same string, stacked."""
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    cover = soup.select_one("header.cover")
    eyebrow = cover.select_one(".cover-eyebrow").get_text(strip=True)
    badges = [b.get_text(strip=True) for b in cover.select(".cover-badges .badge")]
    assert eyebrow not in badges, f"{rtype}: 封面把 {eyebrow!r} 印了兩次"
