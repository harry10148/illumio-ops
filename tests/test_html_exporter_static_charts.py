# tests/test_html_exporter_static_charts.py
"""HTML reports embed static SVG charts, not plotly.js."""
import datetime
from unittest.mock import MagicMock

import pandas as pd

from src.report.exporters.html_exporter import _render_chart_for_html
from src.report.exporters.html_exporter import SecurityRiskHtmlExporter
from src.report.rules._base import Finding

BAR_SPEC = {
    "type": "bar",
    "title": "Top Ports",
    "data": {"labels": ["443", "80"], "values": [12, 8]},
}


def test_chart_html_is_static_svg():
    html = _render_chart_for_html(BAR_SPEC, lang="en")
    assert "<svg" in html
    assert "plotly" not in html.lower()


def test_none_spec_renders_empty():
    assert _render_chart_for_html(None, lang="en") == ""


def test_invalid_spec_degrades_gracefully():
    # 不支援的 type 不得讓整份報表炸掉 — 回傳空字串並繼續
    assert _render_chart_for_html({"type": "sankey", "data": {}}, lang="en") == ""


def test_finding_card_renders_mitre_technique_chips():
    """Findings carrying technique_ids render clickable MITRE ATT&CK chips."""
    finding = Finding(
        rule_id="R01",
        rule_name="Some Rule",
        severity="HIGH",
        category="LateralMovement",
        description="desc",
        recommendation="rec",
        technique_ids=(("T1021", "Remote Services"), ("T1021.002", 'SMB "Admin$"')),
    )
    exporter = SecurityRiskHtmlExporter({"findings": [finding]}, lang="en")
    # _s is normally wired up inside _build(); provide it for this focused call
    from src.report.exporters.report_i18n import STRINGS
    exporter._s = lambda k: STRINGS[k].get("en") or STRINGS[k]["en"]
    html = exporter._findings_html()

    # chip class + technique id text present
    assert "mitre-chip" in html
    assert "T1021" in html
    # top-level technique link
    assert 'href="https://attack.mitre.org/techniques/T1021/"' in html
    # sub-technique: dot becomes a slash in the URL path
    assert 'href="https://attack.mitre.org/techniques/T1021/002/"' in html
    # technique name (with a quote) lands in an attribute and is escaped
    assert "&quot;Admin$&quot;" in html


def test_audit_flags_fold_into_policy_section(tmp_path, monkeypatch):
    """mod10 audit flags must appear inside the policy section, not as a standalone 'allowed' section."""
    from src.report.report_generator import ReportGenerator, ReportResult

    monkeypatch.setattr("src.scheduler.jobs.run_posture_summary", lambda cm: None)

    cm = MagicMock()
    cm.config = {"api": {"url": "https://pce.test", "org_id": "1", "key": "k",
                         "secret": "s", "verify_ssl": False}}
    gen = ReportGenerator(cm, api_client=MagicMock())

    audit_flags_df = pd.DataFrame([
        {"Source": "10.1.1.1", "Destination": "10.2.2.2", "Port": 445, "Reason": "SMB from unmanaged"}
    ])

    df = pd.DataFrame([
        {"src_app": "Web", "dst_app": "DB", "port": 3306, "proto": "TCP", "num_connections": 10},
    ])

    result = ReportResult(
        generated_at=datetime.datetime(2026, 1, 1, 0, 0, 0),
        record_count=len(df),
        date_range=("2024-01-01", "2024-01-31"),
        module_results={
            "mod02": {
                "summary": None,
                "chart_spec": None,
                "port_coverage": None,
                "allowed": {"count": 10, "pct_of_total": 100, "inbound_count": 5,
                            "outbound_count": 5, "top_app_flows": None,
                            "top_inbound_ports": None, "top_outbound_ports": None},
            },
            "mod10": {
                "audit_flags": audit_flags_df,
                "audit_flag_count": 1,
                "top_app_flows": None,
                "chart_spec": None,
            },
            "mod12": {"kpis": []},
        },
        dataframe=df,
    )

    paths = gen.export(result, fmt="html", output_dir=str(tmp_path), lang="en")
    html_path = next(p for p in paths if p.endswith(".html"))
    with open(html_path, encoding="utf-8") as fh:
        html = fh.read()

    # 1. standalone 'allowed' section must be gone
    assert 'id="allowed"' not in html

    # 2. audit flags heading must still render (resolved text, not the raw key)
    assert "rpt_tr_audit_flags" not in html          # i18n key must not leak
    assert "Audit Flags" in html                     # resolved English label must appear

    # 3. the audit flags heading must appear inside the policy section
    policy_start = html.find('id="policy"')
    audit_pos = html.find("Audit Flags")
    # find the next <section after policy_start
    next_section = html.find("<section", policy_start + 1)
    assert policy_start != -1, "policy section not found"
    assert audit_pos != -1, "Audit Flags heading not found"
    assert policy_start < audit_pos < next_section, (
        f"Audit Flags ({audit_pos}) not inside policy section "
        f"[{policy_start}, {next_section})"
    )
