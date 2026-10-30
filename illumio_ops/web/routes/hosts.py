"""Host profile (spec §6.5.3, P6b): one host's inventory, exposure, tamper investigation and ransomware breakdown;
the allow rules behind its services on request; known causes of its tampering."""
from __future__ import annotations

from flask import Blueprint, request
from flask_login import current_user
from pydantic import BaseModel, Field

from illumio_ops.domain.values import TamperPattern
from illumio_ops.services import hosts
from illumio_ops.services.analysis.ransomware import HostRansomware
from illumio_ops.services.hosts import HostProfile
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation


class HostKey(BaseModel):
    key: str = Field(min_length=1, max_length=300)


class TamperNoteAdd(HostKey):
    pattern: TamperPattern | None = None
    process: str | None = Field(default=None, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


OP_PROFILE = operation("hosts.profile", "GET", "/api/hosts/profile", None, HostProfile)
OP_ALLOWS = operation("hosts.ransomware_allows", "POST", "/api/hosts/ransomware-allows", HostKey, HostRansomware)
OP_NOTE_ADD = operation("hosts.tamper_note_add", "POST", "/api/hosts/tamper-notes", TamperNoteAdd, HostProfile)
OP_NOTE_REMOVE = operation("hosts.tamper_note_remove", "POST", "/api/hosts/tamper-notes/<int:note_id>/remove", HostKey,
                           HostProfile)

bp = Blueprint("hosts", __name__)


def _invalid() -> ApiFailure:
    return ApiFailure(400, "invalid_input", "err_invalid_input", field="key")  # never echo input


@api_route(bp, OP_PROFILE)
def profile() -> HostProfile:
    try:
        return hosts.profile(get_ctx(), request.args.get("key", ""))
    except ValueError:
        raise _invalid() from None


@api_route(bp, OP_ALLOWS)
def ransomware_allows(body: HostKey) -> HostRansomware:
    try:
        return hosts.ransomware_allows(get_ctx(), body.key)
    except ValueError:
        raise _invalid() from None


@api_route(bp, OP_NOTE_ADD)
def tamper_note_add(body: TamperNoteAdd) -> HostProfile:
    ctx = get_ctx()
    try:
        hosts.add_tamper_note(ctx, body.key, pattern=body.pattern, process=body.process, reason=body.reason,
                              by=str(current_user.get_id()))
        return hosts.profile(ctx, body.key)
    except ValueError:
        raise _invalid() from None


@api_route(bp, OP_NOTE_REMOVE)
def tamper_note_remove(body: HostKey, note_id: int) -> HostProfile:
    ctx = get_ctx()
    try:
        hosts.remove_tamper_note(ctx, note_id)
        return hosts.profile(ctx, body.key)
    except ValueError:
        raise _invalid() from None
