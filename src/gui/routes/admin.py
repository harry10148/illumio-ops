"""Admin Blueprint: /api/logs, /api/shutdown routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from src.config import ConfigManager
from src.i18n import t


def make_admin_blueprint(
    cm: ConfigManager,
    limiter,
    login_required,
    persistent_mode: bool,
) -> Blueprint:
    bp = Blueprint("admin", __name__)

    @bp.route("/api/logs")
    @login_required
    def api_log_list():
        from src.module_log import ModuleLog, MODULES
        modules = ModuleLog.list_modules()
        # Ensure all known modules appear even if not yet initialized
        present = {m["name"] for m in modules}
        for name, label in MODULES.items():
            if name not in present:
                modules.append({"name": name, "label": label, "count": 0})
        return jsonify({"ok": True, "modules": modules})

    @bp.route("/api/logs/<module_name>")
    @login_required
    def api_log_get(module_name):
        from src.module_log import ModuleLog, MODULES
        lang = cm.config.get('settings', {}).get('language', 'en')
        if module_name not in MODULES:
            return jsonify({"ok": False, "error": t("gui_err_unknown_module", lang=lang)}), 404
        n = min(int(request.args.get("n", 200)), 500)
        ml = ModuleLog.get(module_name)
        return jsonify({"ok": True, "module": module_name, "entries": ml.get_recent(n)})

    @bp.route("/api/shutdown", methods=["POST"])
    @limiter.limit("5 per hour")
    @login_required
    def api_shutdown():
        import os as _os, threading as _threading, signal as _signal
        lang = cm.config.get('settings', {}).get('language', 'en')
        if persistent_mode:
            return jsonify({"ok": False, "error": t("gui_err_shutdown_persistent", lang=lang)}), 403

        def _delayed_exit():
            import time as _t
            _t.sleep(0.5)
            _os.kill(_os.getpid(), _signal.SIGINT)

        _threading.Thread(target=_delayed_exit, daemon=True).start()
        return jsonify({"ok": True})

    return bp
