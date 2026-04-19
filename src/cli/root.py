"""Top-level click command group for illumio-ops."""
from __future__ import annotations

import click

from src.cli.config import config_group
from src.cli.monitor import monitor_cmd
from src.cli.gui_cmd import gui_cmd
from src.cli.report import report_group
from src.cli.rule import rule_group
from src.cli.status import status_cmd
from src.cli.workload import workload_group

@click.group(invoke_without_command=True,
             context_settings={"help_option_names": ["-h", "--help"]})
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Illumio PCE Ops — monitoring, reporting, and policy management."""
    if ctx.invoked_subcommand is None:
        # No subcommand → defer to the legacy interactive main menu.
        # Imported lazily to avoid argparse side-effects.
        from src.main import main_menu
        main_menu()

@cli.command()
def version() -> None:
    """Print the illumio-ops version."""
    try:
        from src import __version__
    except ImportError:
        __version__ = "unknown"
    click.echo(f"illumio-ops {__version__}")

cli.add_command(config_group)
cli.add_command(monitor_cmd)
cli.add_command(gui_cmd)
cli.add_command(report_group)
cli.add_command(rule_group)
cli.add_command(status_cmd)
cli.add_command(workload_group)
