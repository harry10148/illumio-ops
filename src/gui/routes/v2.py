"""V2 preview Blueprint: flag-gated `/v2` route serving the design-v2 shell.

Only registered by src/gui/__init__.py when web_gui.enable_v2_preview is
true; when the flag is off the blueprint is never registered, so /v2 404s
naturally rather than needing an explicit gate in the view itself.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from src.config import ConfigManager


def make_v2_blueprint(cm: ConfigManager, login_required) -> Blueprint:
    bp = Blueprint("v2", __name__)

    @bp.route("/v2")
    @login_required
    def v2_shell():
        return render_template("v2/base.html")

    return bp
