"""System › Security (allowed addresses) and System › Display (language)."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, request
from pydantic import BaseModel, Field

from illumio_ops.domain.values import Language
from illumio_ops.web.auth import get_ctx
from illumio_ops.web.contract import ApiFailure, api_route, operation
from illumio_ops.web.ipallow import InvalidIpEntries, is_allowed, validate_allowed_ips


class SecurityView(BaseModel):
    revision: int
    username: str
    allowed_ips: list[str]
    requester_ip: str


class SecurityUpdate(BaseModel):
    revision: int
    allowed_ips: list[str] = Field(max_length=500)
    confirm_lockout: bool = False


class DisplayView(BaseModel):
    revision: int
    language: Language


class DisplayUpdate(BaseModel):
    revision: int
    language: Language


OP_SECURITY_GET = operation("system.security.get", "GET", "/api/system/security", None, SecurityView)
OP_SECURITY_UPDATE = operation("system.security.update", "PUT", "/api/system/security", SecurityUpdate, SecurityView)
OP_DISPLAY_GET = operation("system.display.get", "GET", "/api/system/display", None, DisplayView)
OP_DISPLAY_UPDATE = operation("system.display.update", "PUT", "/api/system/display", DisplayUpdate, DisplayView)

bp = Blueprint("system_security", __name__)


def _security() -> SecurityView:
    s = get_ctx().settings.current()
    return SecurityView(revision=s.revision, username=s.web.username, allowed_ips=list(s.web.allowed_ips),
                        requester_ip=request.remote_addr or "")


@api_route(bp, OP_SECURITY_GET)
def get_security() -> SecurityView:
    return _security()


@api_route(bp, OP_SECURITY_UPDATE)
def update_security(body: SecurityUpdate) -> SecurityView:
    try:
        allowed = validate_allowed_ips(body.allowed_ips)
    except InvalidIpEntries as exc:
        raise ApiFailure(400, "invalid_ip_entries", "err_invalid_ip_entries", field="allowed_ips",
                         params={"entries": ", ".join(exc.invalid)}) from None
    requester = request.remote_addr or ""
    # Saving a list that leaves out the address you are using cuts this session off:
    # the next request is reset at the connection. Refuse unless explicitly confirmed.
    if allowed and not is_allowed(allowed, requester) and not body.confirm_lockout:
        raise ApiFailure(409, "would_lock_out", "err_would_lock_out", field="allowed_ips", params={"ip": requester})

    def mutate(d: dict[str, Any]) -> None:
        d["web"]["allowed_ips"] = allowed

    get_ctx().settings.update(body.revision, mutate)
    return _security()


def _display() -> DisplayView:
    s = get_ctx().settings.current()
    return DisplayView(revision=s.revision, language=s.display.language)


@api_route(bp, OP_DISPLAY_GET)
def get_display() -> DisplayView:
    return _display()


@api_route(bp, OP_DISPLAY_UPDATE)
def update_display(body: DisplayUpdate) -> DisplayView:
    language = body.language.value

    def mutate(d: dict[str, Any]) -> None:
        d["display"]["language"] = language

    get_ctx().settings.update(body.revision, mutate)
    return _display()
