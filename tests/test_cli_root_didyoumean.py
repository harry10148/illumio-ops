"""Test did-you-mean suggestion at root command level."""
import pytest
from click.testing import CliRunner

from src.cli.root import cli


def test_unknown_command_suggests_close_match(cli_runner):
    runner = cli_runner
    result = runner.invoke(cli, ['staus'])  # typo of 'status'
    assert result.exit_code != 0
    output = (result.stderr or '') + (result.stdout or '') + str(result.exception or '')
    assert 'staus' in output
    assert 'status' in output  # the suggestion
    assert 'did you mean' in output.lower() or 'Did you mean' in output


def test_unknown_command_no_close_match_no_suggestion(cli_runner):
    runner = cli_runner
    result = runner.invoke(cli, ['xyzzy123'])
    assert result.exit_code != 0
    output = (result.stderr or '') + (result.stdout or '')
    assert 'xyzzy123' in output
