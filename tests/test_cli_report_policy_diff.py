"""Tests for the `report policy-diff` CLI command."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from src.cli.report import report_group


def test_policy_diff_command_registered():
    assert "policy-diff" in report_group.commands


def test_policy_diff_invokes_report(tmp_path):
    runner = CliRunner()
    with patch("src.cli.report.generate_policy_diff_report",
               return_value=[str(tmp_path / "Illumio_Policy_Diff_Report_x.html")]) as gen:
        result = runner.invoke(report_group,
                               ["policy-diff", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    gen.assert_called_once()


def test_policy_diff_email_sends_report(tmp_path):
    html = tmp_path / "Illumio_Policy_Diff_Report_x.html"
    html.write_text("<html>diff</html>", encoding="utf-8")

    mock_cm = MagicMock()
    mock_cm.config = {"settings": {"language": "en"}, "report": {"output_dir": str(tmp_path)}}

    runner = CliRunner()
    with patch("src.config.ConfigManager", return_value=mock_cm), \
         patch("src.api_client.ApiClient"), \
         patch("src.main._make_cache_reader", return_value=MagicMock()), \
         patch("src.report.policy_diff_report.PolicyDiffReport") as MockReport, \
         patch("src.reporter.Reporter") as MockReporter:
        MockReport.return_value.run.return_value = str(html)
        result = runner.invoke(report_group,
                               ["policy-diff", "--output-dir", str(tmp_path), "--email"])

    assert result.exit_code == 0, result.output
    MockReporter.return_value.send_report_email.assert_called_once()
