"""Auth Blueprint: login, logout, session, CSRF-token, and the SPA root."""
from __future__ import annotations

import hmac as _hmac

from flask import (
    Blueprint, jsonify, redirect,
    render_template, request, session,
)
from flask_login import login_user, logout_user
from flask_wtf.csrf import generate_csrf
from loguru import logger

from src.config import ConfigManager, verify_password
from src.gui._helpers import (
    _ui_translation_dict, _ok, _err, _safe_log,
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
        """The GUI. Serves the v2 shell — the only frontend this app has.

        Task 11 (switchover) folded the flag-gated `/v2` route into this one
        and deleted src/gui/routes/v2.py. The v2 shell fetches everything it
        renders through /api/* (core/api.mjs), so unlike the legacy
        index.html this template needs no server-rendered dashboard context —
        only the document language, which has to be on <html lang> before any
        script runs.
        """
        cm.load()
        lang = cm.config.get("settings", {}).get("language", "en")
        return render_template("index.html", html_lang=lang.replace("_", "-"))

    @bp.route("/login", methods=["GET"])
    def login_page():
        """The v2 login page (LG-01/LG-02), at the canonical /login path.

        Task 11 replaced the legacy login.html with the v2 one and removed
        the separate /v2/login route; src/gui/__init__.py's security_check
        bypass list lost its /v2/login entry in the same change.

        areas/login.mjs's own i18n.init() call (GET /api/ui_translations)
        401s for an anonymous visitor — every /api/* route sits behind
        security_check's auth gate, and this task does not change that
        ("Backend API zero changes"). _ui_translation_dict() is the exact
        same function that route calls for an authenticated request; calling
        it here, server-side, and embedding the result as this page's own
        template data (not a new API surface) gives login.mjs a real,
        correctly-localized catalogue to seed from before any request can
        succeed. That replaces the legacy page's hand-picked `login_i18n`
        dict, which had to be kept in sync with the JS by hand.
        """
        import json as _json
        cm.load()
        lang = cm.config.get("settings", {}).get("language", "en")
        translations = _ui_translation_dict(lang)
        return render_template(
            "login.html",
            html_lang=lang.replace("_", "-"),
            login_i18n_json=_json.dumps(
                translations, ensure_ascii=False
            ).replace("</", "<\\/"),
        )

    @bp.route("/api/login", methods=["POST"])
    @csrf.exempt
    @limiter.limit("5 per minute")
    def api_login():
        from pydantic import ValidationError as _ValidationError
        from src.auth_models import AdminUser, LoginForm
        _body = request.get_json(silent=True) or {}
        try:
            form = LoginForm.model_validate(_body)
        except _ValidationError as e:
            # 不可回傳 str(e)：pydantic 會把 input_value=...（即送來的密碼
            # 片段/全值）嵌進錯誤訊息（同 src/config.py load() 的既有慣例）。
            # server 端只記欄位位置，client 只拿泛用錯誤。
            locs = ["/".join(str(p) for p in err.get("loc", ())) or "?"
                    for err in e.errors()]
            logger.warning("login form validation failed: fields={}", locs)
            return jsonify({"ok": False, "error": "invalid_form"}), 400

        username = form.username
        password = form.password

        cm.load()
        lang = _body.get('lang') or cm.config.get('settings', {}).get('language', 'en')
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
                # 首登清除 _initial_password：與其他 config 寫入端一致，整段
                # load→mutate→save 以共用鎖序列化，並在鎖內重讀（cm.load()/
                # api_save_settings 都會整個替換 cm.config 物件，鎖外抓的
                # gui_cfg 可能已是孤兒 dict——直接 pop+save 會把明文初始密碼
                # 留在磁碟或蓋掉併發存檔）。
                with cm.write_lock:
                    cm.load()
                    fresh_cfg = cm.config.get("web_gui", {})
                    if fresh_cfg.pop("_initial_password", None) is not None:
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

        return jsonify({"ok": False, "error": t("gui_err_invalid_auth", lang=lang)}), 401

    @bp.route("/logout", methods=["POST"])
    def logout():
        logout_user()
        session.clear()
        return redirect("/login")

    return bp
