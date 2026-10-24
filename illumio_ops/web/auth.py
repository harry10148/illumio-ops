"""Single-admin login, logout, CSRF token and password change."""
from __future__ import annotations

import hmac
import secrets
import time
from typing import Any

from flask import Blueprint, Flask, current_app, g, session
from flask_limiter import Limiter
from flask_login import UserMixin, current_user, login_user, logout_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from loguru import logger
from pydantic import BaseModel, Field

from illumio_ops.services.context import AppContext
from illumio_ops.settings.secrets import (
    PASSWORD_MAX_LEN,
    PASSWORD_MIN_LEN,
    hash_password,
    new_secret_key,
    verify_password,
)
from illumio_ops.web.contract import ApiFailure, Empty, api_route, operation

__all__ = ["PASSWORD_MAX_LEN", "PASSWORD_MIN_LEN", "AdminUser", "get_ctx", "hash_password",
           "make_auth_blueprint", "session_is_active", "verify_password"]

_SESSIONS_KEY = "illumio_ops_sessions"


class AdminUser(UserMixin):
    def __init__(self, username: str) -> None:
        self.id = username


def get_ctx(app: Flask | None = None) -> AppContext:
    ctx: AppContext = (app or current_app).extensions["illumio_ops"]
    return ctx


# Live sessions are tracked server-side (in memory, sid -> issued at) so logout really
# ends a session: the signed cookie alone would stay valid until it expires if someone
# copied it. A restart therefore signs everyone out.
def _active(app: Flask | None = None) -> dict[str, float]:
    sessions: dict[str, float] = (app or current_app).extensions.setdefault(_SESSIONS_KEY, {})
    return sessions


def _prune_expired() -> None:
    lifetime = get_ctx().settings.current().web.session_lifetime_seconds
    cutoff = time.time() - lifetime
    active = _active()
    for sid in [s for s, issued in active.items() if issued < cutoff]:
        del active[sid]


def session_is_active() -> bool:
    sid = session.get("sid")
    return isinstance(sid, str) and sid in _active()


class LoginRequest(BaseModel):
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class PasswordChangeRequest(BaseModel):
    old_password: str | None = Field(default=None, max_length=1024)
    new_password: str = Field(max_length=4096)
    confirm_password: str = Field(max_length=4096)


class CsrfToken(BaseModel):
    csrf_token: str


class Me(BaseModel):
    username: str
    must_change_password: bool


class LoginResult(Me):
    csrf_token: str


OP_CSRF = operation("auth.csrf", "GET", "/api/auth/csrf", None, CsrfToken)
OP_LOGIN = operation("auth.login", "POST", "/api/auth/login", LoginRequest, LoginResult)
OP_LOGOUT = operation("auth.logout", "POST", "/api/auth/logout", None, Empty)
OP_ME = operation("auth.me", "GET", "/api/auth/me", None, Me)
OP_PASSWORD = operation("auth.password", "POST", "/api/auth/password", PasswordChangeRequest, CsrfToken)


def _me() -> Me:
    web = get_ctx().settings.current().web
    return Me(username=web.username, must_change_password=web.must_change_password)


def make_auth_blueprint(csrf: CSRFProtect, limiter: Limiter) -> Blueprint:
    bp = Blueprint("auth", __name__)

    @api_route(bp, OP_CSRF)
    def csrf_token() -> CsrfToken:
        return CsrfToken(csrf_token=generate_csrf())

    @api_route(bp, OP_LOGIN, decorators=[limiter.limit("5 per minute"), csrf.exempt])
    def login(body: LoginRequest) -> LoginResult:
        web = get_ctx().settings.current().web
        # Always run both checks so a wrong username costs the same time as a wrong password.
        username_ok = hmac.compare_digest(body.username.strip().encode(), web.username.strip().encode())
        password_ok = verify_password(body.password, web.password_hash)
        if not (username_ok and password_ok):
            raise ApiFailure(401, "invalid_credentials", "err_invalid_credentials")
        _active().pop(session.get("sid", ""), None)  # a re-login retires the old session
        session.clear()  # no fixation: a fresh session for every login
        _prune_expired()
        sid = secrets.token_urlsafe(24)
        _active()[sid] = time.time()
        session["sid"] = sid
        session.permanent = True
        login_user(AdminUser(web.username))
        return LoginResult(**_me().model_dump(), csrf_token=generate_csrf())

    @api_route(bp, OP_LOGOUT)
    def logout() -> Empty:
        _active().pop(session.get("sid", ""), None)
        logout_user()
        session.clear()
        return Empty()

    @api_route(bp, OP_ME)
    def me() -> Me:
        return _me()

    @api_route(bp, OP_PASSWORD, decorators=[limiter.limit("5 per minute")])
    def change_password(body: PasswordChangeRequest) -> CsrfToken:
        ctx = get_ctx()
        cur = ctx.settings.current()
        if not cur.web.must_change_password:
            if not body.old_password:
                raise ApiFailure(400, "old_password_required", "err_old_password_required", field="old_password")
            if not verify_password(body.old_password, cur.web.password_hash):
                raise ApiFailure(400, "old_password_incorrect", "err_old_password_incorrect", field="old_password")
        new = body.new_password
        if not (PASSWORD_MIN_LEN <= len(new) <= PASSWORD_MAX_LEN) or new != body.confirm_password:
            raise ApiFailure(400, "invalid_new_password", "err_invalid_new_password", field="new_password",
                             params={"min": str(PASSWORD_MIN_LEN), "max": str(PASSWORD_MAX_LEN)})
        new_hash, new_key = hash_password(new), new_secret_key()

        def mutate(d: dict[str, Any]) -> None:
            d["web"].update(password_hash=new_hash, secret_key=new_key, must_change_password=False)

        ctx.settings.update(cur.revision, mutate)  # raises before anything below on failure
        # Every other session ends (a leaked cookie is a common reason to change the
        # password): drop them server-side and rotate the signing key; this response
        # re-signs the caller's session with the new key.
        mine = session.get("sid", "")
        active = _active()
        for sid in [s for s in active if s != mine]:
            del active[sid]
        current_app.secret_key = new_key
        current_app.config["SECRET_KEY"] = new_key
        session.modified = True
        g.pop("csrf_token", None)
        logger.info("admin password changed by {}; other sessions revoked", current_user.get_id())
        return CsrfToken(csrf_token=generate_csrf())

    return bp
