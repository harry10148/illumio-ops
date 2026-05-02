"""Config Blueprint: security, settings, alert-plugins, TLS, and PCE-profile routes."""
from __future__ import annotations

import os
import urllib.parse

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager, hash_password, verify_password
from src.alerts import PLUGIN_METADATA, plugin_config_path
from src.i18n import t
from src.gui._helpers import (
    _err,
    _err_with_log,
    _redact_secrets,
    _strip_redaction_placeholders,
    _validate_allowed_ips,
    _SETTINGS_ALLOWLISTS,
    _plugin_config_roots,
    _ROOT_DIR,
    _SELF_SIGNED_VALIDITY_DAYS,
    _generate_self_signed_cert,
    _get_cert_info,
    _cert_days_remaining,
)


def make_config_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance
    login_required,  # flask_login.login_required decorator
) -> Blueprint:
    bp = Blueprint("config", __name__)

    # ── API: Security ──────────────────────────────────────────────────────────

    @bp.route('/api/security', methods=['GET'])
    def api_security_get():
        cm.load()
        gui_cfg = cm.config.get('web_gui', {})
        return jsonify({
            "username": gui_cfg.get("username", "illumio"),
            "allowed_ips": gui_cfg.get("allowed_ips", []),
            "auth_setup": bool(gui_cfg.get("password"))
        })

    @bp.route('/api/security', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_security_post():
        d = request.json or {}
        cm.load()
        gui_cfg = cm.config.setdefault("web_gui", {})

        # No old_password gate: an authenticated session is sufficient to
        # change credentials. The CLI menu (settings.py) is the recovery path
        # when the password is forgotten and is the only way back in if the
        # admin loses session access too.

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

        if d.get("new_password"):
            new_pw = d["new_password"]
            confirm_pw = d.get("confirm_password", new_pw)
            if not (12 <= len(new_pw) <= 512) or new_pw != confirm_pw:
                return jsonify({"ok": False, "error": t("gui_err_invalid_password_form")}), 400
            gui_cfg["password"] = hash_password(new_pw)
            gui_cfg.pop("_initial_password", None)
            gui_cfg.pop("must_change_password", None)

        cm.save()
        return jsonify({"ok": True})

    # ── API: Settings ──────────────────────────────────────────────────────────

    @bp.route('/api/settings')
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
        return jsonify(_redact_secrets(payload))

    @bp.route('/api/alert-plugins')
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

    @bp.route('/api/settings', methods=['POST'])
    @limiter.limit("30 per hour")
    def api_save_settings():
        d = _strip_redaction_placeholders(request.json or {})
        if 'api' in d:
            api_in = d['api']
            api_allowlist = _SETTINGS_ALLOWLISTS["api"]
            # Validate url scheme before accepting it
            if 'url' in api_in:
                _url_val = str(api_in['url']).strip()
                _scheme = urllib.parse.urlparse(_url_val).scheme.lower()
                if _scheme not in ('http', 'https'):
                    return jsonify({"ok": False, "error": "api.url must use http or https scheme"}), 400
                if _scheme == 'http':
                    logger.warning("api.url uses plain HTTP — TLS verification cannot be performed")
            for k in api_allowlist:
                if k in api_in:
                    cm.config['api'][k] = api_in[k]
        if 'email' in d:
            email_in = d['email']
            if 'sender' in email_in:
                cm.config['email']['sender'] = email_in['sender']
            if 'recipients' in email_in:
                cm.config['email']['recipients'] = email_in['recipients']
        if 'smtp' in d:
            allowlist = _SETTINGS_ALLOWLISTS["smtp"]
            filtered = {k: v for k, v in d['smtp'].items() if k in allowlist}
            cm.config.setdefault('smtp', {}).update(filtered)
        if 'alerts' in d:
            allowlist = _SETTINGS_ALLOWLISTS["alerts"]
            filtered = {k: v for k, v in d['alerts'].items() if k in allowlist}
            cm.config.setdefault('alerts', {}).update(filtered)
        if 'settings' in d:
            allowlist = _SETTINGS_ALLOWLISTS["settings"]
            filtered = {k: v for k, v in d['settings'].items() if k in allowlist}
            cm.config.setdefault('settings', {}).update(filtered)
        if 'report' in d:
            rpt_in = d['report']
            rpt_cfg = cm.config.setdefault('report', {})
            if 'output_dir' in rpt_in:
                rpt_cfg['output_dir'] = rpt_in['output_dir']
            if 'retention_days' in rpt_in:
                try:
                    rpt_cfg['retention_days'] = max(0, int(rpt_in['retention_days']))
                except (TypeError, ValueError):
                    pass  # intentional fallback: keep existing retention_days if new value is not numeric
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

    # ── TLS Certificate Management ─────────────────────────────────────────────

    @bp.route('/api/tls/status', methods=['GET'])
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

    @bp.route('/api/tls/config', methods=['POST'])
    @limiter.limit("10 per hour")
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

    @bp.route('/api/tls/renew', methods=['POST'])
    @limiter.limit("10 per hour")
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
            return _err_with_log("cert_renew", e)

    # ── API: PCE Profiles ──────────────────────────────────────────────────────

    @bp.route('/api/pce-profiles', methods=['GET'])
    def api_list_pce_profiles():
        cm.load()
        return jsonify(_redact_secrets({
            "profiles": cm.get_pce_profiles(),
            "active_pce_id": cm.get_active_pce_id(),
        }))

    @bp.route('/api/pce-profiles', methods=['POST'])
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

    return bp
