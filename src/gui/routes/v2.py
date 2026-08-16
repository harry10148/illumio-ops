"""V2 preview Blueprint: flag-gated `/v2` route serving the design-v2 shell.

Only registered by src/gui/__init__.py when web_gui.enable_v2_preview is
true; when the flag is off the blueprint is never registered, so /v2 404s
naturally rather than needing an explicit gate in the view itself.
"""
from __future__ import annotations

import json as _json

from flask import Blueprint, render_template

from src.config import ConfigManager
from src.gui._helpers import _ui_translation_dict


def make_v2_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("v2", __name__)

    @bp.route("/v2")
    @login_required
    def v2_shell():
        return render_template("v2/base.html")

    # Deliberately NOT @login_required: this is the page an unauthenticated
    # visitor lands on. src/gui/__init__.py's security_check before_request
    # hook must also know this path is reachable pre-auth (same treatment as
    # the existing /login) — see that file's bypass list.
    @bp.route("/v2/login")
    def v2_login():
        cm.load()
        lang = cm.config.get("settings", {}).get("language", "en")
        # login.mjs's own i18n.init() call (GET /api/ui_translations) 401s
        # for an anonymous visitor — every /api/* route sits behind
        # src/gui/__init__.py's security_check auth gate, this task cannot
        # change that ("Backend API zero changes"). _ui_translation_dict()
        # is the exact same function that route calls for an authenticated
        # request; calling it here, server-side, and embedding the result as
        # this page's own template data (not a new API surface) gives
        # login.mjs a real, correctly-localized catalogue to seed from
        # before any request can succeed — mirroring auth.py's
        # login_page()/login_i18n_json for the legacy login.html, just with
        # the full gui_/sched_/status_/error_/pd_ catalogue instead of a
        # hand-picked handful of keys, so nothing here has to be kept in
        # sync with login.mjs's key list by hand.
        translations = _ui_translation_dict(lang)
        return render_template(
            "v2/login.html",
            html_lang=lang.replace("_", "-"),
            login_i18n_json=_json.dumps(
                translations, ensure_ascii=False
            ).replace("</", "<\\/"),
        )

    return bp
