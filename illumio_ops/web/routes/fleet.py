"""VEN fleet: the inventory counted and listed (read-only), enforcement progression and the traffic update rate
increase (write key only), and what was done."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import current_user
from pydantic import BaseModel, Field, ValidationError, model_validator

from illumio_ops.pce.client import (
    PceBudgetExhausted,
    PceNotConfigured,
    PceTransportError,
)
from illumio_ops.pce.collections import PceCollectionIncomplete
from illumio_ops.services import fleet, fleet_write
from illumio_ops.services.collect.guard import BindingMismatch
from illumio_ops.services.fleet import FleetFilter, FleetHostList, FleetOverview
from illumio_ops.services.fleet_write import (
    EnforcementHost,
    EnforcementPreview,
    FleetAction,
    FleetOutcome,
    LabelPick,
    RateCheck,
)
from illumio_ops.services.ondemand import OnDemandFailed
from illumio_ops.store.flowdb.db import StaleGeneration
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation

Key = str


class FleetKeys(BaseModel):
    keys: list[Key] = Field(min_length=1, max_length=fleet_write.MAX_BATCH)


class EnforcementPreviewRequest(BaseModel):
    target: str = Field(min_length=1, max_length=20)
    keys: list[Key] = Field(default_factory=list, max_length=fleet_write.MAX_BATCH)
    labels: list[LabelPick] = Field(default_factory=list, max_length=8)  # every one of them (resolved here only)

    @model_validator(mode="after")
    def _one(self) -> EnforcementPreviewRequest:
        if bool(self.keys) == bool(self.labels):
            raise ValueError("choose hosts or labels")
        return self


class EnforcementApplyRequest(BaseModel):
    target: str = Field(min_length=1, max_length=20)
    hosts: list[EnforcementHost] = Field(min_length=1, max_length=fleet_write.MAX_BATCH)


class FleetHistory(BaseModel):
    actions: list[FleetAction]


OP_OVERVIEW = operation("fleet.overview", "GET", "/api/fleet/overview", None, FleetOverview)
OP_HOSTS = operation("fleet.hosts", "GET", "/api/fleet/hosts", None, FleetHostList)
OP_PREVIEW = operation("fleet.enforcement_preview", "POST", "/api/fleet/enforcement/preview",
                       EnforcementPreviewRequest, EnforcementPreview)
OP_APPLY = operation("fleet.enforcement_apply", "POST", "/api/fleet/enforcement/apply", EnforcementApplyRequest,
                     FleetOutcome)
OP_RATE_CHECK = operation("fleet.rate_check", "POST", "/api/fleet/traffic-rate/check", FleetKeys, RateCheck)
OP_RATE_APPLY = operation("fleet.rate_apply", "POST", "/api/fleet/traffic-rate/apply", FleetKeys, FleetOutcome)
OP_HISTORY = operation("fleet.history", "GET", "/api/fleet/actions", None, FleetHistory)

bp = Blueprint("fleet", __name__)
PCE_FAILURES = (PceCollectionIncomplete, PceTransportError, PceBudgetExhausted, OnDemandFailed)


def _mapped(exc: Exception) -> ApiFailure:
    if isinstance(exc, (StaleGeneration, BindingMismatch)):
        return ApiFailure(409, "pce_switched", "wb_pce_switched")
    if isinstance(exc, fleet_write.NoWriteKey):
        return ApiFailure(409, "no_write_key", "fleet_err_no_write_key")
    if isinstance(exc, PceNotConfigured):
        return ApiFailure(409, "pce_not_configured", "q_err_pce_not_configured")
    if isinstance(exc, PCE_FAILURES):
        return ApiFailure(502, "pce_failed", "fleet_err_pce", params={"error": str(exc)[:300]})
    if isinstance(exc, fleet_write.SelectionTooLarge):
        return ApiFailure(400, "too_many", "fleet_err_too_many",
                          params={"n": str(exc.n), "max": str(fleet_write.MAX_BATCH)})
    return ApiFailure(400, "invalid_input", "err_invalid_input", field="keys")  # ValueError: input never echoed


HANDLED = (StaleGeneration, BindingMismatch, fleet_write.NoWriteKey, PceNotConfigured, *PCE_FAILURES, ValueError)


@api_route(bp, OP_OVERVIEW)
def overview() -> FleetOverview:
    try:
        return fleet.overview(get_ctx())
    except BindingMismatch:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None


@api_route(bp, OP_HOSTS)
def hosts() -> FleetHostList:
    args = {k: request.args[k] for k in ("mode", "env", "online", "q", "no_env") if k in request.args}
    if any(len(v) > 255 for v in args.values()):
        raise ApiFailure(400, "invalid_input", "err_invalid_input", field="q")
    try:
        f = FleetFilter.model_validate(args)
    except ValidationError:
        raise ApiFailure(400, "invalid_input", "err_invalid_input", field="online") from None
    try:
        return fleet.host_list(get_ctx(), f)
    except BindingMismatch:
        raise ApiFailure(409, "pce_switched", "wb_pce_switched") from None


@api_route(bp, OP_PREVIEW)
def enforcement_preview(body: EnforcementPreviewRequest) -> EnforcementPreview:
    ctx = get_ctx()
    try:
        keys = body.keys or fleet_write.select(ctx, body.labels)
        return fleet_write.preview(ctx, keys, body.target)
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_APPLY)
def enforcement_apply(body: EnforcementApplyRequest) -> FleetOutcome:
    try:
        return fleet_write.apply(get_ctx(), body.hosts, body.target, by=str(current_user.get_id()))
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_RATE_CHECK)
def rate_check(body: FleetKeys) -> RateCheck:
    try:
        return fleet_write.rate_check(get_ctx(), body.keys)
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_RATE_APPLY)
def rate_apply(body: FleetKeys) -> FleetOutcome:
    try:
        return fleet_write.increase_rate(get_ctx(), body.keys, by=str(current_user.get_id()))
    except HANDLED as exc:
        raise _mapped(exc) from None


@api_route(bp, OP_HISTORY)
def history() -> FleetHistory:
    return FleetHistory(actions=fleet_write.history(get_ctx()))
