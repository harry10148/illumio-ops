"""`illumio-ops rule ...` subcommand group."""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from src.cli._output import (
    echo_error,
    echo_json,
    is_json,
    is_quiet,
)
from src.cli._exit_codes import EXIT_USAGE
from src.i18n import t


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
@click.pass_context
def list_rules(ctx: click.Context, rule_type: str, enabled_only: bool) -> None:
    """List configured monitoring rules."""
    from src.config import ConfigManager

    cm = ConfigManager()
    rules = cm.config.get("rules", [])
    if rule_type != "all":
        rules = [r for r in rules if r.get("type") == rule_type]
    if enabled_only:
        rules = [r for r in rules if r.get("enabled", True)]

    if is_json(ctx):
        echo_json(ctx, [
            {
                "index": i,
                "type": r.get("type", ""),
                "name": r.get("name", ""),
                "enabled": r.get("enabled", True),
                "threshold": r.get("threshold") if "threshold" in r else None,
            }
            for i, r in enumerate(rules, 1)
        ])
        return

    if is_quiet(ctx):
        for r in rules:
            click.echo(r.get("name", ""))
        return

    console = Console()
    table = Table(title=t("cli_rule_table_title", n=len(rules), default="Monitoring Rules ({n})"),
                  show_header=True, header_style="cyan")
    table.add_column(t("cli_rule_col_num", default="#"), justify="right", no_wrap=True, width=4)
    table.add_column(t("cli_rule_col_type", default="Type"), width=12)
    table.add_column(t("cli_rule_col_name", default="Name"))
    table.add_column(t("cli_rule_col_enabled", default="Enabled"), justify="center", width=8)
    table.add_column(t("cli_rule_col_threshold", default="Threshold"), justify="right", width=10)

    for i, r in enumerate(rules, 1):
        table.add_row(
            str(i),
            r.get("type", ""),
            r.get("name", ""),
            "✓" if r.get("enabled", True) else "✗",
            str(r.get("threshold", "")) if "threshold" in r else "-",
        )
    console.print(table)


@rule_group.command("edit")
@click.argument("rule_id", type=int)
@click.option("--no-preview", is_flag=True, help="Skip the diff preview before save")
@click.pass_context
def edit_rule(ctx: click.Context, rule_id: int, no_preview: bool) -> None:
    """Interactively edit a rule by its 1-based index."""
    import json
    import questionary
    from src.config import ConfigManager
    from rich.syntax import Syntax

    cm = ConfigManager()
    rules = cm.config.get("rules", [])
    if rule_id < 1 or rule_id > len(rules):
        echo_error(ctx, t("cli_rule_err_index_out_of_range", rule_id=rule_id, n=len(rules)))
        ctx.exit(EXIT_USAGE)
        return

    rule = rules[rule_id - 1]
    before = json.dumps(rule, indent=2, ensure_ascii=False)

    name = questionary.text(t("cli_rule_edit_name", default="Rule name:"),
                            default=rule.get("name", "")).unsafe_ask()
    enabled = questionary.confirm(t("cli_rule_edit_enabled", default="Enabled?"),
                                  default=bool(rule.get("enabled", True))).unsafe_ask()
    threshold_str = questionary.text(
        t("cli_rule_edit_threshold", default="Threshold (blank to keep):"),
        default=str(rule.get("threshold", "")),
    ).unsafe_ask()

    rule["name"] = name
    rule["enabled"] = enabled
    if threshold_str.strip():
        try:
            rule["threshold"] = int(threshold_str)
        except ValueError:
            rule["threshold"] = threshold_str

    after = json.dumps(rule, indent=2, ensure_ascii=False)

    if not no_preview and not is_quiet(ctx):
        console = Console()
        console.print(f"[bold]{t('cli_rule_before')}[/bold]")
        console.print(Syntax(before, "json", theme="monokai", line_numbers=False))
        console.print(f"[bold]{t('cli_rule_after')}[/bold]")
        console.print(Syntax(after, "json", theme="monokai", line_numbers=False))
        if not questionary.confirm(t('cli_rule_confirm_save'), default=True).unsafe_ask():
            click.echo(t("cli_rule_aborted"))
            return

    cm.save()
    click.echo(t('cli_rule_saved', id=rule_id))
