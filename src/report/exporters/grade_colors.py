"""Shared maturity-grade tone mapping for HTML reports.

A — excellent → ok
B — good → ok
C — fair → warn
D — fail → crit    (was #F97316 orange — semantically wrong; UX_Review §7.3)
F — fail → crit
fallback — neutral

Until Task 6 of the Phase 2B reskin this module also carried ``GRADE_COLOR`` and
its lookup helper — a hex table read by the old ``cover_page`` module and
re-exported from ``html_exporter``. Both are gone: the v2 shell colours a grade
by putting ``data-tone`` on the element and letting SHELL_CSS resolve it, so an
inline hex had no consumer left. The requirement the hex table encoded — D and F
must read as critical, C as amber, and neither may drift back to orange — is
pinned on the tone table instead, by
``tests/test_report_shell_renderer.py::test_grade_tone_maps_d_and_f_to_critical_red``.
The last version with the hex table is b6917c37.
"""
from __future__ import annotations

# design/v2 shell tones. The shell colours the grade chip through a [data-tone]
# attribute; no exporter emits an inline grade colour any more.
GRADE_TONE: dict[str, str] = {
    "A": "ok",
    "B": "ok",
    "C": "warn",
    "D": "crit",
    "F": "crit",
}


def grade_tone(grade: str | None) -> str:
    """Return the shell tone token for a maturity grade letter (A/B/C/D/F)."""
    if not grade:
        return "neutral"
    return GRADE_TONE.get(str(grade).upper(), "neutral")
