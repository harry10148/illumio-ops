"""Top-level click command group for illumio-ops."""
from __future__ import annotations

import click

from src.cli._completion import completion_group
from src.cli._errors import suggest_command
from src.cli._global_flags import inject_global_flags
from src.cli.cache import cache_group
from src.cli.config import config_group
from src.cli.monitor import monitor_cmd
from src.cli.gui_cmd import gui_cmd
from src.cli.report import report_group
from src.cli.rule import rule_group
from src.cli.siem import siem_group
from src.cli.status import status_cmd
from src.cli.workload import workload_group


class _GroupWithSuggestions(click.Group):
    """Click group that adds 'Did you mean: X?' to UsageError on unknown subcommand."""

    def resolve_command(self, ctx: click.Context, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            if args:
                typed = args[0]
                candidates = list(self.commands.keys())
                suggestion = suggest_command(typed, candidates)
                if suggestion:
                    raise click.UsageError(
                        f"No such command '{typed}'.\n"
                        f"Did you mean: {suggestion}?\n"
                        f"Try: Run 'illumio-ops --help' for the full list."
                    ) from exc
            raise


@click.group(
    cls=_GroupWithSuggestions,
    invoke_without_command=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@inject_global_flags
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Illumio PCE Ops — monitoring, reporting, and policy management.

    Legacy flags remain supported via the compatibility entrypoint:
    --monitor, --monitor-gui, -i/--interval, --gui, -p/--port, --report,
    --report-type, --source, --file, --format, --email, --output-dir.
    """
    if ctx.invoked_subcommand is None:
        from src.cli._output import echo_warning
        echo_warning(
            ctx,
            "Bare 'illumio-ops' invocation is deprecated; use 'illumio-ops shell' "
            "to launch the interactive menu explicitly.",
        )
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


@cli.command()
@click.pass_context
def shell(ctx: click.Context) -> None:
    """Launch the interactive menu (replaces bare-call fallthrough)."""
    from src.main import main_menu
    main_menu()


cli.add_command(cache_group)
cli.add_command(config_group)
cli.add_command(monitor_cmd)
cli.add_command(gui_cmd)
cli.add_command(report_group)
cli.add_command(rule_group)
cli.add_command(siem_group)
cli.add_command(status_cmd)
cli.add_command(workload_group)
cli.add_command(completion_group)
