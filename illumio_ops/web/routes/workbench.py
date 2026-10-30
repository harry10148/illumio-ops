"""Investigate › Workbench (spec §6.5.3, P6a): run a segment, one dimension's top values, an alert's evidence as the
starting conditions, and what the panel offers."""
from __future__ import annotations

from flask import Blueprint
from pydantic import BaseModel, Field, ValidationError

from illumio_ops.domain.values import SegmentDimension
from illumio_ops.services import workbench
from illumio_ops.services.ondemand import OnDemandFailed
from illumio_ops.services.workbench import (
    DimensionTop,
    WorkbenchMeta,
    WorkbenchRequest,
    WorkbenchResult,
)
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class WorkbenchRun(BaseModel):
    request: WorkbenchRequest


class WorkbenchDimension(BaseModel):
    request: WorkbenchRequest
    dimension: SegmentDimension
    label_key: str | None = Field(default=None, min_length=1, max_length=64)


class WorkbenchStart(BaseModel):
    request: WorkbenchRequest
    alert_id: int


OP_META = operation("workbench.meta", "GET", "/api/workbench/meta", None, WorkbenchMeta)
OP_RUN = operation("workbench.run", "POST", "/api/workbench/run", WorkbenchRun, WorkbenchResult)
OP_DIMENSION = operation("workbench.dimension", "POST", "/api/workbench/dimension", WorkbenchDimension, DimensionTop)
OP_FROM_ALERT = operation("workbench.from_alert", "GET", "/api/workbench/from-alert/<int:alert_id>", None,
                          WorkbenchStart)

bp = Blueprint("workbench", __name__)


def _invalid(exc: Exception) -> ApiFailure:
    # never echo input; the request shape was valid, the combination is not (e.g. a dimension of the other source)
    return ApiFailure(400, "invalid_input", "err_invalid_input", field=type(exc).__name__)


@api_route(bp, OP_META)
def meta() -> WorkbenchMeta:
    return workbench.meta(get_ctx())


@api_route(bp, OP_RUN)
def run(body: WorkbenchRun) -> WorkbenchResult:
    try:
        return workbench.run(get_ctx(), body.request)
    except StaleGeneration:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None
    except (ValidationError, ValueError) as exc:
        raise _invalid(exc) from None
    except OnDemandFailed as exc:
        raise ApiFailure(502, "pull_failed", "wb_pull_failed", params={"error": str(exc)[:300]}) from None


@api_route(bp, OP_DIMENSION)
def dimension(body: WorkbenchDimension) -> DimensionTop:
    try:
        return workbench.dimension(get_ctx(), body.request, body.dimension, label_key=body.label_key)
    except StaleGeneration:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None
    except OnDemandFailed as exc:
        raise ApiFailure(502, "pull_failed", "wb_pull_failed", params={"error": str(exc)[:300]}) from None
    except (ValidationError, ValueError) as exc:
        raise _invalid(exc) from None


@api_route(bp, OP_FROM_ALERT)
def from_alert(alert_id: int) -> WorkbenchStart:
    req = workbench.from_alert(get_ctx(), alert_id)
    if req is None:
        raise ApiFailure(404, "not_found", "err_not_found")
    return WorkbenchStart(request=req, alert_id=alert_id)
