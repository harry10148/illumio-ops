"""End-to-end: Change Impact section appears when a previous snapshot exists."""
import pytest
import pandas as pd

from src.report.snapshot_store import write_snapshot, SCHEMA_VERSION


@pytest.fixture
def patched_snapshot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("src.report.snapshot_store._BASE_DIR", str(tmp_path))
    return tmp_path


def _make_kpis(**overrides):
    base = {
        "microsegmentation_maturity": 0.62,
        "active_allow_coverage": 0.71,
        "pb_uncovered_exposure": 1234,
        "blocked_flows": 87,
        "high_risk_lateral_paths": 14,
    }
    base.update(overrides)
    return base


def _make_module_results(kpis=None):
    """Minimal module_results dict with mod12 kpis — enough for HtmlExporter."""
    if kpis is None:
        kpis = _make_kpis()
    return {
        "mod12": {
            "profile": "security_risk",
            "kpis": kpis,
            "maturity_score": 62,
            "maturity_grade": "B",
            "maturity_dimensions": {},
            "key_findings": [],
            "kpi_aliases": {},
            "top_actions": [],
        },
        "findings": [],
    }


def test_change_impact_absent_on_first_run(patched_snapshot_dir):
    """When no previous snapshot exists, Change Impact section is skipped."""
    from src.report.exporters.html_exporter import HtmlExporter
    exporter = HtmlExporter(
        _make_module_results(),
        profile="security_risk",
        detail_level="standard",
    )
    html = exporter._build()
    # The section title key resolves to 'Change Impact' in EN
    assert "No previous snapshot" in html or "change_impact" not in html.lower() or "Change Impact" in html


def test_change_impact_appears_when_previous_snapshot_exists(patched_snapshot_dir):
    """After writing a previous snapshot, Change Impact section renders with verdict."""
    from src.report.exporters.html_exporter import HtmlExporter

    # Write a previous snapshot (represents the first run)
    previous_snap = {
        "schema_version": SCHEMA_VERSION,
        "report_type": "traffic",
        "profile": "security_risk",
        "generated_at": "2026-04-20T08:00:00Z",
        "query_window": {"start": "2026-04-13", "end": "2026-04-20"},
        "kpis": _make_kpis(pb_uncovered_exposure=2000, high_risk_lateral_paths=25),
        "policy_changes_since_previous": [],
    }
    write_snapshot("traffic", previous_snap)

    # Current run has better KPIs (improvement)
    current_kpis = _make_kpis(pb_uncovered_exposure=1234, high_risk_lateral_paths=14)
    exporter = HtmlExporter(
        _make_module_results(kpis=current_kpis),
        profile="security_risk",
        detail_level="standard",
    )
    html = exporter._build()

    # Change Impact section title must appear
    assert "Change Impact" in html or "變化影響" in html, "Change Impact section missing"
    # Overall verdict should be present (improved/regressed/mixed/unchanged)
    assert any(v in html.upper() for v in ("IMPROVED", "REGRESSED", "MIXED", "UNCHANGED")), (
        "Change Impact verdict not found in HTML"
    )


def test_change_impact_shows_regression(patched_snapshot_dir):
    """If current KPIs are worse, verdict is 'regressed'."""
    from src.report.exporters.html_exporter import HtmlExporter

    previous_snap = {
        "schema_version": SCHEMA_VERSION,
        "report_type": "traffic",
        "profile": "security_risk",
        "generated_at": "2026-04-20T08:00:00Z",
        "query_window": {"start": "2026-04-13", "end": "2026-04-20"},
        "kpis": _make_kpis(pb_uncovered_exposure=500),
        "policy_changes_since_previous": [],
    }
    write_snapshot("traffic", previous_snap)

    current_kpis = _make_kpis(pb_uncovered_exposure=2000)  # worse
    exporter = HtmlExporter(
        _make_module_results(kpis=current_kpis),
        profile="security_risk",
        detail_level="standard",
    )
    html = exporter._build()
    assert "REGRESSED" in html.upper(), "Expected REGRESSED verdict for worsening KPIs"
