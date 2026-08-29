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


def test_traffic_report_has_cover_page_block():
    html = HtmlExporter(_make_results())._build(profile="security_risk")
    soup = BeautifulSoup(html, "html.parser")
    cover = soup.select_one(_COVER)
    assert cover is not None, "Traffic report must include a cover-page block"
    # The legacy cover must be gone entirely, not merely unreferenced: its
    # .print-only half becomes display:block in print and would add a second
    # cover page to every PDF.
    assert "report-cover" not in html


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
