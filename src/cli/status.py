import click

from src.cli._output import echo_json, is_json, is_quiet
from src.cli._exit_codes import EXIT_OK


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
    else:
        last_log = "(no log file)"

    if is_json(ctx):
        echo_json(ctx, {
            "pce_url": pce_url,
            "language": language,
            "rules": rules_count,
            "last_log_activity": last_log,
        })
        return

    if is_quiet(ctx):
        click.echo("ok" if last_log != "(no log file)" else "no log")
        return

    console = Console()
    table = Table(title="illumio-ops status", show_header=True, header_style="cyan")
    table.add_column("Item")
    table.add_column("Value")

    table.add_row("PCE URL", pce_url)
    table.add_row("Language", language)
    table.add_row("Rules", str(rules_count))
    table.add_row("Last log activity", last_log)

    console.print(table)
