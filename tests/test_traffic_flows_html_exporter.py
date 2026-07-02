"""Phase 1: TrafficFlowsHtmlExporter output shape."""
import os
import re
import pandas as pd

from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter


def _results():
    df = pd.DataFrame([{"Port": 443, "Protocol": "TCP", "Flow Count": 10}])
    return {
        "findings": [],
        "mod01": {"total_flows": 10, "total_connections": 100,
                  "unique_src_ips": 2, "unique_dst_ips": 3,
                  "allowed_flows": 4, "blocked_flows": 1,
                  "potentially_blocked_flows": 5, "unknown_flows": 0,
                  "total_bytes": 0, "total_mb": 1.0,
                  "policy_coverage_pct": 40.0,
                  "src_managed_pct": 100.0, "dst_managed_pct": 50.0,
                  "date_range": "2026-04-27 ~ 2026-05-04",
                  "top_ports": df, "top_protocols": df},
        "mod02": {"summary": df, "chart_spec": None},
        "mod08": {"unmanaged_flow_count": 3, "unmanaged_pct": 30.0,
                  "unique_unmanaged_src": 1, "unique_unmanaged_dst": 1,
                  "top_unmanaged_src": df},
        "mod09": {"label_distribution": {"src_app": df, "dst_app": df,
                                         "src_env": df, "dst_env": df,
                                         "src_role": df, "dst_role": df},
                  "port_distribution": df, "proto_distribution": df},
        "mod11": {"bytes_data_available": True, "total_mb": 1.0,
                  "top_by_bytes": df, "top_bandwidth": df,
                  "byte_ratio_anomalies": df, "anomaly_threshold": 1.0},
        "mod12": {"generated_at": "2026-07-02 12:00:00", "kpis": [],
                  "findings_summary": {}, "total_findings": 0,
                  "key_findings": [], "findings": [],
                  "boundary_breaches": [], "suspicious_pivot_behavior": [],
                  "blast_radius": [], "blind_spots": [], "action_matrix": []},
    }


def _export(tmp_path, lang="en"):
    exp = TrafficFlowsHtmlExporter(_results(), data_source="api", lang=lang)
    return exp.export(str(tmp_path))


def test_filename_has_no_profile_suffix(tmp_path):
    path = _export(tmp_path)
    name = os.path.basename(path)
    assert re.fullmatch(r"Illumio_Traffic_Report_\d{4}-\d{2}-\d{2}_\d{4}\.html", name), name


def test_no_security_content(tmp_path):
    html = open(_export(tmp_path), encoding="utf-8").read()
    # Strip shared <style>/<script> blocks before checking: the CSS bundle is
    # embedded verbatim in every report (SecurityRisk/NetworkInventory/Traffic
    # alike) and contains an inert "/* Maturity bars */" comment for styles the
    # traffic report never actually renders (_include_maturity() is False, so
    # the maturity block/markup itself is empty). The banned-word check is
    # about rendered SECTIONS, not shared infra text.
    body = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    for banned in ("Maturity", "Lateral", "Ransomware", "Readiness",
                   "Infrastructure Scoring", "Attack"):
        assert banned not in body, banned


def test_sections_and_pdf_button_present(tmp_path):
    html = open(_export(tmp_path), encoding="utf-8").read()
    for anchor in ('id="summary"', 'id="overview"', 'id="policy"',
                   'id="distribution"', 'id="bandwidth"', 'id="unmanaged"'):
        assert anchor in html, anchor
    assert "window.print()" in html  # PDF export button (spec N)


def test_role_loc_dimensions_not_rendered(tmp_path):
    html = open(_export(tmp_path), encoding="utf-8").read()
    assert "Src Role" not in html
