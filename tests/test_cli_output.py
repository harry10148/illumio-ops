"""Test centralized CLI output helpers."""
import json
import sys
import pytest
import click
from click.testing import CliRunner

from src.cli._global_flags import inject_global_flags
from src.cli._output import echo_info, echo_warning, echo_error, echo_json


@pytest.fixture
def runner(cli_runner):
    return cli_runner


def test_echo_json_emits_to_stdout_only(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_json(ctx, [{"id": "x", "n": 1}])

    result = runner.invoke(cli, ['--json', 'cmd'])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed == [{"id": "x", "n": 1}]


def test_echo_info_suppressed_in_quiet(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_info(ctx, "informational message")
        click.echo("always-printed marker")

    result = runner.invoke(cli, ['--quiet', 'cmd'])
    assert "informational message" not in result.output
    assert "always-printed marker" in result.output


def test_echo_warning_goes_to_stderr(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_warning(ctx, "deprecated flag")

    result = runner.invoke(cli, ['cmd'])
    assert "deprecated flag" in result.stderr
    assert "deprecated flag" not in result.stdout


def test_echo_error_goes_to_stderr(runner):
    @click.group()
    @inject_global_flags
    def cli(): pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        echo_error(ctx, "fatal: bad config")

    result = runner.invoke(cli, ['cmd'])
    assert "fatal: bad config" in result.stderr
