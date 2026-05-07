"""Test verb-prefixed aliases for report subcommands."""
import pytest
from click.testing import CliRunner
from unittest.mock import patch

from src.cli.report import report_group


def test_generate_traffic_alias_exists():
    runner = CliRunner()
    result = runner.invoke(report_group, ['generate-traffic', '--help'])
    assert result.exit_code == 0
    assert 'Traffic' in result.output


def test_generate_audit_alias_exists():
    runner = CliRunner()
    result = runner.invoke(report_group, ['generate-audit', '--help'])
    assert result.exit_code == 0


def test_generate_ven_status_alias_exists():
    runner = CliRunner()
    result = runner.invoke(report_group, ['generate-ven-status', '--help'])
    assert result.exit_code == 0


def test_generate_policy_usage_alias_exists():
    runner = CliRunner()
    result = runner.invoke(report_group, ['generate-policy-usage', '--help'])
    assert result.exit_code == 0


def test_bare_noun_emits_deprecation_warning():
    """Calling 'report traffic' should emit a deprecation hint to stderr.

    We mock generate_traffic_report so the command body returns immediately;
    we only care that the deprecation hook fires before the body runs.
    CliRunner mixes stderr into output by default, so result.output contains both.
    """
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=[]):
        result = runner.invoke(report_group, ['traffic'])
    assert 'deprecated' in result.output.lower() or 'generate-traffic' in result.output.lower()


def test_verb_form_does_not_emit_deprecation():
    """Calling 'report generate-traffic' should NOT emit a deprecation hint."""
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=[]):
        result = runner.invoke(report_group, ['generate-traffic'])
    assert 'deprecated' not in result.output.lower()
