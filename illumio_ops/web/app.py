"""Flask application factory. Hook order matters: the IP allowlist gate is registered
before any extension so a refused client never receives an HTTP response."""
from __future__ import annotations

import traceback
import uuid
from pathlib import Path

from flask import Flask, Response, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from loguru import logger
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.wrappers import Response as WerkzeugResponse

from illumio_ops.services.context import AppContext
from illumio_ops.web import security
from illumio_ops.web.auth import AdminUser, make_auth_blueprint, session_is_active
from illumio_ops.web.contract import op_id_for_endpoint
from illumio_ops.web.errors import api_error
from illumio_ops.web.ipallow import RstDrop, is_allowed, rst_drop
from illumio_ops.web.routes import i18n as i18n_routes
from illumio_ops.web.routes import system_jobs, system_pce, system_tls

DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Operations reachable without a session (the login page needs these before signing in).
PUBLIC_OPS = frozenset({"auth.login", "auth.csrf", "i18n.dictionary"})
# While the admin must change the password, only these respond.
PASSWORD_CHANGE_OPS = frozenset({"auth.password", "auth.logout", "auth.me", "auth.csrf"})


def create_app(ctx: AppContext, *, use_https: bool, static_dir: Path | None = None) -> Flask:
    static_root = (static_dir or DEFAULT_STATIC_DIR).resolve()
    app = Flask(__name__, static_folder=None)
    app.extensions["illumio_ops"] = ctx
    web = ctx.settings.current().web

    # 1. IP allowlist — MUST be the first before_request hook (CSRF, limiter and
    #    Talisman hooks below can all emit a response to an untrusted client).
    @app.before_request
    def ip_allowlist_gate() -> None:
        if not is_allowed(ctx.settings.current().web.allowed_ips, request.remote_addr):
            logger.warning("refused connection from a non-allowlisted address")
            rst_drop()

    # 2. Session
    app.secret_key = web.secret_key
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=use_https,
        PERMANENT_SESSION_LIFETIME=web.session_lifetime_seconds,
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        JSON_AS_ASCII=False,
    )

    # 3. Login
    login_manager = LoginManager(app)
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def _load_user(user_id: str) -> AdminUser | None:
        name = ctx.settings.current().web.username
        return AdminUser(name) if user_id == name and session_is_active() else None

    # 4. CSRF
    app.config.update(
        WTF_CSRF_ENABLED=True,
        WTF_CSRF_TIME_LIMIT=web.session_lifetime_seconds,
        WTF_CSRF_CHECK_DEFAULT=True,
        WTF_CSRF_HEADERS=["X-CSRFToken", "X-CSRF-Token"],
    )
    csrf = CSRFProtect(app)

    # 5. Rate limiting (inbound)
    uri = security.limiter_storage_uri(ctx.paths)
    app.config["RATELIMIT_STORAGE_URI"] = uri
    limiter = Limiter(get_remote_address, app=app, default_limits=["300 per minute"],
                      storage_uri=uri, strategy="fixed-window")

    # 6. Security headers
    security.install_talisman(app, use_https=use_https)
    app.after_request(security.add_static_headers)

    # 7. Authentication for /api/*
    @app.before_request
    def require_login() -> tuple[Response, int] | None:
        op_id = op_id_for_endpoint(request.endpoint)
        if not request.path.startswith("/api/") or op_id in PUBLIC_OPS:
            return None
        if not current_user.is_authenticated:
            return api_error(401, "auth_required", "err_auth_required")
        if ctx.settings.current().web.must_change_password and op_id not in PASSWORD_CHANGE_OPS:
            return api_error(423, "password_change_required", "err_password_change_required")
        return None

    app.register_blueprint(make_auth_blueprint(csrf, limiter))
    app.register_blueprint(i18n_routes.bp)
    app.register_blueprint(system_pce.bp)
    app.register_blueprint(system_jobs.bp)
    app.register_blueprint(system_tls.make_blueprint(limiter))

    # 8. The single-page app: hashed assets, anything else that is a file, else index.html
    @app.get("/")
    @app.get("/<path:path>")
    def spa(path: str = "") -> Response:
        if path.startswith("api/"):
            raise NotFound()
        if path and (static_root / path).is_file():
            return send_from_directory(static_root, path, max_age=31536000 if path.startswith("assets/") else 0)
        return send_from_directory(static_root, "index.html", max_age=0)

    @app.errorhandler(RstDrop)
    def _rst(_: RstDrop) -> Response:
        # Refused peers are normally reset at accept time (web.server). This only runs for a
        # keep-alive connection whose address was removed from the list mid-connection, or
        # when the socket could not be reached: end it without content and never with 200.
        return Response(b"", status=403, headers={"Connection": "close"})

    @app.errorhandler(CSRFError)
    def _csrf_error(_: CSRFError) -> tuple[Response, int]:
        return api_error(400, "csrf_error", "err_csrf_error", data={"csrf_token": generate_csrf()})

    @app.errorhandler(429)
    def _rate_limited(_: HTTPException) -> tuple[Response, int]:
        return api_error(429, "rate_limited", "err_rate_limited")

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception) -> WerkzeugResponse | tuple[Response, int]:
        if isinstance(exc, HTTPException):
            if not request.path.startswith("/api/"):
                return exc.get_response()
            if exc.code == 404:
                return api_error(404, "not_found", "err_not_found")
            if exc.code == 405:
                return api_error(405, "method_not_allowed", "err_method_not_allowed")
            return api_error(exc.code or 500, "http_error", "err_http_error", params={"status": str(exc.code)})
        ref = uuid.uuid4().hex[:8]
        logger.error("unhandled error ref={}: {}", ref, traceback.format_exc())
        return api_error(500, "internal_error", "err_internal_error", params={"ref": ref})

    return app
