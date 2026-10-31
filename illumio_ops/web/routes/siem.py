"""SIEM forwarding (spec §6.5 SIEM 轉送, P7): the destinations (HEC tokens masked), the status of every destination and
source, a test line with the values on the page (saved or not), and the DLQ — list, resend, purge, export."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from flask import Blueprint, Response, request, stream_with_context
from flask_login import current_user
from pydantic import BaseModel, Field, ValidationError

from illumio_ops.domain.values import (
    PolicyDecision,
    SiemFormat,
    SiemSource,
    SiemTransport,
)
from illumio_ops.services.siem import dlq
from illumio_ops.services.siem.cursors import place_new_cursors
from illumio_ops.services.siem.status import SiemStatusView, siem_status
from illumio_ops.services.siem.tester import send_test
from illumio_ops.settings.schema import SiemDestination, SiemSettings
from illumio_ops.settings.secrets import (
    MASK,
    CredentialsRequired,
    merge_siem_destinations,
    redact,
)
from illumio_ops.store import siem as store
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation
from illumio_ops.web.errors import api_error


class SiemDestinationInput(BaseModel):
    """The page's copy of a destination: a masked token is not a token, so what is saved or sent is validated as
    SiemDestination after the saved token is merged back in."""
    id: str
    name: str
    enabled: bool
    transport: SiemTransport
    format: SiemFormat
    host: str
    port: int
    framing: Literal["lf", "octet_counting"]
    verify_tls: bool | str
    hec_token: str
    batch_size: int
    max_retries: int
    sources: list[SiemSource]
    new_connection_decisions: list[PolicyDecision]
    new_connection_internal_only: bool
    mask_pii: bool


class SiemSettingsInput(BaseModel):
    enabled: bool
    destinations: list[SiemDestinationInput]
    dlq_max_per_dest: int
    tick_seconds: int
    backlog_warn_rows: int


class SiemSettingsView(BaseModel):
    revision: int
    siem: SiemSettingsInput


class SiemSettingsUpdate(BaseModel):
    revision: int
    siem: SiemSettingsInput


class SiemTestRequest(BaseModel):
    destination: SiemDestinationInput


class SiemTestView(BaseModel):
    ok: bool
    error: str | None
    line: str


class DlqItem(BaseModel):
    id: int
    destination_id: str
    destination: str
    source: str
    external_id: str
    event_time: datetime | None
    error: str
    attempts: int
    quarantined_at: datetime
    preview: str        # the start of the stored line


class DlqPage(BaseModel):
    items: list[DlqItem]
    total: int
    limit: int
    offset: int


class DlqQuery(BaseModel):
    destination_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class DlqAction(BaseModel):
    """ids: those lines; none: every line of destination_id (or of every destination)."""
    ids: list[int] | None = Field(default=None, max_length=1_000)
    destination_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class DlqResendView(BaseModel):
    sent: int
    failed: int
    skipped: int
    changed: int
    remaining: int
    error: str | None


class DlqPurgeView(BaseModel):
    deleted: int


OP_STATUS = operation("siem.status", "GET", "/api/siem/status", None, SiemStatusView)
OP_GET = operation("siem.settings.get", "GET", "/api/siem/settings", None, SiemSettingsView)
OP_UPDATE = operation("siem.settings.update", "PUT", "/api/siem/settings", SiemSettingsUpdate, SiemSettingsView)
OP_TEST = operation("siem.destination.test", "POST", "/api/siem/test", SiemTestRequest, SiemTestView)
OP_DLQ = operation("siem.dlq.list", "GET", "/api/siem/dlq", None, DlqPage)
OP_RESEND = operation("siem.dlq.resend", "POST", "/api/siem/dlq/resend", DlqAction, DlqResendView)
OP_PURGE = operation("siem.dlq.purge", "POST", "/api/siem/dlq/purge", DlqAction, DlqPurgeView)

bp = Blueprint("siem", __name__)


def _invalid(exc: ValidationError, prefix: str = "") -> ApiFailure:
    errs = exc.errors(include_input=False)
    return ApiFailure(400, "invalid_input", "err_invalid_input",
                      field=prefix + ".".join(str(p) for p in errs[0]["loc"]) if errs else None)


def _view() -> SiemSettingsView:
    s = get_ctx().settings.current()
    return SiemSettingsView(revision=s.revision, siem=SiemSettingsInput.model_validate(redact(s)["siem"]))


def _merged(body: SiemSettingsInput) -> dict[str, Any]:
    saved = get_ctx().settings.current().siem
    d = body.model_dump(mode="json")
    try:
        d["destinations"] = merge_siem_destinations(saved, d["destinations"], mask=MASK)
    except CredentialsRequired as exc:
        raise ApiFailure(400, "credentials_required", "err_siem_token_required", field=exc.field) from None
    return d


@api_route(bp, OP_STATUS)
def status() -> SiemStatusView:
    return siem_status(get_ctx())


@api_route(bp, OP_GET)
def get_settings() -> SiemSettingsView:
    return _view()


@api_route(bp, OP_UPDATE)
def update_settings(body: SiemSettingsUpdate) -> SiemSettingsView:
    ctx = get_ctx()
    merged = _merged(body.siem)
    try:
        SiemSettings.model_validate(merged)
    except ValidationError as exc:
        raise _invalid(exc, "siem.") from None
    ctx.settings.update(body.revision, lambda d: d.__setitem__("siem", merged))
    place_new_cursors(ctx)  # a new destination or source starts now, not at the next run
    return _view()


@api_route(bp, OP_TEST)
def test_destination(body: SiemTestRequest) -> SiemTestView:
    ctx = get_ctx()
    d = body.destination.model_dump(mode="json")
    try:
        [merged] = merge_siem_destinations(ctx.settings.current().siem, [d], mask=MASK)
        dest = SiemDestination.model_validate({**merged, "enabled": True})
    except CredentialsRequired as exc:
        raise ApiFailure(400, "credentials_required", "err_siem_token_required", field=exc.field) from None
    except ValidationError as exc:
        raise _invalid(exc, "destination.") from None
    r = send_test(ctx, dest)
    return SiemTestView(ok=r.ok, error=r.error, line=r.line)


@api_route(bp, OP_DLQ)
def list_dlq() -> DlqPage:
    try:
        q = DlqQuery.model_validate(request.args.to_dict())
    except ValidationError as exc:
        raise _invalid(exc) from None
    ctx = get_ctx()
    names = {d.id: d.name for d in ctx.settings.current().siem.destinations}
    with ctx.db() as conn:
        rows = store.dlq_page(conn, destination_id=q.destination_id, limit=q.limit, offset=q.offset)
        total = store.dlq_count(conn, q.destination_id)
    return DlqPage(items=[DlqItem(id=d.id, destination_id=d.destination_id,
                                  destination=names.get(d.destination_id, d.destination_id), source=d.source,
                                  external_id=d.external_id, event_time=d.event_time, error=d.error,
                                  attempts=d.attempts, quarantined_at=d.quarantined_at, preview=d.payload[:300])
                          for d in rows], total=total, limit=q.limit, offset=q.offset)


@api_route(bp, OP_RESEND)
def resend(body: DlqAction) -> DlqResendView:
    r = dlq.resend(get_ctx(), ids=body.ids, destination_id=body.destination_id)
    return DlqResendView(**r.model_dump())


@api_route(bp, OP_PURGE)
def purge(body: DlqAction) -> DlqPurgeView:
    return DlqPurgeView(deleted=dlq.purge(get_ctx(), ids=body.ids, destination_id=body.destination_id))


@bp.get("/siem/dlq/export")
def export() -> Response | tuple[Response, int]:
    ctx = get_ctx()
    if not current_user.is_authenticated:
        return api_error(401, "auth_required", "err_auth_required")
    if ctx.settings.current().web.must_change_password:
        return api_error(423, "password_change_required", "err_password_change_required")
    dest = request.args.get("destination_id") or None
    if dest is not None and not (len(dest) == 32 and all(c in "0123456789abcdef" for c in dest)):
        return api_error(400, "invalid_input", "err_invalid_input")
    resp = Response(stream_with_context(dlq.export_lines(ctx, destination_id=dest)), mimetype="application/x-ndjson")
    resp.headers["Content-Disposition"] = f'attachment; filename="{dlq.export_name()}"'
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp
