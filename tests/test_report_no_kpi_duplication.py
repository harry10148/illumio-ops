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
    """KPI blocks inside the chapter that replaced ``.report-hero``.

    The old selector was ``section.report-hero .kpi-grid .kpi-card``. The v2
    shell has no ``.report-hero`` — the hero became the cover plus the first
    chapter — so that selector stopped matching anything and the assertion below
    became true by construction for every report type, migrated or not.

    The intent is unchanged and stays SCOPED: the executive KPI numbers belong
    to ``.exec-summary``'s ``.kpi-strip``, and re-printing them in the summary
    chapter directly underneath is the duplication this file exists to catch.
    It is deliberately not "any KPI block anywhere outside .exec-summary" —
    ``ven_html_exporter._ransomware_posture_section()`` emits a legitimate
    ``kpi-strip`` of exposure counts in its own chapter, and counting that made
    the guard go red on a correct report as soon as the PCE returned
    ``risk_summary`` (a guard that cries wolf on real data is worse than no
    guard). ``test_ven_ransomware_kpi_panel_is_not_counted_as_duplication``
    pins that case as one that must stay green.
    """
    summary = soup.select_one("#summary")
    assert summary is not None, (
        "找不到 #summary 章——它是 .report-hero 的後繼者，不存在的話這條守門就是空轉")
    return len(summary.select(".kpi-card, .kpi-grid, .kpi-strip"))


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


def test_ven_ransomware_kpi_panel_is_not_counted_as_duplication():
    """The exposure KPI strip in ven's ransomware chapter is legitimate.

    It is that chapter's own severity tally, not a second copy of the executive
    KPIs, and it is the only live non-exec KPI emitter left in the codebase. An
    earlier version of ``_count_hero_kpi_grid`` counted every KPI block outside
    ``.exec-summary`` and therefore went red on a perfectly correct report the
    moment the PCE returned ``risk_summary`` — which the shared fixture does
    not, so nothing noticed. This case must stay GREEN.
    """
    results = {
        "generated_at": "2026-05-15 09:00",
        "online": pd.DataFrame([{"Hostname": "k8s-node-online-01",
                                 "VEN Version": "21.5.35-1042"}]),
        "ransomware_posture": {
            "kpi": {"by_exposure": {"critical": 3, "high": 5, "medium": 8,
                                    "low": 2, "fully_protected": 41},
                    "avg_protection_percent": 72, "pending": 4},
            "per_ven": [{"hostname": "k8s-node-online-01", "severity": "critical",
                         "protection_percent": 12, "open_risky_count": 7}],
            "ports": [],
        },
    }
    soup = BeautifulSoup(VenHtmlExporter(results, pd.DataFrame())._build(),
                         "html.parser")
    panel = soup.select("section.chapter#ransomware-posture .kpi-strip .kpi")
    assert len(panel) == 7, (
        f"exposure KPI panel did not render, so this test proves nothing: {len(panel)}")
    assert _count_hero_kpi_grid(soup) == 0, (
        "the ransomware chapter's own KPI panel was counted as a duplicate "
        "of the executive KPIs")
