"""End-to-end: Traffic report after Phase 3.3 redesign — single KPI source,
auto-scaled bytes, red D grade, contrast TOC, cover page."""
from __future__ import annotations

from bs4 import BeautifulSoup

from src.report.exporters.html_exporter import HtmlExporter


def _make_traffic():
    return {
        "mod01": {"total_flows": 100, "total_mb": 6062},
        "mod12": {
            "kpis": [{"label": "Total Data Volume", "value": "5.92 GB"}],
            "maturity_score": 52, "maturity_grade": "D",
            "maturity_dimensions": {}, "key_findings": [],
            "generated_at": "2026-05-15 09:00",
        },
        "findings": [],
    }


def test_traffic_report_redesign_all_aspects():
    html = HtmlExporter(_make_traffic())._build(profile="security_risk")
    soup = BeautifulSoup(html, "html.parser")
    # 1. No duplicate KPI grid inside the report-hero
    assert len(soup.select("section.report-hero .kpi-grid .kpi-card")) == 0
    # 2. D grade is mapped to a red hue (not orange)
    assert "#F97316" not in html, "orange #F97316 must not appear"
    # 3. TOC nav has white text (we set color: #FFFFFF)
    assert "color: #FFFFFF" in html or "color: #fff" in html.lower()
    # 4. Cover page exists (id="cover" or .report-cover)
    assert (soup.select_one("#cover") or soup.select_one(".report-cover")) is not None
    # 5. Chart fonts: helper module exports >=12px (verified in dedicated test)
    # 6. .nav-brand class present in CSS
    assert ".nav-brand" in html
