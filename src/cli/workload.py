"""`illumio-ops workload ...` subcommand group."""
from __future__ import annotations

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table


@click.group("workload")
def workload_group() -> None:
    """Inspect PCE workloads."""


@workload_group.command("list")
@click.option("--env", default=None, help="Filter by env label value (e.g. 'prod')")
@click.option("--limit", type=int, default=50, help="Max rows to display")
@click.option(
    "--enforcement",
    type=click.Choice(["full", "selective", "visibility_only", "idle", "all"]),
    default="all",
    help="Filter by enforcement mode",
)
@click.option("--managed-only", is_flag=True, default=False,
              help="Show only VEN-managed workloads")
def list_workloads(env: str | None, limit: int, enforcement: str, managed_only: bool) -> None:
    """Fetch and display workloads from PCE."""
    from src.config import ConfigManager
    from src.api_client import ApiClient

    cm = ConfigManager()
    api = ApiClient(cm)

    console = Console()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as prog:
        prog.add_task("Fetching workloads from PCE...", total=None)
        if managed_only:
            workloads = api.fetch_managed_workloads(max_results=limit * 5)
        else:
            workloads = api.search_workloads({"max_results": min(limit * 5, 1000)})

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

    table = Table(title=f"Workloads ({len(workloads)})", header_style="cyan", show_header=True)
    table.add_column("#", justify="right", width=4, no_wrap=True)
    table.add_column("Name")
    table.add_column("Hostname")
    table.add_column("Env")
    table.add_column("Enforcement")
    table.add_column("OS", no_wrap=True)

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
