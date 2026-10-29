"""System › Reports › Rule Hit Count (spec §6.5 RHC): the status, and turning it on after the person confirms."""
from __future__ import annotations

from flask import Blueprint
from pydantic import BaseModel

from illumio_ops.services.rhc import EnableResult, RhcStatus, enable_rhc, rhc_status
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class RhcEnable(BaseModel):
    # The page shows the steps and "this provisions firewall_settings" first; only its confirmation sends true.
    confirm: bool


class RhcEnabled(BaseModel):
    result: EnableResult
    status: RhcStatus  # read again after the attempt, whatever its outcome


OP_STATUS = operation("rhc.status", "GET", "/api/rhc", None, RhcStatus)
OP_ENABLE = operation("rhc.enable", "POST", "/api/rhc/enable", RhcEnable, RhcEnabled)

bp = Blueprint("rhc", __name__)


@api_route(bp, OP_STATUS)
def status() -> RhcStatus:
    return rhc_status(get_ctx())


@api_route(bp, OP_ENABLE)
def enable(body: RhcEnable) -> RhcEnabled:
    if not body.confirm:
        raise ApiFailure(400, "confirm_required", "err_confirm_required")
    ctx = get_ctx()
    result = enable_rhc(ctx)
    return RhcEnabled(result=result, status=rhc_status(ctx))
