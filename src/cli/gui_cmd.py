import click


@click.command("gui")
@click.option("-p", "--port", type=int, default=5001)
@click.option("-h", "--host", type=str, default="0.0.0.0")
def gui_cmd(port: int, host: str) -> None:
    """Launch Web GUI (equivalent to --gui)."""
    from src.config import ConfigManager
    from src.cli._runtime import run_gui_only
    run_gui_only(ConfigManager(), port=port, host=host)
