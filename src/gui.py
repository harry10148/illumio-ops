"""
Illumio PCE Ops — Flask Web GUI.
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
import hashlib
import ipaddress
import secrets
import socket as _socket
import struct

try:
    from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

from src.config import ConfigManager
from src.i18n import t
from src import __version__

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub('', text)


def _capture_stdout(func):
    """Run func, capture its stdout, strip ANSI, return as string."""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        func()
    except Exception as e:
        buf.write(f"\nError: {e}\n")
    finally:
        sys.stdout = old
    return _strip_ansi(buf.getvalue())


# ═══════════════════════════════════════════════════════════════════════════════
# Event Catalog (mirrors settings.py)
# ═══════════════════════════════════════════════════════════════════════════════
# We now dynamically import FULL_EVENT_CATALOG from src.settings inside the API route.


# ═══════════════════════════════════════════════════════════════════════════════
# Flask Application Factory
# ═══════════════════════════════════════════════════════════════════════════════

def _hash_password(salt: str, password: str) -> str:
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()

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

def _rst_drop():
    """Close the underlying TCP socket with RST (SO_LINGER 0) and raise to
    prevent Flask from sending any HTTP response.  To a port scanner the
    connection appears reset — identical to 'connection refused' — so the
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
            # l_onoff=1, l_linger=0 → kernel sends RST on close, not FIN
            sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_LINGER,
                            struct.pack('ii', 1, 0))
            try:
                sock.shutdown(_socket.SHUT_RDWR)
            except OSError:
                pass
    except Exception:
        pass
    # Raise — Flask will attempt to write the 500 but the socket is gone
    raise _RstDrop()


class _RstDrop(Exception):
    """Sentinel: request was silently dropped via TCP RST."""


_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_PKG_DIR)


def _resolve_reports_dir(cm_ref: ConfigManager) -> str:
    """Return absolute path to the report output directory."""
    d = cm_ref.config.get('report', {}).get('output_dir', 'reports')
    return d if os.path.isabs(d) else os.path.join(_ROOT_DIR, d)


def _resolve_config_dir() -> str:
    return os.path.join(_ROOT_DIR, 'config')


def _resolve_state_file() -> str:
    return os.path.join(_ROOT_DIR, 'logs', 'state.json')


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


def _create_app(cm: ConfigManager, persistent_mode: bool = False) -> 'Flask':
    app = Flask(__name__, template_folder=os.path.join(_PKG_DIR, 'templates'), static_folder=os.path.join(_PKG_DIR, 'static'))
    app.config['JSON_AS_ASCII'] = False
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    
    # Initialize session secret
    cm.load()
    app.secret_key = cm.config.get("web_gui", {}).get("secret_key", secrets.token_hex(32))
    app.jinja_env.globals.update(t=t)

    @app.errorhandler(_RstDrop)
    def handle_rst_drop(e):
        # Socket is already closed with RST — return an empty Response object
        # so Flask stops processing without logging an unhandled error
        from flask import Response as _Resp
        return _Resp('', status=200)

    @app.before_request
    def security_check():
        if request.endpoint == 'static' or request.path.startswith('/static/'):
            return

        # IP Allowlist check — silently drop with TCP RST (no HTTP response)
        # so port scanners cannot detect an HTTP service on this port
        allowed_ips = cm.config.get("web_gui", {}).get("allowed_ips", [])
        if not _check_ip_allowed(allowed_ips, request.remote_addr):
            logger.warning(f"[GUI] Blocked untrusted IP: {request.remote_addr}")
            _rst_drop()  # closes socket with RST, raises _RstDrop

        # Auth check (always enforced for all GUI modes)
        # Bypass login routes
        if request.path in ['/login', '/api/login', '/logout']:
            return
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return _err(t("gui_err_unauthorized"), 401)
            return redirect('/login')

        # CSRF protection for state-changing requests
        if request.method in ('POST', 'PUT', 'DELETE'):
            # Exempt login (session not yet established)
            if request.path == '/api/login':
                return
            token = request.headers.get('X-CSRF-Token', '')
            if not token or token != session.get('csrf_token'):
                return _err("CSRF token missing or invalid", 403)

    @app.after_request
    def inject_csrf_cookie(response):
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        response.set_cookie('csrf_token', session['csrf_token'], httponly=False, samesite='Strict')
        return response

    # ─── Frontend SPA ─────────────────────────────────────────────────────
    @app.route('/')
    def index():
        cm.load()
        pce_url = _get_active_pce_url(cm)
        return render_template('index.html', pce_url=pce_url)

    # ─── Auth Routes ──────────────────────────────────────────────────────
    @app.route('/login', methods=['GET'])
    def login_page():
        return render_template('login.html')

    @app.route('/api/login', methods=['POST'])
    def api_login():
        d = request.json or {}
        username = d.get('username', '')
        password = d.get('password', '')
        
        cm.load()
        gui_cfg = cm.config.get("web_gui", {})
        
        saved_username = gui_cfg.get("username", "admin")
        saved_hash = gui_cfg.get("password_hash", "")
        saved_salt = gui_cfg.get("password_salt", "")
        

        if username == saved_username and _hash_password(saved_salt, password) == saved_hash:
            session['logged_in'] = True
            return jsonify({"ok": True})
            
        return jsonify({"ok": False, "error": t("gui_err_invalid_auth")}), 401

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.route('/api/security', methods=['GET'])
    def api_security_get():
        cm.load()
        gui_cfg = cm.config.get('web_gui', {})
        return jsonify({
            "username": gui_cfg.get("username", "admin"),
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
            gui_cfg["allowed_ips"] = d["allowed_ips"]
            
        if "new_password" in d and d["new_password"]:
            # Check old password if there's already one set
            if gui_cfg.get("password_hash"):
                old_pass = d.get("old_password", "")
                salt = gui_cfg.get("password_salt", "")
                if _hash_password(salt, old_pass) != gui_cfg.get("password_hash"):
                    return jsonify({"ok": False, "error": t("gui_err_invalid_old_pass")}), 401
                    
            salt = secrets.token_hex(8)
            gui_cfg["password_salt"] = salt
            gui_cfg["password_hash"] = _hash_password(salt, d["new_password"])
            
        cm.save()
        return jsonify({"ok": True})

    # ─── API: Status ──────────────────────────────────────────────────────
    @app.route('/api/ui_translations')
    def api_ui_translations():
        lang = cm.config.get("settings", {}).get("language", "en")
        from src.i18n import MESSAGES
        ui_dict = {k: v for k, v in MESSAGES.get(lang, MESSAGES["en"]).items() if k.startswith("gui_")}
        return jsonify(ui_dict)

    @app.route('/api/status')
    def api_status():
        cm.load()
        
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

        return jsonify({
            "version": __version__,
            "api_url": _get_active_pce_url(cm),
            "rules_count": len(cm.config['rules']),
            "health_check": cm.config['settings'].get('enable_health_check', True),
            "language": cm.config.get('settings', {}).get('language', 'en'),
            "theme": cm.config.get('settings', {}).get('theme', 'dark'),
            "timezone": cm.config.get('settings', {}).get('timezone', 'local'),
            "cooldowns": cooldowns
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
        from src.settings import FULL_EVENT_CATALOG, ACTION_EVENTS
        from src.i18n import t
        # Build dictionary with translated names
        translated_catalog = {}
        for category, events in FULL_EVENT_CATALOG.items():
            trans_cat = t('cat_' + category.replace(' ', '_').lower(), default=category)
            # Combine Agent Health details
            if category == "Agent Health Detail":
                trans_cat = t('cat_agent_health', default="Agent Health")

            if trans_cat not in translated_catalog:
                translated_catalog[trans_cat] = {}

            for event_id, translation_key in events.items():
                translated_catalog[trans_cat][event_id] = t(translation_key, default=translation_key)
        # Return catalog along with list of events that support status/severity filtering
        return jsonify({'catalog': translated_catalog, 'action_events': ACTION_EVENTS})

    # ─── API: Rules CRUD ──────────────────────────────────────────────────
    @app.route('/api/rules')
    def api_rules():
        cm.load()
        
        # Load state to get cooldowns
        alert_history = {}
        try:
            STATE_FILE = _resolve_state_file()
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    alert_history = state.get("alert_history", {})
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
            rules.append(rule_out)
            
        return jsonify(rules)

    @app.route('/api/rules/event', methods=['POST'])
    def api_add_event_rule():
        d = request.json
        cm.add_or_update_rule({
            "id": int(datetime.datetime.now().timestamp()),
            "type": "event",
            "name": d.get('name', ''),
            "filter_key": "event_type",
            "filter_value": d.get('filter_value', ''),
            "filter_status": d.get('filter_status', 'all'),
            "filter_severity": d.get('filter_severity', 'all'),
            "desc": d.get('name', ''),
            "rec": "Check Logs",
            "threshold_type": d.get('threshold_type', 'immediate'),
            "threshold_count": int(d.get('threshold_count', 1)),
            "threshold_window": int(d.get('threshold_window', 10)),
            "cooldown_minutes": int(d.get('cooldown_minutes', 10))
        })
        if d.get('enable_health_check') is not None:
            cm.config['settings']['enable_health_check'] = bool(d['enable_health_check'])
            cm.save()
        return jsonify({"ok": True})

    @app.route('/api/rules/traffic', methods=['POST'])
    def api_add_traffic_rule():
        d = request.json
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
            "cooldown_minutes": int(d.get('cooldown_minutes', 10))
        })
        return jsonify({"ok": True})

    @app.route('/api/rules/bandwidth', methods=['POST'])
    def api_add_bw_rule():
        d = request.json
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
            "cooldown_minutes": int(d.get('cooldown_minutes', 30))
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

    # ─── API: Settings ────────────────────────────────────────────────────
    @app.route('/api/settings')
    def api_get_settings():
        cm.load()
        rpt = cm.config.get("report", {})
        return jsonify({
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
        cm.sync_api_to_active_profile()
        cm.save()
        return jsonify({"ok": True})

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

    # ─── API: Reports ──────────────────────────────────────────────────────
    @app.route('/api/reports', methods=['GET'])
    def api_list_reports():
        cm.load()
        reports_dir = _resolve_reports_dir(cm)

        if not os.path.exists(reports_dir):
            return jsonify({"ok": True, "reports": []})
        
        reports = []
        for f in os.listdir(reports_dir):
            if f.endswith('.html') or f.endswith('.zip'):
                stat = os.stat(os.path.join(reports_dir, f))
                reports.append({
                    "filename": f,
                    "mtime": stat.st_mtime,
                    "size": stat.st_size
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
                success_count += 1
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")
        
        return jsonify({"ok": True, "deleted": success_count, "errors": errors})

    @app.route('/reports/<path:filename>', methods=['GET'])
    def api_serve_report(filename):
        cm.load()
        reports_dir = _resolve_reports_dir(cm)
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

                safe_filename = os.path.basename(csv_file.filename)
                temp_path = os.path.join(tempfile.gettempdir(), safe_filename)
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
            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            logger.error(f"Report generation failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

    @app.route('/api/audit_report/generate', methods=['POST'])
    def api_generate_audit_report():
        d = request.json or {}
        try:
            from src.report.audit_generator import AuditGenerator
            from src.api_client import ApiClient
            
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
            filenames = [os.path.basename(p) for p in paths]

            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count})
        except Exception as e:
            logger.error(f"Audit generation failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

    # ─── API: VEN Status Report ────────────────────────────────────────────
    @app.route('/api/ven_status_report/generate', methods=['POST'])
    def api_generate_ven_status_report():
        try:
            from src.report.ven_status_generator import VenStatusGenerator
            from src.api_client import ApiClient

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

            return jsonify({"ok": True, "files": filenames, "record_count": result.record_count, "kpis": kpis})
        except Exception as e:
            logger.error(f"VEN status report failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

    # ─── API: Policy Usage Report ──────────────────────────────────────────
    @app.route('/api/policy_usage_report/generate', methods=['POST'])
    def api_generate_policy_usage_report():
        d = request.json or {}
        try:
            from src.report.policy_usage_generator import PolicyUsageGenerator
            from src.api_client import ApiClient

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
            filenames = [os.path.basename(p) for p in paths]
            kpis = result.module_results.get('mod00', {}).get('kpis', [])

            return jsonify({"ok": True, "files": filenames,
                            "record_count": result.record_count, "kpis": kpis})
        except Exception as e:
            logger.error(f"Policy usage report failed: {e}", exc_info=True)
            return jsonify({"ok": False, "error": str(e)})

    # ─── API: Report Schedules ─────────────────────────────────────────────

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
                    now_str = datetime.datetime.utcnow().isoformat()
                    scheduler._save_state(schedule_id, now_str, "success")
                except Exception as e:
                    now_str = datetime.datetime.utcnow().isoformat()
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

    # ─── API: Traffic & Quarantine ─────────────────────────────────────────
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
            now = datetime.datetime.utcnow()
            start_time = (now - datetime.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            
            pd_val = str(d.get("policy_decision", "3"))
            if pd_val == "1": pds = ["potentially_blocked"]
            elif pd_val == "2": pds = ["blocked"]
            elif pd_val == "0": pds = ["allowed"]
            else: pds = ["blocked", "potentially_blocked", "allowed"]

            # Map the inbound payload to the analyzer's query
            params = {
                "start_time": start_time,
                "end_time": end_time,
                "policy_decisions": pds,
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
            now = datetime.datetime.utcnow()
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
                    "dir": "→",
                    "s_name": s_name,
                    "s_ip": s.get('ip', ''),
                    "s_href": s.get('href', ''),
                    "s_labels": s.get('labels', []),
                    "d_name": d_name,
                    "d_ip": dst.get('ip', ''),
                    "d_href": dst.get('href', ''),
                    "d_labels": dst.get('labels', []),
                    "svc": svc_str,
                    "svc_process": sv.get('process', ''),
                    "svc_user": sv.get('user', ''),
                    "pd": pd_int
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
        hrefs = d.get('hrefs', [])
        level = d.get('level')
        try:
            from src.api_client import ApiClient
            api = ApiClient(cm)
            q_hrefs = api.check_and_create_quarantine_labels()
            target_label_href = q_hrefs.get(level)

            results = {"success": 0, "failed": []}
            import concurrent.futures

            def process_wl(href):
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

    # ─── API: Actions ─────────────────────────────────────────────────────
    @app.route('/api/actions/run', methods=['POST'])
    def api_run_once():
        def work():
            from src.api_client import ApiClient
            from src.reporter import Reporter
            from src.analyzer import Analyzer
            api = ApiClient(cm)
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep)
            ana.run_analysis()
            rep.send_alerts()
        output = _capture_stdout(work)
        return jsonify({"ok": True, "output": output})

    @app.route('/api/actions/debug', methods=['POST'])
    def api_debug():
        d = request.json or {}
        mins = int(d.get('mins', 30))
        pd_sel = int(d.get('pd_sel', 3))
        def work():
            from src.api_client import ApiClient
            from src.reporter import Reporter
            from src.analyzer import Analyzer
            api = ApiClient(cm)
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep)
            ana.run_debug_mode(mins=mins, pd_sel=pd_sel)
        output = _capture_stdout(work)
        return jsonify({"ok": True, "output": output})

    @app.route('/api/actions/test-alert', methods=['POST'])
    def api_test_alert():
        def work():
            from src.reporter import Reporter
            Reporter(cm).send_alerts(force_test=True)
        output = _capture_stdout(work)
        return jsonify({"ok": True, "output": output})

    @app.route('/api/actions/best-practices', methods=['POST'])
    def api_best_practices():
        output = _capture_stdout(lambda: cm.load_best_practices())
        return jsonify({"ok": True, "output": output})

    @app.route('/api/actions/test-connection', methods=['POST'])
    def api_test_conn():
        try:
            from src.api_client import ApiClient
            api = ApiClient(cm)
            status, body = api.check_health()
            body_text = str(body)
            clean_body = _strip_ansi(body_text)
            return jsonify({"ok": status == 200, "status": status, "body": clean_body[:500]})
        except Exception as e:
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

    # ─── Rule Scheduler API ────────────────────────────────────────────────

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
            "enabled": rs_cfg.get("enabled", False),
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
            days_str = ",".join([d[:3] for d in db_entry['days']]) if len(db_entry['days']) < 7 else t('rs_action_everyday')
            act_str = t('rs_action_enable_in_window') if db_entry['action'] == 'allow' else t('rs_action_disable_in_window')
            note = f"[📅 {t('rs_sch_tag_recurring')}: {days_str} {db_entry['start']}-{db_entry['end']} {act_str}]"
        else:
            db_entry['expire_at'] = data['expire_at']
            note = f"[⏳ {t('rs_sch_tag_expire')}: {data['expire_at'].replace('T', ' ')}]"

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
        logs = engine.check(silent=True)
        cleaned = [_strip_ansi(l) for l in logs]
        return jsonify({"ok": True, "logs": cleaned})

    # ─── End Rule Scheduler API ────────────────────────────────────────────

    return app


# ═══════════════════════════════════════════════════════════════════════════════
# Launch
# ═══════════════════════════════════════════════════════════════════════════════

def launch_gui(cm: ConfigManager = None, host='0.0.0.0', port=5001, persistent_mode=False):
    if not HAS_FLASK:
        print("Flask is not installed. The Web GUI requires Flask.")
        print("Install it with:")
        print("  pip install flask")
        return

    if cm is None:
        cm = ConfigManager()

    app = _create_app(cm, persistent_mode=persistent_mode)
    print(f"\n  Illumio PCE Ops — Web GUI")
    print(f"  Open in browser: http://127.0.0.1:{port}")
    if persistent_mode:
        print(f"  Running in persistent mode (Press Ctrl+C to stop the entire daemon).")
    else:
        print(f"  Press Ctrl+C to stop.\n")

    if not persistent_mode:
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{port}')).start()
        
    app.run(host=host, port=port, debug=False, use_reloader=False)


# ═══════════════════════════════════════════════════════════════════════════════
# Embedded SPA HTML
# ═══════════════════════════════════════════════════════════════════════════════

_SPA_HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Illumio PCE Ops</title>
<style>
:root {
  --bg: #1a2c32; --bg2: #24393f; --bg3: #2d454c;
  --fg: #F5F5F5; --dim: #989A9B; --accent: #FF5500;
  --accent2: #FFA22F; --success: #299b65; --warn: #FFB74A;
  --danger: #f43f51; --border: #325158;
  --radius: 10px; --shadow: 0 4px 24px rgba(0,0,0,.4);
}
[data-theme="light"] {
  --bg: #F5F5F5; --bg2: #FFFFFF; --bg3: #EAEBEB;
  --fg: #313638; --dim: #6F7274; --accent: #FF5500;
  --accent2: #F97607; --success: #166644; --warn: #FFA22F;
  --danger: #be122f; --border: #D6D7D7;
  --shadow: 0 2px 10px rgba(0,0,0,.05);
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--fg); min-height:100vh; }
a { color:var(--accent2); }

/* Header */
.header { background:linear-gradient(135deg,var(--bg2),var(--bg3)); padding:16px 28px; display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--border); }
.header h1 { font-size:1.3rem; font-weight:700; background:linear-gradient(135deg,var(--accent2),var(--success)); -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.header .meta { color:var(--dim); font-size:.85rem; }

/* Tabs */
.tabs { display:flex; gap:2px; background:var(--bg2); padding:6px 20px 0; border-bottom:1px solid var(--border); }
.tab { padding:10px 22px; cursor:pointer; border-radius:var(--radius) var(--radius) 0 0; color:var(--dim); font-weight:600; font-size:.9rem; transition:.2s; border:1px solid transparent; border-bottom:none; }
.tab:hover { color:var(--fg); background:var(--bg3); }
.tab.active { color:var(--accent2); background:var(--bg); border-color:var(--border); }

/* Panel */
.panel { display:none; padding:24px; animation:fadeIn .2s; }
.panel.active { display:block; }
@keyframes fadeIn { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:none} }

/* Cards */
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin-bottom:20px; }
.card { background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius); padding:18px; text-align:center; }
.card .label { color:var(--dim); font-size:.8rem; margin-bottom:6px; }
.card .value { font-size:1.8rem; font-weight:700; color:var(--accent2); }
.card .value.ok { color:var(--success); }
.card .value.err { color:var(--danger); }

/* Buttons */
.btn { display:inline-flex; align-items:center; gap:6px; padding:9px 18px; border:none; border-radius:8px; font-size:.88rem; font-weight:600; cursor:pointer; transition:.15s; }
.btn-primary { background:var(--accent); color:#fff; }
.btn-primary:hover { background:var(--accent2); color:#1a2c32; }
.btn-success { background:#166644; color:#fff; }
.btn-success:hover { background:var(--success); color:#fff; }
.btn-danger { background:#be122f; color:#fff; }
.btn-danger:hover { background:var(--danger); }
.btn-warn { background:#d97706; color:#fff; }
.btn-warn:hover { background:var(--warn); color:#1a2c32; }
.btn-sm { padding:6px 12px; font-size:.8rem; }
.btn:disabled { opacity:.5; cursor:not-allowed; }

/* Forms */
.form-group { margin-bottom:12px; }
.form-group label { display:block; color:var(--dim); font-size:.82rem; margin-bottom:4px; font-weight:600; }
.form-group input, .form-group select { width:100%; background:var(--bg); border:1px solid var(--border); color:var(--fg); padding:8px 12px; border-radius:6px; font-size:.9rem; }
.form-group input:focus, .form-group select:focus { outline:none; border-color:var(--accent); }
.form-row { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.form-row-3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }

/* Fieldset */
fieldset { border:1px solid var(--border); border-radius:var(--radius); padding:16px; margin-bottom:16px; }
legend { color:var(--accent2); font-weight:700; font-size:.9rem; padding:0 8px; }

/* Table */
.rule-table { width:100%; border-collapse:collapse; margin-top:12px; table-layout:fixed; }
.rule-table th, .rule-table td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--border); font-size:.88rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rule-table th { color:var(--dim); font-weight:600; background:var(--bg2); position:relative; }
.rule-table tr:hover td { background:var(--bg3); }
.resizer { position:absolute; top:25%; right:0; width:4px; height:50%; cursor:col-resize; user-select:none; z-index:2; transition: background 0.2s; background:var(--border); border-radius:2px; }
.resizer:hover, .resizer:active { background:var(--accent); width:6px; }

/* Log */
.log-box { background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius); padding:14px; font-family:'Cascadia Code','Fira Code',monospace; font-size:.82rem; color:var(--fg); max-height:360px; overflow-y:auto; white-space:pre-wrap; word-break:break-all; line-height:1.6; }

/* Actions */
.action-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; margin-bottom:20px; }
.action-card { background:var(--bg2); border:1px solid var(--border); border-radius:var(--radius); padding:18px; display:flex; flex-direction:column; gap:10px; }
.action-card h3 { font-size:.95rem; color:var(--accent2); }
.action-card p { font-size:.8rem; color:var(--dim); flex:1; }

/* Modal */
.modal-bg { display:none; position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:100; align-items:center; justify-content:center; }
.modal-bg.show { display:flex; }
.modal { background:var(--bg); border:1px solid var(--border); border-radius:14px; padding:24px; width:560px; max-width:95vw; max-height:85vh; overflow-y:auto; box-shadow:var(--shadow); }
.modal h2 { font-size:1.1rem; color:var(--accent2); margin-bottom:16px; }
.modal-actions { display:flex; gap:8px; justify-content:flex-end; margin-top:16px; }

/* Toolbar */
.toolbar { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; align-items:center; }
.toolbar .spacer { flex:1; }
.badge { background:var(--accent); color:#fff; padding:2px 10px; border-radius:20px; font-size:.78rem; font-weight:700; }

/* Radio group */
.radio-group { display:flex; gap:12px; flex-wrap:wrap; }
.radio-group label { display:flex; align-items:center; gap:4px; color:var(--fg); font-size:.88rem; cursor:pointer; }
.radio-group input[type=radio] { accent-color:var(--accent); }

/* Checkbox */
.chk label { display:flex; align-items:center; gap:6px; color:var(--fg); font-size:.88rem; cursor:pointer; }
.chk input[type=checkbox] { accent-color:var(--accent); }

/* Toast */
.toast { position:fixed; bottom:24px; right:24px; background:var(--success); color:#000; padding:12px 20px; border-radius:8px; font-weight:600; font-size:.88rem; z-index:200; opacity:0; transition:.3s; pointer-events:none; }
.toast.show { opacity:1; }
.toast.err { background:var(--danger); color:#fff; }
</style>
</head>
<body>

<div class="header">
  <h1 data-i18n="gui_title">◆ Illumio PCE Ops</h1>
  <div style="display:flex;align-items:center;gap:14px"><span class="meta" id="hdr-meta">Loading...</span><button class="btn btn-danger btn-sm" onclick="stopGui()" title="Stop Web GUI" data-i18n="gui_stop">⏹ Stop</button></div>
</div>

<div class="tabs">
  <div class="tab active" onclick="switchTab('dashboard')" data-i18n="gui_tab_dashboard">Dashboard</div>
  <div class="tab" onclick="switchTab('rules')" data-i18n="gui_tab_rules">Rules</div>
  <div class="tab" onclick="switchTab('settings')" data-i18n="gui_tab_settings">Settings</div>
  <div class="tab" onclick="switchTab('actions')" data-i18n="gui_tab_actions">Actions</div>
</div>

<!-- ═══ Dashboard ═══ -->
<div class="panel active" id="p-dashboard">
  <div class="cards">
    <div class="card"><div class="label" data-i18n="gui_active_rules">Active Rules</div><div class="value" id="d-rules">—</div></div>
    <div class="card"><div class="label" data-i18n="gui_health_check">Health Check</div><div class="value" id="d-health">—</div></div>
    <div class="card"><div class="label" data-i18n="gui_language">Language</div><div class="value" id="d-lang">—</div></div>
  </div>
  <fieldset id="cd-field" style="display:none;margin-bottom:14px;border:none;padding:0;">
    <div id="cd-list" class="cards" style="margin-bottom:0;"></div>
  </fieldset>
  <fieldset style="margin-bottom:14px;">
    <legend><span data-i18n="gui_top10_title" style="font-size:1.05rem;">Top 10 Query Report</span></legend>
    <div style="display:flex;gap:8px;margin-bottom:14px;align-items:center;">
       <label data-i18n="gui_window_min" style="font-weight:600;color:var(--dim);font-size:0.85rem;">Window (min):</label>
       <input id="d-global-min" type="number" value="30" style="width:80px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:4px 8px;border-radius:4px;">
       <span style="flex:1"></span>
       <button class="btn btn-warn btn-sm" onclick="openQueryModal()" data-i18n="gui_add_query_widget">➕ Add Query Widget</button>
       <button class="btn btn-primary btn-sm" onclick="runAllQueries()" data-i18n="gui_run_all_queries">▶ Run All</button>
    </div>
    <div id="d-queries-container" style="display:flex;flex-direction:column;gap:16px;">
        <!-- Query Profile Tables generated dynamically -->
    </div>
  </fieldset>
</div>

<!-- ═══ Rules ═══ -->
<div class="panel" id="p-rules">
  <div class="toolbar">
    <span style="font-size:1.1rem;font-weight:700;color:var(--accent2)" data-i18n="gui_tab_rules">Rules</span>
    <span class="badge" id="r-badge">0</span>
    <button class="btn btn-sm" style="margin-left:8px;background:var(--dim);color:#fff" onclick="openModal('m-help')" data-i18n="gui_param_guide">📖 Parameter Guide</button>
    <div class="spacer"></div>
    <button class="btn btn-warn btn-sm" onclick="openModal('m-event')" data-i18n="gui_add_event">📋 + Event</button>
    <button class="btn btn-warn btn-sm" onclick="openModal('m-traffic')" data-i18n="gui_add_traffic">🚦 + Traffic</button>
    <button class="btn btn-warn btn-sm" onclick="openModal('m-bw')" data-i18n="gui_add_bw">📊 + BW/Vol</button>
    <button class="btn btn-danger btn-sm" onclick="deleteSelected()" data-i18n="gui_delete">🗑 Delete</button>
  </div>
  <table class="rule-table">
    <thead><tr><th style="width:30px"><input type="checkbox" id="r-chkall" onchange="toggleAll(this)"></th><th data-i18n="gui_col_type">Type</th><th data-i18n="gui_col_name">Name</th><th style="width:110px" data-i18n="gui_col_status">Status</th><th data-i18n="gui_col_condition">Condition</th><th data-i18n="gui_col_filters">Filters</th><th style="width:50px" data-i18n="gui_col_edit">Edit</th></tr></thead>
    <tbody id="r-body"></tbody>
  </table>
</div>

<!-- ═══ Settings ═══ -->
<div class="panel" id="p-settings">
  <div class="cards" style="margin-bottom:14px;">
    <div class="card"><div class="label" data-i18n="gui_api_status">API Status</div><div class="value" id="d-api">—</div></div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:14px;">
    <button class="btn btn-primary" onclick="testConn()" data-i18n="gui_test_conn">🔗 Test Connection</button>
  </div>
  <div class="log-box" id="s-log" style="height:80px;margin-bottom:14px;font-size:0.85rem;">[Ready]</div>
  <div id="s-form"></div>
  <div style="text-align:right;margin-top:16px;">
    <button class="btn btn-success" onclick="saveSettings()" data-i18n="gui_save_all">💾 Save All Settings</button>
  </div>
</div>

<!-- ═══ Actions ═══ -->
<div class="panel" id="p-actions">
  <div class="action-grid">
    <div class="action-card"><h3 data-i18n="gui_run_once">▶ Run Monitor Once</h3><p data-i18n="gui_run_once_desc">Execute full cycle: Health → Fetch → Analyze → Alert</p><button class="btn btn-primary" onclick="runAction('run')" data-i18n="gui_run_btn">Run</button></div>
    <div class="action-card"><h3 data-i18n="gui_debug_mode">🔍 Debug Mode</h3><p data-i18n="gui_debug_desc">Sandbox mode — no alerts, no state updates</p>
      <div class="form-row" style="margin-bottom:8px;">
        <div class="form-group"><label data-i18n="gui_window_min">Window (min)</label><input id="a-debug-mins" value="30"></div>
        <div class="form-group"><label data-i18n="gui_policy_dec">Policy Dec.</label><select id="a-debug-pd"><option value="1" data-i18n="gui_pd_blocked">Blocked</option><option value="2" data-i18n="gui_pd_allowed">Allowed</option><option value="3" data-i18n="gui_pd_all" selected>All</option></select></div>
      </div>
      <button class="btn btn-primary" onclick="runDebug()" data-i18n="gui_run_debug">Run Debug</button>
    </div>
    <div class="action-card"><h3 data-i18n="gui_test_alert">📧 Send Test Alert</h3><p data-i18n="gui_test_alert_desc">Verify Email / LINE / Webhook delivery</p><button class="btn btn-primary" onclick="runAction('test-alert')" data-i18n="gui_send">Send</button></div>
    <div class="action-card"><h3 data-i18n="gui_best_practices">📋 Load Best Practices</h3><p data-i18n="gui_best_practices_desc">Replace ALL existing rules with recommended defaults</p><button class="btn btn-danger" onclick="confirmBestPractices()" data-i18n="gui_load">Load</button></div>
  </div>
  <h3 style="color:var(--accent2);margin-bottom:8px;" data-i18n="gui_output">Output</h3>
  <div class="log-box" id="a-log"></div>
</div>

<!-- ═══ Modals ═══ -->
<!-- Dashboard Query Profile Modal -->
<div class="modal-bg" id="m-query"><div class="modal">
  <h2><span data-i18n="gui_add_query_widget" id="mq-title">Add Query Widget</span></h2>
  <input type="hidden" id="dq-idx" value="-1">
  <div class="form-row"><div class="form-group"><label data-i18n="gui_query_widget_name">Widget Name</label><input id="dq-name" placeholder="E.g. Core Services Top Clients"></div><div class="form-group"><label data-i18n="gui_rank_by">Rank By</label><select id="dq-rank"><option value="count" data-i18n="gui_rank_count">Connection Count</option><option value="volume" data-i18n="gui_rank_volume">Total Volume (MB)</option><option value="bandwidth" data-i18n="gui_rank_bw">Max Bandwidth (Mbps)</option></select></div></div>
  <fieldset><legend data-i18n="gui_policy_dec">Policy Decision</legend><div class="radio-group" id="dq-pd-group">
    <label><input type="radio" name="dq-pd" value="3" checked> <span data-i18n="gui_pd_all">All</span></label>
    <label><input type="radio" name="dq-pd" value="2"> <span data-i18n="gui_pd_blocked">Blocked</span></label>
    <label><input type="radio" name="dq-pd" value="1"> <span data-i18n="gui_pd_potential">Potential</span></label>
    <label><input type="radio" name="dq-pd" value="0"> <span data-i18n="gui_pd_allowed">Allowed</span></label>
  </div></fieldset>
  <fieldset><legend data-i18n="gui_col_filters">Filters</legend>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_port">Port</label><input id="dq-port" placeholder="e.g. 80, 443"></div><div class="form-group"><label data-i18n="gui_protocol">Protocol</label><select id="dq-proto"><option value="" data-i18n="gui_both">Both</option><option value="6" data-i18n="gui_tcp">TCP</option><option value="17" data-i18n="gui_udp">UDP</option></select></div></div>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_source">Source (Label/IP)</label><input id="dq-src" placeholder="e.g. role=Web, 10.0.0.0/8, 192.168.1.1"></div><div class="form-group"><label data-i18n="gui_dest">Destination (Label/IP)</label><input id="dq-dst" placeholder="e.g. app=DB, 10.1.1.5"></div></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_excludes">Excludes (Optional)</legend>
    <div class="form-row-3"><div class="form-group"><label data-i18n="gui_ex_port">Exclude Port</label><input id="dq-expt" placeholder="e.g. 22"></div><div class="form-group"><label data-i18n="gui_ex_src">Exclude Source</label><input id="dq-exsrc" placeholder="e.g. env=Kube, 10.9.9.9"></div><div class="form-group"><label data-i18n="gui_ex_dest">Exclude Destination</label><input id="dq-exdst" placeholder="e.g. 8.8.8.8"></div></div>
  </fieldset>
  <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal('m-query')" data-i18n="gui_cancel">Cancel</button><button class="btn btn-success" onclick="saveDashboardQuery()" data-i18n="gui_save">💾 Save</button></div>
</div></div>

<!-- Event -->
<div class="modal-bg" id="m-event"><div class="modal">
  <h2><span data-i18n="gui_add_event_rule" id="me-title">Add Event Rule</span></h2>
  <div class="form-group"><label data-i18n="gui_category">Category</label><select id="ev-cat" onchange="populateEvents()"><option value="" data-i18n="gui_select">Select...</option></select></div>
  <div class="form-group"><label data-i18n="gui_event_type">Event Type</label><select id="ev-type"><option value="" data-i18n="gui_select_first">Select category first</option></select></div>
  <fieldset><legend data-i18n="gui_threshold">Threshold</legend>
    <div class="form-group"><label data-i18n="gui_type">Type</label><div class="radio-group"><label><input type="radio" name="ev-tt" value="immediate" checked> <span data-i18n="gui_tt_immediate">Immediate</span></label><label><input type="radio" name="ev-tt" value="count"> <span data-i18n="gui_tt_count">Cumulative</span></label></div></div>
    <div class="form-row-3">
      <div class="form-group"><label data-i18n="gui_count">Count</label><input id="ev-cnt" type="number" value="5"></div>
      <div class="form-group"><label data-i18n="gui_window_min">Window (min)</label><input id="ev-win" type="number" value="10"></div>
      <div class="form-group"><label data-i18n="gui_cooldown">Cooldown (min)</label><input id="ev-cd" type="number" value="10"></div>
    </div>
  </fieldset>
  <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal('m-event')" data-i18n="gui_cancel">Cancel</button><button class="btn btn-success" onclick="saveEvent()" data-i18n="gui_save">💾 Save</button></div>
</div></div>

<!-- Traffic -->
<div class="modal-bg" id="m-traffic"><div class="modal">
  <h2><span data-i18n="gui_add_traffic_rule" id="mt-title">Add Traffic Rule</span></h2>
  <div class="form-group"><label data-i18n="gui_rule_name">Rule Name</label><input id="tr-name"></div>
  <fieldset><legend data-i18n="gui_policy_dec">Policy Decision</legend><div class="radio-group">
    <label><input type="radio" name="tr-pd" value="2" checked> <span data-i18n="gui_pd_blocked">Blocked</span></label>
    <label><input type="radio" name="tr-pd" value="1"> <span data-i18n="gui_pd_potential">Potential</span></label>
    <label><input type="radio" name="tr-pd" value="0"> <span data-i18n="gui_pd_allowed">Allowed</span></label>
    <label><input type="radio" name="tr-pd" value="-1"> <span data-i18n="gui_pd_all">All</span></label>
  </div></fieldset>
  <fieldset><legend data-i18n="gui_col_filters">Filters</legend>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_port">Port</label><input id="tr-port" placeholder="e.g. 80, 443"></div><div class="form-group"><label data-i18n="gui_protocol">Protocol</label><select id="tr-proto"><option value="" data-i18n="gui_both">Both</option><option value="6" data-i18n="gui_tcp">TCP</option><option value="17" data-i18n="gui_udp">UDP</option></select></div></div>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_source">Source (Label/IP)</label><input id="tr-src" placeholder="e.g. role=Web, 10.0.0.0/8, 192.168.1.1"></div><div class="form-group"><label data-i18n="gui_dest">Destination (Label/IP)</label><input id="tr-dst" placeholder="e.g. app=DB, 10.1.1.5"></div></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_excludes">Excludes (Optional)</legend>
    <div class="form-row-3"><div class="form-group"><label data-i18n="gui_ex_port">Exclude Port</label><input id="tr-expt" placeholder="e.g. 22"></div><div class="form-group"><label data-i18n="gui_ex_src">Exclude Source</label><input id="tr-exsrc" placeholder="e.g. env=Kube, 10.9.9.9"></div><div class="form-group"><label data-i18n="gui_ex_dest">Exclude Destination</label><input id="tr-exdst" placeholder="e.g. 8.8.8.8"></div></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_threshold">Threshold</legend>
    <div class="form-row-3"><div class="form-group"><label data-i18n="gui_count">Count</label><input id="tr-cnt" type="number" value="10"></div><div class="form-group"><label data-i18n="gui_window_min">Window (min)</label><input id="tr-win" type="number" value="10"></div><div class="form-group"><label data-i18n="gui_cooldown">Cooldown (min)</label><input id="tr-cd" type="number" value="10"></div></div>
  </fieldset>
  <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal('m-traffic')" data-i18n="gui_cancel">Cancel</button><button class="btn btn-success" onclick="saveTraffic()" data-i18n="gui_save">💾 Save</button></div>
</div></div>

<!-- BW/Volume -->
<div class="modal-bg" id="m-bw"><div class="modal">
  <h2><span data-i18n="gui_add_bw_rule" id="mb-title">Add Bandwidth / Volume Rule</span></h2>
  <div class="form-group"><label data-i18n="gui_rule_name">Rule Name</label><input id="bw-name"></div>
  <fieldset><legend data-i18n="gui_metric_type">Metric Type</legend><div class="radio-group">
    <label><input type="radio" name="bw-mt" value="bandwidth" checked> <span data-i18n="gui_mt_bw">Bandwidth (Mbps, Max)</span></label>
    <label><input type="radio" name="bw-mt" value="volume"> <span data-i18n="gui_mt_vol">Volume (MB, Sum)</span></label>
  </div></fieldset>
  <fieldset><legend data-i18n="gui_policy_dec">Policy Decision</legend><div class="radio-group">
    <label><input type="radio" name="bw-pd" value="2"> <span data-i18n="gui_pd_blocked">Blocked</span></label>
    <label><input type="radio" name="bw-pd" value="1"> <span data-i18n="gui_pd_potential">Potential</span></label>
    <label><input type="radio" name="bw-pd" value="0"> <span data-i18n="gui_pd_allowed">Allowed</span></label>
    <label><input type="radio" name="bw-pd" value="-1" checked> <span data-i18n="gui_pd_all">All</span></label>
  </div></fieldset>
  <fieldset><legend data-i18n="gui_col_filters">Filters</legend>
    <div class="form-row-3"><div class="form-group"><label data-i18n="gui_port">Port</label><input id="bw-port" placeholder="e.g. 443"></div><div class="form-group"><label data-i18n="gui_source">Source (Label/IP)</label><input id="bw-src" placeholder="e.g. role=Web, 10.0.0.0/8"></div><div class="form-group"><label data-i18n="gui_dest">Destination (Label/IP)</label><input id="bw-dst" placeholder="e.g. app=DB, 10.1.1.5"></div></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_excludes">Excludes (Optional)</legend>
    <div class="form-row-3"><div class="form-group"><label data-i18n="gui_ex_port">Exclude Port</label><input id="bw-expt" placeholder="e.g. 22"></div><div class="form-group"><label data-i18n="gui_ex_src">Exclude Source</label><input id="bw-exsrc" placeholder="e.g. env=Kube, 10.9.9.9"></div><div class="form-group"><label data-i18n="gui_ex_dest">Exclude Destination</label><input id="bw-exdst" placeholder="e.g. 8.8.8.8"></div></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_threshold">Threshold</legend>
    <div class="form-row-3"><div class="form-group"><label data-i18n="gui_value">Value</label><input id="bw-val" type="number" value="100"></div><div class="form-group"><label data-i18n="gui_window_min">Window (min)</label><input id="bw-win" type="number" value="10"></div><div class="form-group"><label data-i18n="gui_cooldown">Cooldown (min)</label><input id="bw-cd" type="number" value="30"></div></div>
  </fieldset>
  <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal('m-bw')" data-i18n="gui_cancel">Cancel</button><button class="btn btn-success" onclick="saveBW()" data-i18n="gui_save">💾 Save</button></div>
</div></div>

<!-- Help / Parameter Guide -->
<div class="modal-bg" id="m-help"><div class="modal" style="max-width:600px;">
  <h2><span data-i18n="gui_help_title">📖 Parameter Guide (API 25.2)</span></h2>
  <div style="color:var(--dim);line-height:1.6;font-size:0.95rem;">
    <p data-i18n="gui_help_desc">Illumio PCE Ops leverages the standard Illumio Traffic Analysis REST API parameters.</p>
    <h3 style="color:#fff;margin-top:12px" data-i18n="gui_help_filters">Filters & Excludes</h3>
    <ul style="padding-left:20px;margin-bottom:12px">
      <li data-i18n="gui_help_lf"><strong>Label format:</strong> <code>key=value</code> (e.g., <code>role=Web</code>, <code>env=Production</code>, <code>app=Database</code>). Must exactly match the PCE label keys and values.</li>
      <li data-i18n="gui_help_ipf"><strong>IP List/CIDR format:</strong> Standard CIDR notation (e.g., <code>10.0.0.0/8</code>) or exact IPs (e.g., <code>192.168.1.50</code>).</li>
      <li data-i18n="gui_help_pf"><strong>Port format:</strong> Integer port numbers (e.g., <code>80</code>, <code>443</code>, <code>3306</code>).</li>
    </ul>

    <h3 style="color:#fff;margin-top:12px" data-i18n="gui_help_pd">Policy Decisions</h3>
    <ul style="padding-left:20px;margin-bottom:12px">
      <li data-i18n="gui_help_pd_blk"><strong>Blocked:</strong> Traffic explicitly dropped by policy.</li>
      <li data-i18n="gui_help_pd_pot"><strong>Potential:</strong> Traffic that <em>would</em> be blocked if the workload were placed into Enforced mode.</li>
      <li data-i18n="gui_help_pd_all"><strong>Allowed:</strong> Traffic permitted by policy.</li>
    </ul>
  </div>
  <div class="modal-actions"><button class="btn btn-primary" onclick="closeModal('m-help')" data-i18n="gui_help_close">Close window</button></div>
</div></div>

<div class="toast" id="toast"></div>

<script>
/* ─── Helpers ─────────────────────────────────────────────────────── */
const $=s=>document.getElementById(s);
const api=async(url,opt)=>{const r=await fetch(url,opt);return r.json()};
const post=(url,body)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const put=(url,body)=>api(url,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const del=url=>api(url,{method:'DELETE'});
const rv=name=>document.querySelector(`input[name="${name}"]:checked`)?.value;
const setRv=(name,val)=>{const r=document.querySelector(`input[name="${name}"][value="${val}"]`);if(r)r.checked=true};
let _editIdx=null; // null = add mode, number = edit mode
let _translations={};

async function loadTranslations(){
  _translations=await api('/api/ui_translations');
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const k=el.getAttribute('data-i18n');
    if(_translations[k]){
      if(el.tagName==='INPUT'&&el.type==='button') el.value=_translations[k];
      else el.textContent=_translations[k];
    }
  });
}

function initTableResizers() {
  document.querySelectorAll('.rule-table').forEach(table => {
    const ths = table.querySelectorAll('th');
    ths.forEach(th => {
      if (th.querySelector('.resizer')) return;
      const resizer = document.createElement('div');
      resizer.classList.add('resizer');
      th.appendChild(resizer);
      let startX, startWidth;
      resizer.addEventListener('mousedown', function(e) {
        startX = e.pageX;
        startWidth = th.offsetWidth;
        document.body.style.cursor = 'col-resize';
        const onMouseMove = (e) => {
          const newWidth = startWidth + (e.pageX - startX);
          th.style.width = Math.max(newWidth, 30) + 'px';
        };
        const onMouseUp = () => {
          document.body.style.cursor = 'default';
          document.removeEventListener('mousemove', onMouseMove);
          document.removeEventListener('mouseup', onMouseUp);
        };
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
      });
    });
  });
}

function toast(msg,err){const t=$('toast');t.textContent=msg;t.className='toast'+(err?' err':'')+' show';setTimeout(()=>t.className='toast',3000)}
function dlog(msg){const l=$('d-log');l.textContent+='\n['+new Date().toLocaleTimeString()+'] '+msg;l.scrollTop=l.scrollHeight}
function slog(msg){const l=$('s-log');if(l){l.textContent+='\n['+new Date().toLocaleTimeString()+'] '+msg;l.scrollTop=l.scrollHeight}}
function alog(msg){const l=$('a-log');l.textContent+='\n'+msg;l.scrollTop=l.scrollHeight}

/* ─── Tabs ────────────────────────────────────────────────────────── */
function switchTab(id){
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',t.textContent.trim().toLowerCase().startsWith(id.slice(0,4)))});
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  $('p-'+id).classList.add('active');
  if(id==='rules') loadRules();
  if(id==='settings') loadSettings();
  if(id==='dashboard') loadDashboard();
}

/* ─── Dashboard ───────────────────────────────────────────────────── */
async function loadDashboard(){
  const d=await api('/api/status');
  $('hdr-meta').textContent=`v${d.version} | ${d.api_url}`;
  $('d-rules').textContent=d.rules_count;
  $('d-health').textContent=d.health_check?'ON':'OFF';
  $('d-lang').textContent=(d.language||'en').toUpperCase();
  if(d.theme) document.documentElement.setAttribute('data-theme', d.theme);

  if (d.cooldowns && d.cooldowns.length > 0) {
    const activeCds = d.cooldowns.filter(c => c.remaining_mins > 0).length;
    if (activeCds > 0) {
      const title = _translations['gui_cooldown_title'] || 'Rules in Cooldown';
      $('cd-field').style.display='block';
      $('cd-list').innerHTML = `<div class="card" style="border-color:var(--warn);"><div class="label" style="color:var(--warn);"><span style="margin-right:4px;">⏳</span>${title}</div><div class="value" style="color:var(--warn);">${activeCds}</div></div>`;
    } else {
      $('cd-field').style.display='none';
      $('cd-list').innerHTML='';
    }
  } else {
    $('cd-field').style.display='none';
    $('cd-list').innerHTML='';
  }

  await loadTranslations();
  await loadDashboardQueries();
}
async function testConn(){
  slog('Testing PCE connection...');
  const r=await post('/api/actions/test-connection',{});
  if(r.ok){$('d-api').textContent='Connected';$('d-api').className='value ok';slog('✅ Connected (HTTP '+r.status+')')}
  else{$('d-api').textContent='Error';$('d-api').className='value err';slog('❌ '+( r.error||r.body))}
}

let _dashboardQueries = [];

async function loadDashboardQueries() {
  const rt = await window.fetch('/api/dashboard/queries');
  _dashboardQueries = await rt.json() || [];
  renderDashboardQueries();
}

const escapeHtml = (unsafe) => {
    return (unsafe || '').toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
};

function renderDashboardQueries() {
  const container = $('d-queries-container');
  let html = '';
  if(_dashboardQueries.length === 0){
      html = `<div style="text-align:center;padding:20px;color:var(--dim);font-size:0.9rem;">${_translations['gui_top10_empty']||'No data.'}</div>`;
  } else {
      _dashboardQueries.forEach((q, i) => {
          let badgeColor = "var(--primary)";
          if(q.pd === 2) badgeColor = "var(--danger)";
          else if(q.pd === 1) badgeColor = "var(--warn)";
          else if(q.pd === 0) badgeColor = "var(--success)";
          
          let rankLabel = q.rank_by === 'bandwidth' ? 'Max Bandwidth (Mbps)' : (q.rank_by === 'volume' ? 'Total Volume' : 'Connection Count');
          html += `
          <div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;">
             <div style="display:flex;align-items:center;min-height:30px;">
                <strong style="margin-right:12px;font-size:0.95rem;color:var(--accent2);">${escapeHtml(q.name)}</strong>
                <span style="font-size:10px;background:${badgeColor};color:#fff;padding:2px 6px;border-radius:4px;margin-right:8px;">PD: ${q.pd===3?'All':(q.pd===2?'Blocked':(q.pd===1?'Potential':'Allowed'))}</span>
                <span style="font-size:10px;background:var(--dim);color:#fff;padding:2px 6px;border-radius:4px;margin-right:8px;">${rankLabel}</span>
                <span style="flex:1"></span>
                <span id="d-qstate-${i}" style="color:var(--dim);font-size:0.8rem;margin-right:12px;"></span>
                <button class="btn btn-sm" style="background:var(--bg);border:1px solid var(--border);margin-right:6px;" onclick="openQueryModal(${i})">✏️</button>
                <button class="btn btn-primary btn-sm" onclick="runTop10Query(${i})" data-i18n="gui_run_btn">Run</button>
             </div>
             
             <table class="rule-table" style="margin-top:10px;border-top:1px solid var(--border);font-size:0.8rem;">
              <thead><tr>
                <th style="width:25px">#</th>
                <th style="width:100px" data-i18n="gui_value">Value</th>
                <th style="width:110px">First/Last Seen</th>
                <th style="width:40px;text-align:center;">Dir</th>
                <th>Source</th>
                <th>Destination</th>
                <th style="width:70px">Service</th>
                <th style="width:70px" data-i18n="gui_policy_dec">Decision</th>
              </tr></thead>
              <tbody id="d-qbody-${i}">
                <tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_translations['gui_top10_empty']||'No data. Click Run to query.'}</td></tr>
              </tbody>
             </table>
          </div>`;
      });
  }
  container.innerHTML = html;
  initTableResizers();
  
  if (typeof applyLang === "function") applyLang();
  else loadTranslations().catch(console.error);
}

function openQueryModal(idx = -1) {
  $('dq-idx').value = idx;
  if (idx < 0) {
      $('mq-title').textContent = _translations['gui_add_query_widget'] || 'Add Query Widget';
      $('dq-name').value = '';
      $('dq-rank').value = 'count';
      document.querySelector('input[name="dq-pd"][value="3"]').checked = true;
      $('dq-port').value = ''; $('dq-proto').value = '';
      $('dq-src').value = ''; $('dq-dst').value = '';
      $('dq-expt').value = ''; $('dq-exsrc').value = ''; $('dq-exdst').value = '';
  } else {
      $('mq-title').textContent = 'Edit Query Widget';
      const q = _dashboardQueries[idx];
      $('dq-name').value = q.name || '';
      $('dq-rank').value = q.rank_by || 'count';
      const pdRad = document.querySelector(`input[name="dq-pd"][value="${q.pd}"]`);
      if(pdRad) pdRad.checked = true;
      $('dq-port').value = q.port || ''; 
      $('dq-proto').value = q.proto || '';
      $('dq-src').value = (q.src_label||'')+(q.src_ip_in? (q.src_label? ', ':'')+q.src_ip_in : '');
      $('dq-dst').value = (q.dst_label||'')+(q.dst_ip_in? (q.dst_label? ', ':'')+q.dst_ip_in : '');
      $('dq-expt').value = q.ex_port || '';
      $('dq-exsrc').value = (q.ex_src_label||'')+(q.ex_src_ip? (q.ex_src_label? ', ':'')+q.ex_src_ip : '');
      $('dq-exdst').value = (q.ex_dst_label||'')+(q.ex_dst_ip? (q.ex_dst_label? ', ':'')+q.ex_dst_ip : '');
  }
  let btn = document.querySelector('#m-query .modal-actions');
  let isEdit = idx >= 0;
  if(isEdit && !document.getElementById('m-query-del')){
    let delBtn = document.createElement('button');
    delBtn.id = 'm-query-del';
    delBtn.className = 'btn btn-danger';
    delBtn.innerText = _translations['gui_delete'] || 'Delete';
    delBtn.style.marginRight = 'auto';
    delBtn.onclick = () => deleteTop10Query(idx);
    btn.insertBefore(delBtn, btn.firstChild);
  } else if (!isEdit && document.getElementById('m-query-del')) {
    document.getElementById('m-query-del').remove();
  }
  
  const m = $('m-query');
  if (m) m.classList.add('show');
}

async function saveDashboardQuery() {
    const idx = parseInt($('dq-idx').value);
    const pdMatch = document.querySelector('input[name="dq-pd"]:checked');
    const d = {
        idx: idx >= 0 ? idx : null,
        name: $('dq-name').value,
        rank_by: $('dq-rank').value,
        pd: pdMatch ? parseInt(pdMatch.value) : 3,
        port: parseInt($('dq-port').value) || null,
        proto: parseInt($('dq-proto').value) || null,
        src: $('dq-src').value, dst: $('dq-dst').value,
        ex_port: parseInt($('dq-expt').value) || null,
        ex_src: $('dq-exsrc').value, ex_dst: $('dq-exdst').value
    };
    
    // Quick API helper if not strictly using fetch directly
    const r = await fetch('/api/dashboard/queries', {
      method: 'POST', body: JSON.stringify(d), headers: {'Content-Type': 'application/json'}
    }).then(res => res.json());
    
    if(r.ok) { 
        const m = $('m-query');
        if (m) m.classList.remove('show');
        await loadDashboardQueries(); 
    }
    else alert("Error: " + r.error);
}

async function deleteTop10Query(idx) {
    if(!confirm("Delete this widget?")) return;
    const r = await fetch('/api/dashboard/queries/'+idx, {method:'DELETE'}).then(res => res.json());
    if(r.ok) { 
        const m = $('m-query');
        if (m) m.classList.remove('show');
        await loadDashboardQueries(); 
    }
    else alert("Delete failed");
}

async function runAllQueries() {
    for(let i=0; i<_dashboardQueries.length; i++) {
        await runTop10Query(i);
    }
}

async function runTop10Query(idx){
  const q = _dashboardQueries[idx];
  const ms=$(`d-qstate-${idx}`), bd=$(`d-qbody-${idx}`);
  if(!ms || !bd) return;
  
  const payload = { ...q, mins: parseInt($('d-global-min').value)||30 };
  
  ms.textContent = _translations['gui_top10_querying']||'Querying...'; 
  bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_translations['gui_top10_loading']||'Loading...'}</td></tr>`;
  
  try {
    const r = await fetch('/api/dashboard/top10', {
      method: 'POST', body: JSON.stringify(payload), headers: {'Content-Type': 'application/json'}
    }).then(res => res.json());
    if(!r.ok) throw new Error(r.error||'Unknown error');
    
    if(r.data && r.data.length){
      let html='';
      r.data.forEach((m,i)=>{
        const pBadge = m.pd===2 ? `<span style="background:var(--danger);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">Blocked</span>` :
                       m.pd===1 ? `<span style="background:var(--warn);color:#000;padding:2px 6px;border-radius:4px;font-size:10px;">Potential</span>` :
                       m.pd===0 ? `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;">Allowed</span>` : m.pd;
                       
        const formatLabel = (labels) => {
            if(!labels || !labels.length) return '';
            return labels.map(l => `<span style="background:#e1ecf4;color:#2c5e77;padding:1px 4px;border-radius:4px;font-size:9px;margin-right:2px;display:inline-block;white-space:nowrap;margin-top:2px;">${escapeHtml(l.key)}:${escapeHtml(l.value)}</span>`).join('');
        };
        const sLabels = formatLabel(m.s_labels);
        const dLabels = formatLabel(m.d_labels);
                       
        html+=`
          <tr>
            <td>${i+1}</td>
            <td style="font-weight:bold;color:#6f42c1;">${m.val_fmt}</td>
            <td style="font-size:10px;white-space:nowrap;">${m.first_seen}<br>${m.last_seen}</td>
            <td style="text-align:center;">${m.dir}</td>
            <td><strong style="font-size:11px;">${escapeHtml(m.s_name)}</strong><br><small style="color:var(--dim);">${escapeHtml(m.s_ip)}</small><br>${sLabels}</td>
            <td><strong style="font-size:11px;">${escapeHtml(m.d_name)}</strong><br><small style="color:var(--dim);">${escapeHtml(m.d_ip)}</small><br>${dLabels}</td>
            <td>${escapeHtml(m.svc)}</td>
            <td>${pBadge}</td>
          </tr>`;
      });
      bd.innerHTML=html;
      ms.textContent = (_translations['gui_top10_found']||'Found {count} records. (Top 10)').replace('{count}', r.total);
    } else {
      bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--dim);padding:20px;">${_translations['gui_top10_no_records']||'No records found.'}</td></tr>`;
      ms.textContent = _translations['gui_done']||'Done.';
    }
    initTableResizers();
  } catch(e) {
    ms.textContent = 'Error: '+e.message;
    bd.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--danger);padding:20px;">${_translations['gui_top10_error']||'Error querying data.'}</td></tr>`;
  }
}

/* ─── Rules ───────────────────────────────────────────────────────── */
let _catalog={};
async function loadRules(){
  const rules=await api('/api/rules');
  $('r-badge').textContent=rules.length;
  const pdm={2:'Blocked',1:'Potential',0:'Allowed','-1':'All'};
  
  const cdTitle = _translations['gui_cooldown_active'] || 'Cooldown';
  const readyTitle = _translations['gui_cooldown_ready'] || 'Ready';
  const remTempl = _translations['gui_cooldown_remaining'] || '{mins}m remaining';
  
  let html='';
  rules.forEach(r=>{
    const typ=r.type.charAt(0).toUpperCase()+r.type.slice(1);
    const unit={volume:' MB',bandwidth:' Mbps',traffic:' conns'}[r.type]||'';
    const cond='> '+r.threshold_count+unit+' (Win:'+r.threshold_window+'m CD:'+(r.cooldown_minutes||r.threshold_window)+'m)';
    
    let statusHtml = '';
    if (r.cooldown_remaining > 0) {
      const rem = remTempl.replace('{mins}', r.cooldown_remaining);
      statusHtml = `<span style="background:var(--warn);color:#1a2c32;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">⏳ ${cdTitle} (${rem})</span>`;
    } else {
      statusHtml = `<span style="background:var(--success);color:#fff;padding:2px 6px;border-radius:4px;font-size:0.75rem;font-weight:600;">✅ ${readyTitle}</span>`;
    }
    
    let f=[];
    if(r.type==='event') f.push('Event: '+r.filter_value);
    if(r.pd!==undefined&&r.pd!==null) f.push('PD:'+( pdm[r.pd]||r.pd));
    if(r.port) f.push('Port:'+r.port);
    if(r.src_label) f.push('Src:'+r.src_label);if(r.dst_label) f.push('Dst:'+r.dst_label);
    if(r.src_ip_in) f.push('SrcIP:'+r.src_ip_in);if(r.dst_ip_in) f.push('DstIP:'+r.dst_ip_in);
    html+=`<tr><td><input type="checkbox" class="r-chk" data-idx="${r.index}"></td><td title="${typ}">${typ}</td><td title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td><td>${statusHtml}</td><td title="${cond}">${cond}</td><td title="${escapeHtml(f.join(' | '))}">${escapeHtml(f.join(' | '))||'—'}</td><td><button class="btn btn-primary btn-sm" onclick="editRule(${r.index},'${r.type}')">✏️</button></td></tr>`;
  });
  $('r-body').innerHTML=html||'<tr><td colspan="7" style="color:var(--dim);text-align:center;padding:24px">No rules. Add one above.</td></tr>';
  initTableResizers();
}
function toggleAll(el){document.querySelectorAll('.r-chk').forEach(c=>c.checked=el.checked)}
async function deleteSelected(){
  const ids=[...document.querySelectorAll('.r-chk:checked')].map(c=>parseInt(c.dataset.idx)).sort((a,b)=>b-a);
  if(!ids.length){toast('Select rules first','err');return}
  if(!confirm('Delete '+ids.length+' rule(s)?'))return;
  for(const i of ids) await del('/api/rules/'+i);
  toast('Deleted');loadRules();loadDashboard();
}
function openModal(id,isEdit){
  _editIdx=isEdit??null;$(id).classList.add('show');if(id==='m-event'&&!Object.keys(_catalog).length)loadCatalog();
  // Update modal title
  let target;
  if(id==='m-event') target=$('me-title');
  else if(id==='m-traffic') target=$('mt-title');
  else if(id==='m-bw') target=$('mb-title');
  if(target){
    const baseKey = id==='m-event'?'gui_add_event_rule':id==='m-traffic'?'gui_add_traffic_rule':'gui_add_bw_rule';
    const editKey = id==='m-event'?'gui_edit_event_rule':id==='m-traffic'?'gui_edit_traffic_rule':'gui_edit_bw_rule';
    const key = _editIdx!==null ? editKey : baseKey;
    target.setAttribute('data-i18n', key);
    if(_translations[key]) target.textContent=_translations[key];
  }
}
function closeModal(id){$(id).classList.remove('show');_editIdx=null}
async function loadCatalog(){
  _catalog=await api('/api/event-catalog');
  const sel=$('ev-cat');sel.innerHTML='<option value="">Select...</option>';
  Object.keys(_catalog).forEach(c=>{const o=document.createElement('option');o.value=c;o.textContent=c;sel.appendChild(o)});
}
function populateEvents(){
  const cat=$('ev-cat').value;const sel=$('ev-type');sel.innerHTML='';
  if(!cat||!_catalog[cat]){sel.innerHTML='<option>Select category first</option>';return}
  Object.entries(_catalog[cat]).forEach(([k,v])=>{const o=document.createElement('option');o.value=k;o.textContent=k+' ('+v+')';sel.appendChild(o)});
}

/* ─── Edit Rule ───────────────────────────────────────────────────── */
async function editRule(idx,type){
  try {
    const r=await api('/api/rules/'+idx);
    if(!r || r.error){toast('Rule not found','err');return}
    if(type==='event'){
      await loadCatalog();
      // Find and select category
      for(const[cat,evts] of Object.entries(_catalog)){
        if(r.filter_value in evts){$('ev-cat').value=cat;populateEvents();$('ev-type').value=r.filter_value;break}
      }
      setRv('ev-tt',r.threshold_type||'immediate');
      $('ev-cnt').value=r.threshold_count||5;
      $('ev-win').value=r.threshold_window||10;
      $('ev-cd').value=r.cooldown_minutes||10;
      openModal('m-event',idx);
    } else if(type==='traffic'){
      $('tr-name').value=r.name||'';
      setRv('tr-pd',String(r.pd??2));
      $('tr-port').value=r.port||'';
      $('tr-proto').value=r.proto?String(r.proto):'';
      $('tr-src').value=r.src_label||r.src_ip_in||'';
      $('tr-dst').value=r.dst_label||r.dst_ip_in||'';
      $('tr-expt').value=r.ex_port||'';
      $('tr-exsrc').value=r.ex_src_label||r.ex_src_ip||'';
      $('tr-exdst').value=r.ex_dst_label||r.ex_dst_ip||'';
      $('tr-cnt').value=r.threshold_count||10;
      $('tr-win').value=r.threshold_window||10;
      $('tr-cd').value=r.cooldown_minutes||10;
      openModal('m-traffic',idx);
    } else {
      $('bw-name').value=r.name||'';
      setRv('bw-mt',r.type||'bandwidth');
      setRv('bw-pd',String(r.pd??-1));
      $('bw-port').value=r.port||'';
      $('bw-src').value=r.src_label||r.src_ip_in||'';
      $('bw-dst').value=r.dst_label||r.dst_ip_in||'';
      $('bw-expt').value=r.ex_port||'';
      $('bw-exsrc').value=r.ex_src_label||r.ex_src_ip||'';
      $('bw-exdst').value=r.ex_dst_label||r.ex_dst_ip||'';
      $('bw-val').value=r.threshold_count||100;
      $('bw-win').value=r.threshold_window||10;
      $('bw-cd').value=r.cooldown_minutes||30;
      openModal('m-bw',idx);
    }
  } catch(e) {
    console.error(e);
    alert('UI Error: ' + e.message);
  }
}

async function saveEvent(){
  const cat=$('ev-cat').value,ev=$('ev-type').value;
  if(!cat||!ev){toast('Select category and event','err');return}
  const name=(_catalog[cat]||{})[ev]||ev;
  const data={name,filter_value:ev,threshold_type:rv('ev-tt'),threshold_count:$('ev-cnt').value,threshold_window:$('ev-win').value,cooldown_minutes:$('ev-cd').value};
  if(_editIdx!==null) await put('/api/rules/'+_editIdx,data); else await post('/api/rules/event',data);
  closeModal('m-event');toast('Event rule saved');loadRules();loadDashboard();
}
async function saveTraffic(){
  const name=$('tr-name').value.trim();if(!name){toast('Name required','err');return}
  const data={name,pd:rv('tr-pd'),port:$('tr-port').value,proto:$('tr-proto').value,src:$('tr-src').value,dst:$('tr-dst').value,ex_port:$('tr-expt').value,ex_src:$('tr-exsrc').value,ex_dst:$('tr-exdst').value,threshold_count:$('tr-cnt').value,threshold_window:$('tr-win').value,cooldown_minutes:$('tr-cd').value};
  if(_editIdx!==null) await put('/api/rules/'+_editIdx,data); else await post('/api/rules/traffic',data);
  closeModal('m-traffic');toast('Traffic rule saved');loadRules();loadDashboard();
}
async function saveBW(){
  const name=$('bw-name').value.trim();if(!name){toast('Name required','err');return}
  const data={
    name,rule_type:rv('bw-mt'),pd:rv('bw-pd'),
    port:$('bw-port').value,src:$('bw-src').value,dst:$('bw-dst').value,
    ex_port:$('bw-expt').value,ex_src:$('bw-exsrc').value,ex_dst:$('bw-exdst').value,
    threshold_count:$('bw-val').value,threshold_window:$('bw-win').value,cooldown_minutes:$('bw-cd').value
  };
  if(_editIdx!==null) await put('/api/rules/'+_editIdx,{...data,type:data.rule_type}); else await post('/api/rules/bandwidth',data);
  closeModal('m-bw');toast('Rule saved');loadRules();loadDashboard();
}

function confirmBestPractices(){
  if(!confirm('⚠️ WARNING: This will DELETE all existing rules and replace them with best practice defaults.\n\nAre you sure you want to continue?')) return;
  if(!confirm('This action cannot be undone. Confirm once more to proceed.')) return;
  runAction('best-practices');
}

/* ─── Settings ────────────────────────────────────────────────────── */
let _settings={};
async function loadSettings(){
  _settings=await api('/api/settings');
  const s=_settings,a=s.api||{},e=s.email||{},sm=s.smtp||{},al=s.alerts||{},st=s.settings||{};
  const active=al.active||[];
  $('s-form').innerHTML=`
  <fieldset><legend data-i18n="gui_api_conn">API Connection</legend>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_url">URL</label><input id="s-url" value="${a.url||''}"></div><div class="form-group"><label data-i18n="gui_org_id">Org ID</label><input id="s-org" value="${a.org_id||''}"></div></div>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_api_key">API Key</label><input id="s-key" value="${a.key||''}"></div><div class="form-group"><label data-i18n="gui_api_secret">API Secret</label><input id="s-sec" type="password" value="${a.secret||''}"></div></div>
    <div class="chk"><label><input type="checkbox" id="s-ssl" ${a.verify_ssl?'checked':''}> <span data-i18n="gui_verify_ssl">Verify SSL</span></label></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_email_smtp">Email & SMTP</legend>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_sender">Sender</label><input id="s-sender" value="${e.sender||''}"></div><div class="form-group"><label data-i18n="gui_recipients">Recipients (comma)</label><input id="s-rcpt" value="${(e.recipients||[]).join(', ')}"></div></div>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_smtp_host">SMTP Host</label><input id="s-smhost" value="${sm.host||''}"></div><div class="form-group"><label data-i18n="gui_port">Port</label><input id="s-smport" value="${sm.port||25}"></div></div>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_user">User</label><input id="s-smuser" value="${sm.user||''}"></div><div class="form-group"><label data-i18n="gui_password">Password</label><input id="s-smpass" type="password" value="${sm.password||''}"></div></div>
    <div style="display:flex;gap:20px"><div class="chk"><label><input type="checkbox" id="s-tls" ${sm.enable_tls?'checked':''}> STARTTLS</label></div><div class="chk"><label><input type="checkbox" id="s-auth" ${sm.enable_auth?'checked':''}> Auth</label></div></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_alert_channels">Alert Channels</legend>
    <div style="display:flex;gap:20px;margin-bottom:12px"><div class="chk"><label><input type="checkbox" id="s-amail" ${active.includes('mail')?'checked':''}> 📧 <span data-i18n="gui_mail">Mail</span></label></div><div class="chk"><label><input type="checkbox" id="s-aline" ${active.includes('line')?'checked':''}> 📱 <span data-i18n="gui_line">LINE</span></label></div><div class="chk"><label><input type="checkbox" id="s-awh" ${active.includes('webhook')?'checked':''}> 🔗 <span data-i18n="gui_webhook">Webhook</span></label></div></div>
    <div class="form-row"><div class="form-group"><label data-i18n="gui_line_token">LINE Token</label><input id="s-ltok" value="${al.line_channel_access_token||''}"></div><div class="form-group"><label data-i18n="gui_line_target_id">LINE Target ID</label><input id="s-ltgt" value="${al.line_target_id||''}"></div></div>
    <div class="form-group"><label data-i18n="gui_webhook_url">Webhook URL</label><input id="s-whurl" value="${al.webhook_url||''}"></div>
  </fieldset>
  <fieldset><legend data-i18n="gui_lang_settings">Display & General</legend>
    <div class="chk" style="margin-bottom:12px"><label><input type="checkbox" id="s-hc" ${st.enable_health_check!==false?'checked':''}> <span data-i18n="gui_enable_hc">Enable PCE Health Check</span></label></div>
    <div class="form-row">
      <div class="form-group">
        <label data-i18n="gui_language">Language</label>
        <div class="radio-group">
          <label><input type="radio" name="s-lang" value="en" ${st.language!=='zh_TW'?'checked':''}> <span data-i18n="gui_lang_en">English</span></label>
          <label><input type="radio" name="s-lang" value="zh_TW" ${st.language==='zh_TW'?'checked':''}> <span data-i18n="gui_lang_zh">繁體中文</span></label>
        </div>
      </div>
      <div class="form-group">
        <label>Theme</label>
        <div class="radio-group">
          <label><input type="radio" name="s-theme" value="dark" ${st.theme!=='light'?'checked':''}> <span data-i18n="gui_theme_dark">Dark Theme</span></label>
          <label><input type="radio" name="s-theme" value="light" ${st.theme==='light'?'checked':''}> <span data-i18n="gui_theme_light">Light Theme</span></label>
        </div>
      </div>
    </div>
  </fieldset>`;
  await loadTranslations();
}
async function saveSettings(){
  const active=[];if($('s-amail').checked)active.push('mail');if($('s-aline').checked)active.push('line');if($('s-awh').checked)active.push('webhook');
  const theme = rv('s-theme');
  document.documentElement.setAttribute('data-theme', theme);
  await post('/api/settings',{
    api:{url:$('s-url').value,org_id:$('s-org').value,key:$('s-key').value,secret:$('s-sec').value,verify_ssl:$('s-ssl').checked},
    email:{sender:$('s-sender').value,recipients:$('s-rcpt').value.split(',').map(s=>s.trim()).filter(Boolean)},
    smtp:{host:$('s-smhost').value,port:parseInt($('s-smport').value)||25,user:$('s-smuser').value,password:$('s-smpass').value,enable_tls:$('s-tls').checked,enable_auth:$('s-auth').checked},
    alerts:{active,line_channel_access_token:$('s-ltok').value,line_target_id:$('s-ltgt').value,webhook_url:$('s-whurl').value},
    settings:{language:rv('s-lang'), theme: theme, enable_health_check:$('s-hc').checked}
  });
  toast('Settings saved');
}

/* ─── Actions ─────────────────────────────────────────────────────── */
async function runAction(name){
  $('a-log').textContent='['+new Date().toLocaleTimeString()+'] Running '+name+'...';
  const r=await post('/api/actions/'+name,{});
  alog(r.output||'Done.');
  if(name==='best-practices'){loadRules();loadDashboard()}
  toast('✅ '+name+' completed');
}
async function runDebug(){
  $('a-log').textContent='['+new Date().toLocaleTimeString()+'] Running debug mode...';
  const r=await post('/api/actions/debug',{mins:$('a-debug-mins').value,pd_sel:$('a-debug-pd').value});
  alog(r.output||'Done.');
  toast('✅ Debug completed');
}

/* ─── Init ────────────────────────────────────────────────────────── */
async function stopGui(){
  if(!confirm('Stop the Web GUI server? The browser page will close.')) return;
  try{ await post('/api/shutdown',{}); } catch(e){}
  document.body.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px"><h1 style="color:var(--accent2)">Web GUI Stopped</h1><p style="color:var(--dim)">You may close this tab. Restart from CLI or use --gui.</p></div>';
}
loadDashboard();
testConn();
</script>
</body>
</html>'''
