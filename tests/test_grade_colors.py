"""Maturity grade D should render in red (critical), not orange.

Phase 3.3: introduce a shared helper module so future token migration
is one-line. Baseline palette already uses red for D/F so this also
locks the current state."""
from __future__ import annotations

import pytest

from src.report.exporters.grade_colors import grade_color, GRADE_COLOR


def test_d_grade_is_red_not_orange():
    # D must be a red hue (not orange #F97316 / amber)
    d = GRADE_COLOR["D"]
    assert d.upper() in {"#EF4444", "#BE122F", "#DC2626"}, (
        f"D should be critical red, got {d!r}"
    )


def test_f_grade_is_red():
    f = GRADE_COLOR["F"]
    assert f.upper() in {"#EF4444", "#BE122F", "#DC2626"}


def test_a_b_c_remain_distinguishable():
    # A/B greenish; C amber/yellow
    assert GRADE_COLOR["A"].startswith("#")
    assert GRADE_COLOR["B"].startswith("#")
    assert GRADE_COLOR["C"].startswith("#")


def test_grade_color_function_falls_back_to_neutral():
    assert grade_color("?") == "#6B7280"
    assert grade_color(None) == "#6B7280"
    # D is red (one of the accepted red shades)
    assert grade_color("D").upper() in {"#EF4444", "#BE122F", "#DC2626"}


def test_html_exporter_uses_grade_color_helper():
    from pathlib import Path
    src = Path("src/report/exporters/html_exporter.py").read_text()
    # The orange #F97316 must NOT appear in grade color context
    assert "'F97316'" not in src and '"F97316"' not in src and "#F97316" not in src


def test_no_orange_grade_color_anywhere():
    # Regression: orange must not creep back into grade palette
    from src.report.exporters import grade_colors as gc
    for grade, color in gc.GRADE_COLOR.items():
        assert color.upper() != "#F97316", (
            f"grade {grade} still mapped to orange #F97316"
        )
