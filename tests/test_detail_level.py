"""detail_level parameter must be accepted by all four generators and validated."""
import pytest
import pandas as pd


def test_traffic_generator_rejects_invalid_detail():
    from src.report.report_generator import ReportGenerator
    gen = ReportGenerator.__new__(ReportGenerator)
    with pytest.raises(ValueError, match="detail_level"):
        gen.generate_from_api(detail_level="bogus")


def test_audit_generator_rejects_invalid_detail():
    from src.report.audit_generator import AuditGenerator
    gen = AuditGenerator.__new__(AuditGenerator)
    with pytest.raises(ValueError, match="detail_level"):
        gen.generate_from_api(detail_level="bogus")


def test_policy_usage_generator_rejects_invalid_detail():
    from src.report.policy_usage_generator import PolicyUsageGenerator
    gen = PolicyUsageGenerator.__new__(PolicyUsageGenerator)
    with pytest.raises(ValueError, match="detail_level"):
        gen.generate_from_api(detail_level="bogus")


def test_ven_generator_rejects_invalid_detail():
    from src.report.ven_status_generator import VenStatusGenerator
    gen = VenStatusGenerator.__new__(VenStatusGenerator)
    with pytest.raises(ValueError, match="detail_level"):
        gen.generate(detail_level="bogus")


def test_default_detail_level_is_standard():
    """The default must be standard so legacy callers see no behavior change."""
    import inspect
    from src.report.report_generator import ReportGenerator
    sig = inspect.signature(ReportGenerator.generate_from_api)
    assert sig.parameters.get("detail_level") is not None, "detail_level param missing"
    assert sig.parameters["detail_level"].default == "standard"


@pytest.fixture
def sample_flows_fixture():
    return pd.DataFrame([
        {"src": "a", "dst": "b", "port": 443, "policy_decision": "allowed"},
        {"src": "a", "dst": "c", "port": 445, "policy_decision": "potentially_blocked"},
        {"src": "x", "dst": "y", "port": 22,  "policy_decision": "blocked"},
    ])


def test_executive_renders_fewer_sections_than_standard(sample_flows_fixture):
    """executive detail_level shows fewer sections than standard."""
    from src.report.exporters.html_exporter import HtmlExporter
    exporter = HtmlExporter(results={}, profile="security_risk", detail_level="standard")
    html_exec = exporter._build(profile="security_risk", detail_level="executive")
    html_std  = exporter._build(profile="security_risk", detail_level="standard")
    h2_exec = html_exec.count("<h2")
    h2_std  = html_std.count("<h2")
    assert h2_exec < h2_std, (
        f"executive should have fewer sections than standard; exec={h2_exec}, std={h2_std}")


def test_full_renders_at_least_as_many_sections_as_standard(sample_flows_fixture):
    """full detail_level shows at least as many sections as standard."""
    from src.report.exporters.html_exporter import HtmlExporter
    exporter = HtmlExporter(results={}, profile="security_risk", detail_level="standard")
    html_std  = exporter._build(profile="security_risk", detail_level="standard")
    html_full = exporter._build(profile="security_risk", detail_level="full")
    assert html_full.count("<h2") >= html_std.count("<h2")
