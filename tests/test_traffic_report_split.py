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
