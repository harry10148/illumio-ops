import click

from src.cli._output import echo_json, is_json, is_quiet
from src.cli._exit_codes import EXIT_OK
from src.i18n import t


@click.command("status")
@click.pass_context
def status_cmd(ctx: click.Context) -> None:
    """Show daemon / scheduler / config status."""
    import os
    import datetime as _dt
    from rich.console import Console
    from rich.table import Table
    from src.config import ConfigManager

    cm = ConfigManager()

    pce_url = cm.config["api"]["url"]
    language = cm.config["settings"].get("language", "en")
    rules_count = len(cm.config.get("rules", []))

    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(pkg_dir)
    log_file = os.path.join(root_dir, "logs", "illumio_ops.log")
    if os.path.exists(log_file):
        mtime = _dt.datetime.fromtimestamp(os.path.getmtime(log_file))
        try:
            from src.humanize_ext import human_time_ago
            last_log = human_time_ago(mtime)
        except Exception:
            last_log = mtime.isoformat(timespec="seconds")
        log_exists = True
    else:
        last_log = t("cli_status_no_log_file")
        log_exists = False

    if is_json(ctx):
        echo_json(ctx, {
            "pce_url": pce_url,
            "language": language,
            "rules": rules_count,
            "last_log_activity": last_log,
        })
        return

    if is_quiet(ctx):
        click.echo(t("cli_status_ok") if log_exists else t("cli_status_no_log"))
        return

    console = Console()
    table = Table(title=t("cli_status_table_title"), show_header=True, header_style="cyan")
    table.add_column(t("cli_status_col_item", default="Item"))
    table.add_column(t("cli_status_col_value", default="Value"))

    table.add_row(t("cli_status_row_pce_url"), pce_url)
    table.add_row(t("cli_status_row_language"), language)
    table.add_row(t("cli_status_row_rules"), str(rules_count))
    table.add_row(t("cli_status_row_last_log"), last_log)

    console.print(table)
