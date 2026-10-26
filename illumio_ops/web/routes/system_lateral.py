"""Settings › Lateral movement: management ports, critical assets, admin groups, detector thresholds."""
from __future__ import annotations

from flask import Blueprint
from pydantic import BaseModel

from illumio_ops.services.analysis.status import (
    AdminPortView,
    LabelChoice,
    LateralStatus,
    lateral_overview,
)
from illumio_ops.settings.schema import LateralSettings
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import api_route, operation


class LateralView(BaseModel):
    revision: int
    settings: LateralSettings
    effective_ports: list[AdminPortView]
    label_choices: list[LabelChoice]
    status: LateralStatus


class LateralUpdate(BaseModel):
    revision: int
    settings: LateralSettings


OP_GET = operation("system.lateral.get", "GET", "/api/system/lateral", None, LateralView)
OP_UPDATE = operation("system.lateral.update", "PUT", "/api/system/lateral", LateralUpdate, LateralView)

bp = Blueprint("system_lateral", __name__)


def _view() -> LateralView:
    ctx = get_ctx()
    s = ctx.settings.current()
    o = lateral_overview(ctx)
    return LateralView(revision=s.revision, settings=s.lateral, effective_ports=o.effective_ports,
                       label_choices=o.label_choices, status=o.status)


@api_route(bp, OP_GET)
def get_lateral() -> LateralView:
    return _view()


@api_route(bp, OP_UPDATE)
def update_lateral(body: LateralUpdate) -> LateralView:
    # The next detection run and hourly analysis read the new settings; nothing needs a restart.
    get_ctx().settings.update(body.revision, lambda d: d.__setitem__("lateral", body.settings.model_dump(mode="json")))
    return _view()
