"""Alerts: the current PCE's recent alerts, one alert's detail and evidence, notes, and the policy explanation of
an evidence row (spec §6.5 告警, §6.5.2)."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import current_user
from pydantic import BaseModel, Field, ValidationError

from illumio_ops.services.alerts import known, views
from illumio_ops.services.alerts.known import KnownList, KnownMark
from illumio_ops.services.alerts.views import (
    AlertDetail,
    AlertEvidence,
    AlertList,
    AlertQuery,
    ExplainRequest,
)
from illumio_ops.services.analysis.explain import PolicyExplanation
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class NoteAdd(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


OP_LIST = operation("alerts.list", "GET", "/api/alerts", None, AlertList)
OP_GET = operation("alerts.get", "GET", "/api/alerts/<int:alert_id>", None, AlertDetail)
OP_EVIDENCE = operation("alerts.evidence", "GET", "/api/alerts/<int:alert_id>/evidence", None, AlertEvidence)
OP_NOTE = operation("alerts.note_add", "POST", "/api/alerts/<int:alert_id>/notes", NoteAdd, AlertDetail)
OP_KNOWN = operation("alerts.mark_known", "POST", "/api/alerts/<int:alert_id>/known", KnownMark, KnownList)
OP_EXPLAIN = operation("alerts.explain", "POST", "/api/alerts/<int:alert_id>/explain", ExplainRequest,
                       PolicyExplanation)

bp = Blueprint("alerts", __name__)


def _missing() -> ApiFailure:
    return ApiFailure(404, "not_found", "err_not_found")


@api_route(bp, OP_LIST)
def list_alerts() -> AlertList:
    try:
        q = AlertQuery.model_validate(request.args.to_dict())
    except ValidationError as exc:
        errs = exc.errors(include_input=False)
        raise ApiFailure(400, "invalid_input", "err_invalid_input",
                         field=".".join(str(p) for p in errs[0]["loc"]) if errs else None) from None
    return views.list_alerts(get_ctx(), q)


@api_route(bp, OP_GET)
def get_alert(alert_id: int) -> AlertDetail:
    found = views.alert_detail(get_ctx(), alert_id)
    if found is None:
        raise _missing()
    return found


@api_route(bp, OP_EVIDENCE)
def get_evidence(alert_id: int) -> AlertEvidence:
    found = views.alert_evidence(get_ctx(), alert_id)
    if found is None:
        raise _missing()
    return found


@api_route(bp, OP_NOTE)
def add_note(body: NoteAdd, alert_id: int) -> AlertDetail:
    found = views.add_note(get_ctx(), alert_id, body=body.body, by=str(current_user.get_id()))
    if found is None:
        raise _missing()
    return found


@api_route(bp, OP_EXPLAIN)
def explain(body: ExplainRequest, alert_id: int) -> PolicyExplanation:
    try:
        found = views.explain(get_ctx(), alert_id, body)
    except views.NotFlowAlert:
        raise ApiFailure(400, "not_a_flow_alert", "err_not_a_flow_alert") from None
    if found is None:
        raise _missing()
    return found


@api_route(bp, OP_KNOWN)
def mark_known(body: KnownMark, alert_id: int) -> KnownList:
    try:
        found = known.mark_known(get_ctx(), alert_id, body, by=str(current_user.get_id()))
    except known.NotLateralAlert:
        raise ApiFailure(400, "not_a_lateral_alert", "err_not_a_lateral_alert") from None
    if found is None:
        raise _missing()
    return found
