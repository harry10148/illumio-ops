"""Regression: key display paths must use humanize helpers, not raw format."""

from __future__ import annotations

from pathlib import Path


def test_html_exporters_use_humanize():
    for path in (
        "src/report/exporters/html_exporter.py",
        "src/report/exporters/audit_html_exporter.py",
        "src/report/exporters/ven_html_exporter.py",
        "src/report/exporters/policy_usage_html_exporter.py",
    ):
        src = Path(path).read_text(encoding="utf-8")
        assert "human_" in src, f"{path}: no humanize_ext usage detected"


def test_gui_frontend_formats_through_the_shared_helpers():
    """Task 11 note. The legacy GUI humanized in two places: Jinja filters in
    index.html (`| human_time_ago`, `| human_number`) and dashboard.js's own
    `humanTimeAgo`. The v2 GUI server-renders no data at all, so the Jinja
    half has no counterpart and is not replaced; the JS half became
    core/fmt.mjs, the single module every area imports. Assert that it
    provides the same two operations and that the areas really route through
    it rather than formatting inline."""
    fmt = Path("src/static/js/v2/core/fmt.mjs").read_text(encoding="utf-8")
    assert "export function since(" in fmt, "fmt.mjs missing the time-ago helper"
    assert "export function num(" in fmt, "fmt.mjs missing the number helper"

    areas = sorted(Path("src/static/js/v2/areas").glob("*.mjs"))
    assert areas, "no v2 areas found"
    users = [p.name for p in areas if "core/fmt.mjs" in p.read_text(encoding="utf-8")]
    assert len(users) >= 5, f"only {users} import fmt.mjs — inline formatting is back?"
