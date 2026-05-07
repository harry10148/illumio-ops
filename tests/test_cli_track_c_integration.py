"""Track C — end-to-end integration smoke tests.

Verifies all Track C surfaces compose: did-you-mean, verb aliases, shell
subcommand, completion install. Each test goes through `cli` (the root)
to confirm wiring.
"""
import pytest
from click.testing import CliRunner
from unittest.mock import patch

from src.cli.root import cli


def test_top_level_help_lists_track_c_additions():
    """--help should show shell + completion subcommands."""
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    out = result.output.lower()
    assert 'shell' in out
    assert 'completion' in out


def test_did_you_mean_root_typo():
    runner = CliRunner()
    result = runner.invoke(cli, ['shel'])
    combined = (result.output or '') + (result.stderr or '') + str(result.exception or '')
    assert 'shell' in combined.lower()


def test_report_verb_aliases_all_help_ok():
    runner = CliRunner()
    for verb_name in ['generate-traffic', 'generate-audit',
                      'generate-ven-status', 'generate-policy-usage']:
        result = runner.invoke(cli, ['report', verb_name, '--help'])
        assert result.exit_code == 0, f"{verb_name} help failed"


def test_completion_install_bash_smoke():
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', 'install', 'bash'])
    assert result.exit_code == 0
    assert 'illumio-ops.bash' in result.output


def test_shell_invokes_main_menu():
    runner = CliRunner()
    with patch("src.main.main_menu") as mock:
        mock.return_value = None
        result = runner.invoke(cli, ['shell'])
    assert result.exit_code == 0
    mock.assert_called_once()
