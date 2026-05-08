import logging

import click

from src.cli._exit_codes import EXIT_INTERRUPT, EXIT_SOFTWARE, EXIT_UNAVAILABLE
from src.cli._output import echo_error
from src.i18n import t

log = logging.getLogger(__name__)


@click.command("monitor")
@click.option("-i", "--interval", type=int, default=10, help="Minutes between cycles")
@click.pass_context
def monitor_cmd(ctx: click.Context, interval: int) -> None:
    """Run headless monitoring daemon (equivalent to --monitor)."""
    from src.config import ConfigManager
    from src.cli._runtime import run_daemon_loop
    try:
        run_daemon_loop(ConfigManager(), interval=interval)
    except KeyboardInterrupt:
        ctx.exit(EXIT_INTERRUPT)
    except ConnectionError as exc:
        echo_error(ctx, t("cli_err_connection_failed", exc=exc))
        ctx.exit(EXIT_UNAVAILABLE)
    except Exception as exc:
        log.exception("monitor daemon failed")
        echo_error(ctx, t("cli_err_unexpected", exc=exc))
        ctx.exit(EXIT_SOFTWARE)
