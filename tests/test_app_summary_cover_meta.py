"""The app-summary cover shows its report window when it has one.

It used to show nothing at all, because the exporter is constructed with
results + lang only. But when the caller scoped a window, that IS real data and
belongs on the cover — a reader cannot otherwise tell what period a printed copy
covers.

What this deliberately does not add is a generation timestamp. The legacy cover
stamped datetime.now() at render time; phase 2B removed it, and re-rendering the
same report would print a different time. A date the reader cannot rely on is
worse than no date.
"""
from __future__ import annotations

from src.report.exporters.app_summary_html_exporter import AppSummaryHtmlExporter


def _results(**over):
    base = {"app": "ERP", "env": "", "empty": True}
    base.update(over)
    return base


def test_cover_does_not_stamp_a_render_time():
    """Re-rendering the same report must not produce a different "generated"."""
    html = AppSummaryHtmlExporter(_results(), lang="en")._render_html()
    assert "Generated" not in html


def test_cover_shows_the_date_range_when_the_report_scoped_one():
    html = AppSummaryHtmlExporter(
        _results(date_range=("2026-08-01", "2026-09-01")), lang="en")._render_html()
    assert "2026-08-01" in html and "2026-09-01" in html


def test_cover_omits_the_date_range_when_there_is_none():
    """Better a cover with no range than a cover with an invented one."""
    html = AppSummaryHtmlExporter(_results(), lang="en")._render_html()
    assert "Date Range" not in html
