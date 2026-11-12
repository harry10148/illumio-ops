"""The things to do first (UI redesign spec §9.1, stage 3a): a pure function of a report's findings, read alike by
the HTML's first page, the XLSX and the email, so the three cannot name different things.

Findings that carry the same action code are one thing to do; a finding without a code is a thing of its own.
Order: the highest severity among a thing's findings, then the thing with more findings, then the code's place in
ACTION_ORDER (a code not registered there and a finding without a code come last, in the order they first appear
in the findings). Nothing here reads a language or translates: every text is one a finding already carries.

Length rules: the first page lists TOP_ACTIONS things and is told how many more there are; a thing lists the titles
of its first ACTION_TITLES_MAX findings and counts the rest (titles_more); it carries at most ACTION_FOCUS_MAX
"where most of it is" sentences."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from illumio_ops.domain.report import Finding
from illumio_ops.domain.values import SEVERITY_ORDER, Severity

# The order codes were registered in: the last thing two equal actions are ordered by. A new code is added here.
ACTION_ORDER: tuple[str, ...] = ("enforce", "cross_env_rules", "narrow_rules", "write_rules", "unmanaged",
                                 "accounts", "transfers", "legacy_protocols")
TOP_ACTIONS = 3
ACTION_TITLES_MAX = 4
ACTION_FOCUS_MAX = 2


@dataclass(frozen=True)
class TopAction:
    severity: Severity  # the highest among its findings
    short: str  # the action_short of its most severe finding; for a finding without a code, that finding's title
    findings: tuple[int, ...]  # indexes into the findings given, the most severe first
    titles: tuple[str, ...]  # the titles of the first ACTION_TITLES_MAX of them
    titles_more: int  # findings whose title is not listed
    focus: tuple[str, ...]  # the first ACTION_FOCUS_MAX non-empty action_focus sentences


def _rank(severity: Severity) -> int:
    return SEVERITY_ORDER.index(severity)


def group_actions(findings: Sequence[Finding]) -> tuple[TopAction, ...]:
    """Every thing to do, in order. Each finding's index is in exactly one of them."""
    members: dict[tuple[str | None, int], list[int]] = {}
    for i, f in enumerate(findings):
        members.setdefault((f.action_code, 0) if f.action_code is not None else (None, i), []).append(i)
    keyed: list[tuple[tuple[int, int, int, int], TopAction]] = []
    for (code, _), indexes in members.items():
        ordered = sorted(indexes, key=lambda i: (-_rank(findings[i].severity), i))
        lead = findings[ordered[0]]
        focus = [findings[i].action_focus for i in ordered if findings[i].action_focus]
        place = ACTION_ORDER.index(code) if code in ACTION_ORDER else len(ACTION_ORDER)
        keyed.append(((-_rank(lead.severity), -len(ordered), place, indexes[0]), TopAction(
            severity=lead.severity, short=lead.action_short if code is not None else lead.title,
            findings=tuple(ordered), titles=tuple(findings[i].title for i in ordered[:ACTION_TITLES_MAX]),
            titles_more=max(0, len(ordered) - ACTION_TITLES_MAX), focus=tuple(focus[:ACTION_FOCUS_MAX]))))
    return tuple(action for _, action in sorted(keyed, key=lambda pair: pair[0]))


def top_actions(findings: Sequence[Finding]) -> tuple[tuple[TopAction, ...], int]:
    """The first TOP_ACTIONS things to do, and how many more there are."""
    every = group_actions(findings)
    return every[:TOP_ACTIONS], max(0, len(every) - TOP_ACTIONS)


def action_number(findings: Sequence[Finding]) -> dict[int, int]:
    """Finding index -> which of the first page's things to do it belongs to (from 1). A finding of a thing that is
    not among the first TOP_ACTIONS is not in the mapping."""
    top, _ = top_actions(findings)
    return {i: n for n, action in enumerate(top, start=1) for i in action.findings}
