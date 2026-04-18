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
import logging
import ipaddress
from contextlib import redirect_stdout
from collections import Counter
import secrets
import socket as _socket
import struct

try:
    from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect
    HAS_FLASK = True
    FLASK_IMPORT_ERROR = ""
except ImportError:
    HAS_FLASK = False
    FLASK_IMPORT_ERROR = str(sys.exc_info()[1])

from src.config import ConfigManager, hash_password, verify_password, verify_and_upgrade_password
from src.i18n import t, get_messages
from src import __version__
from src.alerts import PLUGIN_METADATA, plugin_config_path, plugin_config_value
from src.report.dashboard_summaries import (
    build_audit_dashboard_summary,
    build_policy_usage_dashboard_summary,
    write_audit_dashboard_summary,
    write_policy_usage_dashboard_summary,
)

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


# ????????????????????????????????????????????????????????????????????????????????# Event Catalog (mirrors settings.py)
# ????????????????????????????????????????????????????????????????????????????????# We now dynamically import FULL_EVENT_CATALOG from src.settings inside the API route.


# ????????????????????????????????????????????????????????????????????????????????# Flask Application Factory
# ????????????????????????????????????????????????????????????????????????????????
def _check_ip_allowed(allowed_ips: list, remote_addr: str) -> bool:
    if not allowed_ips:
        return True
    try:
        remote = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False
    for allowed in allowed_ips:
        try:
            if '/' in allowed:
                net = ipaddress.ip_network(allowed, strict=False)
                if remote in net:
                    return True
            else:
                ip = ipaddress.ip_address(allowed)
                if remote == ip:
                    return True
        except ValueError:
            continue
    return False


def _validate_allowed_ips(values) -> tuple[list, list]:
    normalized = []
    invalid = []
    for raw in values or []:
        item = str(raw or "").strip()
        if not item:
            continue
        try:
            if "/" in item:
                ipaddress.ip_network(item, strict=False)
            else:
                ipaddress.ip_address(item)
            normalized.append(item)
        except ValueError:
            invalid.append(item)
    return normalized, invalid


def _normalize_rule_throttle(raw_value):
    value = str(raw_value or "").strip()
    if not value:
        return ""
    try:
        from src.events import parse_throttle
    except Exception:
        parse_throttle = None
    if parse_throttle and not parse_throttle(value):
        raise ValueError("Invalid throttle format. Use values like 2/10m or 5/1h.")
    return value


def _normalize_match_fields(raw_value):
    if not raw_value:
        return {}
    if isinstance(raw_value, dict):
        normalized = {}
        for key, value in raw_value.items():
            key_str = str(key or "").strip()
            value_str = str(value or "").strip()
            if key_str and value_str:
                normalized[key_str] = value_str
        return normalized
    raise ValueError("match_fields must be an object of field-path to pattern.")


def _is_workload_href(href: str) -> bool:
    normalized = str(href or "").strip()
    return bool(normalized) and "/workloads/" in normalized


def _normalize_quarantine_hrefs(raw_hrefs) -> list[str]:
    normalized: list[str] = []
    for raw_href in raw_hrefs or []:
        href = str(raw_href or "").strip()
        if href and _is_workload_href(href) and href not in normalized:
            normalized.append(href)
    return normalized

def _rst_drop():
    """Close the underlying TCP socket with RST (SO_LINGER 0) and raise to
    prevent Flask from sending any HTTP response.  To a port scanner the
    connection appears reset ??identical to 'connection refused' ??so the
    port does not register as an open HTTP service.
    """
    try:
        environ = request.environ
        # Werkzeug exposes the raw socket in several possible locations
        sock = environ.get('werkzeug.socket')
        if sock is None:
            wsgi_in = environ.get('wsgi.input')
            for attr in ('raw', '_sock', 'raw._sock'):
                obj = wsgi_in
                for part in attr.split('.'):
                    obj = getattr(obj, part, None)
                    if obj is None:
                        break
                if isinstance(obj, _socket.socket):
                    sock = obj
                    break
        if sock is not None:
            # l_onoff=1, l_linger=0 ??kernel sends RST on close, not FIN
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                            struct.pack('ii', 1, 0))
            try:
                sock.shutdown(_socket.SHUT_RDWR)
            except OSError:
                pass
    except Exception:
        pass
    # Raise ??Flask will attempt to write the 500 but the socket is gone
    raise _RstDrop()


class _RstDrop(Exception):
    """Sentinel: request was silently dropped via TCP RST."""


_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_PKG_DIR)

# ?? Rule Scheduler log history (in-memory, thread-safe) ??????????????????????
_rs_log_history: list = []
_rs_log_lock = threading.Lock()


def _append_rs_logs(logs: list) -> None:
    """Append one check-run's output to the in-memory log history."""
    with _rs_log_lock:
        entry = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "logs": [_ANSI_RE.sub('', l) for l in logs],
        }
        _rs_log_history.append(entry)
        if len(_rs_log_history) > 200:
            del _rs_log_history[:-200]


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
                logger.info("[RuleScheduler] Auto-check completed (%d entries).", len(logs))
        except Exception as exc:
            logger.error("[RuleScheduler] Background error: %s", exc, exc_info=True)


def _resolve_reports_dir(cm_ref: ConfigManager) -> str:
    """Return absolute path to the report output directory."""
    d = cm_ref.config.get('report', {}).get('output_dir', 'reports')
    return d if os.path.isabs(d) else os.path.join(_ROOT_DIR, d)


def _resolve_config_dir() -> str:
    return os.path.join(_ROOT_DIR, 'config')


def _resolve_state_file() -> str:
    return os.path.join(_ROOT_DIR, 'logs', 'state.json')


def _plugin_config_roots() -> set[str]:
    roots: set[str] = set()
    for plugin_name, meta in PLUGIN_METADATA.items():
        for field_key in meta.fields:
            path = plugin_config_path(plugin_name, field_key)
            if path:
                roots.add(path[0])
    return roots


def _summarize_alert_channels(config: dict, dispatch_history: list) -> list[dict]:
    active = set(config.get("alerts", {}).get("active", []) or [])
    summaries = []
    for name, meta in PLUGIN_METADATA.items():
        required_missing = []
        for key, field in meta.fields.items():
            if not field.required:
                continue
            value = plugin_config_value(config, name, key)
            if isinstance(value, list):
                present = any(str(item or "").strip() for item in value)
            elif isinstance(value, (int, float)):
                present = True
            else:
                present = bool(str(value or "").strip()) if not isinstance(value, bool) else value
            if not present:
                required_missing.append(key)

        latest = next((item for item in reversed(dispatch_history or []) if item.get("channel") == name), None)
        summaries.append({
            "name": name,
            "display_name": meta.display_name,
            "description": meta.description,
            "enabled": name in active,
            "configured": len(required_missing) == 0,
            "missing_required": required_missing,
            "last_status": latest.get("status", "") if latest else "",
            "last_target": latest.get("target", "") if latest else "",
            "last_timestamp": latest.get("timestamp", "") if latest else "",
            "last_error": latest.get("error", "") if latest else "",
        })
    return summaries


def _ok(data=None, **kw):
    """Standard success response: {"ok": true, ...}"""
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    body.update(kw)
    return jsonify(body)


def _err(msg, status=400):
    """Standard error response: {"ok": false, "error": "..."}"""
    return jsonify({"ok": False, "error": msg}), status


def _get_active_pce_url(cm: 'ConfigManager') -> str:
    """Return the active PCE profile URL, falling back to config['api']['url']."""
    active_id = cm.config.get('active_pce_id')
    if active_id is not None:
        for p in cm.config.get('pce_profiles', []):
            if p.get('id') == active_id:
                return p.get('url', '') or cm.config.get('api', {}).get('url', '')
    return cm.config.get('api', {}).get('url', '')

def _build_audit_dashboard_summary(result) -> dict:
    return build_audit_dashboard_summary(result)


def _write_audit_dashboard_summary(output_dir: str, result) -> str:
    return write_audit_dashboard_summary(output_dir, result)


def _build_policy_usage_dashboard_summary(result) -> dict:
    return build_policy_usage_dashboard_summary(result)


def _write_policy_usage_dashboard_summary(output_dir: str, result) -> str:
    return write_policy_usage_dashboard_summary(output_dir, result)


def _create_app(cm: ConfigManager, persistent_mode: bool = False) -> 'Flask':
    app = Flask(__name__, template_folder=os.path.join(_PKG_DIR, 'templates'), static_folder=os.path.join(_PKG_DIR, 'static'))
    app.config['JSON_AS_ASCII'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = False
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['CM'] = cm
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600

    # Initialize session secret
    cm.load()
    gui_cfg = cm.config.get("web_gui", {})
    app.secret_key = gui_cfg.get("secret_key", secrets.token_hex(32))
    # Enable Secure cookie flag when HTTPS is configured
    tls_cfg = gui_cfg.get("tls", {})
    if tls_cfg.get("enabled"):
        app.config['SESSION_COOKIE_SECURE'] = True
    app.jinja_env.globals.update(t=t)

    # ── flask-login setup ──────────────────────────────────────────────────────
    from flask_login import LoginManager, current_user, login_user, logout_user
    from src.auth_models import AdminUser, LoginForm

    login_manager = LoginManager(app)
    login_manager.login_view = "login_page"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def _load_user(user_id: str):
        admin_name = cm.config.get("web_gui", {}).get("username", "illumio")
        return AdminUser(admin_name) if user_id == admin_name else None

    # ── flask-wtf CSRF setup ───────────────────────────────────────────────────
    from flask_wtf.csrf import CSRFProtect, generate_csrf

    app.config["WTF_CSRF_ENABLED"] = True
    app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1 hour
    app.config["WTF_CSRF_CHECK_DEFAULT"] = True
    # Accept both X-CSRFToken (flask-wtf default) and X-CSRF-Token (legacy SPA header)
    app.config["WTF_CSRF_HEADERS"] = ["X-CSRFToken", "X-CSRF-Token"]

    csrf = CSRFProtect(app)

    # ── flask-limiter rate limiting ────────────────────────────────────────────
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=[],          # no global limit; apply per-endpoint
        storage_uri="memory://",    # single-node deployment
        strategy="fixed-window",
    )

    # ── flask-talisman security headers ───────────────────────────────────────
    from flask_talisman import Talisman

    tls_enabled = cm.config.get("web_gui", {}).get("tls", {}).get("enabled", False)

    # CSP: allow inline scripts/styles (SPA uses them); locked down otherwise
    _csp = {
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'"],  # SPA inline JS
        'style-src': ["'self'", "'unsafe-inline'"],   # SPA inline CSS
        'img-src': ["'self'", "data:"],
        'font-src': "'self'",
        'connect-src': "'self'",
    }

    Talisman(
        app,
        force_https=tls_enabled,               # only when TLS is configured
        strict_transport_security=tls_enabled,
        content_security_policy=_csp,
        content_security_policy_nonce_in=[],   # inline not nonce-based (SPA compat)
        frame_options='DENY',
        referrer_policy='strict-origin-when-cross-origin',
    )

    @app.context_processor
    def inject_csrf():
        return dict(csrf_token=generate_csrf)

    # SPA endpoint to refresh tokens without full reload
    @app.route('/api/csrf-token')
    def api_csrf_token():
        return jsonify({"csrf_token": generate_csrf()})

    @app.errorhandler(_RstDrop)
    def handle_rst_drop(e):
        # Socket is already closed with RST ??return an empty Response object
        # so Flask stops processing without logging an unhandled error
        from flask import Response as _Resp
        return _Resp('', status=200)

    @app.before_request
    def security_check():
        if request.endpoint == 'static' or request.path.startswith('/static/'):
            return

        # IP Allowlist check ??silently drop with TCP RST (no HTTP response)
        # so port scanners cannot detect an HTTP service on this port
        allowed_ips = cm.config.get("web_gui", {}).get("allowed_ips", [])
        if not _check_ip_allowed(allowed_ips, request.remote_addr):
            logger.warning(f"[GUI] Blocked untrusted IP: {request.remote_addr}")
            _rst_drop()  # closes socket with RST, raises _RstDrop

        # Auth check (always enforced for all GUI modes)
        # Bypass login routes
        if request.path in ['/login', '/api/login', '/logout', '/api/csrf-token']:
            return
        if not current_user.is_authenticated:
            if request.path.startswith('/api/'):
                return _err(t("gui_err_unauthorized"), 401)
            return redirect('/login')

    @app.after_request
    def add_security_headers(response):
        # Security headers (talisman will add CSP/HSTS in Task 7; keep fallbacks here)
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        _tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
        if _tls_cfg.get("enabled"):
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response

    # ??? Frontend SPA ?????????????????????????????????????????????????????
    @app.route('/')
    def index():
        cm.load()
        pce_url = _get_active_pce_url(cm)
        # csrf_token() is a Jinja2 global injected by flask-wtf CSRFProtect
        return render_template('index.html', pce_url=pce_url)

    # ??? Auth Routes ??????????????????????????????????????????????????????
    @app.route('/login', methods=['GET'])
    def login_page():
        return render_template('login.html')

    @app.route('/api/login', methods=['POST'])
    @csrf.exempt
    @limiter.limit("5 per minute")
    def api_login():
        from pydantic import ValidationError as _ValidationError
        try:
            form = LoginForm.model_validate(request.get_json(silent=True) or {})
        except _ValidationError as e:
            return jsonify({"ok": False, "error": "invalid_form", "detail": str(e)}), 400

        username = form.username
        password = form.password

        cm.load()
        gui_cfg = cm.config.get("web_gui", {})

        saved_username = gui_cfg.get("username", "illumio")
        saved_hash = gui_cfg.get("password_hash", "")
        saved_salt = gui_cfg.get("password_salt", "")

        if not saved_hash:
            # No password configured — reject all logins until config is repaired
            logger.error("[GUI] Login attempted but no password hash configured.")
            return jsonify({"ok": False, "error": t("gui_err_invalid_auth")}), 401

        ok, new_hash = verify_and_upgrade_password(saved_hash, saved_salt, password)
        if username == saved_username and ok:
            login_user(AdminUser(username))
            if new_hash is not None:
                # Silent upgrade: PBKDF2/SHA256 → argon2id
                gui_cfg["password_hash"] = new_hash
                gui_cfg["password_salt"] = ""   # argon2 embeds salt
                cm.save()
                logger.info("[GUI] Upgraded password hash to argon2id for user '%s'.", saved_username)
            # Clear legacy _initial_password if present
            if gui_cfg.get("_initial_password"):
                del gui_cfg["_initial_password"]
                cm.save()
            return jsonify({"ok": True, "csrf_token": generate_csrf()})

        return jsonify({"ok": False, "error": t("gui_err_invalid_auth")}), 401

    @app.route('/logout')
    def logout():
        logout_user()
        session.clear()
        return redirect('/login')

    @app.route('/api/security', methods=['GET'])
    def api_security_get():
        cm.load()
        gui_cfg = cm.config.get('web_gui', {})
        return jsonify({
            "username": gui_cfg.get("username", "illumio"),
            "allowed_ips": gui_cfg.get("allowed_ips", []),
            "auth_setup": bool(gui_cfg.get("password_hash"))
        })

    @app.route('/api/security', methods=['POST'])
    def api_security_post():
        d = request.json or {}
        cm.load()
        gui_cfg = cm.config.setdefault("web_gui", {})
        
        if "username" in d:
            gui_cfg["username"] = d["username"]
        
        if "allowed_ips" in d:
            allowed_ips, invalid_ips = _validate_allowed_ips(d["allowed_ips"])
            if invalid_ips:
                return jsonify({
                    "ok": False,
                    "error": f"Invalid allowlist entries: {', '.join(invalid_ips)}"
                }), 400
            gui_cfg["allowed_ips"] = allowed_ips
            
        if "new_password" in d and d["new_password"]:
            # Check old password if there's already one set
            if gui_cfg.get("password_hash"):
                old_pass = d.get("old_password", "")
                stored = gui_cfg.get("password_hash", "")
                salt = gui_cfg.get("password_salt", "")
                if not verify_password(stored, salt, old_pass):
                    return jsonify({"ok": False, "error": t("gui_err_invalid_old_pass")}), 401

            from src.config import hash_password_argon2 as _hash_argon2
            gui_cfg["password_salt"] = ""   # argon2 embeds salt
            gui_cfg["password_hash"] = _hash_argon2(d["new_password"])
            gui_cfg.pop("_initial_password", None)
            
        cm.save()
        return jsonify({"ok": True})

    # ??? API: Status ??????????????????????????????????????????????????????
    @app.route('/api/ui_translations')
    def api_ui_translations():
        lang = cm.config.get("settings", {}).get("language", "en")
        merged = get_messages(lang)
        ui_dict = {k: v for k, v in merged.items() if k.startswith("gui_")}
        return jsonify(ui_dict)

    @app.route('/api/status')
    def api_status():
        cm.load()
        state = {}
        cooldowns = []
        try:
            STATE_FILE = _resolve_state_file()
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                now = datetime.datetime.now(datetime.timezone.utc)
                alert_history = state.get("alert_history", {})
                
                for rule in cm.config['rules']:
                    rid = str(rule['id'])
                    rem_mins = 0
                    if rid in alert_history:
                        try:
                            last_alert_str = alert_history[rid]
                            last_ts = datetime.datetime.strptime(last_alert_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                            cd_mins = int(rule.get('cooldown_minutes', 0))
                            if cd_mins > 0:
                                elapsed = (now - last_ts).total_seconds()
                                total_cd = cd_mins * 60
                                if elapsed < total_cd:
                                    rem_mins = int((total_cd - elapsed) // 60) + 1
                        except Exception as e:
                            logger.error(f"Error parsing cooldown for rule {rid}: {e}")
                    
                    cooldowns.append({
                        "id": rule['id'],
                        "name": rule.get('name', 'Unknown Rule'),
                        "remaining_mins": rem_mins
                    })
        except Exception as e:
            logger.error(f"Error reading state file for cooldowns: {e}")

        has_health_rule = any(
            r.get("type") == "system" and r.get("filter_value") == "pce_health"
            for r in cm.config.get("rules", [])
        )
        return jsonify({
            "version": __version__,
            "api_url": _get_active_pce_url(cm),
            "rules_count": len(cm.config['rules']),
            "health_check": has_health_rule,
            "language": cm.config.get('settings', {}).get('language', 'en'),
            "theme": cm.config.get('settings', {}).get('theme', 'dark'),
            "timezone": cm.config.get('settings', {}).get('timezone', 'local'),
            "cooldowns": cooldowns,
            "event_watermark": state.get("event_watermark") or state.get("last_check"),
            "event_overflow": state.get("event_overflow", {}),
            "unknown_events": state.get("unknown_events", {}),
            "event_parser_stats": state.get("event_parser_stats", {}),
            "event_parser_samples": state.get("event_parser_samples", []),
            "pce_stats": state.get("pce_stats", {}),
            "throttle_state": state.get("throttle_state", {}),
            "dispatch_history": state.get("dispatch_history", []),
            "alert_channels": _summarize_alert_channels(cm.config, state.get("dispatch_history", [])),
            "event_timeline": state.get("event_timeline", []),
        })

    @app.route('/api/events/viewer')
    def api_events_viewer():
        cm.load()
        try:
            from src.api_client import ApiClient, EventFetchError
            from src.events import event_identity, format_utc, normalize_event, parse_event_timestamp
            from src.settings import _event_category
        except Exception as exc:
            logger.error("Failed to load event viewer dependencies: %s", exc)
            return _err(str(exc), 500)

        try:
            mins = max(5, min(int(request.args.get('mins', 60)), 10080))
        except (TypeError, ValueError):
            mins = 60
        try:
            limit = max(1, min(int(request.args.get('limit', 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(request.args.get('offset', 0)))
        except (TypeError, ValueError):
            offset = 0

        search = str(request.args.get('search', '') or '').strip().lower()
        category_filter = str(request.args.get('category', '') or '').strip()
        type_group_filter = str(request.args.get('type_group', '') or '').strip()
        event_type_filter = str(request.args.get('event_type', '') or '').strip()

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        since_utc = now_utc - datetime.timedelta(minutes=mins)
        query_since = format_utc(since_utc)
        query_until = format_utc(now_utc)
        fetch_limit = min(max((offset + limit) * 4, 100), 5000)

        api_client = ApiClient(cm)
        try:
            raw_events = api_client.fetch_events_strict(
                start_time_str=query_since,
                end_time_str=query_until,
                max_results=fetch_limit,
            )
        except EventFetchError as exc:
            logger.error("Event viewer fetch failed: %s - %s", exc.status, exc.message)
            return _err(f"PCE event fetch failed ({exc.status}): {exc.message[:300]}", 502)
        except Exception as exc:
            logger.error("Event viewer fetch failed: %s", exc, exc_info=True)
            return _err(f"PCE event fetch failed: {exc}", 502)

        items = []
        for raw_event in raw_events:
            normalized = normalize_event(raw_event)
            event_type = normalized.get("event_type") or raw_event.get("event_type") or ""
            event_group = "*" if event_type == "*" else event_type.split(".", 1)[0]

            if event_type_filter and event_type != event_type_filter:
                continue
            if type_group_filter and event_group != type_group_filter:
                continue
            if category_filter and _event_category(event_type) != category_filter:
                continue

            if search:
                haystack = " ".join([
                    event_type,
                    normalized.get('actor', ''),
                    normalized.get('target_name', ''),
                    normalized.get('resource_name', ''),
                    normalized.get('action', ''),
                    normalized.get('source_ip', ''),
                    json.dumps(raw_event, ensure_ascii=False, default=str),
                ]).lower()
                if search not in haystack:
                    continue

            items.append({
                "event_id": event_identity(raw_event),
                "timestamp": normalized.get("timestamp") or raw_event.get("timestamp"),
                "event_type": event_type,
                "status": normalized.get("status") or raw_event.get("status"),
                "severity": normalized.get("severity") or raw_event.get("severity"),
                "known_event_type": normalized.get("known_event_type"),
                "parser_notes": normalized.get("parser_notes") or [],
                "category": _event_category(event_type),
                "type_group": event_group,
                "normalized": normalized,
                "raw": raw_event,
            })

        items.sort(
            key=lambda item: parse_event_timestamp(item.get("timestamp")) or now_utc,
            reverse=True,
        )
        visible_items = items[offset:offset + limit]

        return jsonify({
            "ok": True,
            "items": visible_items,
            "summary": {
                "fetched_count": len(raw_events),
                "matched_count": len(items),
                "returned_count": len(visible_items),
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < len(items),
                "query_since": query_since,
                "query_until": query_until,
                "category": category_filter,
                "type_group": type_group_filter,
                "event_type": event_type_filter,
            },
        })

    @app.route('/api/events/shadow_compare')
    def api_events_shadow_compare():
        cm.load()
        try:
            from src.api_client import ApiClient, EventFetchError
            from src.events import compare_event_rules, format_utc
        except Exception as exc:
            logger.error("Failed to load shadow compare dependencies: %s", exc)
            return _err(str(exc), 500)

        try:
            mins = max(5, min(int(request.args.get('mins', 60)), 10080))
        except (TypeError, ValueError):
            mins = 60
        try:
            limit = max(1, min(int(request.args.get('limit', 200)), 500))
        except (TypeError, ValueError):
            limit = 200

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        since_utc = now_utc - datetime.timedelta(minutes=mins)
        query_since = format_utc(since_utc)
        query_until = format_utc(now_utc)

        api_client = ApiClient(cm)
        try:
            events = api_client.fetch_events_strict(
                start_time_str=query_since,
                end_time_str=query_until,
                max_results=limit,
            )
        except EventFetchError as exc:
            return _err(f"PCE event fetch failed ({exc.status}): {exc.message[:300]}", 502)
        except Exception as exc:
            return _err(f"PCE event fetch failed: {exc}", 502)

        event_rules = [rule for rule in cm.config.get("rules", []) if rule.get("type") == "event"]
        comparisons = compare_event_rules(event_rules, events)
        divergent = [item for item in comparisons if item.get("status") != "same"]

        return jsonify({
            "ok": True,
            "summary": {
                "query_since": query_since,
                "query_until": query_until,
                "fetched_events": len(events),
                "rule_count": len(event_rules),
                "divergent_rules": len(divergent),
            },
            "items": comparisons,
        })

    @app.route('/api/events/rule_test')
    def api_events_rule_test():
        cm.load()
        try:
            from src.api_client import ApiClient, EventFetchError
            from src.events import (
                compare_event_rules,
                event_identity,
                format_utc,
                matches_event_rule,
                matches_event_rule_legacy,
                normalize_event,
            )
        except Exception as exc:
            logger.error("Failed to load rule test dependencies: %s", exc)
            return _err(str(exc), 500)

        try:
            idx = int(request.args.get('idx', '-1'))
        except (TypeError, ValueError):
            return _err("invalid rule index", 400)
        if idx < 0 or idx >= len(cm.config.get('rules', [])):
            return _err("rule not found", 404)

        rule = cm.config['rules'][idx]
        if rule.get('type') != 'event':
            return _err("rule is not an event rule", 400)

        try:
            mins = max(5, min(int(request.args.get('mins', 60)), 10080))
        except (TypeError, ValueError):
            mins = 60
        try:
            limit = max(1, min(int(request.args.get('limit', 300)), 500))
        except (TypeError, ValueError):
            limit = 300

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        since_utc = now_utc - datetime.timedelta(minutes=mins)
        query_since = format_utc(since_utc)
        query_until = format_utc(now_utc)

        api_client = ApiClient(cm)
        try:
            events = api_client.fetch_events_strict(
                start_time_str=query_since,
                end_time_str=query_until,
                max_results=limit,
            )
        except EventFetchError as exc:
            return _err(f"PCE event fetch failed ({exc.status}): {exc.message[:300]}", 502)
        except Exception as exc:
            return _err(f"PCE event fetch failed: {exc}", 502)

        event_lookup = {event_identity(event): event for event in events}
        current_ids = {
            event_identity(event)
            for event in events
            if matches_event_rule(rule, event)
        }
        legacy_ids = {
            event_identity(event)
            for event in events
            if matches_event_rule_legacy(rule, event)
        }
        only_current = sorted(current_ids - legacy_ids)
        only_legacy = sorted(legacy_ids - current_ids)
        current_matches = sorted(current_ids)
        comparison = compare_event_rules([rule], events)[0]

        def _serialize(event_id):
            raw_event = event_lookup.get(event_id, {})
            return {
                "event_id": event_id,
                "timestamp": raw_event.get("timestamp"),
                "event_type": raw_event.get("event_type"),
                "normalized": normalize_event(raw_event),
                "raw": raw_event,
            }

        return jsonify({
            "ok": True,
            "rule": {
                "index": idx,
                "id": rule.get("id"),
                "name": rule.get("name"),
                "filter_value": rule.get("filter_value"),
                "filter_status": rule.get("filter_status"),
                "filter_severity": rule.get("filter_severity"),
                "match_fields": rule.get("match_fields") or rule.get("filter_match_fields") or {},
            },
            "summary": {
                "query_since": query_since,
                "query_until": query_until,
                "fetched_events": len(events),
                "current_count": len(current_ids),
                "legacy_count": len(legacy_ids),
                "delta": len(current_ids) - len(legacy_ids),
                "status": comparison.get("status"),
            },
            "current_matches": [_serialize(event_id) for event_id in current_matches[:20]],
            "only_current": [_serialize(event_id) for event_id in only_current[:10]],
            "only_legacy": [_serialize(event_id) for event_id in only_legacy[:10]],
        })

    @app.route('/api/init_quarantine', methods=['POST'])
    def api_init_quarantine():
        """Ensure Quarantine labels exist on the PCE upon loading the new UI module."""
        cm.load()
        from src.api_client import ApiClient
        api = ApiClient(cm)
        api.check_and_create_quarantine_labels()
        return jsonify({"ok": True})

    @app.route('/api/event-catalog')
    def api_event_catalog():
        from src.events.catalog import LOCAL_EXTENSION_EVENT_TYPES
        from src.settings import FULL_EVENT_CATALOG, ACTION_EVENTS, SEVERITY_FILTER_EVENTS
        from src.i18n import set_language, t

        cm.load()
        set_language(cm.config.get("settings", {}).get("language", "en"))

        translated_catalog = {}
        categories = []
        for category, events in FULL_EVENT_CATALOG.items():
            trans_cat = t('cat_' + category.replace(' ', '_').lower())
            if category == "Agent Health Detail":
                trans_cat = t('cat_agent_health', default="Agent Health")

            if trans_cat not in translated_catalog:
                translated_catalog[trans_cat] = {}

            event_items = []
            for event_id, translation_key in events.items():
                description = t(translation_key)
                supports_status = event_id in ACTION_EVENTS
                supports_severity = event_id in SEVERITY_FILTER_EVENTS or event_id == "*"
                translated_catalog[trans_cat][event_id] = description
                event_items.append({
                    'id': event_id,
                    'label': description,
                    'description': description,
                    'source': 'local_extension' if event_id in LOCAL_EXTENSION_EVENT_TYPES else 'vendor_baseline',
                    'supports_status': supports_status,
                    'supports_severity': supports_severity,
                })

            categories.append({
                'id': category,
                'label': trans_cat,
                'events': event_items,
            })

        return jsonify({
            'catalog': translated_catalog,
            'categories': categories,
            'action_events': ACTION_EVENTS,
            'severity_filter_events': SEVERITY_FILTER_EVENTS,
        })

    # ??? API: Rules CRUD ??????????????????????????????????????????????????
    @app.route('/api/rules')
    def api_rules():
        cm.load()
        
        # Load state to get cooldowns
        alert_history = {}
        throttle_state = {}
        try:
            STATE_FILE = _resolve_state_file()
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    alert_history = state.get("alert_history", {})
                    throttle_state = state.get("throttle_state", {})
        except Exception as e:
            logger.error(f"Error reading state file for rules: {e}")

        now = datetime.datetime.now(datetime.timezone.utc)
        rules = []
        for i, r in enumerate(cm.config['rules']):
            rule_out = {"index": i, **r}
            rem_mins = 0
            rid = str(r['id'])
            if rid in alert_history:
                try:
                    last_alert_str = alert_history[rid]
                    last_ts = datetime.datetime.strptime(last_alert_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    cd_mins = int(r.get('cooldown_minutes', 0))
                    if cd_mins > 0:
                        elapsed = (now - last_ts).total_seconds()
                        total_cd = cd_mins * 60
                        if elapsed < total_cd:
                            rem_mins = int((total_cd - elapsed) // 60) + 1
                except Exception as e:
                    pass
            rule_out['cooldown_remaining'] = rem_mins
            throttle_entry = throttle_state.get(rid, {})
            rule_out['throttle_state'] = {
                "cooldown_suppressed": int(throttle_entry.get("cooldown_suppressed", 0) or 0),
                "throttle_suppressed": int(throttle_entry.get("throttle_suppressed", 0) or 0),
                "next_allowed_at": throttle_entry.get("next_allowed_at", ""),
            }
            rules.append(rule_out)
            
        return jsonify(rules)

    @app.route('/api/rules/event', methods=['POST'])
    def api_add_event_rule():
        d = request.json
        try:
            throttle = _normalize_rule_throttle(d.get('throttle', ''))
            match_fields = _normalize_match_fields(d.get('match_fields'))
        except ValueError as exc:
            return _err(str(exc), 400)
        filter_value = d.get('filter_value', '')
        if filter_value == 'pce_health':
            return _err("pce_health must be created from the system health rule form", 400)
        cm.add_or_update_rule({
            "id": int(datetime.datetime.now().timestamp()),
            "type": "event",
            "filter_key": "event_type",
            "name": d.get('name', ''),
            "filter_value": filter_value,
            "filter_status": d.get('filter_status', 'all'),
            "filter_severity": d.get('filter_severity', 'all'),
            "desc": d.get('name', ''),
            "rec": "Check Logs",
            "threshold_type": d.get('threshold_type', 'immediate'),
            "threshold_count": int(d.get('threshold_count', 1)),
            "threshold_window": int(d.get('threshold_window', 10)),
            "cooldown_minutes": int(d.get('cooldown_minutes', 10)),
            "throttle": throttle,
            "match_fields": match_fields,
        })
        return jsonify({"ok": True})

    @app.route('/api/rules/system', methods=['POST'])
    def api_add_system_rule():
        d = request.json or {}
        try:
            throttle = _normalize_rule_throttle(d.get('throttle', ''))
        except ValueError as exc:
            return _err(str(exc), 400)
        filter_value = str(d.get('filter_value') or 'pce_health').strip() or 'pce_health'
        if filter_value != 'pce_health':
            return _err("unsupported system rule type", 400)
        cm.add_or_update_rule({
            "id": int(datetime.datetime.now().timestamp()),
            "type": "system",
            "name": d.get('name') or t('rule_pce_health'),
            "filter_value": "pce_health",
            "desc": t('rule_pce_health_desc', default='PCE health check failed.'),
            "rec": t('rule_pce_health_rec', default='Check PCE service status and network connectivity.'),
            "threshold_type": "immediate",
            "threshold_count": 1,
            "threshold_window": 10,
            "cooldown_minutes": int(d.get('cooldown_minutes', 30)),
            "throttle": throttle,
            "match_fields": {},
        })
        return jsonify({"ok": True})

    @app.route('/api/rules/traffic', methods=['POST'])
    def api_add_traffic_rule():
        d = request.json
        try:
            throttle = _normalize_rule_throttle(d.get('throttle', ''))
        except ValueError as exc:
            return _err(str(exc), 400)
        src = (d.get('src') or '').strip()
        dst = (d.get('dst') or '').strip()
        src_label, src_ip = (src, None) if src and '=' in src else (None, src or None)
        dst_label, dst_ip = (dst, None) if dst and '=' in dst else (None, dst or None)
        ex_src = (d.get('ex_src') or '').strip()
        ex_dst = (d.get('ex_dst') or '').strip()
        ex_src_label, ex_src_ip = (ex_src, None) if ex_src and '=' in ex_src else (None, ex_src or None)
        ex_dst_label, ex_dst_ip = (ex_dst, None) if ex_dst and '=' in ex_dst else (None, ex_dst or None)
        port = d.get('port')
        if port:
            try: port = int(port)
            except (ValueError, TypeError): port = None
        ex_port = d.get('ex_port')
        if ex_port:
            try: ex_port = int(ex_port)
            except (ValueError, TypeError): ex_port = None
        proto = d.get('proto')
        if proto:
            try: proto = int(proto)
            except (ValueError, TypeError): proto = None

        cm.add_or_update_rule({
            "id": int(datetime.datetime.now().timestamp()),
            "type": "traffic",
            "name": d.get('name', ''),
            "pd": int(d.get('pd', 2)),
            "port": port, "proto": proto,
            "src_label": src_label, "dst_label": dst_label,
            "src_ip_in": src_ip, "dst_ip_in": dst_ip,
            "ex_port": ex_port,
            "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
            "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip,
            "desc": d.get('name', ''), "rec": "Check Policy",
            "threshold_type": "count",
            "threshold_count": int(d.get('threshold_count', 10)),
            "threshold_window": int(d.get('threshold_window', 10)),
            "cooldown_minutes": int(d.get('cooldown_minutes', 10)),
            "throttle": throttle,
        })
        return jsonify({"ok": True})

    @app.route('/api/rules/bandwidth', methods=['POST'])
    def api_add_bw_rule():
        d = request.json
        try:
            throttle = _normalize_rule_throttle(d.get('throttle', ''))
        except ValueError as exc:
            return _err(str(exc), 400)
        src = (d.get('src') or '').strip()
        dst = (d.get('dst') or '').strip()
        src_label, src_ip = (src, None) if src and '=' in src else (None, src or None)
        dst_label, dst_ip = (dst, None) if dst and '=' in dst else (None, dst or None)
        ex_src = (d.get('ex_src') or '').strip()
        ex_dst = (d.get('ex_dst') or '').strip()
        ex_src_label, ex_src_ip = (ex_src, None) if ex_src and '=' in ex_src else (None, ex_src or None)
        ex_dst_label, ex_dst_ip = (ex_dst, None) if ex_dst and '=' in ex_dst else (None, ex_dst or None)
        port = d.get('port')
        if port:
            try: port = int(port)
            except (ValueError, TypeError): port = None
        ex_port = d.get('ex_port')
        if ex_port:
            try: ex_port = int(ex_port)
            except (ValueError, TypeError): ex_port = None

        cm.add_or_update_rule({
            "id": int(datetime.datetime.now().timestamp()),
            "type": d.get('rule_type', 'bandwidth'),
            "name": d.get('name', ''),
            "pd": int(d.get('pd', -1)),
            "port": port, "proto": None,
            "src_label": src_label, "dst_label": dst_label,
            "src_ip_in": src_ip, "dst_ip_in": dst_ip,
            "ex_port": ex_port,
            "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
            "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip,
            "desc": d.get('name', ''), "rec": "Check Logs",
            "threshold_type": "count",
            "threshold_count": float(d.get('threshold_count', 100)),
            "threshold_window": int(d.get('threshold_window', 10)),
            "cooldown_minutes": int(d.get('cooldown_minutes', 30)),
            "throttle": throttle,
        })
        return jsonify({"ok": True})

    @app.route('/api/rules/<int:idx>')
    def api_get_rule(idx):
        cm.load()
        if 0 <= idx < len(cm.config['rules']):
            return jsonify({"index": idx, **cm.config['rules'][idx]})
        return _err(t("gui_not_found"), 404)

    @app.route('/api/rules/<int:idx>', methods=['PUT'])
    def api_update_rule(idx):
        d = request.json
        if 0 <= idx < len(cm.config['rules']):
            old = cm.config['rules'][idx]
            if 'throttle' in d:
                try:
                    d['throttle'] = _normalize_rule_throttle(d.get('throttle', ''))
                except ValueError as exc:
                    return _err(str(exc), 400)
            if 'match_fields' in d:
                try:
                    d['match_fields'] = _normalize_match_fields(d.get('match_fields'))
                except ValueError as exc:
                    return _err(str(exc), 400)
            old.update(d)
            # Re-parse label/ip fields for traffic and bw/vol
            for prefix in ('src', 'dst', 'ex_src', 'ex_dst'):
                raw = d.get(prefix, '')
                if raw is not None:
                    raw = str(raw).strip()
                    if raw and '=' in raw:
                        old[prefix + '_label'] = raw
                        old[prefix + '_ip_in' if 'ex_' not in prefix else prefix + '_ip'] = None
                    else:
                        old[prefix + '_label'] = None
                        if 'ex_' in prefix:
                            old[prefix + '_ip'] = raw or None
                        else:
                            old[prefix + '_ip_in'] = raw or None
            # Cast numeric fields
            for k in ('port', 'ex_port', 'proto', 'threshold_count', 'threshold_window', 'cooldown_minutes', 'pd'):
                if k in old and old[k] is not None:
                    try: old[k] = int(old[k]) if k != 'threshold_count' else float(old[k])
                    except (ValueError, TypeError): pass
            cm.save()
            return jsonify({"ok": True})
        return _err(t("gui_not_found"), 404)

    @app.route('/api/rules/<int:idx>', methods=['DELETE'])
    def api_delete_rule(idx):
        cm.remove_rules_by_index([idx])
        return jsonify({"ok": True})

    # ??? API: Settings ????????????????????????????????????????????????????
    @app.route('/api/settings')
    def api_get_settings():
        cm.load()
        rpt = cm.config.get("report", {})
        payload = {
            "api": cm.config.get("api", {}),
            "email": cm.config.get("email", {}),
            "smtp": cm.config.get("smtp", {}),
            "alerts": cm.config.get("alerts", {}),
            "settings": cm.config.get("settings", {}),
            "report": {
                "output_dir":      rpt.get("output_dir", "reports/"),
                "retention_days":  rpt.get("retention_days", 30),
            },
            "pce_profiles":   cm.get_pce_profiles(),
            "active_pce_id":  cm.get_active_pce_id(),
        }
        for root in _plugin_config_roots():
            payload.setdefault(root, cm.config.get(root, {}))
        return jsonify(payload)

    @app.route('/api/alert-plugins')
    def api_alert_plugins():
        return jsonify({
            "plugins": {
                name: {
                    "name": meta.name,
                    "display_name": meta.display_name,
                    "description": meta.description,
                    "fields": [
                        {
                            "key": key,
                            "label": field.label,
                            "help": field.help,
                            "required": field.required,
                            "secret": field.secret,
                            "placeholder": field.placeholder,
                            "input_type": field.input_type,
                            "value_type": field.value_type,
                            "list_delimiter": field.list_delimiter,
                            "config_path": list(plugin_config_path(name, key)),
                        }
                        for key, field in meta.fields.items()
                    ],
                }
                for name, meta in PLUGIN_METADATA.items()
            }
        })

    @app.route('/api/settings', methods=['POST'])
    def api_save_settings():
        d = request.json
        if 'api' in d:
            for k in ('url', 'org_id', 'key', 'secret', 'verify_ssl'):
                if k in d['api']:
                    cm.config['api'][k] = d['api'][k]
        if 'email' in d:
            if 'sender' in d['email']:
                cm.config['email']['sender'] = d['email']['sender']
            if 'recipients' in d['email']:
                cm.config['email']['recipients'] = d['email']['recipients']
        if 'smtp' in d:
            cm.config.setdefault('smtp', {}).update(d['smtp'])
        if 'alerts' in d:
            cm.config.setdefault('alerts', {}).update(d['alerts'])
        if 'settings' in d:
            cm.config.setdefault('settings', {}).update(d['settings'])
        if 'report' in d:
            rpt_in = d['report']
            rpt_cfg = cm.config.setdefault('report', {})
            if 'output_dir' in rpt_in:
                rpt_cfg['output_dir'] = rpt_in['output_dir']
            if 'retention_days' in rpt_in:
                try:
                    rpt_cfg['retention_days'] = max(0, int(rpt_in['retention_days']))
                except (TypeError, ValueError):
                    pass
        known_roots = {'api', 'email', 'smtp', 'alerts', 'settings', 'report', 'pce_profiles', 'active_pce_id'}
        for root in _plugin_config_roots():
            if root in known_roots or root not in d:
                continue
            incoming = d.get(root)
            if isinstance(incoming, dict):
                cm.config.setdefault(root, {}).update(incoming)
            else:
                cm.config[root] = incoming
        cm.sync_api_to_active_profile()
        cm.save()
        return jsonify({"ok": True})

    # ── TLS Certificate Management ─────────────────────────────────────────

    @app.route('/api/tls/status', methods=['GET'])
    def api_tls_status():
        cm.load()
        tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
        result = {
            "enabled": bool(tls_cfg.get("enabled")),
            "self_signed": bool(tls_cfg.get("self_signed")),
            "cert_file": tls_cfg.get("cert_file", ""),
            "key_file": tls_cfg.get("key_file", ""),
            # Default auto_renew=True so new installs get protected out of
            # the box; users who explicitly disabled it keep their choice.
            "auto_renew": bool(tls_cfg.get("auto_renew", True)),
            "auto_renew_days": int(tls_cfg.get("auto_renew_days", 30)),
            "default_validity_days": _SELF_SIGNED_VALIDITY_DAYS,
        }
        cert_path = None
        if tls_cfg.get("self_signed"):
            cert_path = os.path.join(_ROOT_DIR, "config", "tls", "self_signed.pem")
            result["cert_info"] = _get_cert_info(cert_path)
        elif tls_cfg.get("cert_file"):
            cert_path = tls_cfg["cert_file"]
            result["cert_info"] = _get_cert_info(cert_path)
        if cert_path:
            result["days_remaining"] = _cert_days_remaining(cert_path)
        return jsonify(result)

    @app.route('/api/tls/config', methods=['POST'])
    def api_tls_config():
        d = request.json or {}
        cm.load()
        gui_cfg = cm.config.setdefault("web_gui", {})
        tls = gui_cfg.setdefault("tls", {})
        tls["enabled"] = bool(d.get("enabled", False))
        tls["self_signed"] = bool(d.get("self_signed", False))
        tls["cert_file"] = str(d.get("cert_file", "")).strip()
        tls["key_file"] = str(d.get("key_file", "")).strip()
        tls["auto_renew"] = bool(d.get("auto_renew", True))
        # Clamp the threshold into a sensible range so the UI can't push a
        # zero (auto-renew every restart) or a negative value.
        try:
            days = int(d.get("auto_renew_days", 30))
        except (TypeError, ValueError):
            days = 30
        tls["auto_renew_days"] = max(1, min(days, 365))
        cm.save()
        return jsonify({"ok": True, "message": "TLS settings saved. Restart the server to apply."})

    @app.route('/api/tls/renew', methods=['POST'])
    def api_tls_renew():
        cm.load()
        tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
        if not tls_cfg.get("self_signed"):
            return jsonify({"ok": False, "error": "Renew is only available for self-signed certificates."}), 400
        cert_dir = os.path.join(_ROOT_DIR, "config", "tls")
        try:
            cert_path, key_path = _generate_self_signed_cert(cert_dir, force=True)
            info = _get_cert_info(cert_path)
            return jsonify({
                "ok": True,
                "message": "Self-signed certificate renewed. Restart the server to apply.",
                "cert_info": info,
            })
        except RuntimeError as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route('/api/pce-profiles', methods=['GET'])
    def api_list_pce_profiles():
        cm.load()
        return jsonify({
            "profiles": cm.get_pce_profiles(),
            "active_pce_id": cm.get_active_pce_id(),
        })

    @app.route('/api/pce-profiles', methods=['POST'])
    def api_pce_profiles_action():
        d = request.json or {}
        action = d.get("action")
        if action == "add":
            profile = {
                "name":       d.get("name", "").strip(),
                "url":        d.get("url", "").strip(),
                "org_id":     d.get("org_id", "1"),
                "key":        d.get("key", ""),
                "secret":     d.get("secret", ""),
                "verify_ssl": bool(d.get("verify_ssl", True)),
            }
            if not profile["name"] or not profile["url"]:
                return _err("name and url required")
            p = cm.add_pce_profile(profile)
            return jsonify({"ok": True, "profile": p})
        elif action == "update":
            pid = d.get("id")
            if not pid:
                return _err("id required")
            updates = {k: d[k] for k in ("name", "url", "org_id", "key", "secret", "verify_ssl") if k in d}
            if not cm.update_pce_profile(int(pid), updates):
                return _err("profile not found")
            return jsonify({"ok": True})
        elif action == "activate":
            pid = d.get("id")
            if not pid:
                return _err("id required")
            if not cm.activate_pce_profile(int(pid)):
                return _err("profile not found")
            return jsonify({"ok": True})
        elif action == "delete":
            pid = d.get("id")
            if not pid:
                return _err("id required")
            if not cm.remove_pce_profile(int(pid)):
                return _err("profile not found")
            return jsonify({"ok": True})
        else:
            return _err("unknown action")

    @app.route('/api/dashboard/queries', methods=['GET'])
    def api_get_dashboard_queries():
        cm.load()
        queries = cm.config.get('settings', {}).get('dashboard_queries', [])
        return jsonify(queries)
        
    @app.route('/api/dashboard/queries', methods=['POST'])
    def api_save_dashboard_query():
        d = request.json or {}
        cm.load()
        if 'settings' not in cm.config:
            cm.config['settings'] = {}
        if 'dashboard_queries' not in cm.config['settings']:
            cm.config['settings']['dashboard_queries'] = []
            
        name = d.get('name', 'My Query')
        rank_by = d.get('rank_by', 'count')
        pd_sel = int(d.get('pd', 3))
        
        src = (d.get('src') or '').strip()
        dst = (d.get('dst') or '').strip()
        src_label, src_ip = (src, None) if src and '=' in src else (None, src or None)
        dst_label, dst_ip = (dst, None) if dst and '=' in dst else (None, dst or None)
        
        ex_src = (d.get('ex_src') or '').strip()
        ex_dst = (d.get('ex_dst') or '').strip()
        ex_src_label, ex_src_ip = (ex_src, None) if ex_src and '=' in ex_src else (None, ex_src or None)
        ex_dst_label, ex_dst_ip = (ex_dst, None) if ex_dst and '=' in ex_dst else (None, ex_dst or None)
        
        port = d.get('port')
        if port:
            try: port = int(port)
            except (ValueError, TypeError): port = None
            
        ex_port = d.get('ex_port')
        if ex_port:
            try: ex_port = int(ex_port)
            except (ValueError, TypeError): ex_port = None
            
        proto = d.get('proto')
        if proto:
            try: proto = int(proto)
            except (ValueError, TypeError): proto = None
            
        idx = d.get('idx')
        query_def = {
            "name": name,
            "rank_by": rank_by,
            "pd": pd_sel,
            "port": port, "proto": proto,
            "src_label": src_label, "dst_label": dst_label,
            "src_ip_in": src_ip, "dst_ip_in": dst_ip,
            "ex_port": ex_port,
            "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
            "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip
        }
        
        if idx is not None and 0 <= int(idx) < len(cm.config['settings']['dashboard_queries']):
            cm.config['settings']['dashboard_queries'][int(idx)] = query_def
        else:
            cm.config['settings']['dashboard_queries'].append(query_def)
            
        cm.save()
        return jsonify({"ok": True})

    @app.route('/api/dashboard/queries/<int:idx>', methods=['DELETE'])
    def api_delete_dashboard_query(idx):
        cm.load()
        if 'settings' in cm.config and 'dashboard_queries' in cm.config['settings']:
            if 0 <= idx < len(cm.config['settings']['dashboard_queries']):
                cm.config['settings']['dashboard_queries'].pop(idx)
                cm.save()
                return jsonify({"ok": True})
        return _err(t("gui_not_found"), 404)

    @app.route('/api/dashboard/snapshot', methods=['GET'])
    def api_dashboard_snapshot():
        cm.load()
        reports_dir = _resolve_reports_dir(cm)

        snapshot_path = os.path.join(reports_dir, 'latest_snapshot.json')
        if not os.path.exists(snapshot_path):
            return jsonify({"ok": False, "error": t("gui_no_snapshot")})
            
        try:
            import json
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({"ok": True, "snapshot": data})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/api/dashboard/audit_summary', methods=['GET'])
    def api_dashboard_audit_summary():
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        summary_path = os.path.join(reports_dir, 'latest_audit_summary.json')
        if not os.path.exists(summary_path):
            return jsonify({"ok": False, "error": t("gui_dashboard_no_audit_summary", default="No audit report summary found.")})
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({"ok": True, "summary": data})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/api/dashboard/policy_usage_summary', methods=['GET'])
    def api_dashboard_policy_usage_summary():
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        summary_path = os.path.join(reports_dir, 'latest_policy_usage_summary.json')
        if not os.path.exists(summary_path):
            return jsonify({"ok": False, "error": t("gui_dashboard_no_policy_usage_summary", default="No policy usage report summary found.")})
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({"ok": True, "summary": data})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

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
                pass
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
                        pass
                success_count += 1
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")
        
        return jsonify({"ok": True, "deleted": success_count, "errors": errors})

    @app.route('/reports/<path:filename>', methods=['GET'])
    def api_serve_report(filename):
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
        # Path traversal protection: ensure resolved path stays within reports_dir
        target = os.path.realpath(os.path.join(reports_dir, filename))
        if not target.startswith(os.path.realpath(reports_dir) + os.sep):
            return jsonify({"ok": False, "error": "Invalid path"}), 403
        return send_from_directory(reports_dir, filename)

    @app.route('/api/reports/generate', methods=['POST'])
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
                pass

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            reporter = Reporter(cm)

            gen = ReportGenerator(cm, api_client=api, config_dir=config_dir)

            source = d.get('source', 'api')
            if source == 'csv':
                if 'file' not in request.files:
                    return jsonify({"ok": False, "error": t("gui_err_no_csv")})
                csv_file = request.files['file']
                if csv_file.filename == '':
                    return jsonify({"ok": False, "error": t("gui_err_empty_csv")})

                import uuid as _uuid
                safe_filename = os.path.basename(csv_file.filename)
                temp_path = os.path.join(tempfile.gettempdir(), f"{_uuid.uuid4().hex}_{safe_filename}")
                csv_file.save(temp_path)
                try:
                    result = gen.generate_from_csv(temp_path)
                finally:
                    try:
                        os.remove(temp_path)
                    except:
                        pass
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

                result = gen.generate_from_api(start_date=start_date, end_date=end_date, filters=report_filters)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_traffic_data")})

            fmt = d.get('format', 'all')
            output_dir = _resolve_reports_dir(cm)
                
            paths = gen.export(result, fmt=fmt, output_dir=output_dir, send_email=str(d.get('send_email', '')).lower() == 'true', reporter=reporter)
            
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _rlog:
                    _rlog.info(f"Completed: {filenames}")
            except Exception:
                pass
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            try:
                if _rlog:
                    _rlog.error(f"Traffic report failed: {e}")
            except Exception:
                pass
            logger.error(f"Report generation failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

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
                pass

            cm.load()
            config_dir = _resolve_config_dir()
            api = ApiClient(cm)
            gen = AuditGenerator(cm, api_client=api, config_dir=config_dir)

            start_date = d.get('start_date')
            end_date = d.get('end_date')

            result = gen.generate_from_api(start_date, end_date)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_audit_data")})

            output_dir = _resolve_reports_dir(cm)
                
            paths = gen.export(result, fmt='all', output_dir=output_dir)
            _write_audit_dashboard_summary(output_dir, result)
            filenames = [os.path.basename(p) for p in paths]
            try:
                if _arlog:
                    _arlog.info(f"Saved: {filenames}")
            except Exception:
                pass
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            try:
                if _arlog:
                    _arlog.error(f"Audit report generation failed: {e}")
            except Exception:
                pass
            logger.error(f"Audit generation failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

    # ??? API: VEN Status Report ????????????????????????????????????????????
    @app.route('/api/ven_status_report/generate', methods=['POST'])
    def api_generate_ven_status_report():
        _vrlog = None
        try:
            from src.report.ven_status_generator import VenStatusGenerator
            from src.api_client import ApiClient
            try:
                from src.module_log import ModuleLog as _ML
                _vrlog = _ML.get("reports")
                _vrlog.separator(f"VEN Status Report {datetime.datetime.now().strftime('%H:%M:%S')}")
            except Exception:
                pass

            cm.load()
            api = ApiClient(cm)
            gen = VenStatusGenerator(cm, api_client=api)

            result = gen.generate()

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_ven_data")})

            output_dir = _resolve_reports_dir(cm)

            paths = gen.export(result, fmt='all', output_dir=output_dir)
            filenames = [os.path.basename(p) for p in paths]
            kpis = result.module_results.get('kpis', [])
            try:
                if _vrlog:
                    _vrlog.info(f"Saved: {filenames}")
            except Exception:
                pass
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count, "kpis": kpis})
        except Exception as e:
            try:
                if _vrlog:
                    _vrlog.error(f"VEN status report generation failed: {e}")
            except Exception:
                pass
            logger.error(f"VEN status report failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

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
                pass

            cm.load()
            api = ApiClient(cm)
            config_dir = _resolve_config_dir()
            gen = PolicyUsageGenerator(cm, api_client=api, config_dir=config_dir)

            start_date = d.get('start_date')
            end_date   = d.get('end_date')

            result = gen.generate_from_api(start_date=start_date, end_date=end_date)

            if result.record_count == 0:
                return jsonify({"ok": False, "error": t("gui_no_pu_data")})

            output_dir = _resolve_reports_dir(cm)
            paths = gen.export(result, fmt='all', output_dir=output_dir)
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
                pass
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
                pass
            logger.error(f"Policy usage report failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

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
                pass
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
            return jsonify({"ok": False, "error": str(e)}), 400

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
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.route('/api/report-schedules/<int:schedule_id>', methods=['DELETE'])
    def api_delete_report_schedule(schedule_id):
        try:
            cm.load()
            ok = cm.remove_report_schedule(schedule_id)
            if not ok:
                return jsonify({"ok": False, "error": t("gui_schedule_not_found")}), 404
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

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
            return jsonify({"ok": False, "error": str(e)}), 400

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
            return jsonify({"ok": False, "error": str(e)}), 400

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
            return jsonify({"ok": False, "error": str(e)}), 400

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
            logger.error(f"Quarantine Search Error: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/api/dashboard/top10', methods=['POST'])
    def api_dashboard_top10():
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

            pd_val = int(d.get("pd", 3))
            if pd_val == 1: pds = ["potentially_blocked"]
            elif pd_val == 2: pds = ["blocked"]
            elif pd_val == 0: pds = ["allowed"]
            else: pds = ["blocked", "potentially_blocked", "allowed"]

            rank_by = d.get("rank_by", "bandwidth")
            
            # Map the inbound payload to the analyzer's query
            params = {
                "start_time": start_time,
                "end_time": end_time,
                "policy_decisions": pds,
                "sort_by": rank_by,
                "search": d.get("search", ""),
                "src_ip_in": d.get("src_ip_in"), "dst_ip_in": d.get("dst_ip_in"),
                "src_label": d.get("src_label"), "dst_label": d.get("dst_label"),
                "ex_src_ip": d.get("ex_src_ip"), "ex_dst_ip": d.get("ex_dst_ip"),
                "ex_src_label": d.get("ex_src_label"), "ex_dst_label": d.get("ex_dst_label"),
                "port": d.get("port"), "ex_port": d.get("ex_port"),
                "proto": d.get("proto"),
                "any_label": d.get("any_label"), "any_ip": d.get("any_ip"),
                "ex_any_label": d.get("ex_any_label"), "ex_any_ip": d.get("ex_any_ip"),
            }
            results = base_ana.query_flows(params)

            # Sort and get top 10
            if rank_by == "bandwidth":
                sorted_v = sorted(results, key=lambda x: x.get("max_bandwidth_mbps", 0), reverse=True)
            elif rank_by == "volume":
                sorted_v = sorted(results, key=lambda x: x.get("total_volume_mb", 0), reverse=True)
            else: # count
                sorted_v = sorted(results, key=lambda x: x.get("total_connections", 0), reverse=True)
            
            top10 = []
            for item in sorted_v[:10]:
                s = item.get('source', {})
                dst = item.get('destination', {})
                sv = item.get('service', {})
                
                s_name = s.get('name', 'N/A')
                d_name = dst.get('name', 'N/A')
                port = sv.get('port', 'All')
                proto_name = sv.get('proto', '')
                svc_name = sv.get('name') or getattr(sv, 'name', '') or ''
                svc_str = f"{proto_name}/{port}"
                if svc_name:
                    svc_str = f"{svc_name} {svc_str}"
                
                # Policy Decision mapping for UI
                flow_pd = item.get("policy_decision", "")
                if flow_pd == "allowed": pd_int = 0
                elif flow_pd == "potentially_blocked": pd_int = 1
                else: pd_int = 2 # default to Blocked if unknown or explicitly blocked
                
                if rank_by == "bandwidth": val_fmt = f"{item.get('max_bandwidth_mbps', 0):.2f} Mbps"
                elif rank_by == "volume":
                    vol_bytes = (item.get('total_volume_mb', 0) or 0) * 1024 * 1024
                    if vol_bytes >= 1024 ** 4:
                        val_fmt = f"{vol_bytes / 1024 ** 4:.2f} TB"
                    elif vol_bytes >= 1024 ** 3:
                        val_fmt = f"{vol_bytes / 1024 ** 3:.2f} GB"
                    elif vol_bytes >= 1024 ** 2:
                        val_fmt = f"{vol_bytes / 1024 ** 2:.1f} MB"
                    elif vol_bytes >= 1024:
                        val_fmt = f"{vol_bytes / 1024:.1f} KB"
                    else:
                        val_fmt = f"{int(vol_bytes)} B"
                else: val_fmt = f"{item.get('total_connections', 0)}"
                
                first_seen = item.get("first_seen", "")
                last_seen = item.get("last_seen", "")
                
                top10.append({
                    "val_fmt": val_fmt,
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    "dir": "<->",
                    "s_name": s_name,
                    "s_ip": s.get('ip', ''),
                    "s_href": s.get('href', ''),
                    "s_process": s.get('process', ''),
                    "s_user": s.get('user', ''),
                    "s_labels": s.get('labels', []),
                    "d_name": d_name,
                    "d_ip": dst.get('ip', ''),
                    "d_href": dst.get('href', ''),
                    "d_process": dst.get('process', ''),
                    "d_user": dst.get('user', ''),
                    "d_labels": dst.get('labels', []),
                    "svc": svc_str,
                    "svc_process": sv.get('process', ''),
                    "svc_user": sv.get('user', ''),
                    "pd": pd_int,
                    "draft_pd": item.get('draft_policy_decision', ''),
                })
                
            return jsonify({"ok": True, "data": top10, "total": len(sorted_v)})
        except Exception as e:
            logger.error(f"Top 10 Query Error: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

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
            logger.error(f"Search Workload Error: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

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
            logger.error(f"Quarantine Apply Error: {e}")
            return jsonify({"ok": False, "error": str(e)})

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
            logger.error(f"Bulk Quarantine Error: {e}")
            return jsonify({"ok": False, "error": str(e)})

    # ??? API: Actions ?????????????????????????????????????????????????????
    @app.route('/api/actions/run', methods=['POST'])
    def api_run_once():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Manually triggered monitoring analysis")
        except Exception:
            pass
        from src.api_client import ApiClient
        from src.reporter import Reporter
        from src.analyzer import Analyzer
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep)
        ana.run_analysis()
        rep.send_alerts()
        return jsonify({"ok": True, "output": "Analysis cycle and alerts completed."})

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
            pass
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
            pass
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
            pass
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
                pass
            return jsonify({"ok": status == 200, "status": status, "body": clean_body[:500]})
        except Exception as e:
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("actions").error(f"Connection failed: {e}")
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/api/shutdown', methods=['POST'])
    def api_shutdown():
        if persistent_mode:
            return jsonify({"ok": False, "error": "Shutdown not allowed in persistent mode"}), 403
            
        func = request.environ.get('werkzeug.server.shutdown')
        if func:
            func()
        else:
            os._exit(0)
        return jsonify({"ok": True})

    # ??? Rule Scheduler API ????????????????????????????????????????????????

    def extract_id(href):
        return href.split('/')[-1] if href else ""

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
        except Exception:
            pass

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
                "id": extract_id(rs['href']),
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
        except Exception:
            pass
        all_rs = api.get_all_rulesets()
        results = []
        q_lower = q.lower()
        for rs in all_rs:
            rs_id = extract_id(rs['href'])
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
                rule_id = extract_id(r['href'])
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
        except Exception:
            pass
        try:
            rs = api.get_ruleset_by_id(rs_id)
        except Exception as e:
            return _err(f"PCE API error: {e}", 502)
        if not rs:
            return _err("Not found", 404)

        ut = rs.get('update_type')
        rs_row = {
            "href": rs['href'],
            "id": extract_id(rs['href']),
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
                "id": extract_id(r['href']),
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
            entry['id'] = extract_id(href)
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
        return jsonify({"ok": True, "id": extract_id(href)})

    @app.route('/api/rule_scheduler/schedules/<path:href>')
    def rs_schedule_detail(href):
        db, _, _ = _get_rs_components()
        href = '/' + href if not href.startswith('/') else href
        conf = db.get(href)
        if not conf:
            return _err("Not found", 404)
        entry = dict(conf)
        entry['href'] = href
        entry['id'] = extract_id(href)
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
            except Exception:
                pass
            if db.delete(href):
                deleted.append(extract_id(href))
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

    return app


# ????????????????????????????????????????????????????????????????????????????????# Launch
# ????????????????????????????????????????????????????????????????????????????????
# Default validity period for self-signed certs. 5 years keeps the cert
# effectively "set and forget" for internal deployments while still giving
# the auto-renew path meaningful runway before expiry.
_SELF_SIGNED_VALIDITY_DAYS = 1825  # 5 years


def _generate_self_signed_cert(cert_dir: str, force: bool = False,
                               days: int = _SELF_SIGNED_VALIDITY_DAYS) -> tuple[str, str]:
    """Generate a self-signed TLS certificate for local HTTPS.

    Args:
        cert_dir: Directory to store cert and key files.
        force: If True, regenerate even if existing cert is still valid.
        days: Validity period in days (default: 5 years).

    Returns:
        (cert_path, key_path) tuple.
    """
    import subprocess

    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "self_signed.pem")
    key_path = os.path.join(cert_dir, "self_signed_key.pem")

    if not force and os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    try:
        subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", str(days), "-nodes",
                "-subj", "/CN=IllumioOps/O=IllumioPCEOps/C=TW",
            ],
            check=True,
            capture_output=True,
        )
        os.chmod(key_path, 0o600)
        print(f"  Self-signed certificate generated ({days} days): {cert_path}")
        return cert_path, key_path
    except FileNotFoundError:
        raise RuntimeError(
            "openssl command not found. Install OpenSSL to use self-signed certificates, "
            "or provide your own cert_file and key_file in config."
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to generate self-signed certificate: {e.stderr.decode()}")


def _cert_days_remaining(cert_path: str) -> int | None:
    """Return the number of days until the cert expires, or None if unknown.

    Negative values mean the cert is already expired. Works via openssl's
    enddate field so no Python cryptography dependency is required.
    """
    import subprocess
    from datetime import datetime, timezone

    if not os.path.exists(cert_path):
        return None
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
            capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    line = result.stdout.strip()
    if not line.startswith("notAfter="):
        return None
    # "notAfter=Sep  3 12:34:56 2030 GMT"
    raw = line[len("notAfter="):].strip()
    try:
        expiry = datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z")
    except ValueError:
        try:
            expiry = datetime.strptime(raw.replace("GMT", "UTC"), "%b %d %H:%M:%S %Y %Z")
        except ValueError:
            return None
    expiry = expiry.replace(tzinfo=timezone.utc)
    delta = expiry - datetime.now(timezone.utc)
    return int(delta.total_seconds() // 86400)


def _maybe_auto_renew_self_signed(cert_dir: str, threshold_days: int = 30) -> tuple[bool, int | None]:
    """Regenerate the self-signed cert if it expires within ``threshold_days``.

    Called at server startup. Returns ``(renewed, days_remaining_after)`` so
    the caller can log what happened.
    """
    cert_path = os.path.join(cert_dir, "self_signed.pem")
    days = _cert_days_remaining(cert_path)
    if days is None:
        # No cert present (or openssl unavailable) — caller will generate
        # one fresh via the normal path.
        return False, None
    if days > threshold_days:
        return False, days
    try:
        _generate_self_signed_cert(cert_dir, force=True)
    except RuntimeError:
        return False, days
    return True, _cert_days_remaining(cert_path)


def _get_cert_info(cert_path: str) -> dict:
    """Read certificate expiry and subject via openssl."""
    import subprocess
    info = {"path": cert_path, "exists": os.path.exists(cert_path)}
    if not info["exists"]:
        return info
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout",
             "-subject", "-enddate", "-startdate"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.strip().splitlines():
            if line.startswith("subject="):
                info["subject"] = line[len("subject="):].strip()
            elif line.startswith("notAfter="):
                info["not_after"] = line[len("notAfter="):].strip()
            elif line.startswith("notBefore="):
                info["not_before"] = line[len("notBefore="):].strip()
        # Check if expired
        check = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-checkend", "0"],
            capture_output=True,
        )
        info["expired"] = check.returncode != 0
        # Check if expiring within 30 days
        check30 = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-checkend", "2592000"],
            capture_output=True,
        )
        info["expiring_soon"] = check30.returncode != 0
    except (FileNotFoundError, subprocess.CalledProcessError):
        info["error"] = "openssl not available"
    return info


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
    tls_cfg = cm.config.get("web_gui", {}).get("tls", {})
    ssl_context = None

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
                cert_file, key_file = _generate_self_signed_cert(cert_dir)
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

    app.run(host=host, port=port, debug=False, use_reloader=False, ssl_context=ssl_context)
