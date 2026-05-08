import logging

import click

from src.cli._exit_codes import EXIT_INTERRUPT, EXIT_SOFTWARE, EXIT_UNAVAILABLE
from src.cli._output import echo_error

log = logging.getLogger(__name__)


@click.command("monitor-gui")
@click.option("-i", "--interval", type=int, default=10, help="Minutes between monitor cycles")
@click.option("-p", "--port", type=int, default=5001, help="GUI port")
@click.option("--host", type=str, default="0.0.0.0", help="GUI bind host")
@click.pass_context
def monitor_gui_cmd(ctx: click.Context, interval: int, port: int, host: str) -> None:
    """Run headless monitor + Web GUI together (equivalent to --monitor-gui)."""
    from src.config import ConfigManager
    from src.cli._runtime import run_daemon_with_gui
    try:
        run_daemon_with_gui(ConfigManager(), interval=interval, port=port, host=host)
    except KeyboardInterrupt:
        ctx.exit(EXIT_INTERRUPT)
    except OSError as exc:
        if "address already in use" in str(exc).lower():
            echo_error(ctx, f"Port {port} is already in use: {exc}")
            ctx.exit(EXIT_UNAVAILABLE)
        else:
            log.exception("monitor-gui failed with OSError")
            echo_error(ctx, f"OS error: {exc}")
            ctx.exit(EXIT_SOFTWARE)
    except ConnectionError as exc:
        echo_error(ctx, f"Connection failed: {exc}")
        ctx.exit(EXIT_UNAVAILABLE)
    except Exception as exc:
        log.exception("monitor-gui failed")
        echo_error(ctx, f"Unexpected error: {exc}")
        ctx.exit(EXIT_SOFTWARE)
