import click

@click.command("gui")
@click.option("-p", "--port", type=int, default=5001)
def gui_cmd(port: int) -> None:
    """Launch Web GUI (equivalent to --gui)."""
    from src.config import ConfigManager
    from src.gui import launch_gui, HAS_FLASK
    if not HAS_FLASK:
        click.echo("Flask is required; run: pip install -r requirements.txt", err=True)
        raise click.Abort()
    launch_gui(ConfigManager(), port=port)
