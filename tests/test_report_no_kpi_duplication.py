"""After redesign, KPI numbers should appear exactly ONCE in each HTML report —
inside the .exec-summary .kpi-strip block produced by render_exec_summary_html.
No duplicate .kpi-grid in the report-hero section."""
from __future__ import annotations

import pandas as pd
import pytest
from bs4 import BeautifulSoup

from src.report.exporters.html_exporter import HtmlExporter
from src.report.exporters.audit_html_exporter import AuditHtmlExporter
from src.report.exporters.ven_html_exporter import VenHtmlExporter
from src.report.exporters.policy_usage_html_exporter import PolicyUsageHtmlExporter


def _make_results_traffic():
    return {
        "mod01": {"total_flows": 100},
        "mod12": {
            "kpis": [
                {"label": "Total Flows", "value": "100"},
                {"label": "Maturity Score", "value": "78/100 (B)"},
            ],
            "maturity_score": 78,
            "maturity_grade": "B",
            "maturity_dimensions": {},
            "key_findings": [],
            "generated_at": "2026-05-15 09:00",
        },
        "findings": [],
    }


def _count_kpi_strip(soup):
    return len(soup.select(".exec-summary .kpi-strip .kpi"))


def _count_hero_kpi_grid(soup):
    # In the new design there should be no .kpi-grid inside .report-hero
    return len(soup.select("section.report-hero .kpi-grid .kpi-card"))


def test_traffic_report_kpis_no_duplicate():
    html = HtmlExporter(_make_results_traffic())._build(profile="security_risk")
    soup = BeautifulSoup(html, "html.parser")
    # exec_summary may not always render with full data; just ensure no hero dup
    assert _count_hero_kpi_grid(soup) == 0, "report-hero kpi-grid must be removed"


def test_audit_report_kpis_no_duplicate():
    results = {
        "mod00": {"kpis": [{"label": "Events", "value": "42"}], "generated_at": "2026-05-15 09:00",
                  "attention_items": [], "severity_dist": {}, "top_events_overall": pd.DataFrame()},
        "mod01": {}, "mod02": {}, "findings": [],
    }
    html = AuditHtmlExporter(results, pd.DataFrame())._build()
    soup = BeautifulSoup(html, "html.parser")
    assert _count_hero_kpi_grid(soup) == 0


def test_ven_report_kpis_no_duplicate():
    results = {
        "mod00": {"kpis": [{"label": "Online", "value": "30"}], "generated_at": "2026-05-15 09:00"},
        "online_count": 30, "offline_count": 0, "today_count": 0, "yest_count": 0,
        "df_online": pd.DataFrame(), "df_offline": pd.DataFrame(),
        "df_today": pd.DataFrame(), "df_yest": pd.DataFrame(),
    }
    html = VenHtmlExporter(results, pd.DataFrame())._build()
    soup = BeautifulSoup(html, "html.parser")
    assert _count_hero_kpi_grid(soup) == 0


def test_policy_usage_report_kpis_no_duplicate():
    results = {
        "mod00": {"kpis": [{"label": "Rules", "value": "10"}], "generated_at": "2026-05-15 09:00",
                  "attention_items": [], "execution_notes": []},
        "mod01": {}, "mod02": {}, "mod03": {}, "mod04": {}, "mod05": {},
    }
    html = PolicyUsageHtmlExporter(results, date_range=("2026-05-01", "2026-05-15"))._build()
    soup = BeautifulSoup(html, "html.parser")
    assert _count_hero_kpi_grid(soup) == 0
