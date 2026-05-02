"""
Illumio PCE Ops ??Flask Web GUI.
Optional dependency: pip install flask

Features full parity with CLI:
  Dashboard, Rules (add event/traffic/bandwidth, delete), Settings, Actions (Run, Debug, Test Alert, Best Practices).
"""
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

def _create_app(cm: ConfigManager, persistent_mode: bool = False) -> 'Flask':
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
        force_https=True,
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        strict_transport_security_include_subdomains=True,
        strict_transport_security_preload=True,
        session_cookie_secure=True,
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

    @app.route('/api/init_quarantine', methods=['POST'])
    def api_init_quarantine():
        """Ensure Quarantine labels exist on the PCE upon loading the new UI module."""
        cm.load()
        from src.api_client import ApiClient
        api = ApiClient(cm)
        api.check_and_create_quarantine_labels()
        return jsonify({"ok": True})

    # ??? API: Reports ??????????????????????????????????????????????????????

    @app.route('/api/reports', methods=['GET'])
    def api_list_reports():
        cm.load()
        reports_dir = _resolve_reports_dir(cm)

        if not os.path.exists(reports_dir):
            return jsonify({"ok": True, "reports": []})
        
        reports = []
        for f in os.listdir(reports_dir):
            if f.endswith('.html') or f.endswith('.zip'):
                report_path = os.path.join(reports_dir, f)
                stat = os.stat(report_path)
                metadata = {}
                metadata_path = report_path + ".metadata.json"
                if os.path.isfile(metadata_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as mf:
                            metadata = json.load(mf) or {}
                    except Exception:
                        metadata = {}
                reports.append({
                    "filename": f,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size,
                    "report_type": metadata.get("report_type", ""),
                    "summary": metadata.get("summary", ""),
                    "attack_summary": metadata.get("attack_summary", {}),
                    "attack_summary_counts": metadata.get("attack_summary_counts", {}),
                    "execution_stats": metadata.get("execution_stats", {}),
                    "reused_rule_details": metadata.get("reused_rule_details", []),
                    "pending_rule_details": metadata.get("pending_rule_details", []),
                    "failed_rule_details": metadata.get("failed_rule_details", []),
                })
        
        reports.sort(key=lambda x: x['mtime'], reverse=True)
        return jsonify({"ok": True, "reports": reports})

    @app.route('/api/reports/<path:filename>', methods=['DELETE'])
    def api_delete_report(filename):
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        # Prevent path traversal
        target = os.path.realpath(os.path.join(reports_dir, filename))
        if not target.startswith(os.path.realpath(reports_dir) + os.sep):
            return jsonify({"ok": False, "error": t("gui_invalid_filename")}), 400
        if not os.path.isfile(target):
            return jsonify({"ok": False, "error": t("gui_file_not_found")}), 404
        os.remove(target)
        metadata_path = target + ".metadata.json"
        if os.path.isfile(metadata_path):
            try:
                os.remove(metadata_path)
            except OSError:
                pass  # intentional fallback: metadata file deletion is best-effort
        return jsonify({"ok": True})

    @app.route('/api/reports/bulk-delete', methods=['POST'])
    def api_bulk_delete_reports():
        d = request.json or {}
        filenames = d.get('filenames', [])
        if not filenames:
            return jsonify({"ok": False, "error": "No filenames provided"}), 400
            
        cm.load()
        reports_dir = _resolve_reports_dir(cm)

        resolved_reports_dir = os.path.realpath(reports_dir)
        
        success_count = 0
        errors = []
        
        for filename in filenames:
            try:
                target = os.path.realpath(os.path.join(reports_dir, filename))
                if not target.startswith(resolved_reports_dir + os.sep):
                    errors.append(f"{filename}: {t('gui_invalid_filename')}")
                    continue
                if not os.path.isfile(target):
                    errors.append(f"{filename}: {t('gui_file_not_found')}")
                    continue
                os.remove(target)
                metadata_path = target + ".metadata.json"
                if os.path.isfile(metadata_path):
                    try:
                        os.remove(metadata_path)
                    except OSError:
                        pass  # intentional fallback: metadata file deletion is best-effort in bulk delete
                success_count += 1
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")
        
        return jsonify({"ok": True, "deleted": success_count, "errors": errors})

    @app.route('/reports/<path:filename>', methods=['GET'])
    def api_serve_report(filename):
        if '..' in filename or filename.startswith('/'):
            return jsonify({"ok": False, "error": "Invalid path"}), 403
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        # Path traversal protection: ensure resolved path stays within reports_dir
        target = os.path.realpath(os.path.join(reports_dir, filename))
        if not target.startswith(os.path.realpath(reports_dir) + os.sep):
            return jsonify({"ok": False, "error": "Invalid path"}), 403
        as_download = request.args.get('download') == '1'
        return send_from_directory(reports_dir, filename, as_attachment=as_download)

    @app.route('/api/reports/generate', methods=['POST'])
    @limiter.limit("30 per hour")
    def api_generate_report():
        if request.is_json:
            d = request.json or {}
        else:
            d = request.form.to_dict()
            
        try:
            from src.report.report_generator import ReportGenerator
            from src.api_client import ApiClient
            from src.reporter import Reporter
            import tempfile
            _rlog = None
            try:
                from src.module_log import ModuleLog as _ML
                _rlog = _ML.get("reports")
                _rlog.separator(f"Traffic Report {datetime.datetime.now().strftime('%H:%M:%S')}")
                _rlog.info(f"source={d.get('source')} format={d.get('format')} range={d.get('start_date')}~{d.get('end_date')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; report generation must not fail if logging setup fails

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            reporter = Reporter(cm)

            gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)

            source = d.get('source', 'api')
            _VALID_PROFILES = ("security_risk", "network_inventory")
            traffic_report_profile = d.get('traffic_report_profile', 'security_risk')
            if traffic_report_profile not in _VALID_PROFILES:
                traffic_report_profile = 'security_risk'

            lang = d.get('lang', 'en')
            if lang not in ('en', 'zh_TW'):
                lang = 'en'

            if source == 'csv':
                if 'file' not in request.files:
                    return jsonify({"ok": False, "error": t("gui_err_no_csv")})
                csv_file = request.files['file']
                if csv_file.filename == '':
                    return jsonify({"ok": False, "error": t("gui_err_empty_csv")})
                if csv_file.mimetype not in {
                    'text/csv', 'application/vnd.ms-excel',
                    'text/plain', 'application/octet-stream',
                }:
                    return jsonify({"ok": False, "error": "Invalid file type"}), 415

                import uuid as _uuid
                safe_filename = secure_filename(csv_file.filename) or 'upload.csv'
                temp_path = os.path.join(tempfile.gettempdir(), f"{_uuid.uuid4().hex}_{safe_filename}")
                csv_file.save(temp_path)
                try:
                    result = gen.generate_from_csv(temp_path, traffic_report_profile=traffic_report_profile, lang=lang)
                finally:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass  # intentional fallback: temp file cleanup is best-effort
            else:
                start_date = d.get('start_date')
                end_date = d.get('end_date')

                # Extract optional traffic filters (API source only)
                report_filters = None
                raw_filters = d.get('filters') or {}
                if raw_filters:
                    report_filters = {
                        'policy_decisions': raw_filters.get('policy_decisions') or None,
                        'src_labels': [s for s in (raw_filters.get('src_labels') or []) if s],
                        'dst_labels': [s for s in (raw_filters.get('dst_labels') or []) if s],
                        'src_ip': (raw_filters.get('src_ip') or '').strip(),
                        'dst_ip': (raw_filters.get('dst_ip') or '').strip(),
                        'port': (raw_filters.get('port') or '').strip(),
                        'proto': raw_filters.get('proto'),
                        'ex_src_labels': [s for s in (raw_filters.get('ex_src_labels') or []) if s],
                        'ex_dst_labels': [s for s in (raw_filters.get('ex_dst_labels') or []) if s],
                        'ex_src_ip': (raw_filters.get('ex_src_ip') or '').strip(),
                        'ex_dst_ip': (raw_filters.get('ex_dst_ip') or '').strip(),
                        'ex_port': (raw_filters.get('ex_port') or '').strip(),
                    }
                    # Discard if all values are empty/falsy
                    if not any(v for v in report_filters.values() if v):
                        report_filters = None

                result = gen.generate_from_api(start_date=start_date, end_date=end_date, filters=report_filters, traffic_report_profile=traffic_report_profile, lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_traffic_data")})

            fmt = d.get('format', 'all')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'all'
            output_dir = _resolve_reports_dir(cm)

            paths = gen.export(result, fmt=fmt, output_dir=output_dir, send_email=str(d.get('send_email', '')).lower() == 'true', reporter=reporter, traffic_report_profile=traffic_report_profile, lang=lang)
            
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _rlog:
                    _rlog.info(f"Completed: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            try:
                if _rlog:
                    _rlog.error(f"Traffic report failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_traffic_generate", e)

    @app.route('/api/audit_report/generate', methods=['POST'])
    def api_generate_audit_report():
        d = request.json or {}
        _arlog = None
        try:
            from src.report.audit_generator import AuditGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _arlog = _ML.get("reports")
                _arlog.separator(f"Audit Report {datetime.datetime.now().strftime('%H:%M:%S')}")
                _arlog.info(f"range={d.get('start_date')}~{d.get('end_date')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; audit report must not fail if logging setup fails

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            gen = AuditGenerator(cm, api_client=api, config_dir=config_dir)

            start_date = d.get('start_date')
            end_date = d.get('end_date')
            lang = d.get('lang', 'en')
            if lang not in ('en', 'zh_TW'):
                lang = 'en'

            result = gen.generate_from_api(start_date, end_date, lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_audit_data")})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            _write_audit_dashboard_summary(output_dir, result)
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _arlog:
                    _arlog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            try:
                if _arlog:
                    _arlog.error(f"Audit report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_audit_generate", e)

    # ??? API: VEN Status Report ????????????????????????????????????????????
    @app.route('/api/ven_status_report/generate', methods=['POST'])
    def api_generate_ven_status_report():
        d = request.json or {}
        _vrlog = None
        try:
            from src.report.ven_status_generator import VenStatusGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _vrlog = _ML.get("reports")
                _vrlog.separator(f"VEN Status Report {datetime.datetime.now().strftime('%H:%M:%S')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; VEN status report must not fail if logging setup fails

            cm.load()
            api = ApiClient(cm)
            gen = VenStatusGenerator(cm, api_client=api)

            lang = d.get('lang', 'en')
            if lang not in ('en', 'zh_TW'):
                lang = 'en'

            result = gen.generate(lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_ven_data")})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            filenames = [os.path.basename(p) for p in paths]
            kpis = result.module_results.get('kpis', [])
            try:
                if _vrlog:
                    _vrlog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count, "kpis": kpis})
        except Exception as e:
            try:
                if _vrlog:
                    _vrlog.error(f"VEN status report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_ven_status_generate", e)

    # ??? API: Policy Usage Report ??????????????????????????????????????????
    @app.route('/api/policy_usage_report/generate', methods=['POST'])
    def api_generate_policy_usage_report():
        d = request.json or {}
        _pulog = None
        try:
            from src.report.policy_usage_generator import PolicyUsageGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _pulog = _ML.get("reports")
                _pulog.separator(f"Policy Usage Report {datetime.datetime.now().strftime('%H:%M:%S')}")
                _pulog.info(f"range={d.get('start_date')}~{d.get('end_date')}")
            except Exception:
                pass  # intentional fallback: ModuleLog is optional; policy usage report must not fail if logging setup fails

            cm.load()
            api = ApiClient(cm)
            config_dir = _resolve_config_dir()
            gen = PolicyUsageGenerator(cm, api_client=api, config_dir=config_dir)

            start_date = d.get('start_date')
            end_date   = d.get('end_date')
            lang = d.get('lang', 'en')
            if lang not in ('en', 'zh_TW'):
                lang = 'en'

            result = gen.generate_from_api(start_date=start_date, end_date=end_date, lang=lang)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_pu_data")})

            output_dir = _resolve_reports_dir(cm)
            fmt = d.get('format', 'html')
            fmt = fmt if fmt in _ALLOWED_REPORT_FORMATS else 'html'
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, lang=lang)
            _write_policy_usage_dashboard_summary(output_dir, result)
            filenames = [os.path.basename(p) for p in paths]
            mod00 = result.module_results.get('mod00', {})
            kpis = mod00.get('kpis', [])
            execution_stats = getattr(result, "execution_stats", {}) or mod00.get("execution_stats", {})
            execution_notes = mod00.get("execution_notes", [])

            try:
                if _pulog:
                    _pulog.info(f"Saved: {filenames}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return jsonify({"ok": True, "files": filenames,
                            "record_count": result.record_count, "kpis": kpis,
                            "execution_stats": execution_stats, "execution_notes": execution_notes,
                            "reused_rule_details": execution_stats.get("reused_rule_details", []),
                            "pending_rule_details": execution_stats.get("pending_rule_details", []),
                            "failed_rule_details": execution_stats.get("failed_rule_details", [])})
        except Exception as e:
            try:
                if _pulog:
                    _pulog.error(f"Policy usage report generation failed: {e}")
            except Exception:
                pass  # intentional fallback: ModuleLog write is best-effort
            return _err_with_log("report_policy_usage_generate", e)

    # ??? API: Report Schedules ?????????????????????????????????????????????

    @app.route('/api/report-schedules', methods=['GET'])
    def api_list_report_schedules():
        cm.load()
        schedules = cm.get_report_schedules()
        # Enrich with last-run state from state.json
        state_file = _resolve_state_file()
        states = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    states = json.load(f).get("report_schedule_states", {})
            except Exception:
                pass  # intentional fallback: state enrichment is best-effort; schedules still listed without last-run state
        result = []
        for s in schedules:
            sid = str(s.get("id", ""))
            state = states.get(sid, {})
            entry = dict(s)
            entry["last_run"] = state.get("last_run")
            entry["last_status"] = state.get("status")
            entry["last_error"] = state.get("error", "")
            result.append(entry)
        return jsonify({"ok": True, "schedules": result})

    @app.route('/api/report-schedules', methods=['POST'])
    def api_create_report_schedule():
        d = request.json or {}
        try:
            cm.load()
            # Preserve optional traffic filters if provided
            raw_filters = d.get('filters') or {}
            if raw_filters:
                d['filters'] = raw_filters
            elif 'filters' in d:
                del d['filters']
            sched = cm.add_report_schedule(d)
            return jsonify({"ok": True, "schedule": sched})
        except Exception as e:
            return _err_with_log("report_schedule_create", e, 400)

    @app.route('/api/report-schedules/<int:schedule_id>', methods=['PUT'])
    def api_update_report_schedule(schedule_id):
        d = request.json or {}
        try:
            cm.load()
            ok = cm.update_report_schedule(schedule_id, d)
            if not ok:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found")}), 404
            return jsonify({"ok": True})
        except Exception as e:
            return _err_with_log("report_schedule_update", e, 400)

    @app.route('/api/report-schedules/<int:schedule_id>', methods=['DELETE'])
    def api_delete_report_schedule(schedule_id):
        try:
            cm.load()
            ok = cm.remove_report_schedule(schedule_id)
            if not ok:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found")}), 404
            return jsonify({"ok": True})
        except Exception as e:
            return _err_with_log("report_schedule_delete", e, 400)

    @app.route('/api/report-schedules/<int:schedule_id>/toggle', methods=['POST'])
    def api_toggle_report_schedule(schedule_id):
        try:
            cm.load()
            schedules = cm.get_report_schedules()
            sched = next((s for s in schedules if s.get("id") == schedule_id), None)
            if not sched:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found")}), 404
            new_enabled = not sched.get("enabled", False)
            cm.update_report_schedule(schedule_id, {"enabled": new_enabled})
            return jsonify({"ok": True, "enabled": new_enabled})
        except Exception as e:
            return _err_with_log("report_schedule_toggle", e, 400)

    @app.route('/api/report-schedules/<int:schedule_id>/run', methods=['POST'])
    def api_run_report_schedule(schedule_id):
        try:
            cm.load()
            schedules = cm.get_report_schedules()
            sched = next((s for s in schedules if s.get("id") == schedule_id), None)
            if not sched:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found")}), 404

            from src.report_scheduler import ReportScheduler
            from src.reporter import Reporter
            reporter = Reporter(cm)
            scheduler = ReportScheduler(cm, reporter)
            scheduler._state_file = _resolve_state_file()
            now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
            scheduler._save_state(schedule_id, now_str, "running")

            def _run():
                try:
                    scheduler.run_schedule(sched)
                    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    scheduler._save_state(schedule_id, now_str, "success")
                except Exception as e:
                    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    scheduler._save_state(schedule_id, now_str, "failed", str(e))
                    logger.error(f"GUI-triggered schedule {schedule_id} failed: {e}", exc_info=True)

            t_thread = threading.Thread(target=_run, daemon=True)
            t_thread.start()
            return jsonify({"ok": True, "message": t("gui_msg_sched_started")})
        except Exception as e:
            return _err_with_log("report_schedule_run", e, 400)

    @app.route('/api/report-schedules/<int:schedule_id>/history', methods=['GET'])
    def api_report_schedule_history(schedule_id):
        state_file = _resolve_state_file()
        try:
            if not os.path.exists(state_file):
                return jsonify({"ok": True, "history": []})
            with open(state_file, "r", encoding="utf-8") as f:
                states = json.load(f).get("report_schedule_states", {})
            entry = states.get(str(schedule_id), {})
            return jsonify({"ok": True, "history": [entry] if entry else []})
        except Exception as e:
            return _err_with_log("report_schedule_history", e, 400)

    # ??? API: Traffic & Quarantine ?????????????????????????????????????????
    @app.route('/api/quarantine/search', methods=['POST'])
    def api_quarantine_search():
        d = request.json or {}
        try:
            from src.api_client import ApiClient
            from src.analyzer import Analyzer
            from src.reporter import Reporter
            import datetime

            api = ApiClient(cm)
            base_ana = Analyzer(cm, api, Reporter(cm))

            mins = int(d.get("mins", 30))
            now = datetime.datetime.now(datetime.timezone.utc)
            start_time = (now - datetime.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            # policy_decision now accepts string values: "blocked", "potentially_blocked", "allowed", or "-1"/""=all
            pd_val = str(d.get("policy_decision", "-1")).strip()
            if pd_val == "blocked": pds = ["blocked"]
            elif pd_val == "potentially_blocked": pds = ["potentially_blocked"]
            elif pd_val == "allowed": pds = ["allowed"]
            # legacy integer values kept for backwards compat
            elif pd_val == "2": pds = ["blocked"]
            elif pd_val == "1": pds = ["potentially_blocked"]
            elif pd_val == "0": pds = ["allowed"]
            else: pds = ["blocked", "potentially_blocked", "allowed"]

            # Map the inbound payload to the analyzer's query
            params = {
                "start_time": start_time,
                "end_time": end_time,
                "policy_decisions": pds,
                "draft_policy_decision": d.get("draft_policy_decision", ""),
                "sort_by": d.get("sort_by", "bandwidth"),
                "search": d.get("search", ""),
                "src_label": d.get("src_label", ""),
                "src_ip_in": d.get("src_ip_in", ""),
                "dst_label": d.get("dst_label", ""),
                "dst_ip_in": d.get("dst_ip_in", ""),
                "ex_src_label": d.get("ex_src_label", ""),
                "ex_src_ip": d.get("ex_src_ip", ""),
                "ex_dst_label": d.get("ex_dst_label", ""),
                "ex_dst_ip": d.get("ex_dst_ip", ""),
                "port": d.get("port", ""),
                "ex_port": d.get("ex_port", ""),
                "proto": d.get("proto", ""),
                "any_label": d.get("any_label", ""),
                "any_ip": d.get("any_ip", ""),
                "ex_any_label": d.get("ex_any_label", ""),
                "ex_any_ip": d.get("ex_any_ip", ""),
            }
            results = base_ana.query_flows(params)
            
            for r in results:
                flow_pd = r.get("policy_decision", "")
                if flow_pd == "allowed": r["pd"] = 0
                elif flow_pd == "potentially_blocked": r["pd"] = 1
                else: r["pd"] = 2
                
            return jsonify({"ok": True, "data": results})
        except Exception as e:
            return _err_with_log("quarantine_search", e)

    @app.route('/api/workloads', methods=['GET', 'POST'])
    def api_search_workloads():
        if request.method == 'POST':
            d = request.json or {}
        else:
            d = request.args.to_dict()
        try:
            from src.api_client import ApiClient
            import ipaddress
            api = ApiClient(cm)
            
            # API query parameters mapping
            params = {}
            if "name" in d and d["name"]: params["name"] = d["name"]
            if "hostname" in d and d["hostname"]: params["hostname"] = d["hostname"]
            
            ip_query = d.get("ip_address", "").strip()
            local_ip_filter = False
            target_networks = []
            
            if ip_query:
                if "," in ip_query or "/" in ip_query:
                    local_ip_filter = True
                    parts = [p.strip() for p in ip_query.split(",") if p.strip()]
                    for p in parts:
                        try:
                            if "/" in p:
                                target_networks.append(ipaddress.ip_network(p, strict=False))
                            else:
                                target_networks.append(ipaddress.ip_address(p))
                        except ValueError:
                            pass
                else:
                    params["ip_address"] = ip_query

            if "max_results" in d: 
                params["max_results"] = d["max_results"]
            else: 
                params["max_results"] = 100000 if local_ip_filter else 500

            workloads = api.search_workloads(params)
            
            if local_ip_filter and target_networks:
                filtered_workloads = []
                for wl in workloads:
                    interfaces = wl.get("interfaces", [])
                    matched = False
                    for iface in interfaces:
                        ip_str = iface.get("address")
                        if ip_str:
                            try:
                                ip_obj = ipaddress.ip_address(ip_str)
                                for target in target_networks:
                                    if isinstance(target, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
                                        if ip_obj in target:
                                            matched = True
                                            break
                                    else:
                                        if ip_obj == target:
                                            matched = True
                                            break
                            except ValueError:
                                pass
                        if matched:
                            break
                    if matched:
                        filtered_workloads.append(wl)
                workloads = filtered_workloads

            return jsonify({"ok": True, "data": workloads})
        except Exception as e:
            return _err_with_log("workloads_search", e)

    @app.route('/api/quarantine/apply', methods=['POST'])
    def api_quarantine_apply():
        d = request.json or {}
        href = d.get('href')
        level = d.get('level')  # Mild, Moderate, Severe
        try:
            if not _is_workload_href(href):
                return jsonify({"ok": False, "error": t("gui_q_invalid_target")})
            from src.api_client import ApiClient
            api = ApiClient(cm)
            
            # 1. Fetch labels to get target Href
            q_hrefs = api.check_and_create_quarantine_labels()
            target_label_href = q_hrefs.get(level)
            if not target_label_href:
                return jsonify({"ok": False, "error": t("gui_label_fetch_failed", level=level)})

            # 2. Fetch Workload's current labels
            wl = api.get_workload(href)
            if not wl:
                return jsonify({"ok": False, "error": t("gui_workload_not_found")})

            # 3. Filter out existing Quarantine labels and append the new one
            current_labels = wl.get("labels", [])
            new_labels = [{"href": l.get("href")} for l in current_labels if l.get("href") not in q_hrefs.values()]
            new_labels.append({"href": target_label_href})

            # 4. Commit
            success = api.update_workload_labels(href, new_labels)
            if success:
                return jsonify({"ok": True, "level": level})
            else:
                return jsonify({"ok": False, "error": t("gui_api_update_failed")})
        except Exception as e:
            return _err_with_log("quarantine_apply", e)

    @app.route('/api/quarantine/bulk_apply', methods=['POST'])
    def api_quarantine_bulk_apply():
        d = request.json or {}
        raw_hrefs = d.get('hrefs', [])
        hrefs = _normalize_quarantine_hrefs(raw_hrefs)
        level = d.get('level')
        try:
            if not hrefs:
                return jsonify({"ok": False, "error": t("gui_q_no_targets")})
            from src.api_client import ApiClient
            api = ApiClient(cm)
            q_hrefs = api.check_and_create_quarantine_labels()
            target_label_href = q_hrefs.get(level)

            invalid_count = sum(1 for h in (raw_hrefs or []) if str(h or "").strip() and not _is_workload_href(h))
            results = {"success": 0, "failed": [], "skipped_invalid": invalid_count}
            import concurrent.futures

            def process_wl(href):
                if not _is_workload_href(href):
                    return href, False
                wl = api.get_workload(href)
                if not wl: return href, False
                current_labels = wl.get("labels", [])
                new_labels = [{"href": l.get("href")} for l in current_labels if l.get("href") not in q_hrefs.values()]
                new_labels.append({"href": target_label_href})
                return href, api.update_workload_labels(href, new_labels)

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futures = {ex.submit(process_wl, h): h for h in hrefs}
                for f in concurrent.futures.as_completed(futures):
                    h, ok = f.result()
                    if ok:
                        results["success"] = int(results["success"]) + 1
                    else:
                        failed_list = results["failed"]
                        if isinstance(failed_list, list):
                            failed_list.append(h)

            return jsonify({"ok": True, "results": results})
        except Exception as e:
            return _err_with_log("quarantine_bulk_apply", e)

    # ??? API: Actions ?????????????????????????????????????????????????????
    @app.route('/api/actions/run', methods=['POST'])
    def api_run_once():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Manually triggered monitoring analysis")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        from src.api_client import ApiClient
        from src.reporter import Reporter
        from src.analyzer import Analyzer
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep)
        ana.run_analysis()
        rep.send_alerts()
        return jsonify({"ok": True, "output": t("gui_action_run_completed")})

    @app.route('/api/actions/debug', methods=['POST'])
    def api_debug():
        d = request.json or {}
        mins = int(d.get('mins', 30))
        pd_sel = int(d.get('pd_sel', 3))
        from src.api_client import ApiClient
        from src.reporter import Reporter
        from src.analyzer import Analyzer
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep)
        buf = io.StringIO()
        with redirect_stdout(buf):
            ana.run_debug_mode(mins=mins, pd_sel=pd_sel, interactive=False)
        return jsonify({"ok": True, "output": _strip_ansi(buf.getvalue()).strip() or "Debug mode execution completed."})

    @app.route('/api/actions/test-alert', methods=['POST'])
    def api_test_alert():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Manually triggered test alert")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        data = request.json or {}
        channel = str(data.get("channel", "") or "").strip()
        channels = [channel] if channel else None
        if channel and channel not in PLUGIN_METADATA:
            return _err(f"Unknown alert channel: {channel}", 400)

        from src.reporter import Reporter
        results = Reporter(cm).send_alerts(force_test=True, channels=channels)
        if channel and not results:
            return _err(f"Channel {channel} is not active or produced no result.", 400)
        status_text = ", ".join(
            f"{item.get('channel', 'channel')}={item.get('status', 'unknown')}"
            for item in results
        ) or "no channels dispatched"
        return jsonify({
            "ok": True,
            "output": f"Test alerts sent: {status_text}",
            "results": results,
        })

    @app.route('/api/actions/best-practices', methods=['POST'])
    def api_best_practices():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Load best practice rules")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        data = request.json or {}
        mode = str(data.get("mode", "append_missing") or "append_missing")
        result = cm.apply_best_practices(mode=mode)
        output = t(
            'best_practice_loaded_summary',
            default='Best practices applied: mode={mode}, added={added}, replaced={replaced}, skipped={skipped}, total={total}.',
            mode=result["mode"],
            added=result["added_count"],
            replaced=result["replaced_count"],
            skipped=result["skipped_count"],
            total=result["total_rules"],
        )
        return jsonify({"ok": True, "output": output, "summary": result})

    @app.route('/api/actions/test-connection', methods=['POST'])
    def api_test_conn():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Testing PCE connection")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        try:
            from src.api_client import ApiClient
            api = ApiClient(cm)
            status, body = api.check_health()
            body_text = str(body)
            clean_body = _strip_ansi(body_text)
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("actions").info(f"Connection result: status={status}")
            except Exception:
                pass  # intentional: audit-log best-effort, must not block primary action
            return jsonify({"ok": status == 200, "status": status, "body": clean_body[:500]})
        except Exception as e:
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("actions").error(f"Connection failed: {e}")
            except Exception:
                pass  # intentional: audit-log best-effort, must not block primary action
            return _err_with_log("pce_test_connection", e)

    @app.route('/api/shutdown', methods=['POST'])
    @limiter.limit("5 per hour")
    def api_shutdown():
        if persistent_mode:
            return jsonify({"ok": False, "error": "Shutdown not allowed in persistent mode"}), 403

        def _delayed_exit():
            import time as _t
            _t.sleep(0.5)  # Let the response flush to the client
            import signal as _signal
            # SIGINT (not SIGTERM): cheroot's _run_http catches KeyboardInterrupt
            # and runs server.stop() in finally, allowing atexit hooks (sqlite WAL
            # checkpoint, APScheduler.shutdown) to run. SIGTERM would skip atexit
            # because no SIGTERM handler is installed in the --gui startup paths
            # where this endpoint is reachable.
            os.kill(os.getpid(), _signal.SIGINT)

        threading.Thread(target=_delayed_exit, daemon=True).start()
        return jsonify({"ok": True})

    # ??? Rule Scheduler API ????????????????????????????????????????????????

    def _get_rs_components():
        """Lazy-init Rule Scheduler components."""
        from src.rule_scheduler import ScheduleDB, ScheduleEngine
        from src.api_client import ApiClient
        db_path = os.path.join(_resolve_config_dir(), "rule_schedules.json")
        db = ScheduleDB(db_path)
        db.load()
        api = ApiClient(cm)
        engine = ScheduleEngine(db, api)
        return db, api, engine

    @app.route('/api/rule_scheduler/status')
    def rs_status():
        rs_cfg = cm.config.get("rule_scheduler", {})
        from src.rule_scheduler import ScheduleDB
        db = ScheduleDB(os.path.join(_resolve_config_dir(), "rule_schedules.json"))
        db.load()
        return jsonify({
            "check_interval_seconds": rs_cfg.get("check_interval_seconds", 300),
            "schedule_count": len(db.get_all())
        })

    @app.route('/api/rule_scheduler/rulesets')
    def rs_rulesets():
        db, api, _ = _get_rs_components()
        q = request.args.get('q', '').strip()
        page = int(request.args.get('page', 1))
        size = int(request.args.get('size', 50))
        try:
            api.update_label_cache(silent=True)
        except Exception as _e:
            logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up

        try:
            if q:
                if q.isdigit():
                    rs = api.get_ruleset_by_id(q)
                    all_rs = [rs] if rs else api.search_rulesets(q)
                else:
                    all_rs = api.search_rulesets(q)
            else:
                all_rs = api.get_all_rulesets()
        except Exception as e:
            return jsonify({"items": [], "total": 0, "page": page, "size": size,
                            "error": f"PCE API error: {e}"}), 200

        total = len(all_rs)
        start = (page - 1) * size
        page_items = all_rs[start:start + size]

        results = []
        for rs in page_items:
            stype = db.get_schedule_type(rs)
            ut = rs.get('update_type')
            all_rules_count = (len(rs.get('rules', [])) + len(rs.get('sec_rules', [])) +
                               len(rs.get('deny_rules', [])))
            results.append({
                "href": rs['href'],
                "id": _extract_id_href(rs['href']),
                "name": rs.get('name', ''),
                "enabled": rs.get('enabled', False),
                "rules_count": all_rules_count,
                "schedule_type": stype,
                "provision_state": "DRAFT" if ut else "ACTIVE"
            })
        return jsonify({"items": results, "total": total, "page": page, "size": size})

    @app.route('/api/rule_scheduler/rules/search')
    def rs_rules_search():
        db, api, _ = _get_rs_components()
        q = request.args.get('q', '').strip()
        scope = request.args.get('scope', 'desc')  # 'id' or 'desc'
        if not q:
            return jsonify({"items": []})
        try:
            api.update_label_cache(silent=True)
        except Exception as _e:
            logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up
        all_rs = api.get_all_rulesets()
        results = []
        q_lower = q.lower()
        for rs in all_rs:
            rs_id = _extract_id_href(rs['href'])
            rs_name = rs.get('name', '')
            typed_rules = []
            for r in rs.get('sec_rules', []) + rs.get('rules', []):
                typed_rules.append((r, 'allow'))
            for r in rs.get('deny_rules', []):
                rule_type = 'override_deny' if r.get('override') else 'deny'
                typed_rules.append((r, rule_type))
            # Assign no per type section
            no_counters = {'allow': 0, 'deny': 0, 'override_deny': 0}
            for r, rule_type in typed_rules:
                no_counters[rule_type] += 1
                rule_id = _extract_id_href(r['href'])
                desc = r.get('description', '') or ''
                matched = (scope == 'id' and q == rule_id) or \
                          (scope == 'desc' and q_lower in desc.lower())
                if matched:
                    dest_field = r.get('destinations', r.get('consumers', []))
                    results.append({
                        "rs_id": rs_id,
                        "rs_name": rs_name,
                        "rule_id": rule_id,
                        "rule_no": no_counters[rule_type],
                        "rule_type": rule_type,
                        "enabled": r.get('enabled', False),
                        "description": desc,
                        "source": api.resolve_actor_str(dest_field),
                        "dest": api.resolve_actor_str(r.get('providers', [])),
                        "service": api.resolve_service_str(r.get('ingress_services', [])),
                    })
        return jsonify({"items": results})

    @app.route('/api/rule_scheduler/rulesets/<rs_id>')
    def rs_ruleset_detail(rs_id):
        db, api, _ = _get_rs_components()
        try:
            api.update_label_cache(silent=True)
        except Exception as _e:
            logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up
        try:
            rs = api.get_ruleset_by_id(rs_id)
        except Exception as e:
            return _err(f"PCE API error: {e}", 502)
        if not rs:
            return _err("Not found", 404)

        ut = rs.get('update_type')
        rs_row = {
            "href": rs['href'],
            "id": _extract_id_href(rs['href']),
            "name": rs.get('name', ''),
            "enabled": rs.get('enabled', False),
            "provision_state": "DRAFT" if ut else "ACTIVE",
            "is_scheduled": rs['href'] in db.get_all(),
            "type": "ruleset"
        }

        rules = []
        scheduled_hrefs = db.get_all()
        typed_rules = []
        for r in rs.get('sec_rules', []) + rs.get('rules', []):
            typed_rules.append((r, 'allow'))
        for r in rs.get('deny_rules', []):
            rule_type = 'override_deny' if r.get('override') else 'deny'
            typed_rules.append((r, rule_type))

        no_counters = {'allow': 0, 'deny': 0, 'override_deny': 0}
        for r, rule_type in typed_rules:
            no_counters[rule_type] += 1
            r_ut = r.get('update_type')
            dest_field = r.get('destinations', r.get('consumers', []))
            rules.append({
                "href": r['href'],
                "id": _extract_id_href(r['href']),
                "no": no_counters[rule_type],
                "enabled": r.get('enabled', False),
                "description": r.get('description', ''),
                "provision_state": "DRAFT" if r_ut else "ACTIVE",
                "is_scheduled": r['href'] in scheduled_hrefs,
                "source": api.resolve_actor_str(dest_field),
                "dest": api.resolve_actor_str(r.get('providers', [])),
                "service": api.resolve_service_str(r.get('ingress_services', [])),
                "rule_type": rule_type,
                "type": "rule"
            })
        return jsonify({"ruleset": rs_row, "rules": rules})

    @app.route('/api/rule_scheduler/schedules')
    def rs_schedules_list():
        db, api, _ = _get_rs_components()
        db_data = db.get_all()
        result = []
        for href, conf in db_data.items():
            entry = dict(conf)
            entry['href'] = href
            entry['id'] = _extract_id_href(href)
            # Live status check
            try:
                status, data = api.get_live_item(href)
                if status == 200 and data:
                    entry['live_enabled'] = data.get('enabled')
                    entry['live_name'] = data.get('name', conf.get('name', ''))
                    if conf.get('pce_status') == 'deleted':
                        conf['pce_status'] = 'active'
                        db.put(href, conf)
                        entry['pce_status'] = 'active'
                elif status == 404:
                    entry['live_enabled'] = None
                    entry['live_name'] = conf.get('name', '')
                    if conf.get('pce_status') != 'deleted':
                        conf['pce_status'] = 'deleted'
                        db.put(href, conf)
                    entry['pce_status'] = 'deleted'
                else:
                    entry['live_enabled'] = None
                    entry['live_name'] = conf.get('name', '')
            except Exception:
                entry['live_enabled'] = None
                entry['live_name'] = conf.get('name', '')
            result.append(entry)
        return jsonify(result)

    @app.route('/api/rule_scheduler/schedules', methods=['POST'])
    def rs_schedule_create():
        db, api, _ = _get_rs_components()
        data = request.get_json()
        href = data.get('href', '')
        if not href:
            return _err("href required", 400)

        # Block draft-only scheduling natively for GUI
        if api.has_draft_changes(href) or not api.is_provisioned(href):
            return jsonify({"ok": False, "error": t("rs_sch_draft_block")}), 400

        # Validate time format for recurring
        if data.get('type') == 'recurring':
            try:
                datetime.datetime.strptime(data['start'], "%H:%M")
                datetime.datetime.strptime(data['end'], "%H:%M")
            except (ValueError, KeyError):
                return _err("Invalid time format (use HH:MM)", 400)
        elif data.get('type') == 'one_time':
            try:
                ex = data['expire_at'].replace(' ', 'T')
                datetime.datetime.fromisoformat(ex)
                data['expire_at'] = ex
            except (ValueError, KeyError):
                return _err("Invalid expiration format", 400)

        db_entry = {
            "type": data.get('type', 'recurring'),
            "name": data.get('name', ''),
            "is_ruleset": data.get('is_ruleset', False),
            "action": data.get('action', 'allow'),
            "detail_rs": data.get('detail_rs', ''),
            "detail_src": data.get('detail_src', 'All'),
            "detail_dst": data.get('detail_dst', 'All'),
            "detail_svc": data.get('detail_svc', 'All'),
            "detail_name": data.get('detail_name', data.get('name', ''))
        }

        if data.get('type') == 'recurring':
            db_entry['days'] = data.get('days', [])
            db_entry['start'] = data['start']
            db_entry['end'] = data['end']
            db_entry['timezone'] = data.get('timezone', 'local')
            days_str = ",".join([d[:3] for d in db_entry['days']]) if len(db_entry['days']) < 7 else t('rs_action_everyday')
            act_str = t('rs_action_enable_in_window') if db_entry['action'] == 'allow' else t('rs_action_disable_in_window')
            tz_display = db_entry['timezone'] if db_entry['timezone'] != 'local' else 'Local'
            note = f"[?? {t('rs_sch_tag_recurring')}: {days_str} {db_entry['start']}-{db_entry['end']} ({tz_display}) {act_str}]"
        else:
            db_entry['expire_at'] = data['expire_at']
            db_entry['timezone'] = data.get('timezone', 'local')
            note = f"[??{t('rs_sch_tag_expire')}: {data['expire_at'].replace('T', ' ')}]"

        db.put(href, db_entry)
        api.update_rule_note(href, note)
        return jsonify({"ok": True, "id": _extract_id_href(href)})

    @app.route('/api/rule_scheduler/schedules/<path:href>')
    def rs_schedule_detail(href):
        db, _, _ = _get_rs_components()
        href = '/' + href if not href.startswith('/') else href
        conf = db.get(href)
        if not conf:
            return _err("Not found", 404)
        entry = dict(conf)
        entry['href'] = href
        entry['id'] = _extract_id_href(href)
        return jsonify(entry)

    @app.route('/api/rule_scheduler/schedules/delete', methods=['POST'])
    def rs_schedule_delete():
        db, api, _ = _get_rs_components()
        data = request.get_json()
        hrefs = data.get('hrefs', [])
        deleted = []
        for href in hrefs:
            try:
                api.update_rule_note(href, "", remove=True)
            except Exception as _e:
                logger.debug(f"[GUI:rule_note_clear] swallowed: {_e}")  # best-effort note removal
            if db.delete(href):
                deleted.append(_extract_id_href(href))
        return jsonify({"ok": True, "deleted": deleted})

    @app.route('/api/rule_scheduler/check', methods=['POST'])
    def rs_check():
        _, _, engine = _get_rs_components()
        tz_str = cm.config.get('settings', {}).get('timezone', 'local')
        logs = engine.check(silent=True, tz_str=tz_str)
        _append_rs_logs(logs)
        cleaned = [_strip_ansi(l) for l in logs]
        return jsonify({"ok": True, "logs": cleaned})

    @app.route('/api/rule_scheduler/logs')
    def rs_log_history_api():
        with _rs_log_lock:
            history = list(_rs_log_history)
        return jsonify({"ok": True, "history": history})

    # ??? Module Log API ??????????????????????????????????????????????????????
    @app.route('/api/logs')
    def api_log_list():
        from src.module_log import ModuleLog, MODULES
        modules = ModuleLog.list_modules()
        # Ensure all known modules appear even if not yet initialized
        present = {m["name"] for m in modules}
        for name, label in MODULES.items():
            if name not in present:
                modules.append({"name": name, "label": label, "count": 0})
        return jsonify({"ok": True, "modules": modules})

    @app.route('/api/logs/<module_name>')
    def api_log_get(module_name):
        from src.module_log import ModuleLog, MODULES
        if module_name not in MODULES:
            return jsonify({"ok": False, "error": "Unknown module"}), 404
        n = min(int(request.args.get('n', 200)), 500)
        ml = ModuleLog.get(module_name)
        return jsonify({"ok": True, "module": module_name, "entries": ml.get_recent(n)})

    # ??? End Rule Scheduler API ????????????????????????????????????????????

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
def _run_https(app, host: str, port: int, cert_file: str, key_file: str) -> None:
    """HTTPS via cheroot — production-grade WSGI server with hardened TLS."""
    import threading as _threading
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

    # HTTP → HTTPS redirect server (daemon thread, best-effort)
    _redirect_port = int(_tls_cfg.get("http_redirect_port", 80))
    _https_port = port

    def _redirect_app(environ, start_response):
        _host_hdr = environ.get("HTTP_HOST", f"localhost:{_https_port}").split(":")[0]
        _path = environ.get("PATH_INFO", "/")
        _qs = environ.get("QUERY_STRING", "")
        _location = f"https://{_host_hdr}:{_https_port}{_path}"
        if _qs:
            _location += f"?{_qs}"
        start_response("308 Permanent Redirect", [
            ("Location", _location),
            ("Content-Length", "0"),
        ])
        return [b""]

    def _start_redirect_server():
        _rserver = _cheroot_wsgi.Server((host, _redirect_port), _redirect_app, numthreads=2)
        try:
            _rserver.start()
        except OSError as _e:
            logger.warning(
                "HTTP redirect server could not bind port {} ({}). "
                "Skipping redirect — HTTPS is still available.",
                _redirect_port, _e,
            )
        finally:
            try:
                _rserver.stop()
            except Exception:
                pass  # intentional: shutdown best-effort, secondary errors not actionable

    _t = _threading.Thread(target=_start_redirect_server, daemon=True, name="http-redirect")
    _t.start()

    try:
        server.start()
    except OSError as e:
        if "Address already in use" in str(e):
            logger.error("Port {} is already in use. Stop the existing process first (fuser -k {}/tcp) then retry.", port, port)
        else:
            raise
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


def build_app(cm: ConfigManager, persistent_mode: bool = False) -> 'Flask':
    """Public factory: build a configured Flask app bound to the given ConfigManager.

    Pure constructor — does NOT call app.run(). Used by launch_gui and tests.
    """
    return _create_app(cm, persistent_mode=persistent_mode)

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

    app = build_app(cm, persistent_mode=persistent_mode)

    # TLS / HTTPS configuration
    cm.load()
    try:
        from src.siem.preview import emit_preview_warning
        emit_preview_warning(cm, context="web_gui_startup")
    except Exception:
        pass  # intentional fallback: preview warning must not block GUI startup
    tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
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
