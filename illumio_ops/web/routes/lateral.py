"""Lateral movement (spec §6.5.1, P6c): the exposure and what is happening, the lightweight pull that computes the
exposure on request, and deny rule simulation (read-only: never a write to the PCE)."""
from __future__ import annotations

from typing import Literal

from flask import Blueprint
from pydantic import BaseModel, ValidationError

from illumio_ops.domain.deny import DenyProposal
from illumio_ops.services import lateral_view
from illumio_ops.services.collect.guard import BindingMismatch
from illumio_ops.services.lateral_view import (
    DenySimulationView,
    LateralPage,
    NotComputed,
)
from illumio_ops.services.ondemand import OnDemandFailed
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class LateralCompute(BaseModel):
    days: Literal[1, 7, 30]


class LateralSimulate(BaseModel):
    proposal: DenyProposal


OP_VIEW = operation("lateral.view", "GET", "/api/lateral", None, LateralPage)
OP_COMPUTE = operation("lateral.compute", "POST", "/api/lateral/compute", LateralCompute, LateralPage)
OP_SIMULATE = operation("lateral.simulate", "POST", "/api/lateral/simulate", LateralSimulate, DenySimulationView)

bp = Blueprint("lateral", __name__)


def _switched() -> ApiFailure:
    return ApiFailure(409, "pce_switched", "wb_pce_switched")


def _pull_failed(exc: OnDemandFailed) -> ApiFailure:
    return ApiFailure(502, "pull_failed", "wb_pull_failed", params={"error": str(exc)[:300]})


def _invalid(exc: Exception) -> ApiFailure:
    return ApiFailure(400, "invalid_input", "err_invalid_input", field=type(exc).__name__)  # input never echoed


@api_route(bp, OP_VIEW)
def view() -> LateralPage:
    try:
        return lateral_view.view(get_ctx())
    except (StaleGeneration, BindingMismatch):
        raise _switched() from None


@api_route(bp, OP_COMPUTE)
def compute(body: LateralCompute) -> LateralPage:
    try:
        return lateral_view.compute(get_ctx(), body.days)
    except (StaleGeneration, BindingMismatch):
        raise _switched() from None
    except OnDemandFailed as exc:
        raise _pull_failed(exc) from None
    except ValueError as exc:
        raise _invalid(exc) from None


@api_route(bp, OP_SIMULATE)
def simulate(body: LateralSimulate) -> DenySimulationView:
    try:
        return lateral_view.simulate(get_ctx(), body.proposal)
    except (StaleGeneration, BindingMismatch):
        raise _switched() from None
    except NotComputed:
        raise ApiFailure(409, "not_computed", "lat_err_not_computed") from None
    except OnDemandFailed as exc:
        raise _pull_failed(exc) from None
    except (ValidationError, ValueError) as exc:
        raise _invalid(exc) from None
