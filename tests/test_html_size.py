"""Traffic HTML report must be under 5 MB after Plotly single-bundle optimization."""
import pytest
import pandas as pd


def _make_chart_spec(chart_type: str = "bar", title: str = "Test") -> dict:
    """Return a minimal chart_spec that renders without error."""
    if chart_type == "pie":
        return {
            "type": "pie",
            "title": title,
            "data": {"labels": ["A", "B", "C"], "values": [10, 20, 30]},
        }
    return {
        "type": "bar",
        "title": title,
        "x_label": "X",
        "y_label": "Y",
        "data": {"labels": ["A", "B", "C"], "values": [10, 20, 30]},
    }


@pytest.fixture
def results_with_charts():
    """Minimal results dict that triggers chart rendering in all chart-capable modules."""
    return {
        "mod12": {"kpis": [], "key_findings": [], "generated_at": "2026-01-01"},
        "mod02": {
            "summary": pd.DataFrame([{"Decision": "allowed", "Count": 100}]),
            "chart_spec": _make_chart_spec("pie", "Policy Decisions"),
        },
        "mod07": {
            "matrices": {},
            "chart_spec": _make_chart_spec("bar", "Cross-Label Matrix"),
        },
        "mod10": {
            "chart_spec": _make_chart_spec("bar", "Allowed Traffic"),
            "audit_flag_count": 0,
        },
        "mod15": {
            "chart_spec": _make_chart_spec("bar", "Lateral Movement"),
            "total_lateral_flows": 0,
            "lateral_pct": 0,
        },
        "findings": [],
    }


def test_traffic_standard_under_5mb(results_with_charts):
    """Standard Traffic report with charts must be under 5 MB."""
    from src.report.exporters.html_exporter import HtmlExporter
    exporter = HtmlExporter(results=results_with_charts, profile="security_risk", detail_level="standard")
    html = exporter._build(profile="security_risk", detail_level="standard")
    size_mb = len(html.encode("utf-8")) / (1024 * 1024)
    assert size_mb < 5.0, f"Traffic standard report is {size_mb:.1f} MB (target <5 MB)"


def test_plotly_bundle_inlined_only_once(results_with_charts):
    """Only one large Plotly script block should appear in the output."""
    from src.report.exporters.html_exporter import HtmlExporter
    exporter = HtmlExporter(results=results_with_charts, profile="security_risk", detail_level="standard")
    html = exporter._build(profile="security_risk", detail_level="standard")
    script_blocks = html.split("<script")
    big_scripts = [s for s in script_blocks if len(s) > 100_000]
    assert len(big_scripts) <= 1, (
        f"expected at most 1 big Plotly bundle (>100KB), found {len(big_scripts)}"
    )
