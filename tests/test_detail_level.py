"""detail_level parameter must be accepted by all four generators and validated."""
import pytest


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
