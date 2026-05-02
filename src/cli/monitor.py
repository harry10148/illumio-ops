import click


@click.command("monitor")
@click.option("-i", "--interval", type=int, default=10, help="Minutes between cycles")
def monitor_cmd(interval: int) -> None:
    """Run headless monitoring daemon (equivalent to --monitor)."""
    from src.config import ConfigManager
    from src.cli._runtime import run_daemon_loop
    run_daemon_loop(ConfigManager(), interval=interval)
