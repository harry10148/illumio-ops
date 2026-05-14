"""Report grade coloring: A/B = green, C = orange/yellow, D/F = red.
Per UX_Review §7.3 — 'D 評分為 D 但配色橘色而非紅色 (不及格應有 critical 視覺)'."""
from __future__ import annotations

from src.report.exporters.html_exporter import _grade_to_color


def test_grade_a_green():
    assert _grade_to_color("A").upper() == "#16A34A"


def test_grade_b_green():
    assert _grade_to_color("B").upper() == "#16A34A"


def test_grade_c_orange():
    assert _grade_to_color("C").upper() == "#F59E0B"


def test_grade_d_red():
    assert _grade_to_color("D").upper() == "#BE122F"


def test_grade_f_red():
    assert _grade_to_color("F").upper() == "#BE122F"


def test_grade_unknown_neutral():
    assert _grade_to_color("?").upper() == "#6B7280"
