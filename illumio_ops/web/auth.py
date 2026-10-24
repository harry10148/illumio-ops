"""Single-admin login, logout, CSRF token and password change."""
from __future__ import annotations

import hmac
from typing import Any

from flask import Blueprint, Flask, Response, current_app, g, session
from flask import request as flask_request
from flask_limiter import Limiter
from flask_login import UserMixin, current_user, login_user, logout_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from illumio_ops.services.context import AppContext
from illumio_ops.settings.secrets import (
    PASSWORD_MAX_LEN,
    PASSWORD_MIN_LEN,
    hash_password,
    new_secret_key,
    verify_password,
)
from illumio_ops.web.errors import api_error, api_ok

# Re-exported for callers that think of these as web concerns.
__all__ = ["PASSWORD_MAX_LEN", "PASSWORD_MIN_LEN", "AdminUser", "get_ctx", "hash_password",
           "make_auth_blueprint", "verify_password"]


class AdminUser(UserMixin):
    def __init__(self, username: str) -> None:
        self.id = username


def get_ctx(app: Flask | None = None) -> AppContext:
    ctx: AppContext = (app or current_app).extensions["illumio_ops"]
    return ctx


class _Login(BaseModel):
    model_config = ConfigDict(extra="ignore")
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class _PasswordChange(BaseModel):
    model_config = ConfigDict(extra="ignore")
    old_password: str | None = Field(default=None, max_length=1024)
    new_password: str = Field(max_length=4096)
    confirm_password: str = Field(max_length=4096)


def _body(model: type[BaseModel]) -> Any:
    try:
        return model.model_validate(flask_request.get_json(silent=True) or {})
    except ValidationError as exc:
        # Never echo the body: it carries passwords.
        locs = [".".join(str(p) for p in e["loc"]) for e in exc.errors(include_input=False)]
        logger.warning("auth form rejected: fields={}", locs)
        return None


def _me() -> dict[str, Any]:
    s = get_ctx().settings.current()
    return {"username": s.web.username, "must_change_password": s.web.must_change_password}


def make_auth_blueprint(csrf: CSRFProtect, limiter: Limiter) -> Blueprint:
    bp = Blueprint("auth", __name__)

    @bp.get("/api/auth/csrf")
    def csrf_token() -> tuple[Response, int]:
        return api_ok({"csrf_token": generate_csrf()})

    @bp.post("/api/auth/login")
    @csrf.exempt
    @limiter.limit("5 per minute")
    def login() -> tuple[Response, int]:
        form = _body(_Login)
        if form is None:
            return api_error(400, "invalid_input", "err_invalid_input")
        web = get_ctx().settings.current().web
        # Always run both checks so a wrong username costs the same time as a wrong password.
        username_ok = hmac.compare_digest(form.username.strip().encode(), web.username.strip().encode())
        password_ok = verify_password(form.password, web.password_hash)
        if not (username_ok and password_ok):
            return api_error(401, "invalid_credentials", "err_invalid_credentials")
        session.permanent = True
        login_user(AdminUser(web.username))
        return api_ok(_me() | {"csrf_token": generate_csrf()})

    @bp.post("/api/auth/logout")
    def logout() -> tuple[Response, int]:
        logout_user()
        session.clear()
        return api_ok({})

    @bp.get("/api/auth/me")
    def me() -> tuple[Response, int]:
        return api_ok(_me())

    @bp.post("/api/auth/password")
    def change_password() -> tuple[Response, int]:
        form = _body(_PasswordChange)
        if form is None:
            return api_error(400, "invalid_input", "err_invalid_input")
        ctx = get_ctx()
        cur = ctx.settings.current()
        if not cur.web.must_change_password:
            if not form.old_password:
                return api_error(400, "old_password_required", "err_old_password_required", field="old_password")
            if not verify_password(form.old_password, cur.web.password_hash):
                return api_error(400, "old_password_incorrect", "err_old_password_incorrect", field="old_password")
        new = form.new_password
        if not (PASSWORD_MIN_LEN <= len(new) <= PASSWORD_MAX_LEN) or new != form.confirm_password:
            return api_error(400, "invalid_new_password", "err_invalid_new_password", field="new_password",
                             params={"min": str(PASSWORD_MIN_LEN), "max": str(PASSWORD_MAX_LEN)})
        new_hash, new_key = hash_password(new), new_secret_key()

        def mutate(d: dict[str, Any]) -> None:
            d["web"].update(password_hash=new_hash, secret_key=new_key, must_change_password=False)

        ctx.settings.update(cur.revision, mutate)
        # Rotating the signing key logs out every other session (a leaked cookie is a
        # common reason to change the password); this response re-signs the caller's.
        current_app.secret_key = new_key
        current_app.config["SECRET_KEY"] = new_key
        session.modified = True
        g.pop("csrf_token", None)
        logger.info("admin password changed by {}; other sessions revoked", current_user.get_id())
        return api_ok({"csrf_token": generate_csrf()})

    return bp
