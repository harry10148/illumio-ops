"""Shared maturity-grade colour palette for HTML reports.

A — excellent → green
B — good → green
C — fair → amber
D — fail → critical red    (was #F97316 orange — semantically wrong; UX_Review §7.3)
F — fail → critical red
fallback — neutral grey

This module is the single source of truth used by html_exporter and
cover_page so a future design-token migration only touches one place.
"""
from __future__ import annotations

GRADE_COLOR: dict[str, str] = {
    "A": "#16A34A",
    "B": "#16A34A",
    "C": "#F59E0B",
    "D": "#BE122F",
    "F": "#BE122F",
}

_FALLBACK = "#6B7280"


def grade_color(grade: str | None) -> str:
    """Return the colour hex for a maturity grade letter (A/B/C/D/F)."""
    if not grade:
        return _FALLBACK
    return GRADE_COLOR.get(str(grade).upper(), _FALLBACK)
