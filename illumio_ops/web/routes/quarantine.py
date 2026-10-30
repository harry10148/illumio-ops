"""Quarantine (spec §6.5.1 防堵, P6d): which policy refers to each level, what the hosts' traffic was, put the label on
or take it off (write key only), and what was done."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import current_user
from pydantic import BaseModel, Field

from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceNotConfigured,
    PceTransportError,
)
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services import quarantine
from illumio_ops.services.collect.guard import BindingMismatch
from illumio_ops.services.ondemand import OnDemandFailed
from illumio_ops.services.quarantine import (
    QuarantineAction,
    QuarantineOutcome,
    QuarantinePreview,
)
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation

Keys = list[str]


class QuarantineTargets(BaseModel):
    keys: Keys = Field(min_length=1, max_length=quarantine.MAX_BATCH)


class QuarantinePreviewRequest(QuarantineTargets):
    level: str = Field(min_length=1, max_length=20)


class QuarantineApplyRequest(QuarantinePreviewRequest):
    acknowledge_no_policy: bool = False


class QuarantineHistory(BaseModel):
    actions: list[QuarantineAction]


OP_PREVIEW = operation("quarantine.preview", "POST", "/api/quarantine/preview", QuarantinePreviewRequest,
                       QuarantinePreview)
OP_APPLY = operation("quarantine.apply", "POST", "/api/quarantine/apply", QuarantineApplyRequest, QuarantineOutcome)
OP_REMOVE = operation("quarantine.remove", "POST", "/api/quarantine/remove", QuarantineTargets, QuarantineOutcome)
OP_HISTORY = operation("quarantine.history", "GET", "/api/quarantine/history", None, QuarantineHistory)

bp = Blueprint("quarantine", __name__)
PCE_FAILURES = (PceCollectionIncomplete, PceTransportError, PceBudgetExhausted, OnDemandFailed)


def _mapped(exc: Exception) -> ApiFailure:
    if isinstance(exc, (StaleGeneration, BindingMismatch)):
        return ApiFailure(409, "pce_switched", "wb_pce_switched")
    if isinstance(exc, quarantine.NoWriteKey):
        return ApiFailure(409, "no_write_key", "q_err_no_write_key")
    if isinstance(exc, PceNotConfigured):
        return ApiFailure(409, "pce_not_configured", "q_err_pce_not_configured")
    if isinstance(exc, quarantine.NoPolicy):
        return ApiFailure(409, "no_policy", "q_err_no_policy")
    if isinstance(exc, PCE_FAILURES):
        return ApiFailure(502, "pce_failed", "q_err_pce", params={"error": str(exc)[:300]})
    return ApiFailure(400, "invalid_input", "err_invalid_input", field="keys")  # ValueError: input never echoed


HANDLED = (StaleGeneration, BindingMismatch, quarantine.NoWriteKey, PceNotConfigured, quarantine.NoPolicy,
           *PCE_FAILURES, ValueError)



@api_route(bp, OP_PREVIEW)
def preview(body: QuarantinePreviewRequest) -> QuarantinePreview:
    try:
        return quarantine.preview(get_ctx(), body.keys, body.level)
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_APPLY)
def apply(body: QuarantineApplyRequest) -> QuarantineOutcome:
    try:
        return quarantine.apply(get_ctx(), body.keys, body.level, by=str(current_user.get_id()),
                                acknowledge_no_policy=body.acknowledge_no_policy)
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_REMOVE)
def remove(body: QuarantineTargets) -> QuarantineOutcome:
    try:
        return quarantine.remove(get_ctx(), body.keys, by=str(current_user.get_id()))
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_HISTORY)
def history() -> QuarantineHistory:
    key = request.args.get("key") or None
    if key is not None and len(key) > 300:
        raise ApiFailure(400, "invalid_input", "err_invalid_input", field="key")
    return QuarantineHistory(actions=quarantine.history(get_ctx(), key))
