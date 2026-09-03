"""POST /api/policy/explain — which PCE rules cover a flow (v3 investigate hub)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from src.api.policy_explain import BASIS_VALUES, explain_flow, proto_number
from src.gui._helpers import _err, _err_with_log


def make_policy_blueprint(cm, login_required) -> Blueprint:
    bp = Blueprint("policy_api", __name__)

    @bp.route("/api/policy/explain", methods=["POST"])
    def explain():
        lang = cm.config.get("settings", {}).get("language", "en")
        data = request.get_json(silent=True) or {}
        src = data.get("src") or {}
        dst = data.get("dst") or {}
        if not isinstance(src, dict) or not isinstance(dst, dict):
            return _err("src and dst must be objects", 400)
        if not (src.get("href") or src.get("ip") or dst.get("href") or dst.get("ip")):
            return _err("src or dst must carry an href or ip", 400)
        try:
            port = int(data.get("port"))
            proto = proto_number(data.get("proto"))
        except (TypeError, ValueError):
            return _err("port and proto are required", 400)
        basis = data.get("basis") or "active"
        if basis not in BASIS_VALUES:
            return _err("basis must be active or draft", 400)
        try:
            from src.api_client import ApiClient
            with ApiClient(cm) as api:
                result = explain_flow(api, src=src, dst=dst, port=port, proto=proto, basis=basis)
        except Exception as exc:
            return _err_with_log("policy_explain", exc, lang=lang)
        if result.get("pce_error") is not None:
            return jsonify({"ok": False, "code": "pce_error", **result}), 502
        return jsonify({"ok": True, **result})

    return bp
