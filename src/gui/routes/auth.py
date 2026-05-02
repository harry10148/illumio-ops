"""Auth Blueprint: login, logout, session, CSRF-token, and the SPA root."""
from __future__ import annotations

import hmac as _hmac

from flask import (
    Blueprint, jsonify, redirect,
    render_template, request, session,
)
from flask_login import login_user, logout_user
from flask_wtf.csrf import generate_csrf

from src.config import ConfigManager, verify_password
from src.gui._helpers import (
    _get_active_pce_url, _ui_translation_dict, _ok, _err, _safe_log,
)
from src.i18n import t


def make_auth_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance
    limiter,        # flask_limiter.Limiter instance
    login_required,  # flask_login.login_required decorator
) -> Blueprint:
    bp = Blueprint("auth", __name__)

    @bp.route("/api/csrf-token")
    def api_csrf_token():
        return jsonify({"csrf_token": generate_csrf()})

    @bp.route("/")
    @login_required
    def index():
        import datetime as _dt
        import json as _json
        cm.load()
        pce_url = _get_active_pce_url(cm)
        rules_count = len(cm.config.get("rules", []))
        schedules_count = len(cm.config.get("report_schedules", []))
        config_loaded_at = _dt.datetime.now()
        lang = cm.config.get("settings", {}).get("language", "en")
        ui_translations = _ui_translation_dict(lang)
        return render_template(
            "index.html",
            pce_url=pce_url,
            rules_count=rules_count,
            schedules_count=schedules_count,
            config_loaded_at=config_loaded_at,
            ui_translations_json=_json.dumps(
                ui_translations, ensure_ascii=False
            ).replace("</", "<\\/"),
        )

    @bp.route("/login", methods=["GET"])
    def login_page():
        return render_template("login.html")

    @bp.route("/api/login", methods=["POST"])
    @csrf.exempt
    @limiter.limit("5 per minute")
    def api_login():
        from pydantic import ValidationError as _ValidationError
        from src.auth_models import AdminUser, LoginForm
        try:
            form = LoginForm.model_validate(request.get_json(silent=True) or {})
        except _ValidationError as e:
            return jsonify({"ok": False, "error": "invalid_form", "detail": str(e)}), 400

        username = form.username
        password = form.password

        cm.load()
        gui_cfg = cm.config.get("web_gui", {})

        saved_username = gui_cfg.get("username", "illumio")
        saved_password = gui_cfg.get("password", "")

        # H1: always run verify_password to equalize timing, even if username
        # is wrong. We compare the boolean results last to avoid short-circuit.
        # Do NOT insert early returns or blank lines between these two lines.
        username_ok = _hmac.compare_digest(username.strip(), saved_username.strip())
        password_ok = verify_password(password, saved_password)
        if username_ok and password_ok:
            session.permanent = True
            login_user(AdminUser(username))
            if gui_cfg.get("_initial_password"):
                gui_cfg.pop("_initial_password", None)
                cm.save()
            return jsonify({
                "ok": True,
                "csrf_token": generate_csrf(),
                # Surface the must_change_password gate to the login UI so it
                # can show an inline change-password form before letting the
                # user reach the dashboard (M4 gate would otherwise 423 every
                # API call and the UI would look broken).
                "must_change_password": bool(gui_cfg.get("must_change_password")),
            })

        return jsonify({"ok": False, "error": t("gui_err_invalid_auth")}), 401

    @bp.route("/logout", methods=["POST"])
    def logout():
        logout_user()
        session.clear()
        return redirect("/login")

    return bp
