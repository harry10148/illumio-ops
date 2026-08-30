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
import re

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

# All ten HTML report types are on the v2 shell as of Task 5; the list is
# complete. It stays a list rather than being folded into ``REPORT_TYPES``
# because the two mean different things — that one is "every type a fixture can
# render", this one is "every type the shell owns", and Task 6 still has to be
# able to tell them apart. Adding an eleventh type needs, at minimum:
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
            "audit", "ven_status", "policy_usage",
            "policy_diff", "app_summary", "rule_hit_count", "readiness"]

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

# --------------------------------------------------------------------------
# Task 5's own exemptions (policy_diff / app_summary / rule_hit_count /
# readiness). The wall-clock string below is the minute THIS batch's baselines
# were captured; Task 3's and Task 4's are different minutes and none of the
# three sets is reusable. Capture your own, write your own reasons.
#
# What is structurally different about this batch: none of these four types
# ever had a footer, so "Illumio PCE Ops" — the screen cover's brand eyebrow —
# is a leaf in its own right here instead of surviving as a substring of the
# footer text the way it did for Tasks 3 and 4. It needs an exemption of its
# own, and that is why _LEGACY_COVER_BRAND is not simply reused.
# --------------------------------------------------------------------------
_T5_WALL_CLOCK_COVER = norm("2026-08-30 15:17")
# The legacy build_cover_page() stamped datetime.now() into both the screen and
# the print cover. The call is gone (B4/C6) and the value was unreachable in any
# case: the baseline froze the minute it was captured. Where a type has a real
# generation timestamp it travels to the cover meta instead — none of these four
# carries one, which is itself asserted by
# test_cover_meta_carries_the_generation_timestamp_and_period.

_LEGACY_SCREEN_COVER_BRAND = norm("Illumio PCE Ops")
# The screen cover block's eyebrow — vendor branding chrome, not report content,
# and the direct counterpart of _LEGACY_COVER_BRAND ("Illumio Operations") on
# the print cover. Tasks 3 and 4 needed no entry for it because their types all
# print a footer that starts with the same words; these four print no footer at
# all, so here it really does have no successor. The report TYPE label, which
# the legacy cover showed in .cover-type, survives on the v2 cover eyebrow.

_LEGACY_COVER_GENERATED_LABEL = norm("Generated")
# The label of the print cover's datetime.now() stamp. The value is exempted
# above as a wall clock; the label has nothing left to introduce, because none
# of these four types has a real generation timestamp to put on the v2 cover.
# The paired positive assertion is in
# test_cover_meta_carries_the_generation_timestamp_and_period, which requires
# the label to be ABSENT for exactly these four.

_T5_ALLOWLIST = frozenset({
    _T5_WALL_CLOCK_COVER,
    _LEGACY_COVER_BRAND,
    _LEGACY_SCREEN_COVER_BRAND,
    _LEGACY_COVER_GENERATED_LABEL,
})

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
    # All four need exactly the same four entries and no more: none of them had
    # a footer, a sidebar with its own wording, or a hero that glued a label to
    # a value, so the three shapes Tasks 3 and 4 had to exempt do not arise here.
    "policy_diff": _T5_ALLOWLIST,
    "app_summary": _T5_ALLOWLIST,
    "rule_hit_count": _T5_ALLOWLIST,
    "readiness": _T5_ALLOWLIST,
}

# The i18n key each type's footer text comes from. It moves into the appendix
# colophon; the dated leaf is exempted above, so this is what keeps the
# exemption from also covering the footer text itself disappearing.
#
# Four of the ten types never printed a footer at all, so there is no dated leaf
# to exempt and nothing for this assertion to look for. Declaring them ``None``
# rather than leaving them out flips the check instead of skipping it: the
# appendix must then carry NO colophon, so a stray one — or a footer quietly
# invented during the migration — is a failure too. Leaving them out of the dict
# would raise KeyError, and "skip when absent" is the vacuous form this file
# keeps having to unlearn. policy_diff's entry is not a footer: it is the
# document-level attribution caveat that used to sit as a <p class="note"> after
# the last section and now rides in the same colophon slot.
FOOTER_KEY: dict[str, str | None] = {
    "traffic": "rpt_tr_footer",
    "security_risk": "rpt_tr_footer",
    "network_inventory": "rpt_tr_footer",
    "audit": "rpt_au_footer",
    "ven_status": "rpt_ven_footer",
    "policy_usage": "rpt_pu_footer",
    "policy_diff": "rpt_policy_diff_attribution_note",
    "app_summary": None,
    "rule_hit_count": None,
    "readiness": None,
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
    "policy_diff": ("exec-summary", "ruleset-changes", "rule-changes",
                    "ip-list-changes", "service-changes", "label-group-changes"),
    "app_summary": ("exec-summary", "inbound", "outbound", "coverage",
                    "policy-impact", "enforcement", "findings"),
    "rule_hit_count": ("exec-summary", "rhc-hit", "rhc-unused", "rhc-cleanup"),
    # readiness-summary becomes the exec chapter and therefore takes the shared
    # exec-summary id; its own heading text ("Executive Summary") is a prefix of
    # the new one, so nothing leaves the document.
    "readiness": ("exec-summary", "readiness-queue", "readiness-factors",
                  "readiness-recommendations", "readiness-trend"),
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
    # None of these four had an executive summary block at all; their KPI row
    # becomes the exec chapter and the suffix is the type label the v2 cover
    # eyebrow shows, so the two agree by construction.
    "policy_diff": "Policy Diff Report",
    "app_summary": "App Summary Report",
    "rule_hit_count": "Rule Hit Count (VEN-measured)",
    "readiness": "Enforcement Readiness",
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
    # The three hand-written tables keep their own markup (see the task report);
    # the invariant is the same either way — walk from the cell back to the <th>
    # at its own index.
    "policy_diff": ("bob.chen@lab.local", "Operator"),
    # app_summary's baseline tables go through render_df_table with col_i18n={},
    # so the heading is the raw column name.
    "app_summary": ("web-tier-inbound", "src_app"),
    "rule_hit_count": ("consumer-alfa", "Consumers (Source)"),
    # Only the advancement queue carries this value; the recommendations table
    # has its own "app-bravo (production)" under the same heading text.
    "readiness": ("app-alfa (production)", "App (Env)"),
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

    ``FOOTER_KEY[rtype] is None`` means the type never printed one; the check
    then flips to "the appendix carries no colophon at all" rather than being
    skipped, so a footer appearing out of nowhere is caught too.
    """
    if FOOTER_KEY[rtype] is None:
        soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
        # Assert the appendix itself is there first: "no colophon" is trivially
        # true in a document with no appendix, which is exactly the vacuous
        # shape C5b forbids.
        appendix = soup.select_one("section.appendix")
        assert appendix is not None, f"{rtype}: 沒有附錄，這條守門就是空轉"
        colophon = appendix.select_one(".colophon")
        assert colophon is None, (
            f"{rtype} 沒有 footer，附錄不該有 colophon："
            f"{colophon.get_text(strip=True)[:80]!r}")
        return
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
        # Task 5's four never carried a generation timestamp: the only thing the
        # legacy cover stamped was datetime.now() at render time, which is what
        # _T5_WALL_CLOCK_COVER exempts. Two of them do carry a report window, and
        # that value has to reach the new cover.
        "rule_hit_count": {t("rpt_cover_date_range", lang="en"):
                           "2026-06-01 – 2026-07-01"},
        "readiness": {t("rpt_cover_date_range", lang="en"):
                      "2026-07-01 – 2026-07-08"},
        # These two exporters are constructed with results + lang only: no
        # pce_url, no org_name, no date_range, no generated_at. There is nothing
        # to put on the cover meta, and inventing a row would be a lie.
        "policy_diff": {},
        "app_summary": {},
    }[rtype]
    for label, value in expected.items():
        assert pairs.get(label) == value, f"{rtype}: 封面 meta 缺 {label}={value!r}：{pairs}"
    # The types with no real generation timestamp must not print the label
    # either — this is the positive half of the "Generated" label exemptions.
    if rtype in ("ven_status", "policy_diff", "app_summary", "rule_hit_count",
                 "readiness"):
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


# R1: "no inline colour" needs a predicate that is neither of the two we had.
# ``"color" not in style`` catches ``color:red`` and ``color:rgb(...)`` but
# walks past ``background:#FEFCE8``; ``"#" not in style`` is exactly the other
# way round. Simply re-adding the old one is not the fix — 20 legal
# ``color:var(--token)`` declarations across the exporters would fail it, and
# one of them is this task's own ``<h2 style="color:var(--ink)">``.
#
# So the rule is anchored on the token, not on the word "color": a value that
# names a colour literally is a colour frozen out of the tone system, and a
# property that can hold NOTHING BUT a colour has to go through ``var()``.
# Shorthands (``border``, ``background``, ``box-shadow``) are deliberately not
# subject to the second half — most of their declarations are not colours at
# all (``border-radius:6px``, ``border-collapse:collapse``), and demanding
# ``var()`` there flagged five legitimate elements when this predicate was
# first written. A NAMED colour inside a shorthand (``border:1px solid red``)
# is the one form neither half sees; no exporter writes it today.
#
# Verified against every styled element of all six fixtures before adoption:
# zero hits inside the guarded selectors. That check is the point — a guard
# that goes red on correct output is the F1 defect, not a stricter guard.
_LITERAL_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", re.I)
_COLOUR_ONLY_PROP = re.compile(r"(^|-)colou?r$|^fill$|^stroke$", re.I)
_COLOURLESS = frozenset({"none", "transparent", "inherit", "initial", "unset",
                         "currentcolor", "revert"})


def inline_colour_literals(style: str) -> list[str]:
    """Declarations in ``style`` that name a colour without going through a token."""
    found = []
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        prop, _, value = declaration.partition(":")
        prop, value = prop.strip().lower(), value.strip()
        if not value:
            continue
        if _LITERAL_COLOUR.search(value):
            found.append(declaration.strip())
        elif (_COLOUR_ONLY_PROP.search(prop) and "var(" not in value
                and value.lower() not in _COLOURLESS):
            found.append(declaration.strip())
    return found


# The tones the grade-carrying elements must DECLARE, in document order. Only
# security_risk shows a grade at all, and it shows two: the maturity grade "D"
# (on the cover chip and on the score hero) and the readiness grade "?" (its own
# score hero). Written out rather than computed from grade_tone(): a test that
# re-derives its expected answer from the table the product uses cannot notice
# that table changing underneath it.
#
# readiness joins with a single element: its cover carries the readiness grade
# (the legacy cover passed ``maturity_grade=readiness["grade"]``), and this
# fixture's grade is "B" -> ok. Like security_risk's third element this is
# FIXTURE-DEPENDENT: change the fixture's grade and the literal below must
# change with it. That is the intended behaviour of writing the answer out
# instead of re-deriving it from grade_tone().
GRADE_TONES: dict[str, tuple[str, ...]] = {
    "security_risk": ("crit", "crit", "neutral"),
    "readiness": ("ok",),
}
_GRADE_SELECTOR = ".score-hero, .score-num, .grade-chip, .grade-hero"


@pytest.mark.parametrize("rtype", MIGRATED)
def test_grade_colour_comes_from_data_tone_not_inline_style(rtype):
    """A1: the grade's colour arrives through a tone, and through ITS OWN tone.

    Three ways this assertion used to hold without checking anything:

    * the loop matched nothing for five of six types and never ran (F7);
    * ``"color" not in style`` is a substring test, so ``background:#FEFCE8``
      and ``border:1px solid #D4A017`` walked straight past it;
    * it asked only whether SOME ``[data-tone]`` ancestor existed. Every chapter
      carries one, so deleting the grade elements' own tone kept it green while
      the cover chip went rgb(194,47,47) -> rgb(92,100,114) and the score number
      went red -> grey. A D-grade report lost its entire grade signal and the
      guard did not notice — which is precisely what report_shell.py's comment on
      ``.score-num { color: var(--ink) }`` warns about.

    So: the tone a grade element resolves to must be OWNED by a grade element
    (inheriting from ``.score-hero`` stays legal — that is how the wrapper is
    meant to colour its children — but inheriting from the chapter is the bug),
    and the declared tones must be the expected ones.
    """
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    elements = soup.select(_GRADE_SELECTOR)
    assert bool(elements) == (rtype in GRADE_TONES), (
        f"{rtype}: 預期 {'有' if rtype in GRADE_TONES else '沒有'} grade 元素，"
        f"實際找到 {len(elements)} 個——迴圈本體會空轉")
    declared: list[str] = []
    for element in elements:
        style = element.get("style", "")
        assert not inline_colour_literals(style), (
            f"{rtype}: {element.name} 仍帶 inline 色碼 "
            f"{inline_colour_literals(style)}——顏色沒有走 tone")
        owner = element if element.get("data-tone") else element.find_parent(
            attrs={"data-tone": True})
        assert owner is not None, f"{rtype}: {element} 沒有任何 data-tone 祖先"
        assert owner in soup.select(_GRADE_SELECTOR), (
            f"{rtype}: {element.get('class')} 的 tone 來自 <{owner.name} "
            f"class={owner.get('class')}>，那不是 grade 元素——等級訊號其實是"
            f"章節的顏色，grade 自己的訊號已經消失")
        if element.get("data-tone"):
            declared.append(element["data-tone"])
    assert tuple(declared) == GRADE_TONES.get(rtype, ()), (
        f"{rtype}: grade 元素宣告的 tone 是 {tuple(declared)}，"
        f"應為 {GRADE_TONES.get(rtype, ())}")


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
    # Every box, not just the two the docstring is about: "data-sev is present"
    # was existence-only, so the other three could have carried any tone at all.
    # Written out rather than read from SEVERITY_TONE — see GRADE_TONES.
    assert by_sev == {"CRITICAL": "crit", "HIGH": "crit", "MEDIUM": "warn",
                      "LOW": "info", "INFO": "neutral"}, (
        f"嚴重度分布方塊的 tone 對映不對：{by_sev}")


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
    # The same collision in the OTHER slot: policy usage's rpt_kicker_policy and
    # rpt_cover_type_policy are both "Policy Usage Report", so the eyebrow and
    # the kicker stack one line on top of an identical one. The badge assertion
    # above cannot see it — policy usage has no badges at all.
    kicker = cover.select_one(".cover-kicker")
    if kicker is not None:
        assert kicker.get_text(strip=True) != eyebrow, (
            f"{rtype}: eyebrow 與 kicker 是同一句話，封面印了兩次")


@pytest.mark.parametrize("rtype", MIGRATED)
def test_every_table_sits_inside_a_report_table_panel(rtype):
    """Every print-survival rule in SHELL_CSS hangs off the panel, not the table.

    ``render_df_table`` builds the panel itself, but policy_diff, rule_hit_count
    and readiness hand-write their tables (row colouring by change type, a
    truncated cell whose full value lives in ``title``, a timestamp that must
    stay one token — none of which ``render_cell`` can express, since it only
    supplies a cell's inner html). They call ``wrap_table_panel`` instead. A
    table outside a panel is not clipped — the global release rules in the print
    block still apply — but it silently loses the reduced print font, the
    tighter padding, the long-text column's share and the readable floor for the
    meta columns, which is how a wide table turns into unreadable vertical
    lettering. Nothing else in this file can see that: every character is still
    on the page.
    """
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    tables = soup.select("table.report-table")
    assert tables, f"{rtype}: 沒有表格，這條守門就是空轉"
    orphans = [str(tb)[:90] for tb in tables
               if tb.find_parent(class_="report-table-panel") is None]
    assert orphans == [], (
        f"{rtype}: {len(orphans)} 個表格不在 .report-table-panel 裡，"
        f"寬表列印處理整組失效：{orphans}")


# The widest table each type renders, and whether the shared predicate in
# table_renderer calls it wide. Written out rather than recomputed from the
# rendered column count: a test that asks the product for the answer cannot
# notice the product changing its mind. rule_hit_count is the one that matters
# most — eleven columns from _COLS, more from a real PCE.
WIDEST_TABLE_IS_WIDE: dict[str, bool] = {
    "traffic": False, "security_risk": False, "network_inventory": False,
    "audit": False, "ven_status": False, "policy_usage": False,
    # 9 columns: over table_renderer's threshold of 8, so it takes the reduced
    # print font and the column floors but stays in A4 portrait (landscape
    # starts at 10). The task plan guessed "too few columns for the wide hint";
    # the shared predicate disagrees and the PDF evidence backed the predicate.
    "policy_diff": True,
    "app_summary": False,
    "rule_hit_count": True,
    "readiness": True,
}


@pytest.mark.parametrize("rtype", MIGRATED)
def test_the_widest_table_gets_the_wide_verdict_it_should(rtype):
    """Pairs with the panel check: being in a panel is not the same as --wide."""
    soup = BeautifulSoup(BUILDERS[rtype](), "html.parser")
    panels = soup.select(".report-table-panel")
    assert panels, f"{rtype}: 沒有表格面板，這條守門就是空轉"
    got = any("report-table-panel--wide" in (p.get("class") or []) for p in panels)
    assert got == WIDEST_TABLE_IS_WIDE[rtype], (
        f"{rtype}: 寬表判定為 {got}，宣告為 {WIDEST_TABLE_IS_WIDE[rtype]}")


def test_policy_diff_ships_its_own_component_stylesheet():
    """The pd-* row and risk colours have no rule in SHELL_CSS, by design.

    They are this one report type's components, and report_css.py — where they
    used to live (470-483) — is deleted in Task 6, so the exporter carries them
    in extra_head. This is the loss conservation is structurally blind to:
    without the stylesheet every row loses the added/removed/modified colour and
    the risk column loses its bold weight, while every character of text
    survives, so nothing else in this file would go red.

    Note the ``.pd-risk-*`` colour declarations do NOT render in either shell —
    measured, not assumed: they are specificity (0,1,0) against
    ``.report-table tbody td``'s (0,2,1). Only the font-weight takes effect.
    They are ported unchanged anyway; correcting that would put a new colour on
    the page rather than restore one (see the comment on _COMPONENT_CSS).
    """
    html = BUILDERS["policy_diff"]()
    assert 'class="pd-modified"' in html, "fixture rendered no colour-coded row"
    for rule in (".pd-added td", ".pd-removed td", ".pd-modified td",
                 ".pd-risk-critical", ".pd-risk-medium", ".pd-risk-low",
                 ".pd-risk-info"):
        assert rule in html, f"policy diff 的元件樣式缺 {rule!r}"
    # The colours have to come from shell tone tokens: the old palette variables
    # (--green-10 / --red-10 / --gold-110) do not exist once build_css is gone,
    # and a declaration reading an undefined variable is dropped silently. Read
    # from the constant, not from the whole document — SHELL_CSS's own comments
    # name the old tokens while explaining why they were replaced.
    from src.report.exporters.policy_diff_html_exporter import _COMPONENT_CSS
    assert _COMPONENT_CSS in html, "元件樣式沒有進到文件裡"
    for token in ("var(--tone-ok-bg)", "var(--tone-crit-bg)", "var(--tone-warn-bg)",
                  "var(--tone-crit-fg)", "var(--tone-warn-fg)", "var(--tone-ok-fg)"):
        assert token in _COMPONENT_CSS, f"policy diff 的元件樣式沒有用 {token}"
    for dead in ("--green-10", "--red-10", "--gold-110", "--slate-50",
                 "var(--red)", "var(--green)"):
        assert dead not in _COMPONENT_CSS, (
            f"policy diff 仍引用 build_css 刪除後不存在的舊 token {dead!r}")
    # …and it must reach the document through the shell's extra_head, not by
    # having been pasted into SHELL_CSS (which the drift guard would reject).
    from src.report.exporters.report_shell import SHELL_CSS
    assert ".pd-risk-critical" not in SHELL_CSS


def test_app_summary_renders_a_whole_document_when_the_app_has_no_flows():
    """The empty branch is a separate code path and no fixture covers it.

    It used to short-circuit to one <section class="card"> inside the old shell.
    It must still be a complete document — cover, table of contents, chapter,
    appendix — carrying the same rpt_app_empty narrative, not a bare note.
    """
    from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter
    results = {"app": "DB", "env": "Prod", "empty": True, "baseline": {},
               "mod03": {}, "policy_impact": {}, "enforcement": {}, "findings": []}
    html = AppSummaryHtmlExporter(results, lang="en")._render_html()
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select_one("div.sheet > div.doc") is not None
    assert soup.select_one("header.cover h1").get_text(strip=True) == \
        t("rpt_app_title", lang="en")
    chapters = [s["id"] for s in soup.select("div.chapters > section.chapter")]
    assert chapters == ["findings"], chapters
    assert t("rpt_app_empty", lang="en") in soup.select_one(
        "section.chapter#findings").get_text()
    assert soup.select_one("nav.toc ol li") is not None
    assert soup.select_one("section.appendix") is not None
    # The app/env line is the only place the report says WHICH app has no flows.
    kicker = soup.select_one("header.cover .cover-kicker")
    assert kicker is not None, "封面沒有 kicker，看不出是哪個 app 沒有流量"
    assert kicker.get_text(strip=True) == "DB / Prod"


def test_policy_usage_ships_its_own_component_stylesheet():
    """The .pu-* rule-card layout has no rule in SHELL_CSS, by design.

    It is this one report type's component, and report_css.py — where it used to
    live — is deleted in Task 6, so the exporter carries it in extra_head. This
    is the loss conservation is structurally blind to: without the stylesheet the
    three-column rule cards collapse into stacked unstyled divs while every
    character of text survives, so nothing else in this file would go red.
    """
    html = BUILDERS["policy_usage"]()
    assert '<div class="pu-cards">' in html, "fixture rendered no rule cards"
    for rule in (".pu-cards {", ".pu-card {", ".pu-col {", ".pu-badge-deny {",
                 ".attention-box {", ".caveat-box {"):
        assert rule in html, f"policy usage 的元件樣式缺 {rule!r}"
    # …and it must be reaching the document through the shell's extra_head, not
    # by having been pasted into SHELL_CSS (which the drift guard would reject).
    from src.report.exporters.report_shell import SHELL_CSS
    assert ".pu-card {" not in SHELL_CSS


# ---------------------------------------------------------------------------
# Fix round 1 — F4/F5. Both are user-visible colour, so both are asserted on the
# rendered document rather than on a helper's return value.
# ---------------------------------------------------------------------------

def _audit_with_attention(risks):
    """An audit report whose attention block carries exactly ``risks``."""
    import pandas as pd
    from src.report.exporters.audit_html_exporter import AuditHtmlExporter

    events = pd.DataFrame([{"event_type": "agent.tampering",
                            "severity": "error-lima", "count": 3,
                            "last_seen": "2026-07-11T09:14:23Z"}])
    items = [{"risk": r, "event_type": f"user.login_{i}", "count": 1,
              "summary": f"summary text {i}", "recommendation": f"do thing {i}",
              "actors": [f"actor{i}@lab.local"]}
             for i, r in enumerate(risks)]
    results = {"mod00": {"generated_at": "2026-07-23 12:00:00",
                         "attention_items": items,
                         "top_events_overall": events},
               "mod01": {"recent": events}, "mod02": {}, "mod03": {}, "mod04": {}}
    return AuditHtmlExporter(results, date_range=("2026-07-16", "2026-07-23"),
                             lang="en")._build()


def test_the_attention_block_still_flags_itself():
    """F4: the heading used to be red and the migration left it in default ink.

    ``--red`` was declared on report_css.py's ``:root``, so the old
    ``style="color:var(--red)"`` really rendered (measured on 730dbd8f:
    rgb(220,38,38)). Judging it dead code was reasoning about the
    implementation instead of the shipped output. The signal has to survive a
    list of nothing but LOW items, which is exactly when the per-card badges
    cannot stand in for it.
    """
    soup = BeautifulSoup(_audit_with_attention(["LOW"]), "html.parser")
    heading = soup.find("h2", string=lambda s: s and "Attention" in s)
    assert heading is not None, "找不到「需要注意」標題"
    # The tone has to be on the block's OWN wrapper. Asking only for "some
    # [data-tone] ancestor" is not a gate: every chapter carries one, so the
    # first version of this assertion passed even with the wrapper's tone
    # deleted — it was reading the chapter's tone and calling it a signal.
    block = heading.parent
    assert block.name == "div" and block.get("data-tone") == "crit", (
        f"警示區塊自己沒有 tone，只有 LOW 項目時整段就沒有任何警示訊號："
        f"{block.name} data-tone={block.get('data-tone')!r}")
    # The colour comes from that tone, not from a hex frozen into the markup.
    assert "var(--ink)" in heading.get("style", "")
    assert "#" not in heading.get("style", "")


def test_one_severity_has_one_look_across_the_whole_report():
    """F5: concern cards and event tables must not use two palettes.

    concern_card kept writing RISK_COLOR/RISK_BG into a style attribute, which
    beats the stylesheet: one MEDIUM was rgb(212,160,23) on a card and
    rgb(138,93,0) in a table, and CRITICAL was outlined in one place and solid
    in the other. Same severity, same document, two looks.
    """
    soup = BeautifulSoup(_audit_with_attention(["CRITICAL", "MEDIUM"]),
                         "html.parser")
    # The tone each severity must resolve to. Written out, not read from
    # SEVERITY_TONE — see GRADE_TONES for why.
    expected = {"CRITICAL": "crit", "MEDIUM": "warn"}
    badges = soup.select(".risk-badge")
    assert len(badges) >= 3, f"樣本不足以比較兩處徽章：{len(badges)}"
    for badge in badges:
        literals = inline_colour_literals(badge.get("style", ""))
        assert not literals, (
            f"風險徽章仍帶 inline 色碼 {literals}，會蓋過殼的 tone：{badge}")
        sev = badge.get("data-sev")
        assert sev in expected, f"未預期的嚴重度 {sev!r}：{badge}"
        # Not "has a data-tone" — every badge having SOME tone is compatible
        # with all of them having the WRONG one (a LOW card painted crit red is
        # exactly the T3/F2 defect this file already learned once).
        assert badge.get("data-tone") == expected[sev], (
            f"{sev} 徽章的 tone 是 {badge.get('data-tone')!r}，應為 {expected[sev]!r}")
    # Both places one severity appears must agree, which the per-badge check
    # above already implies; this states it so a future expected-map edit that
    # loses a severity cannot quietly stop comparing the two sites.
    by_sev: dict[str, set] = {}
    for badge in badges:
        by_sev.setdefault(badge["data-sev"], set()).add(badge["data-tone"])
    assert set(by_sev) == set(expected), f"兩處徽章的嚴重度集合不一致：{by_sev}"
    for sev, tones in by_sev.items():
        assert len(tones) == 1, f"{sev} 在同一份報表裡有兩種 tone：{tones}"
    # And the cards carry the tone of their OWN risk: inside the crit-toned
    # attention block an untoned — or uniformly toned — card takes the block's
    # red left rule (the T3/F2 lesson this assertion's comment already cited
    # while only checking that a tone existed).
    cards = {c["class"][2]: c.get("data-tone") for c in soup.select(".concern-card")}
    assert cards == {"risk-CRITICAL": "crit", "risk-MEDIUM": "warn"}, (
        f"發現卡沒有依自己的風險等級上色：{cards}")
