"""Report detail level is a legacy no-op; reports render full detail."""
import inspect

import pytest


def test_traffic_generator_default_detail_level_is_full():
    from src.report.report_generator import ReportGenerator

    sig = inspect.signature(ReportGenerator.generate_from_api)
    assert sig.parameters.get("detail_level") is not None
    assert sig.parameters["detail_level"].default == "full"


@pytest.mark.parametrize(
    ("factory", "method_name", "error_pattern"),
    [
        ("src.report.report_generator.ReportGenerator", "generate_from_api", "api_client"),
        ("src.report.audit_generator.AuditGenerator", "generate_from_api", "api_client"),
        ("src.report.policy_usage_generator.PolicyUsageGenerator", "generate_from_api", "api_client"),
        ("src.report.ven_status_generator.VenStatusGenerator", "generate", "api_client"),
    ],
)
def test_report_generators_do_not_validate_legacy_detail_level(factory, method_name, error_pattern):
    module_name, class_name = factory.rsplit(".", 1)
    module = __import__(module_name, fromlist=[class_name])
    cls = getattr(module, class_name)
    gen = cls.__new__(cls)
    gen.api = None

    with pytest.raises(RuntimeError, match=error_pattern):
        getattr(gen, method_name)(detail_level="bogus")


def test_html_exporter_treats_all_detail_values_as_full():
    from src.report.exporters.html_exporter import HtmlExporter

    exporter = HtmlExporter(results={}, profile="security_risk", detail_level="executive")

    html_from_legacy_exec = exporter._build(profile="security_risk", detail_level="executive")
    html_from_full = exporter._build(profile="security_risk", detail_level="full")

    assert exporter._detail_level == "full"
    assert html_from_legacy_exec == html_from_full
