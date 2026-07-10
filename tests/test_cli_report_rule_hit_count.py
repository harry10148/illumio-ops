"""Tests for the `report rule-hit-count` CLI command."""
from __future__ import annotations

from unittest.mock import patch

import click
from click.testing import CliRunner

from src.cli._exit_codes import EXIT_DATAERR, EXIT_UNAVAILABLE
from src.cli.report import report_group
from src.report.rule_hit_count_enablement import EnablementStatus, RuleHitCountNotEnabled


def test_rule_hit_count_command_registered():
    assert "rule-hit-count" in report_group.commands


def test_rule_hit_count_invokes_report(tmp_path):
    runner = CliRunner()
    with patch("src.cli.report.generate_rule_hit_count_report",
               return_value=[str(tmp_path / "Illumio_Rule_Hit_Count_Report_x.html")]) as gen:
        result = runner.invoke(report_group,
                               ["rule-hit-count", "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    gen.assert_called_once_with(source="native", file_path=None, start_date=None,
                                end_date=None, fmt="html", output_dir=str(tmp_path))


def test_rule_hit_count_csv_source(tmp_path):
    csv = tmp_path / "rhc.csv"
    csv.write_text("Rule HREF,Rule Hit Count\n/r/1,3\n", encoding="utf-8")
    runner = CliRunner()
    with patch("src.cli.report.generate_rule_hit_count_report",
               return_value=[str(tmp_path / "x.html")]) as gen:
        result = runner.invoke(report_group,
                               ["rule-hit-count", "--source", "csv",
                                "--file", str(csv), "--output-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert gen.call_args.kwargs["source"] == "csv"


def test_not_enabled_non_tty_exits_unavailable(tmp_path):
    """Without a TTY the wizard must NOT run; command exits EXIT_UNAVAILABLE."""
    runner = CliRunner()
    exc = RuleHitCountNotEnabled(EnablementStatus("disabled", False, False, "off"))
    with patch("src.cli.report.generate_rule_hit_count_report", side_effect=exc):
        result = runner.invoke(report_group, ["rule-hit-count"])
    assert result.exit_code == EXIT_UNAVAILABLE


def test_rule_hit_count_click_exception_maps_to_dataerr():
    runner = CliRunner()
    with patch("src.cli.report.generate_rule_hit_count_report",
               side_effect=click.ClickException("no data")):
        result = runner.invoke(report_group, ["rule-hit-count"])
    assert result.exit_code == EXIT_DATAERR
