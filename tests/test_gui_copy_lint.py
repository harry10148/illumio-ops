"""v3.1 §5.2 / §7 — the copy lint: what the GUI is not allowed to print.

Spec: docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md
§5.2 (文案與識別碼) and §7 (驗收). The 2026-09-04 source inventory behind it
counted the engineer-facing tells still on screen after 3B: 37 links whose
text was a route, 18 config keys printed as labels, 12 raw-JSON panes, 19
uppercase panel titles. Those numbers were an estimate over several patterns
at once; the per-rule counts this file measures are in each rule's comment,
and they are the ones being ratcheted down.

## Two kinds of rule in here, and the difference matters

**Live rules** fail today and are fixed by the task that owns them. **Ratchets**
already hold and exist so the pattern cannot come back. A ratchet is not
evidence of anything having been cleaned up, so each one says so rather than
being quietly counted as a passing check.

Rules whose subject belongs to a later task carry `xfail(strict=True)`: they
must fail now, and the day the work lands the strict marker turns the
unexpected pass into a failure, which is what forces the marker's removal.

## Where this file stops

A source lint sees idioms, not screens. It catches the one idiom that put
every route on screen after 3B, but it cannot promise that no OTHER expression
ever composes one. That promise is made against the rendered DOM instead, by
tests/test_v2_page_types_e2e.py::test_no_visible_text_is_a_route — which is
also what found four of the seven sites this file's first rule now names.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "src" / "static" / "js" / "v2"
CSS_DIR = ROOT / "src" / "static" / "css" / "v2"
CATALOGUES = [
    ROOT / "src" / "i18n_en.json",
    ROOT / "src" / "i18n_zh_TW.json",
    ROOT / "src" / "i18n" / "data" / "zh_explicit.json",
]


def _strip_comments(text: str) -> str:
    """Drop /* */ and // comments.

    Several modules quote the idioms below in their porting notes, and a
    module that DOCUMENTS a banned pattern is not committing it — the same
    distinction tests/test_color_token_lint.py draws for colour literals.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


def _sources() -> list[tuple[str, str]]:
    """Every module that renders operator-facing copy, as (relpath, code)."""
    paths = sorted((JS_DIR / "areas").glob("*.mjs"))
    paths += sorted((JS_DIR / "components").glob("*.mjs"))
    paths += [JS_DIR / "shell.mjs", JS_DIR / "app.mjs"]
    return [
        (str(p.relative_to(JS_DIR)), _strip_comments(p.read_text(encoding="utf-8")))
        for p in paths
    ]


def _hits(pattern: re.Pattern) -> dict[str, int]:
    out = {}
    for rel, text in _sources():
        n = len(pattern.findall(text))
        if n:
            out[rel] = n
    return out


# ── live rules ──────────────────────────────────────────────────────────────

def test_the_go_to_label_is_never_concatenated_with_anything():
    """§5.2: link text is a verb or an object name, never a route.

    Every route that reached the screen after 3B arrived the same way — the
    "Go to" label glued to a route variable: `t("gui_health_goto") + " " +
    route`, in the shared card helper, the home page, the traffic and event
    pages, the schedule board, the alert-ops panel and the health rail's
    popover. Seven sites, one idiom.

    The rule names the IDIOM rather than any one helper, because a helper is
    renameable and the idiom is the defect. The fix has no concatenation at
    all: `tf("gui_health_goto_named", {name})` with the destination resolved to
    the name the left-hand nav already gives it (components/page.mjs's
    goLabel), so the affordance survives and the address does not appear.
    """
    hits = _hits(re.compile(r'gui_health_goto"\)\s*\+'))
    assert hits == {}, (
        "the go-to label is being glued to a route (spec §5.2) — use "
        f"goLabel(route), which names the destination instead: {hits}"
    )


def test_no_hash_route_is_used_as_a_literal_piece_of_visible_text():
    """RATCHET (0 today): nothing may pass a route as an element's text.

    This has never fired; it exists so the deleted pattern cannot return as a
    literal. The runtime-composed form is the DOM gate's job — see the module
    docstring.
    """
    hits = _hits(re.compile(r"""text:\s*["']#/"""))
    assert hits == {}, hits


def test_no_catalogue_value_contains_a_hash_route():
    """RATCHET (0 today): a route inside a translated string is a route that
    cannot be localized, renamed, or checked by the router."""
    offenders = {}
    for path in CATALOGUES:
        data = json.loads(path.read_text(encoding="utf-8"))
        bad = {k: v for k, v in data.items() if isinstance(v, str) and "#/" in v}
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, offenders


# ── rules whose subject belongs to a later task ─────────────────────────────

# roField's first argument is an i18n key now, so the shape this matches — a
# bare snake_case string — is exactly a config key printed as a label. It had
# 18 hits before Task 5, all in areas/system.mjs (`cache_read_max_rows`,
# `hec_token`, `old_password`); the config key itself moved to the value's
# data-field, where a DOM reader can still find it and an operator cannot.
_ROFIELD_RE = re.compile(r"""roField\(\s*["'](?!gui_)[a-z][a-z0-9_]*["']""")


# Measured across the whole tree, not just the file the plan named: 65 rows
# print a config key as their label, in four modules. Task 5 cleared
# areas/system.mjs's 18; the other 47 are the alert-rule drawers
# (policy_rules), the ruleset and schedule drawers (policy_scheduler) and one
# report row, all of them Task 6's area. So the baseline is asserted PER FILE
# rather than at zero: system.mjs may not regress, and none of the other three
# may grow.
_ROFIELD_BASELINE = {
    "areas/policy_rules.mjs": 27,
    "areas/policy_scheduler.mjs": 19,
    "areas/reports.mjs": 1,
}


def test_no_config_keys_are_printed_on_screen():
    """§5.2: `smtp.password` and friends are not words an operator knows."""
    hits = _hits(_ROFIELD_RE)
    assert hits == _ROFIELD_BASELINE, (
        "config keys rendered as field labels (spec §5.2). system.mjs must "
        f"stay at zero and policy_rules.mjs must not grow: {hits}"
    )


# A per-file RATCHET, and the reason it is a ratchet rather than a principle
# is worth stating: this rule was written twice with a rule of thumb ("only a
# log viewer or a debug console"), and both times opening the actual panes
# broke it. What survives inspection is narrower and less quotable — a
# `.codepane` holds text the operator reads or copies VERBATIM, where
# rendering it would destroy the thing they came for:
#
#   areas/system.mjs           5  the module-log message and raw line; the
#                                 quarantined event's error text and the exact
#                                 payload that failed to send; the CSR's PEM.
#   areas/investigate.mjs      1  the RAW event, as the PCE sent it — what an
#                                 operator compares against the PCE's own
#                                 console. (Its PARSED sibling was a JSON dump
#                                 standing in for a rendering and is now named
#                                 rows; that was this rule's real catch.)
#   areas/policy_rules.mjs     2  the alert-ops output console (AL-13) and the
#                                 rule-test response, already collapsed and
#                                 labelled as the evidence for the sentence
#                                 above it.
#   areas/policy_scheduler.mjs 2  the schedule check's log output, and the
#                                 exact note text the PCE will be given.
#
# So the gate is: these counts may not GROW. A new pane has to be argued for
# here, by name, which is the property the whitelist was reaching for.
_CODEPANE_ALLOWED = {
    "areas/system.mjs": 5,
    "areas/investigate.mjs": 1,
    "areas/policy_rules.mjs": 2,
    "areas/policy_scheduler.mjs": 2,
}


def test_raw_json_panes_are_confined_to_logs_and_debug_consoles():
    hits = _hits(re.compile(r'class:\s*"codepane'))
    assert hits == _CODEPANE_ALLOWED, (
        f"unexpected raw-output panes (spec §5.2): {hits} != {_CODEPANE_ALLOWED}"
    )


_RULE_RE = re.compile(r"([^{}]+)\{([^}]*)\}", re.DOTALL)


def _uppercase_selectors() -> set[str]:
    found = set()
    for path in sorted(CSS_DIR.glob("*.css")):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
        for m in _RULE_RE.finditer(css):
            if "text-transform: uppercase" not in m.group(2):
                continue
            for sel in m.group(1).split(","):
                found.add(sel.strip())
    return found


# §5.2: "面板標題不全大寫 … 眉標（uppercase＋字距）只留右欄卡片標題與表頭".
#
# The rule is about what uppercase is FOR, not about a list of class names.
# Uppercase with letter-spacing is a label device: it marks a small caption
# sitting over a value, and the app has a dozen of those — KPI captions, filter
# column labels, the palette's group chip, table heads. They are fine and they
# are what §5.2 preserves.
#
# What §5.2 stops is a HEADING that shouts. A panel title, a popover title, an
# error card's title and an empty state's title are the page talking to you in
# sentences, and setting them in caps is what made 3B read as an instrument
# console. So the rule is exactly that: no CSS rule may uppercase a heading.
_HEADING_RE = re.compile(r"(^|\s|>)(h[1-4]|\.et)$")


def _uppercase_headings() -> set[str]:
    return {sel for sel in _uppercase_selectors() if _HEADING_RE.search(sel)}


def test_no_heading_is_set_in_uppercase():
    """§5.2: headings are sentences, not signage."""
    shouting = _uppercase_headings()
    assert shouting == set(), (
        "these headings are uppercased (spec §5.2 — uppercase is for eyebrows, "
        f"table heads and chips, never for a title): {sorted(shouting)}"
    )


def test_the_uppercase_probe_is_not_a_dead_letter():
    """Guard the guard: the sweep must really be finding uppercase rules.

    Without this, a change to the CSS parser or to how `text-transform` is
    written would leave a rule that finds nothing and looks stricter than it
    is. The label device §5.2 keeps is what proves the probe still works.
    """
    found = _uppercase_selectors()
    assert ".eyebrow" in found, sorted(found)
    assert len(found) >= 8, sorted(found)
