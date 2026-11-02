"""The frame around every page: mode, collection state, unprocessed alerts (UI redesign spec §3)."""
from __future__ import annotations

from flask import Blueprint

from illumio_ops.services import shell
from illumio_ops.services.shell import ShellStatus
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import api_route, operation

OP_STATUS = operation("shell.status", "GET", "/api/shell/status", None, ShellStatus)

bp = Blueprint("shell", __name__)


@api_route(bp, OP_STATUS)
def shell_status() -> ShellStatus:
    return shell.status(get_ctx())
