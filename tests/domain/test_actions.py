"""The things to do first (stage 3a): findings that ask for the same thing are one thing to do; the first page of a
report, its XLSX and its email all read this one grouping."""
import pytest

from illumio_ops.domain.actions import (
    ACTION_FOCUS_MAX,
    ACTION_ORDER,
    ACTION_TITLES_MAX,
    TOP_ACTIONS,
    action_number,
    group_actions,
    top_actions,
)
from illumio_ops.domain.report import Finding
from illumio_ops.domain.values import Severity

C, H, M, L = Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW


def f(severity, code=None, *, title=None, focus=""):
    name = title or f"{code or 'none'}-{severity.value}"
    return Finding(severity=severity, title=name, why="w", action="a", action_code=code,
                   action_short=f"do {code} ({name})" if code else "", action_focus=focus)


SIX = (f(H, "enforce"), f(M, "enforce", title="e2"), f(C, "narrow_rules"), f(H, title="alone"), f(M, "unmanaged"),
       f(M, "enforce", title="e3"))


def test_the_registered_codes():
    assert ACTION_ORDER == ("enforce", "cross_env_rules", "narrow_rules", "write_rules", "unmanaged", "accounts",
                            "transfers", "legacy_protocols")
    assert (TOP_ACTIONS, ACTION_TITLES_MAX, ACTION_FOCUS_MAX) == (3, 4, 2)


def test_same_code_is_one_thing_and_the_worst_comes_first():
    got = group_actions(SIX)
    assert [a.findings for a in got] == [(2,), (0, 1, 5), (3,), (4,)]
    assert [a.severity for a in got] == [C, H, H, M]
    assert [a.short for a in got] == ["do narrow_rules (narrow_rules-critical)", "do enforce (enforce-high)", "alone",
                                      "do unmanaged (unmanaged-medium)"]
    top, more = top_actions(SIX)
    assert top == got[:3] and more == 1


def test_more_findings_first_at_the_same_severity():
    got = group_actions((f(H, "unmanaged"), f(H, "transfers"), f(L, "transfers", title="t2")))
    assert [a.findings for a in got] == [(1, 2), (0,)]


def test_registered_order_breaks_a_tie():
    got = group_actions((f(H, "transfers"), f(H, "accounts"), f(H, "enforce"), f(H, "write_rules")))
    assert [a.short.split()[1] for a in got] == ["enforce", "write_rules", "accounts", "transfers"]


def test_unregistered_codes_and_findings_without_a_code_come_last_in_the_order_they_appear():
    got = group_actions((f(H, title="first"), f(H, "zzz_new"), f(H, "legacy_protocols"), f(H, title="second")))
    assert [a.findings for a in got] == [(2,), (0,), (1,), (3,)]


def test_findings_without_a_code_are_never_merged():
    got = group_actions((f(M, title="same"), f(M, title="same")))
    assert [a.findings for a in got] == [(0,), (1,)] and [a.short for a in got] == ["same", "same"]


@pytest.mark.parametrize("findings", [
    (),
    SIX,
    (f(L), f(C), f(M), f(H)),
    tuple(f(s, "enforce", title=f"t{i}") for i, s in enumerate((L, C, M, H, C, L))),
    (f(L, "accounts"), f(L, "accounts", title="x"), f(C), f(C, "zzz"), f(C, "zzz", title="y")),
    tuple(f(M, code, title=f"{code}{i}") for i in range(3) for code in ACTION_ORDER),
    (f(H, "transfers"),),
    (f(M, title="a"), f(M, "enforce"), f(M, title="b"), f(M, "enforce", title="c"), f(H, "unmanaged")),
])
def test_every_finding_belongs_to_exactly_one_thing(findings):
    got = group_actions(findings)
    assert sorted(i for a in got for i in a.findings) == list(range(len(findings)))
    top, more = top_actions(findings)
    assert top == got[:TOP_ACTIONS] and more == len(got) - len(top) and len(top) <= TOP_ACTIONS
    numbers = action_number(findings)
    assert numbers == {i: n for n, a in enumerate(top, start=1) for i in a.findings}
    for a in got:  # within one thing: the most severe first, then as the report lists them
        ranks = [(-list(Severity).index(findings[i].severity), i) for i in a.findings]
        assert ranks == sorted(ranks) and a.severity is findings[a.findings[0]].severity
        assert len(a.titles) + a.titles_more == len(a.findings)


def test_six_findings_in_one_thing_list_four_titles_and_two_focus_sentences():
    findings = (f(M, "enforce", title="m1", focus=""), f(H, "enforce", title="h1", focus="Most: app-01."),
                f(M, "enforce", title="m2", focus="Most: db-01."), f(L, "enforce", title="l1", focus="Most: x."),
                f(C, "enforce", title="c1", focus=""), f(M, "enforce", title="m3", focus="Most: y."))
    (a,) = group_actions(findings)
    assert a.findings == (4, 1, 0, 2, 5, 3)
    assert a.titles == ("c1", "h1", "m1", "m2") and a.titles_more == 2
    assert a.focus == ("Most: app-01.", "Most: db-01.")
    assert a.short == "do enforce (c1)" and a.severity is C


def test_the_fourth_thing_has_no_number_on_the_first_page():
    numbers = action_number(SIX)
    assert numbers == {2: 1, 0: 2, 1: 2, 5: 2, 3: 3} and 4 not in numbers


def test_nothing_to_do():
    assert group_actions(()) == () and top_actions(()) == ((), 0) and action_number(()) == {}
