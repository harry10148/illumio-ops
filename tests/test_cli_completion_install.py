"""Test 'illumio-ops completion install' subcommand."""
import os
import pytest
from click.testing import CliRunner

from src.cli.root import cli


def test_completion_help_lists_shells():
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', '--help'])
    assert result.exit_code == 0


def test_completion_install_help_lists_shells():
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', 'install', '--help'])
    assert result.exit_code == 0
    out = result.output.lower()
    assert 'bash' in out
    assert 'zsh' in out
    assert 'fish' in out


def test_completion_install_bash_prints_source_line():
    """`illumio-ops completion install bash` (no --apply) prints the source line."""
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', 'install', 'bash'])
    assert result.exit_code == 0
    assert 'source' in result.output.lower()
    assert 'illumio-ops.bash' in result.output


def test_completion_install_unknown_shell_errors():
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', 'install', 'tcsh'])
    assert result.exit_code != 0


def test_completion_install_zsh_prints_fpath():
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', 'install', 'zsh'])
    assert result.exit_code == 0
    assert '_illumio-ops' in result.output


def test_completion_install_fish_prints_path():
    runner = CliRunner()
    result = runner.invoke(cli, ['completion', 'install', 'fish'])
    assert result.exit_code == 0
    assert 'illumio-ops.fish' in result.output
