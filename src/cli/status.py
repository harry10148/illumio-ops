import click

@click.command("status")
def status_cmd() -> None:
    """Show daemon / scheduler / config status."""
    import os
    import datetime as _dt
    from rich.console import Console
    from rich.table import Table
    from src.config import ConfigManager

    cm = ConfigManager()
    console = Console()
    table = Table(title="illumio-ops status", show_header=True, header_style="cyan")
    table.add_column("Item")
    table.add_column("Value")

    table.add_row("PCE URL", cm.config["api"]["url"])
    table.add_row("Language", cm.config["settings"].get("language", "en"))
    table.add_row("Rules", str(len(cm.config.get("rules", []))))

    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(pkg_dir)
    log_file = os.path.join(root_dir, "logs", "illumio_ops.log")
    if os.path.exists(log_file):
        mtime = _dt.datetime.fromtimestamp(os.path.getmtime(log_file))
        try:
            from src.humanize_ext import human_time_ago
            table.add_row("Last log activity", human_time_ago(mtime))
        except Exception:
            table.add_row("Last log activity", mtime.isoformat(timespec="seconds"))
    else:
        table.add_row("Last log activity", "(no log file)")

    console.print(table)
