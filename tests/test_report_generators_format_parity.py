"""Phase 10 parity: all 4 generators must accept html/csv/pdf/xlsx/all without crashing."""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field


def _make_cm():
    cm = MagicMock()
    cm.config = {
        "api": {"url": "https://pce.test", "org_id": "1", "key": "k", "secret": "s",
                "verify_ssl": False},
    }
    return cm


@pytest.mark.parametrize("fmt", ["html", "csv", "pdf", "xlsx", "all"])
def test_report_generator_export_accepts_format(tmp_path, fmt):
    from src.report.report_generator import ReportGenerator, ReportResult
    gen = ReportGenerator(_make_cm(), api_client=MagicMock())
    result = ReportResult(record_count=0, date_range=("2024-01-01", "2024-01-31"))
    with patch("src.report.exporters.html_exporter.HtmlExporter.export", return_value=str(tmp_path / "r.html")), \
         patch("src.report.exporters.html_exporter.HtmlExporter._build", return_value="<html></html>"), \
         patch("src.report.exporters.csv_exporter.CsvExporter.export", return_value=str(tmp_path / "r.zip")), \
         patch("src.report.exporters.pdf_exporter.export_pdf"), \
         patch("src.report.exporters.xlsx_exporter.export_xlsx"), \
         patch("src.report.report_generator.ReportGenerator._write_report_metadata"), \
         patch("src.report.report_generator.ReportGenerator._build_report_metadata", return_value={}):
        paths = gen.export(result, fmt=fmt, output_dir=str(tmp_path))
    assert isinstance(paths, list)


@pytest.mark.parametrize("fmt", ["html", "csv", "pdf", "xlsx", "all"])
def test_audit_generator_export_accepts_format(tmp_path, fmt):
    from src.report.audit_generator import AuditGenerator, AuditReportResult
    import pandas as pd
    gen = AuditGenerator(_make_cm(), api_client=MagicMock())
    result = AuditReportResult(record_count=0, date_range=("2024-01-01", "2024-01-31"),
                               module_results={}, dataframe=pd.DataFrame())
    with patch("src.report.exporters.audit_html_exporter.AuditHtmlExporter.export", return_value=str(tmp_path / "a.html")), \
         patch("src.report.exporters.audit_html_exporter.AuditHtmlExporter._build", return_value="<html></html>"), \
         patch("src.report.exporters.csv_exporter.CsvExporter.export", return_value=str(tmp_path / "a.zip")), \
         patch("src.report.exporters.pdf_exporter.export_pdf"), \
         patch("src.report.exporters.xlsx_exporter.export_xlsx"), \
         patch("src.report.audit_generator.AuditGenerator._write_report_metadata"), \
         patch("src.report.audit_generator.write_audit_dashboard_summary"), \
         patch("src.report.trend_store.save_snapshot"), \
         patch("src.report.trend_store.load_previous", return_value=None):
        paths = gen.export(result, fmt=fmt, output_dir=str(tmp_path))
    assert isinstance(paths, list)


@pytest.mark.parametrize("fmt", ["html", "csv", "pdf", "xlsx", "all"])
def test_ven_generator_export_accepts_format(tmp_path, fmt):
    from src.report.ven_status_generator import VenStatusGenerator, VenStatusResult
    import pandas as pd
    gen = VenStatusGenerator(_make_cm(), api_client=MagicMock())
    result = VenStatusResult(record_count=0, module_results={}, dataframe=pd.DataFrame())
    with patch("src.report.exporters.ven_html_exporter.VenHtmlExporter.export", return_value=str(tmp_path / "v.html")), \
         patch("src.report.exporters.ven_html_exporter.VenHtmlExporter._build", return_value="<html></html>"), \
         patch("src.report.exporters.csv_exporter.CsvExporter.export", return_value=str(tmp_path / "v.zip")), \
         patch("src.report.exporters.pdf_exporter.export_pdf"), \
         patch("src.report.exporters.xlsx_exporter.export_xlsx"):
        paths = gen.export(result, fmt=fmt, output_dir=str(tmp_path))
    assert isinstance(paths, list)


@pytest.mark.parametrize("fmt", ["html", "csv", "pdf", "xlsx", "all"])
def test_policy_usage_generator_export_accepts_format(tmp_path, fmt):
    from src.report.policy_usage_generator import PolicyUsageGenerator, PolicyUsageResult
    import pandas as pd
    gen = PolicyUsageGenerator(_make_cm(), api_client=MagicMock())
    result = PolicyUsageResult(record_count=0, date_range=("2024-01-01", "2024-01-31"),
                               module_results={}, dataframe=pd.DataFrame())
    with patch("src.report.exporters.policy_usage_html_exporter.PolicyUsageHtmlExporter.export", return_value=str(tmp_path / "p.html")), \
         patch("src.report.exporters.policy_usage_html_exporter.PolicyUsageHtmlExporter._build", return_value="<html></html>"), \
         patch("src.report.exporters.csv_exporter.CsvExporter.export", return_value=str(tmp_path / "p.zip")), \
         patch("src.report.exporters.pdf_exporter.export_pdf"), \
         patch("src.report.exporters.xlsx_exporter.export_xlsx"), \
         patch("src.report.policy_usage_generator.PolicyUsageGenerator._write_report_metadata"):
        paths = gen.export(result, fmt=fmt, output_dir=str(tmp_path))
    assert isinstance(paths, list)
