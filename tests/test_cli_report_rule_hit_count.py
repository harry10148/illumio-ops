"""Tests for the `report rule-hit-count` CLI command."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner

from src.api.reports import RuleHitCountPullTimeout
from src.cli._exit_codes import EXIT_DATAERR, EXIT_UNAVAILABLE
from src.cli.report import _run_rhc_enablement_wizard, report_group
from src.i18n import t
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


def test_pull_timeout_exits_unavailable_with_i18n_message():
    """Finding 2: RuleHitCountPullTimeout (TimeoutError -> OSError subclass) must NOT
    fall through to the generic OSError/Exception handlers (EXIT_SOFTWARE / traceback);
    it needs its own i18n message + EXIT_UNAVAILABLE."""
    runner = CliRunner()
    exc = RuleHitCountPullTimeout("/orgs/1/reports/abc123")
    with patch("src.cli.report.generate_rule_hit_count_report", side_effect=exc), \
         patch("src.cli.report._ctx_lang", return_value="en"):
        result = runner.invoke(report_group, ["rule-hit-count"])
    assert result.exit_code == EXIT_UNAVAILABLE, result.output
    assert "Traceback" not in result.output
    assert t("cli_rhc_pull_timeout", lang="en") in result.output


class TestWizardScopeLabelsEmpty:
    """Finding 1: choosing 'labels' scope but ending with zero hrefs must NOT
    silently fall back to scopes=None (== all VENs)."""

    def _run(self, picked_labels: dict):
        fake_confirm = MagicMock()
        fake_confirm.unsafe_ask.return_value = True
        fake_select = MagicMock()
        fake_select.unsafe_ask.return_value = "labels"

        api = MagicMock()
        api.get_all_labels.return_value = []

        with patch.object(sys.stdin, "isatty", return_value=True), \
             patch.object(sys.stdout, "isatty", return_value=True), \
             patch("questionary.confirm", return_value=fake_confirm), \
             patch("questionary.select", return_value=fake_select), \
             patch("src.cli.object_picker.pick_objects", return_value=picked_labels), \
             patch("src.report.rule_hit_count_enablement.enable_rule_hit_count") as enable_mock:
            result = _run_rhc_enablement_wizard(api, "en")
        return result, enable_mock

    def test_picker_done_immediately_does_not_enable(self, capsys):
        result, enable_mock = self._run({})
        assert result is False
        enable_mock.assert_not_called()
        captured = capsys.readouterr()
        assert t("cli_rhc_no_labels_selected", lang="en") in captured.out

    def test_href_lookup_miss_does_not_enable(self, capsys):
        # picker returned a label kv the href lookup can't resolve.
        result, enable_mock = self._run({"labels": ["env=prod"]})
        assert result is False
        enable_mock.assert_not_called()
        captured = capsys.readouterr()
        assert t("cli_rhc_no_labels_selected", lang="en") in captured.out
