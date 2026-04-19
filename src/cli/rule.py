"""`illumio-ops rule ...` subcommand group."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table


@click.group("rule")
def rule_group() -> None:
    """Inspect monitoring rules."""


@rule_group.command("list")
@click.option(
    "--type", "rule_type",
    type=click.Choice(["event", "traffic", "bandwidth", "volume", "system", "all"]),
    default="all",
    help="Filter by rule type",
)
@click.option("--enabled-only", is_flag=True, default=False, help="Show only enabled rules")
def list_rules(rule_type: str, enabled_only: bool) -> None:
    """List configured monitoring rules."""
    from src.config import ConfigManager

    cm = ConfigManager()
    rules = cm.config.get("rules", [])
    if rule_type != "all":
        rules = [r for r in rules if r.get("type") == rule_type]
    if enabled_only:
        rules = [r for r in rules if r.get("enabled", True)]

    console = Console()
    table = Table(title=f"Monitoring Rules ({len(rules)})", show_header=True, header_style="cyan")
    table.add_column("#", justify="right", no_wrap=True, width=4)
    table.add_column("Type", width=12)
    table.add_column("Name")
    table.add_column("Enabled", justify="center", width=8)
    table.add_column("Threshold", justify="right", width=10)

    for i, r in enumerate(rules, 1):
        table.add_row(
            str(i),
            r.get("type", ""),
            r.get("name", ""),
            "✓" if r.get("enabled", True) else "✗",
            str(r.get("threshold", "")) if "threshold" in r else "-",
        )
    console.print(table)
