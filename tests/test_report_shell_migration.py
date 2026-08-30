"""Old→new conservation and structure gate for the v2 report-shell migration.

Every report type that has been moved onto ``build_shell_document`` is listed in
``MIGRATED``; the whole module is parametrised over it, so Tasks 4 and 5 extend
it in place — nothing here needs restructuring. The checklist for adding a type
is on ``MIGRATED`` itself: it is six items, not one, and the ones that are easy
to miss are the per-type ``KNOWN_CELLS`` entry, the per-type
``EXPECTED_SECTION_IDS`` entry, and the per-type ``ALLOWLIST`` entry for
whatever render-time clock values that type's baseline froze.

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

import pandas as pd
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
#   5. an entry in `EXPECTED_SECTION_IDS` — `test_new_shell_structure` only
#      proves the TOC agrees with the body, which stays true when a whole
#      chapter stops rendering; the static list is what notices.
#   6. an entry in `FOOTER_KEY` — the appendix-colophon check is per type and
#      pairs with that type's dated footer exemption.
# Nothing here needs restructuring; every test is parametrised over MIGRATED.
MIGRATED = ["traffic", "security_risk", "network_inventory",
            "audit", "ven_status", "policy_usage"]

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

# --------------------------------------------------------------------------
# Task 4's own exemptions. The wall-clock strings below are the minute and the
# day Task 4's baselines were captured; they are NOT Task 3's and neither set is
# reusable by Task 5 — capture your own and write your own reasons.
# --------------------------------------------------------------------------
_T4_WALL_CLOCK_COVER = norm("2026-08-30 08:48")
# Same mechanism as _WALL_CLOCK_COVER above, different capture minute: the
# legacy build_cover_page() stamped datetime.now() into both the screen and the
# print cover. The call is gone (A9/B4) and the value was unreachable anyway —
# it froze the minute the baseline was taken. Each report's real generation
# timestamp (mod00.generated_at) travels to the cover meta and is asserted by
# test_cover_meta_carries_the_generation_timestamp_and_period.

_AUDIT_FOOTER_WITH_DATE = norm("Illumio PCE Ops Audit Report · 2026-08-30")
_VEN_FOOTER_WITH_DATE = norm("Illumio PCE Ops VEN Status Report · 2026-08-30")
_PU_FOOTER_WITH_DATE = norm("Illumio PCE Ops Policy Usage Report · 2026-08-30")
# Each footer is ``rpt_<type>_footer + " · " + date.today()``. The i18n half
# moves into the appendix colophon and is asserted per type by
# test_footer_text_survives_into_the_appendix (see FOOTER_KEY); only the date
# half follows the calendar, so these leaves go red the day after capture no
# matter what the migration did.

_AUDIT_HERO_SUBTITLE = norm(
    "Generated: 2026-07-23 12:00:00  |  Period: 2026-07-16 ~ 2026-07-23")
# The audit hero glued four things into ONE text node: the "Generated" label,
# the generation timestamp, the "Period" label and the date range. The v2 cover
# splits them into separate dt/dd rows, and label_value_preserved() only
# tolerates ONE label:value split (it partitions on the first colon), so the
# glued form cannot be matched even though every part of it survives. Both
# values are asserted individually by
# test_cover_meta_carries_the_generation_timestamp_and_period; the tilde-joined
# range itself is separately conserved by the summary chapter's period pill.

# The deleted sidebar's own labels (rpt_*_nav_*). Most of them are prefixes of
# the chapter heading they linked to ("1 System Health" -> "1 System Health &
# Agent"), so they survive as substrings and need no entry; the ones below chose
# different words from their own heading and therefore have no successor. The
# heading is the fuller of the two in every case, and it is what the v2 table of
# contents shows, so keeping the sidebar wording instead would delete the
# qualifier ("Detail", "Decision", "Rule", "Connection") from the document. What
# these exemptions must not be allowed to cover is the CHAPTER going missing —
# EXPECTED_SECTION_IDS pins every id for that.
#   audit  "3 Policy Changes"    -> heading "3 Policy Modifications"
#   ven    "Lost Today (<24h)"   -> heading "Lost Connection in Last 24h"
#   ven    "Lost Yesterday"      -> heading "Lost Connection 24-48h Ago"
#   pu     "Deny Effectiveness"  -> heading "Deny Rule Effectiveness"
#   pu     "Draft Policy Risk"   -> heading "Draft Policy Decision Risk"
_AUDIT_NAV_ABBREVS = frozenset({norm("3 Policy Changes")})
_VEN_NAV_ABBREVS = frozenset({norm("Lost Today (<24h)"), norm("Lost Yesterday")})
_PU_NAV_ABBREVS = frozenset({norm("Deny Effectiveness"), norm("Draft Policy Risk")})

_VEN_EMPTY_GENERATED_LABEL = norm("Generated: ")
_VEN_LEGACY_COVER_GENERATED_LABEL = norm("Generated")
# Two labels with nothing behind them, both specific to the VEN fixture:
#   * the hero printed ``rpt_generated`` even when the report carried no
#     generation timestamp (this fixture's ``generated_at`` is empty), so the
#     node was a bare label and a trailing colon;
#   * the deleted print cover printed ``rpt_cover_generated`` as the label of
#     its ``datetime.now()`` stamp — the value is exempted above as a wall
#     clock, and the label has nothing left to introduce.
# The v2 cover emits a meta row only when there is a value to show.
# test_cover_meta_carries_the_generation_timestamp_and_period asserts both
# halves: audit and policy_usage DO get the label back because they have a real
# timestamp, and ven_status must not print it while it has none.

ALLOWLIST: dict[str, frozenset[str]] = {
    "traffic": _COMMON_ALLOWLIST,
    "security_risk": _COMMON_ALLOWLIST | {_WRONG_EXEC_SUFFIX},
    "network_inventory": _COMMON_ALLOWLIST | {_WRONG_EXEC_SUFFIX},
    "audit": frozenset({_T4_WALL_CLOCK_COVER, _LEGACY_COVER_BRAND,
                        _AUDIT_FOOTER_WITH_DATE,
                        _AUDIT_HERO_SUBTITLE}) | _AUDIT_NAV_ABBREVS,
    "ven_status": frozenset({_T4_WALL_CLOCK_COVER, _LEGACY_COVER_BRAND,
                             _VEN_FOOTER_WITH_DATE, _VEN_EMPTY_GENERATED_LABEL,
                             _VEN_LEGACY_COVER_GENERATED_LABEL}) | _VEN_NAV_ABBREVS,
    "policy_usage": frozenset({_T4_WALL_CLOCK_COVER, _LEGACY_COVER_BRAND,
                               _PU_FOOTER_WITH_DATE}) | _PU_NAV_ABBREVS,
}

# The i18n key each type's footer text comes from. It moves into the appendix
# colophon; the dated leaf is exempted above, so this is what keeps the
# exemption from also covering the footer text itself disappearing.
FOOTER_KEY: dict[str, str] = {
    "traffic": "rpt_tr_footer",
    "security_risk": "rpt_tr_footer",
    "network_inventory": "rpt_tr_footer",
    "audit": "rpt_au_footer",
    "ven_status": "rpt_ven_footer",
    "policy_usage": "rpt_pu_footer",
}

# The chapters each fixture must render, in order. ``test_new_shell_structure``
# only proves the TOC and the body agree with each other, which stays true when
# a chapter silently stops rendering (the whole point of the prototype's
# reskin_report 417-424 lesson) — this is the static half of that pair.
EXPECTED_SECTION_IDS: dict[str, tuple[str, ...]] = {
    "traffic": ("exec-summary", "summary", "overview", "policy",
                "distribution", "bandwidth", "unmanaged"),
    "security_risk": ("exec-summary", "summary", "drift", "overview", "policy",
                      "uncovered", "ransomware", "readiness", "infrastructure",
                      "lateral", "findings"),
    "network_inventory": ("exec-summary", "summary", "labels", "policy",
                          "matrix", "unmanaged", "ringfence", "change_impact"),
    "audit": ("exec-summary", "summary", "health", "users", "policy",
              "correlation"),
    "ven_status": ("exec-summary", "summary", "online", "sync-issues",
                   "offline", "lost-today", "lost-yest"),
    "policy_usage": ("exec-summary", "summary", "overview", "hit-rules",
                     "unused-rules", "deny-rules", "draft-pd"),
}

# The report-type label each type's executive summary must name (F5).
EXEC_SUFFIX: dict[str, str] = {
    "traffic": "Traffic Report",
    "security_risk": "Security Risk Profile",
    "network_inventory": "Network Inventory",
    # These three already named their own report type before the migration
    # (t('gui_btn_audit_report') and friends), so unlike the traffic family they
    # need no _WRONG_EXEC_SUFFIX exemption and the suffix keeps its old value.
    "audit": "Audit Report",
    "ven_status": "VEN Status Report",
    "policy_usage": "Policy Usage Report",
}

# One cell value per type that must still sit under its own column heading.
# (report_type, cell value, expected column heading text)
KNOWN_CELLS: dict[str, tuple[str, str]] = {
    "traffic": ("tcp-prts-alfa", "Protocol"),
    "security_risk": ("Policy Coverage", "Metric"),
    "network_inventory": ("tcp-unmg-alfa", "Protocol"),
    # Not the audit event_type column: its cells carry a risk badge and <wbr>
    # breaks, so get_text() returns "INFOsec_policy.create.evtzulu" and the
    # invariant would be checking the badge as much as the cell.
    "audit": ("informational-sevzulu", "severity"),
    # Not the online chapter: since spec K2 that chapter is a version-count
    # summary, and the per-host columns only exist in sync-issues/offline.
    "ven_status": ("k8s-node-syncissue-01", "Hostname"),
    "policy_usage": ("Category-tango", "Category"),
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
    assert norm(t(FOOTER_KEY[rtype], lang="en")) in flat


@pytest.mark.parametrize("rtype", MIGRATED)
def test_the_expected_chapters_are_all_there_in_the_expected_order(rtype):
    """``toc == body_ids`` is self-consistency; this is the external check.

    A chapter that stops rendering disappears from both sides at once and
    leaves that assertion green, and conservation cannot see it either as long
    as the chapter's text survives anywhere else (e.g. in a guidance block that
    other chapters share). Order matters too: two chapters whose contents are
    exchanged is a documented conservation blind spot.
    """
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    ids = tuple(s["id"] for s in soup.select(
        "section.exec[id], div.chapters > section.chapter"))
    assert ids == EXPECTED_SECTION_IDS[rtype]


@pytest.mark.parametrize("rtype", MIGRATED)
def test_cover_meta_carries_the_generation_timestamp_and_period(rtype):
    """Pairs with the hero-subtitle and empty-"Generated:" exemptions.

    Those two exemptions drop old text nodes that mixed a label with a value;
    this is what proves the values themselves reached the new cover instead of
    vanishing with the node. The label is asserted by key, not by literal, so a
    translation change cannot quietly turn this green.
    """
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    meta = soup.select_one("header.cover dl.cover-meta")
    # No skip when the element is missing: "the cover has no meta list at all"
    # is a failure for every type that expects a row, and the assertion below
    # says so. Only the VEN fixture legitimately has nothing to show.
    pairs = {} if meta is None else dict(
        zip([dt.get_text(strip=True) for dt in meta.select("dt")],
            [dd.get_text(strip=True) for dd in meta.select("dd")]))
    expected = {
        "audit": {t("rpt_cover_generated", lang="en"): "2026-07-23 12:00:00",
                  t("rpt_cover_date_range", lang="en"): "2026-07-16 – 2026-07-23"},
        "policy_usage": {t("rpt_cover_generated", lang="en"): "2026-07-02 12:00:00"},
        "traffic": {t("rpt_cover_generated", lang="en"): "2026-07-02 12:00:00"},
        "security_risk": {t("rpt_cover_generated", lang="en"): "2026-05-15 09:00"},
        "network_inventory": {t("rpt_cover_generated", lang="en"): "2026-07-02 12:00:00"},
        # The VEN fixture has no generated_at at all — that is exactly why its
        # old "Generated: " node is exempted. Nothing to assert but the absence.
        "ven_status": {},
    }[rtype]
    for label, value in expected.items():
        assert pairs.get(label) == value, f"{rtype}: 封面 meta 缺 {label}={value!r}：{pairs}"
    if rtype == "ven_status":
        assert t("rpt_cover_generated", lang="en") not in pairs


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


def _build_security(results):
    from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
    return SecurityRiskHtmlExporter(results, lang="en").build()


def _security_html(severities):
    return _build_security(_findings_results(severities))


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

    The findings chapter's tone follows its own tally, so zero findings reads as
    neutral even though the action matrix printed a CRITICAL badge.
    """
    soup = BeautifulSoup(_security_html([]), "html.parser")
    # The action matrix (CRITICAL) and its badge are rendered, but there are no
    # findings, so the findings chapter and the cover must both stay quiet.
    assert soup.select_one('td .badge[data-sev="CRITICAL"]') is not None
    assert soup.select_one("section.chapter#findings")["data-tone"] == "neutral"
    assert soup.select_one("header.cover")["data-tone"] != "crit"


def test_a_critical_detail_chapter_does_not_reach_the_cover():
    """G1: chapters may colour themselves; only findings speak for the document.

    ``ransomware`` carries a per-port table with a severity column, so a single
    CRITICAL row tints that chapter — correctly. The cover must not follow it:
    this report found nothing.
    """
    results = _findings_results([])
    results["mod04"] = {
        "risk_flows_total": 2,
        # part_a_summary is rendered with severity_col="Risk Level", so these
        # rows become CRITICAL/LOW severity badges inside the chapter.
        "part_a_summary": pd.DataFrame([
            {"Risk Level": "CRITICAL", "Flow Count": 1234, "Detail": "smb exposure"},
            {"Risk Level": "LOW", "Flow Count": 2345, "Detail": "ssh admin path"},
        ]),
    }
    soup = BeautifulSoup(_build_security(results), "html.parser")
    ransomware = soup.select_one("section.chapter#ransomware")
    assert ransomware["data-tone"] == "crit", "有 CRITICAL 列的章本來就該染色"
    assert soup.select_one("section.chapter#findings")["data-tone"] == "neutral"
    assert soup.select_one("header.cover")["data-tone"] == "neutral", (
        "非 findings 章的 tone 不得傳到封面")


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
