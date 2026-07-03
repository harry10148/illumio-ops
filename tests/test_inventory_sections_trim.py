"""Inventory 報表移除流量三章（spec C1）：overview/distribution/bandwidth。"""
from src.report.exporters.html_exporter import (
    NetworkInventoryHtmlExporter, SecurityRiskHtmlExporter,
)


def _results():
    return {
        "mod12": {"kpis": [], "key_findings": []},
        "mod01": {"total_flows": 10, "date_range": "2026-01-01 → 2026-01-02"},
        "mod09": {"label_distribution": {}},
        "mod11": {"bytes_data_available": False},
        "findings": [],
    }


def test_inventory_drops_traffic_chapters():
    html = NetworkInventoryHtmlExporter(_results(), lang="en").build()
    for anchor in ('id="overview"', 'id="distribution"', 'id="bandwidth"'):
        assert anchor not in html, f"{anchor} 應已自 inventory 移除"
    for anchor in ('id="labels"', 'id="policy"', 'id="unmanaged"'):
        assert anchor in html


def test_security_keeps_overview():
    html = SecurityRiskHtmlExporter(_results(), lang="en").build()
    assert 'id="overview"' in html
