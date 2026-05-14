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


def test_bare_noun_does_not_emit_deprecation():
    """Calling 'report traffic' (canonical form) should NOT emit a deprecation hint.

    The short forms (traffic / audit / ven-status / policy-usage) are the
    canonical names matching the WebUI button labels; generate-* are aliases.
    """
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=[]):
        result = runner.invoke(report_group, ['traffic'])
    assert 'deprecated' not in result.output.lower()


def test_verb_form_does_not_emit_deprecation():
    """Calling 'report generate-traffic' should NOT emit a deprecation hint."""
    runner = CliRunner()
    with patch("src.cli.report.generate_traffic_report", return_value=[]):
        result = runner.invoke(report_group, ['generate-traffic'])
    assert 'deprecated' not in result.output.lower()
