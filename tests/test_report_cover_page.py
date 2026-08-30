"""Traffic report must include a cover page; cover must NOT duplicate the
exec-summary kpi-strip."""
from __future__ import annotations

from bs4 import BeautifulSoup

from src.report.exporters.html_exporter import HtmlExporter


def _make_results():
    return {
        "mod01": {"total_flows": 100, "total_mb": 6062},
        "mod12": {
            "kpis": [{"label": "Total Flows", "value": "100"}],
            "maturity_score": 52, "maturity_grade": "D",
            "maturity_dimensions": {},
            "key_findings": [],
            "generated_at": "2026-05-15 09:00",
        },
        "findings": [],
    }


# The traffic family renders the v2 shell cover (header.cover) instead of
# cover_page.build_cover_page()'s .report-cover / .report-cover-block pair.
_COVER = 'header.cover[data-shell="cover"]'


def test_traffic_report_has_exactly_one_cover_page_block():
    html = HtmlExporter(_make_results())._build(profile="security_risk")
    soup = BeautifulSoup(html, "html.parser")
    covers = soup.select(_COVER)
    assert len(covers) == 1, (
        f"Traffic report must include exactly one cover-page block, "
        f"found {len(covers)}")
    # This used to assert ``"report-cover" not in html``. With cover_page.py
    # deleted (Task 6) that string cannot appear from anywhere, so the guard
    # would be permanently true. What it protected against — a second cover
    # page appearing in the PDF because something still emits one — is counted
    # above instead, which stays able to fail.
    assert covers[0].select_one("h1") is not None, "cover has no title"


def test_cover_does_not_duplicate_kpi_strip():
    html = HtmlExporter(_make_results())._build(profile="security_risk")
    soup = BeautifulSoup(html, "html.parser")
    cover_kpi_strips = soup.select(f"{_COVER} .kpi-strip")
    assert len(cover_kpi_strips) == 0, "Cover must not embed a full kpi-strip"


def test_cover_shows_maturity_grade():
    html = HtmlExporter(_make_results())._build(profile="security_risk")
    soup = BeautifulSoup(html, "html.parser")
    grade_div = soup.select_one(f"{_COVER} .grade-chip")
    assert grade_div is not None, "cover should include maturity grade block"
    assert "D" in grade_div.get_text()
    # The score rode along with the grade on the legacy cover ("D (52/100)")
    # and still has to reach the page.
    assert "52/100" in grade_div.get_text()
