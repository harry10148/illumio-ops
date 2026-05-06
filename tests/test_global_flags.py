"""Test global flag context (--json, --quiet, --verbose)."""
import json
import pytest
import click
from click.testing import CliRunner

from src.cli._global_flags import inject_global_flags, get_global_flags


@pytest.fixture
def runner():
    return CliRunner()


def test_global_flags_default(runner):
    @click.group()
    @inject_global_flags
    def cli():
        pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        flags = get_global_flags(ctx)
        click.echo(json.dumps({"json": flags["json"], "quiet": flags["quiet"], "verbose": flags["verbose"]}))

    result = runner.invoke(cli, ['cmd'])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"json": False, "quiet": False, "verbose": False}


def test_global_flags_json(runner):
    @click.group()
    @inject_global_flags
    def cli():
        pass

    @cli.command()
    @click.pass_context
    def cmd(ctx):
        flags = get_global_flags(ctx)
        click.echo(str(flags["json"]))

    result = runner.invoke(cli, ['--json', 'cmd'])
    assert result.exit_code == 0
    assert result.output.strip() == "True"


def test_global_flags_quiet_verbose_mutually_exclusive(runner):
    @click.group()
    @inject_global_flags
    def cli():
        pass

    @cli.command()
    def cmd():
        click.echo("ok")

    result = runner.invoke(cli, ['--quiet', '--verbose', 'cmd'])
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output.lower()
