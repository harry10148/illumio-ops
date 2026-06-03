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


def test_scheduler_routes_network_inventory(monkeypatch, tmp_path):
    import src.report_scheduler as rs
    import src.main as main
    captured = {}

    class _FakeResult:
        record_count = 1
        module_results = _results()
        data_source = "api"

    class _FakeGen:
        def __init__(self, *a, **k):
            pass

        def generate_from_api(self, **k):
            captured["gen_profile"] = k.get("traffic_report_profile")
            return _FakeResult()

        def export(self, result, **k):
            captured["export_profile"] = k.get("traffic_report_profile")
            return ["reports/Illumio_Traffic_Report_NetworkInventory_x.html"]

    # The scheduler does a function-local `from src.report.report_generator
    # import ReportGenerator`, so patch the source module attribute.
    monkeypatch.setattr("src.report.report_generator.ReportGenerator", _FakeGen, raising=False)
    # _make_cache_reader is imported from src.main inside the method and would
    # dereference cm.models.pce_cache.enabled (cm is None here) — stub it out.
    monkeypatch.setattr(main, "_make_cache_reader", lambda cm: None)

    sched = rs.ReportScheduler.__new__(rs.ReportScheduler)
    sched.cm = None
    sched._config_dir = "config"

    result, paths = sched._generate_report(
        "network_inventory", api=object(), fmt="html", output_dir=str(tmp_path),
        start_date=None, end_date=None, name="t",
    )

    assert captured.get("gen_profile") == "network_inventory"
    assert captured.get("export_profile") == "network_inventory"
    assert any("NetworkInventory" in p for p in paths)


def test_reports_have_distinct_h1_titles():
    sec = SecurityRiskHtmlExporter(_results()).build()
    inv = NetworkInventoryHtmlExporter(_results()).build()
    # Each report's H1 uses its own title key (English default lang).
    # _s() renders the literal "&" (no HTML-escaping) in the live markup.
    assert "<h1>Illumio Security & Risk Report</h1>" in sec
    assert "<h1>Illumio Network & Traffic Inventory Report</h1>" in inv
    # The shared generic title must no longer be the H1 of either.
    assert "<h1>Illumio Traffic Flow Report</h1>" not in sec
    assert "<h1>Illumio Traffic Flow Report</h1>" not in inv


def test_scheduler_prune_by_count_handles_new_types(tmp_path):
    """Count-based pruning must work for security_risk/network_inventory schedules
    (regression: the new report types were initially absent from _REPORT_PREFIXES,
    so _prune_by_count returned early and never pruned them)."""
    import os
    import src.report_scheduler as rs
    sched = rs.ReportScheduler.__new__(rs.ReportScheduler)
    for rtype, prefix in (("network_inventory", "Illumio_Traffic_Report_NetworkInventory_"),
                          ("security_risk", "Illumio_Traffic_Report_SecurityRisk_")):
        d = tmp_path / rtype
        d.mkdir()
        files = []
        for i in range(4):
            f = d / f"{prefix}2026-06-0{i+1}_0000.html"
            f.write_text("x")
            os.utime(f, (1_000_000 + i, 1_000_000 + i))  # ascending mtime
            files.append(f)
        sched._prune_by_count(str(d), rtype, max_reports=2)
        remaining = sorted(p.name for p in d.iterdir())
        assert len(remaining) == 2, remaining
        # newest two kept (i=2,3)
        assert files[3].name in remaining and files[2].name in remaining
        assert files[0].name not in remaining
