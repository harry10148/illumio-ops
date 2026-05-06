"""
Illumio PCE Ops ??Flask Web GUI.
Optional dependency: pip install flask

Features full parity with CLI:
  Dashboard, Rules (add event/traffic/bandwidth, delete), Settings, Actions (Run, Debug, Test Alert, Best Practices).
"""
from __future__ import annotations

import re
import os
import sys
import io
import json
import datetime
import threading
import ssl as _ssl
import hmac as _hmac

import uuid as _uuid
import traceback as _traceback
from loguru import logger
import ipaddress
from contextlib import redirect_stdout
import secrets
import socket as _socket
import struct

try:
    from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect
    from werkzeug.utils import secure_filename
    from werkzeug.exceptions import HTTPException
    HAS_FLASK = True
    FLASK_IMPORT_ERROR = ""
except ImportError:
    HAS_FLASK = False
    FLASK_IMPORT_ERROR = str(sys.exc_info()[1])

from src.config import ConfigManager
from src.i18n import t, get_messages
from src import __version__
from src.alerts import PLUGIN_METADATA, plugin_config_value
from src.report.dashboard_summaries import (
    build_audit_dashboard_summary,
    build_policy_usage_dashboard_summary,
    write_audit_dashboard_summary,
    write_policy_usage_dashboard_summary,
)
from src.href_utils import extract_id as _extract_id_href

# Daemon-restart hook state. Set by run_daemon_with_gui() in src/main.py.
_GUI_OWNS_DAEMON: bool = False
_DAEMON_SCHEDULER = None
_DAEMON_RESTART_FN = None

# ── Shared helpers (moved to _helpers.py; re-exported here for backwards compat) ─
from src.gui._helpers import (  # noqa: F401
    _ANSI_RE, _strip_ansi,
    _normalize_ip_token, _loopback_equivalent,
    _check_ip_allowed, _validate_allowed_ips,
    _SECRET_PATTERN, _redact_secrets, _strip_redaction_placeholders,
    _SETTINGS_ALLOWLISTS,
    _normalize_rule_throttle, _normalize_match_fields,
    _is_workload_href, _normalize_quarantine_hrefs,
    _rst_drop, _RstDrop,
    _GUI_DIR, _PKG_DIR, _ROOT_DIR,
    _ALLOWED_REPORT_FORMATS,
    _resolve_reports_dir, _resolve_config_dir, _resolve_state_file,
    _UI_EXTRA_KEYS, _ui_translation_dict,
    _plugin_config_roots, _summarize_alert_channels,
    _ok, _err, _safe_log, _err_with_log,
    _get_active_pce_url,
    _build_audit_dashboard_summary, _write_audit_dashboard_summary,
    _build_policy_usage_dashboard_summary, _write_policy_usage_dashboard_summary,
    _spec_to_plotly_figure, _load_state_for_charts,
    _build_traffic_timeline_spec, _build_policy_decisions_spec,
    _build_ven_status_spec, _build_rule_hits_spec,
    # TLS helpers
    _SELF_SIGNED_VALIDITY_DAYS, _cert_has_san, _get_local_ips,
    _generate_self_signed_cert, _get_cert_info, _cert_days_remaining,
    _maybe_auto_renew_self_signed, _build_ssl_context,
)
# ?? Rule Scheduler log history (in-memory, thread-safe) ??????????????????????
import collections as _collections
_rs_log_history: _collections.deque = _collections.deque(maxlen=200)
_rs_log_lock = threading.Lock()

def _append_rs_logs(logs: list) -> None:
    """Append one check-run's output to the in-memory log history."""
    with _rs_log_lock:
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "logs": [_ANSI_RE.sub('', l) for l in logs],
        }
        _rs_log_history.append(entry)  # deque(maxlen=200) auto-evicts oldest

def _rs_background_scheduler(cm: ConfigManager) -> None:
    """Background thread: run rule scheduler periodically in GUI-only mode."""
    import time
    last_check: float | None = None
    while True:
        time.sleep(60)
        try:
            cm.load()
            rs_cfg = cm.config.get("rule_scheduler", {})
            interval = rs_cfg.get("check_interval_seconds", 300)
            now = time.time()
            if last_check is None or (now - last_check) >= interval:
                from src.rule_scheduler import ScheduleDB, ScheduleEngine
                from src.api_client import ApiClient as _ApiClient
                db_path = os.path.join(_resolve_config_dir(), "rule_schedules.json")
                db = ScheduleDB(db_path)
                db.load()
                engine = ScheduleEngine(db, _ApiClient(cm))
                tz_str = cm.config.get('settings', {}).get('timezone', 'local')
                logs = engine.check(silent=True, tz_str=tz_str)
                _append_rs_logs(logs)
                last_check = now
                logger.info("[RuleScheduler] Auto-check completed ({} entries).", len(logs))
        except Exception as exc:
            logger.error("[RuleScheduler] Background error: {}", exc, exc_info=True)

def _create_app(cm: ConfigManager, persistent_mode: bool = False, use_https: bool = True) -> 'Flask':
    app = Flask(__name__, template_folder=os.path.join(_PKG_DIR, 'templates'), static_folder=os.path.join(_PKG_DIR, 'static'))
    app.config['JSON_AS_ASCII'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = False
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB
    app.config['CM'] = cm
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.config['PERMANENT_SESSION_LIFETIME'] = 28800  # 8 hours

    # Initialize session secret
    cm.load()
    gui_cfg = cm.config.get("web_gui", {})
    app.secret_key = gui_cfg.get("secret_key") or secrets.token_hex(32)
    # Always set Secure cookie flag (TLS is the default)
    tls_cfg = gui_cfg.get("tls", {})
    app.config['SESSION_COOKIE_SECURE'] = True
    app.jinja_env.globals.update(t=t)

    # ── pygments CSS — generated once at startup ───────────────────────────────
    from src.report.exporters.code_highlighter import get_highlight_css as _ghcss
    from pathlib import Path as _Path
    _pygments_css = _Path(app.static_folder) / "pygments.css"
    if not _pygments_css.exists():
        _pygments_css.write_text(_ghcss(), encoding="utf-8")

    # ── humanize Jinja filters ─────────────────────────────────────────────────
    from src.humanize_ext import human_time_ago as _hta, human_size as _hs, human_number as _hn

    @app.template_filter("human_time_ago")
    def _filter_hta(dt):
        if dt is None:
            return "-"
        return _hta(dt)

    @app.template_filter("human_size")
    def _filter_hs(n):
        return _hs(n) if n is not None else "-"

    @app.template_filter("human_number")
    def _filter_hn(n):
        return _hn(n) if n is not None else "-"

    # ── flask-login setup ──────────────────────────────────────────────────────
    from flask_login import LoginManager, current_user, login_required
    from src.auth_models import AdminUser

    login_manager = LoginManager(app)
    login_manager.login_view = "auth.login_page"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def _load_user(user_id: str):
        admin_name = cm.config.get("web_gui", {}).get("username", "illumio")
        return AdminUser(admin_name) if user_id == admin_name else None

    # ── flask-wtf CSRF setup ───────────────────────────────────────────────────
    from flask_wtf.csrf import CSRFProtect, CSRFError, generate_csrf

    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = 28800  # match GUI session lifetime
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    # Accept both X-CSRFToken (flask-wtf default) and X-CSRF-Token (legacy SPA header)
    app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken", "X-CSRF-Token"]

    csrf = CSRFProtect(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        # /logout is a fetch-driven endpoint (no form), so emit JSON 400 like /api/*
        # rather than redirecting — the SPA can refresh the token and retry.
        if request.path.startswith('/api/') or request.path == '/logout':
            return jsonify({
                "ok": False,
                "code": "csrf_error",
                "error": t("gui_err_csrf_expired"),
                "csrf_token": generate_csrf(),
            }), 400
        return redirect('/login')

    # ── flask-limiter rate limiting ────────────────────────────────────────────
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["300 per minute"],
        storage_uri="memory://",    # single-node deployment
        strategy="fixed-window",
    )

    @app.errorhandler(429)
    def ratelimit_handler(e):
        # Keep the API contract consistent: JSON response
        return jsonify({
            "ok": False,
            "error": "rate_limit_exceeded",
            "description": str(e.description) if hasattr(e, 'description') else "too many requests",
        }), 429

    # ── flask-talisman security headers ───────────────────────────────────────
    from flask_talisman import Talisman

    # CSP: 'unsafe-inline' on script-src AND style-src.
    #
    # Trade-off accepted on the code-review-fixes branch: 40+ dynamically-
    # injected inline `onclick=` handlers across the JS codebase still need
    # to function while the M1 dispatcher migration is incomplete. Per CSP
    # Level 3, inline event handler attributes require 'unsafe-inline'
    # (nonces don't cover them). Mixing 'nonce-...' with 'unsafe-inline'
    # would make browsers IGNORE 'unsafe-inline', so the nonce is dropped
    # from script-src entirely.
    #
    # Compensating controls: CSRF, IP allowlist, escapeHtml on all dynamic
    # HTML insertions (utils.js:63 + integrations.js:7 — both escape ', ",
    # <, >, &).
    #
    # Vulnerability scanners (Mozilla Observatory, securityheaders.com,
    # Nessus, Qualys, OWASP ZAP, CIS benchmarks) WILL flag this — typically
    # Low/Medium. Risk-accepted until the M1 data-action sweep finishes.
    _csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'img-src': ["'self'", "data:"],
        # Fonts are bundled locally (src/static/fonts/); no external font CDN.
        'font-src': "'self'",
        'connect-src': "'self'",
    }

    _talisman = Talisman(
        app,
        force_https=use_https,
        strict_transport_security=use_https,
        strict_transport_security_max_age=31536000 if use_https else 0,
        strict_transport_security_include_subdomains=use_https,
        strict_transport_security_preload=use_https,
        session_cookie_secure=use_https,
        content_security_policy=_csp,
        # No nonce injection: per CSP Level 3, the presence of a nonce in a
        # directive causes browsers to IGNORE 'unsafe-inline' in the same
        # directive. Inline <script nonce="..."> / <style nonce="..."> markers
        # left in templates by csp_nonce() are harmless (unused) under this
        # policy.
        content_security_policy_nonce_in=[],
        frame_options='DENY',
        referrer_policy='strict-origin-when-cross-origin',
        permissions_policy={
            "camera": "()",
            "microphone": "()",
            "geolocation": "()",
            "interest-cohort": "()",
            "browsing-topics": "()",
            "payment": "()",
            "usb": "()",
        },
    )

    # Disable HTTPS redirect during testing so test clients (plain HTTP) work.
    # This is set after Talisman init because tests set app.testing=True after
    # _create_app() returns.
    _orig_force_https = _talisman._force_https

    def _force_https_unless_testing():
        if app.testing:
            return None
        return _orig_force_https()

    # Replace the registered before_request handler in-place so existing
    # registrations remain intact (position in the list is preserved).
    try:
        idx = app.before_request_funcs[None].index(_orig_force_https)
        app.before_request_funcs[None][idx] = _force_https_unless_testing
    except (ValueError, KeyError):
        pass  # Talisman internals changed; fall back to always-on (production safe)

    # ── Auth Blueprint ─────────────────────────────────────────────────────────
    from src.gui.routes.auth import make_auth_blueprint
    app.register_blueprint(make_auth_blueprint(cm, csrf, limiter, login_required))

    # ── Dashboard Blueprint ────────────────────────────────────────────────────
    from src.gui.routes.dashboard import make_dashboard_blueprint
    app.register_blueprint(make_dashboard_blueprint(cm, csrf, limiter, login_required))

    # ── Config Blueprint ───────────────────────────────────────────────────────
    from src.gui.routes.config import make_config_blueprint
    app.register_blueprint(make_config_blueprint(cm, csrf, limiter, login_required))

    # ── Rules Blueprint ────────────────────────────────────────────────────────
    from src.gui.routes.rules import make_rules_blueprint
    app.register_blueprint(make_rules_blueprint(cm, csrf, limiter, login_required))

    # ── Events Blueprint ───────────────────────────────────────────────────────
    from src.gui.routes.events import make_events_blueprint
    app.register_blueprint(make_events_blueprint(cm, csrf, limiter, login_required))

    # ── Reports Blueprint ──────────────────────────────────────────────────────
    from src.gui.routes.reports import make_reports_blueprint
    app.register_blueprint(make_reports_blueprint(cm, csrf, limiter, login_required))

    # ── Actions Blueprint ──────────────────────────────────────────────────────
    from src.gui.routes.actions import make_actions_blueprint
    app.register_blueprint(make_actions_blueprint(cm, csrf, limiter, login_required))

    # ── Rule Scheduler Blueprint ───────────────────────────────────────────────
    from src.gui.routes.rule_scheduler import make_rule_scheduler_blueprint
    app.register_blueprint(make_rule_scheduler_blueprint(cm, login_required))

    # ── Admin Blueprint ────────────────────────────────────────────────────────
    from src.gui.routes.admin import make_admin_blueprint
    app.register_blueprint(make_admin_blueprint(cm, limiter, login_required, persistent_mode))

    @app.errorhandler(_RstDrop)
    def handle_rst_drop(e):
        # Socket is already closed with RST ??return an empty Response object
        # so Flask stops processing without logging an unhandled error
        from flask import Response as _Resp
        return _Resp('', status=200)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        if isinstance(exc, HTTPException):
            return exc
        req_id = str(_uuid.uuid4())[:8]
        logger.error(f"[GUI] Unhandled exception req={req_id}: {_traceback.format_exc()}")
        return jsonify({"ok": False, "error": "Internal server error", "request_id": req_id}), 500

    @app.before_request
    def security_check():
        if request.endpoint == 'static' or request.path.startswith('/static/'):
            return

        # IP Allowlist check ??silently drop with TCP RST (no HTTP response)
        # so port scanners cannot detect an HTTP service on this port
        allowed_ips = cm.config.get("web_gui", {}).get("allowed_ips", [])
        if not _check_ip_allowed(allowed_ips, request.remote_addr):
            logger.warning(f"[GUI] Blocked untrusted IP: {_safe_log(request.remote_addr)}")
            _rst_drop()  # closes socket with RST, raises _RstDrop

        # Auth check (always enforced for all GUI modes)
        # Bypass login routes
        if request.path in ['/login', '/api/login', '/logout', '/api/csrf-token']:
            return
        if not current_user.is_authenticated:
            if request.path.startswith('/api/'):
                return _err(t("gui_err_unauthorized"), 401)
            return redirect('/login')

        # Force password change if flagged
        if current_user.is_authenticated:
            gui_cfg = cm.config.get("web_gui", {})
            if gui_cfg.get("must_change_password") and request.endpoint not in (
                'config.api_security_get', 'config.api_security_post', 'auth.logout', 'auth.api_csrf_token'
            ):
                return jsonify({"ok": False, "error": "must_change_password", "code": 423}), 423

    @app.after_request
    def add_security_headers(response):
        # Security headers (talisman will add CSP/HSTS in Task 7; keep fallbacks here)
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        _tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
        if _tls_cfg.get("enabled"):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        # Isolation headers — safe for same-origin SPA; omit COEP to avoid breaking
        # embedded third-party resources that may not send CORP headers.
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-site'
        # Remove server fingerprint header
        response.headers.pop('Server', None)
        # Prevent browser from caching JS/CSS so code changes take effect immediately
        if request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response


    try:
        from src.siem.web import bp as siem_bp
        app.register_blueprint(siem_bp)
    except Exception:
        pass  # intentional: optional module — siem blueprint absent on slim installs

    try:
        from src.pce_cache.web import bp as cache_bp
        app.register_blueprint(cache_bp)
    except Exception:
        pass  # intentional: optional module — pce_cache blueprint absent on slim installs

    @app.route('/api/daemon/restart', methods=['POST'])
    @limiter.limit("5 per hour")
    @login_required
    def api_daemon_restart():
        import src.gui as _self
        if not _self._GUI_OWNS_DAEMON:
            return jsonify({"ok": False,
                            "error": "Daemon is managed externally; restart via systemctl or your service manager."}), 409
        if _self._DAEMON_RESTART_FN is None:
            return jsonify({"ok": False, "error": "restart hook not installed"}), 500
        try:
            _self._DAEMON_SCHEDULER = _self._DAEMON_RESTART_FN()
            return jsonify({"ok": True}), 200
        except Exception as exc:
            return _err_with_log("daemon_restart", exc)

    return app

# ????????????????????????????????????????????????????????????????????????????????# Launch
# ????????????????????????????????????????????????????????????????????????????????
# Default validity period for self-signed certs. 5 years keeps the cert
# effectively "set and forget" for internal deployments while still giving
# the auto-renew path meaningful runway before expiry.
def _run_server(app, host: str, port: int, ssl_context,
                cert_file: str = "", key_file: str = "") -> None:
    """HTTP and HTTPS both served by cheroot (thread pool, native SSL)."""
    if ssl_context is None:
        _run_http(app, host, port)
    else:
        _run_https(app, host, port, cert_file, key_file)


def _run_http(app, host: str, port: int) -> None:
    from cheroot import wsgi as _cheroot_wsgi
    logger.info("Starting HTTP server via cheroot on {}:{}", host, port)
    server = _cheroot_wsgi.Server((host, port), app, numthreads=10)
    try:
        server.start()
    except OSError as e:
        if "Address already in use" in str(e):
            logger.error("Port {} is already in use. Stop the existing process first (fuser -k {}/tcp) then retry.", port, port)
            print(f"\n  ERROR: Port {port} is already in use. Stop the existing process first, then retry.")
        else:
            raise
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def _run_https(app, host: str, port: int, cert_file: str, key_file: str) -> None:
    """HTTPS via cheroot — production-grade WSGI server with hardened TLS."""
    from cheroot import wsgi as _cheroot_wsgi
    from cheroot.ssl.builtin import BuiltinSSLAdapter as _SSLAdapter

    # Read TLS hardening config
    try:
        from src.config import ConfigManager as _CM
        _tls_cfg = _CM().config.get("web_gui", {}).get("tls", {})
    except Exception:
        _tls_cfg = {}

    ctx = _build_ssl_context(_tls_cfg)
    ctx.load_cert_chain(cert_file, key_file)

    # M3: avoid cheroot's default-context creation by skipping BuiltinSSLAdapter.__init__
    # entirely and supplying the pre-hardened context. The grandparent Adapter.__init__
    # only stores certificate/private_key/chain attributes. The `context` setter wires
    # cheroot's SNI callback into ctx.
    # SSL_SERVER_* WSGI env vars are not consumed anywhere in this codebase
    # (verified by grep over src/ and tests/), so we skip rebuilding _server_env.
    class _HardenedSSLAdapter(_SSLAdapter):
        def __init__(self, certificate, private_key, ctx):  # noqa: D401
            super(_SSLAdapter, self).__init__(certificate, private_key)
            self.context = ctx
            self._server_env = {}

    adapter = _HardenedSSLAdapter(cert_file, key_file, ctx)

    logger.info("Starting HTTPS server via cheroot on {}:{}", host, port)
    server = _cheroot_wsgi.Server((host, port), app, numthreads=10)

    _orig_error_log = server.error_log

    _TLS_NOISE = ("SSLV3_ALERT", "UNEXPECTED_EOF_WHILE_READING")

    def _filtered_error_log(msg='', level=20, traceback=False):
        if not any(k in str(msg) for k in _TLS_NOISE):
            _orig_error_log(msg, level, traceback)

    server.error_log = _filtered_error_log
    server.ssl_adapter = adapter

    try:
        server.start()
    except OSError as e:
        if "Address already in use" in str(e):
            logger.error("Port {} is already in use. Stop the existing process first (fuser -k {}/tcp) then retry.", port, port)
            print(f"\n  ERROR: Port {port} is already in use. Stop the existing process first, then retry.")
        else:
            raise
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def build_app(cm: ConfigManager, persistent_mode: bool = False, use_https: bool = True) -> 'Flask':
    """Public factory: build a configured Flask app bound to the given ConfigManager.

    Pure constructor — does NOT call app.run(). Used by launch_gui and tests.
    """
    return _create_app(cm, persistent_mode=persistent_mode, use_https=use_https)

def launch_gui(cm: ConfigManager = None, host='0.0.0.0', port=5001, persistent_mode=False):
    if not HAS_FLASK:
        print("Flask is not installed. The Web GUI requires Flask.")
        print("Install it with:")
        if FLASK_IMPORT_ERROR:
            print(f"  Import error: {FLASK_IMPORT_ERROR}")
        print("  pip install flask")
        return

    if cm is None:
        cm = ConfigManager()

    from src.module_log import ModuleLog as _ML
    _ML.init(os.path.join(_ROOT_DIR, 'logs'))

    # TLS / HTTPS configuration — must be determined before build_app so that
    # Talisman's force_https and session_cookie_secure match the actual transport.
    cm.load()
    tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
    use_https = bool(tls_cfg.get("enabled"))

    app = build_app(cm, persistent_mode=persistent_mode, use_https=use_https)
    try:
        from src.siem.preview import emit_preview_warning
        emit_preview_warning(cm, context="web_gui_startup")
    except Exception:
        pass  # intentional fallback: preview warning must not block GUI startup
    ssl_context = None
    cert_file = ""
    key_file = ""

    if tls_cfg.get("enabled"):
        import ssl
        cert_file = tls_cfg.get("cert_file", "").strip()
        key_file = tls_cfg.get("key_file", "").strip()

        if cert_file and key_file:
            # User-provided certificate
            if not os.path.exists(cert_file):
                print(f"  ERROR: TLS cert_file not found: {cert_file}")
                return
            if not os.path.exists(key_file):
                print(f"  ERROR: TLS key_file not found: {key_file}")
                return
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(cert_file, key_file)
            print(f"  TLS: Using certificate {cert_file}")
        elif tls_cfg.get("self_signed"):
            # Auto-generate self-signed certificate
            cert_dir = os.path.join(_ROOT_DIR, "config", "tls")
            try:
                # Auto-renew on startup when opted in and the existing cert
                # is within `auto_renew_days` (default 30) of expiry. No-op
                # if the cert is still comfortably valid.
                if tls_cfg.get("auto_renew", True):
                    threshold = int(tls_cfg.get("auto_renew_days", 30))
                    renewed, days_after = _maybe_auto_renew_self_signed(
                        cert_dir, threshold_days=threshold
                    )
                    if renewed:
                        print(f"  TLS: Self-signed cert auto-renewed ({days_after} days remaining).")
                cert_file, key_file = _generate_self_signed_cert(
                    cert_dir,
                    days=int(tls_cfg.get("validity_days", _SELF_SIGNED_VALIDITY_DAYS)),
                    key_algorithm=tls_cfg.get("key_algorithm", "ecdsa-p256"),
                )
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(cert_file, key_file)
                days_left = _cert_days_remaining(cert_file)
                if days_left is not None:
                    print(f"  TLS: Using self-signed certificate ({days_left} days remaining)")
                else:
                    print(f"  TLS: Using self-signed certificate")
            except RuntimeError as e:
                print(f"  ERROR: {e}")
                return
        else:
            print("  ERROR: TLS enabled but no cert_file/key_file and self_signed=false")
            return

    scheme = "https" if ssl_context else "http"
    print(f"\n  Illumio PCE Ops — Web GUI")
    print(f"  Open in browser: {scheme}://127.0.0.1:{port}")
    if ssl_context and tls_cfg.get("self_signed"):
        print(f"  Note: Self-signed certificate — browser will show a security warning.")
    if persistent_mode:
        print(f"  Running in persistent mode (Press Ctrl+C to stop the entire daemon).")
    else:
        print(f"  Press Ctrl+C to stop.\n")

    if not persistent_mode:
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f'{scheme}://127.0.0.1:{port}')).start()

    _run_server(app, host, port, ssl_context, cert_file, key_file)
