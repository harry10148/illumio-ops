import logging

import click

from src.cli._exit_codes import EXIT_SOFTWARE, EXIT_UNAVAILABLE
from src.cli._output import echo_error
from src.i18n import t

log = logging.getLogger(__name__)


@click.command("gui")
@click.option("-p", "--port", type=int, default=5001)
@click.option("-h", "--host", type=str, default="0.0.0.0")
@click.pass_context
def gui_cmd(ctx: click.Context, port: int, host: str) -> None:
    """Launch Web GUI (equivalent to --gui)."""
    from src.config import ConfigManager
    from src.cli._runtime import run_gui_only
    try:
        run_gui_only(ConfigManager(), port=port, host=host)
    except OSError as exc:
        if "address already in use" in str(exc).lower():
            echo_error(ctx, t("cli_err_port_in_use", port=port, exc=exc))
            ctx.exit(EXIT_UNAVAILABLE)
        else:
            log.exception("gui failed with OSError")
            echo_error(ctx, t("cli_err_os_error", exc=exc))
            ctx.exit(EXIT_SOFTWARE)
    except Exception as exc:
        log.exception("gui failed")
        echo_error(ctx, t("cli_err_unexpected", exc=exc))
        ctx.exit(EXIT_SOFTWARE)
