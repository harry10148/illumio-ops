"""`illumio-ops workload ...` subcommand group."""
from __future__ import annotations

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from src.cli._output import (
    echo_error,
    echo_json,
    is_json,
    is_quiet,
)
from src.cli._exit_codes import EXIT_UNAVAILABLE
from src.i18n import t


@click.group("workload")
def workload_group() -> None:
    """Inspect PCE workloads."""


@workload_group.command("list")
@click.option("--env", default=None, help="Filter by env label value (e.g. 'prod')")
@click.option("--limit", type=click.IntRange(min=1), default=50, help="Max rows to display")
@click.option(
    "--enforcement",
    type=click.Choice(["full", "selective", "visibility_only", "idle", "all"]),
    default="all",
    help="Filter by enforcement mode",
)
@click.option("--managed-only", is_flag=True, default=False,
              help="Show only VEN-managed workloads")
@click.pass_context
def list_workloads(ctx: click.Context, env: str | None, limit: int, enforcement: str, managed_only: bool) -> None:
    """Fetch and display workloads from PCE."""
    from src.config import ConfigManager
    from src.api_client import ApiClient

    cm = ConfigManager()
    api = ApiClient(cm)

    use_spinner = not is_json(ctx) and not is_quiet(ctx)
    console = Console()

    try:
        if use_spinner:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
                console=console,
            ) as prog:
                prog.add_task(t("cli_wl_fetching"), total=None)
                if managed_only:
                    workloads = api.fetch_managed_workloads(max_results=limit * 5)
                else:
                    workloads = api.search_workloads({"max_results": min(limit * 5, 1000)})
        else:
            if managed_only:
                workloads = api.fetch_managed_workloads(max_results=limit * 5)
            else:
                workloads = api.search_workloads({"max_results": min(limit * 5, 1000)})
    except ConnectionError as exc:
        echo_error(ctx, t("cli_wl_cannot_reach_pce", exc=exc))
        ctx.exit(EXIT_UNAVAILABLE)
        return

    # Filter
    if env:
        workloads = [
            w for w in workloads
            if any(
                lbl.get("key") == "env" and lbl.get("value") == env
                for lbl in w.get("labels", [])
            )
        ]
    if enforcement != "all":
        workloads = [w for w in workloads if w.get("enforcement_mode") == enforcement]

    workloads = workloads[:limit]

    if is_json(ctx):
        echo_json(ctx, [
            {
                "index": i,
                "name": w.get("name") or w.get("hostname") or "",
                "hostname": w.get("hostname") or "",
                "env": next(
                    (lbl.get("value", "") for lbl in w.get("labels", []) if lbl.get("key") == "env"),
                    "",
                ),
                "enforcement": w.get("enforcement_mode", ""),
                "os": w.get("os_id") or "",
            }
            for i, w in enumerate(workloads, 1)
        ])
        return

    if is_quiet(ctx):
        for w in workloads:
            click.echo(w.get("hostname") or "")
        return

    table = Table(title=t("cli_wl_table_title", n=len(workloads)), header_style="cyan", show_header=True)
    table.add_column(t("cli_wl_col_num"), justify="right", width=4, no_wrap=True)
    table.add_column(t("cli_wl_col_name"))
    table.add_column(t("cli_wl_col_hostname"))
    table.add_column(t("cli_wl_col_env"))
    table.add_column(t("cli_wl_col_enforcement"))
    table.add_column(t("cli_wl_col_os"), no_wrap=True)

    for i, w in enumerate(workloads, 1):
        env_val = next(
            (lbl.get("value", "") for lbl in w.get("labels", []) if lbl.get("key") == "env"),
            "",
        )
        table.add_row(
            str(i),
            (w.get("name") or w.get("hostname") or "-")[:40],
            (w.get("hostname") or "-")[:30],
            env_val,
            w.get("enforcement_mode", ""),
            (w.get("os_id") or "-")[:20],
        )

    console.print(table)
