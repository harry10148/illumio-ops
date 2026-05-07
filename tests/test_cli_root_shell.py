"""Test 'illumio-ops shell' explicit interactive entry."""
import pytest
from click.testing import CliRunner
from unittest.mock import patch

from src.cli.root import cli


def test_shell_subcommand_invokes_main_menu():
    """`illumio-ops shell` should call src.main.main_menu()."""
    runner = CliRunner()
    with patch("src.main.main_menu") as mock_menu:
        mock_menu.return_value = None
        result = runner.invoke(cli, ['shell'])
    assert result.exit_code == 0
    mock_menu.assert_called_once()


def test_shell_listed_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert 'shell' in result.output.lower()


def test_bare_call_emits_deprecation_hint():
    """`illumio-ops` (no subcommand) still works but emits a hint about 'shell'."""
    runner = CliRunner()
    with patch("src.main.main_menu") as mock_menu:
        mock_menu.return_value = None
        result = runner.invoke(cli, [])
    mock_menu.assert_called_once()
    # CliRunner mixes stderr into output by default; check combined output.
    assert 'shell' in (result.output or '').lower()
