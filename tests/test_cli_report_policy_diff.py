"""Tests for the `report policy-diff` CLI command."""
from __future__ import annotations

from unittest.mock import patch

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
