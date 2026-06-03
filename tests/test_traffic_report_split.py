"""Traffic report split: two independent exporter types from a shared base."""
from src.report.exporters.html_exporter import (
    _TrafficReportBase, SecurityRiskHtmlExporter, NetworkInventoryHtmlExporter,
)


def _results():
    # Minimal module results so _build() runs without a live PCE.
    return {
        "mod00": {}, "mod01": {"total_flows": 10}, "mod02": {}, "mod03": {},
        "mod04": {}, "mod06": {}, "mod07": {}, "mod08": {}, "mod09": {},
        "mod10": {}, "mod11": {}, "mod13": {}, "mod14": {}, "mod15": {},
        "mod12": {"kpis": [], "key_findings": [], "maturity_score": 60,
                  "maturity_grade": "B", "maturity_dimensions": {}},
        "findings": [],
    }


def test_base_is_abstract():
    import pytest
    b = _TrafficReportBase(_results())
    with pytest.raises(NotImplementedError):
        b._ordered_section_keys()


def test_security_renders_maturity_and_readiness():
    html = SecurityRiskHtmlExporter(_results()).build()
    assert 'id="summary"' in html       # maturity hero section present
    assert 'id="readiness"' in html
    assert 'id="ransomware"' in html
    assert 'id="findings"' in html


def test_inventory_omits_maturity_and_readiness():
    html = NetworkInventoryHtmlExporter(_results()).build()
    assert 'id="readiness"' not in html     # deduped: security-only
    # maturity hero deduped: the rendered block emits <div class="score-hero"><span class="score-num"...
    # (bare ".score-hero" also lives in the embedded CSS, so match the live markup fragment).
    assert '<div class="score-hero">' not in html
    assert 'id="unmanaged"' in html
    assert 'id="distribution"' in html
    # shared sections kept in both:
    assert 'id="overview"' in html and 'id="policy"' in html


def test_facades_produce_files(tmp_path, monkeypatch):
    from src.report.security_risk_report import SecurityRiskReport
    from src.report.network_inventory_report import NetworkInventoryReport
    import types
    fake_result = types.SimpleNamespace(record_count=1, module_results=_results())
    class _Gen:
        def __init__(self, *a, **k): pass
        def generate_from_api(self, **k): return fake_result
    monkeypatch.setattr("src.report.security_risk_report.ReportGenerator", _Gen)
    monkeypatch.setattr("src.report.network_inventory_report.ReportGenerator", _Gen)
    p1 = SecurityRiskReport(cm=None, api_client=None).run(output_dir=str(tmp_path))
    p2 = NetworkInventoryReport(cm=None, api_client=None).run(output_dir=str(tmp_path))
    assert "SecurityRisk" in p1 and p1.endswith(".html")
    assert "NetworkInventory" in p2 and p2.endswith(".html")


def test_cli_has_security_and_inventory_commands(cli_runner):
    from src.cli.root import cli
    out = cli_runner.invoke(cli, ['report', '--help']).output
    assert 'security' in out and 'inventory' in out
