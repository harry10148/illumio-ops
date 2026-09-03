"""Alert inbox API — the persisted alert records behind the v3 investigate hub.

    GET   /api/alerts?status&type&since&page&page_size
    GET   /api/alerts/<id>
    PATCH /api/alerts/<id>            {"status": "new"|"ack"|"done"}
    GET   /api/alerts/<id>/traffic_query

Auth is the app-wide before_request gate; PATCH goes through the app-wide
CSRF check. Reads/writes go through src.alerts.store.AlertStore only.
"""
from __future__ import annotations

import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user

from src.alerts.store import ALERT_STATUSES, ALERT_TYPES, AlertStore
from src.gui._helpers import _err, _err_with_log

# Scalar filter keys a traffic / bandwidth alert rule may carry. Mirrors
# TRAFFIC_FILTER_KEYS / BW_FILTER_KEYS in src/static/js/v2/areas/alerting.mjs
# (the read-only rows of the two flow-rule drawers). Only keys the rule
# actually has are returned; nothing is invented.
_FLOW_RULE_QUERY_KEYS = (
    "type", "pd", "threshold_window", "filters",
    "src_label", "dst_label", "src_ip_in", "dst_ip_in", "port", "proto",
    "ex_src_label", "ex_dst_label", "ex_src_ip", "ex_dst_ip", "ex_port",
)
_FLOW_RULE_TYPES = ("traffic", "bandwidth", "volume")
_MAX_PAGE_SIZE = 200


def _parse_iso(value: str) -> bool:
    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def make_alerts_blueprint(cm, login_required) -> Blueprint:
    bp = Blueprint("alerts_api", __name__)

    def _lang() -> str:
        return cm.config.get("settings", {}).get("language", "en")

    @bp.route("/api/alerts")
    def list_alerts():
        status = request.args.get("status") or None
        type_ = request.args.get("type") or None
        since = request.args.get("since") or None
        if status and status not in ALERT_STATUSES:
            return _err("invalid status", 400)
        if type_ and type_ not in ALERT_TYPES:
            return _err("invalid type", 400)
        if since and not _parse_iso(since):
            return _err("invalid since", 400)
        try:
            page = max(1, int(request.args.get("page", 1)))
            page_size = min(_MAX_PAGE_SIZE, max(1, int(request.args.get("page_size", 50))))
        except ValueError:
            return _err("invalid paging", 400)
        try:
            store = AlertStore()
            try:
                page_data = store.list(status=status, type=type_, since=since, page=page, page_size=page_size)
                counts = store.counts()
            finally:
                store.close()
        except Exception as exc:
            return _err_with_log("alerts_api", exc, lang=_lang())
        return jsonify({"ok": True, **page_data, "counts": counts})

    @bp.route("/api/alerts/<int:alert_id>")
    def get_alert(alert_id: int):
        try:
            store = AlertStore()
            try:
                row = store.get(alert_id)
            finally:
                store.close()
        except Exception as exc:
            return _err_with_log("alerts_api", exc, lang=_lang())
        if row is None:
            return _err("alert not found", 404)
        return jsonify({"ok": True, "alert": row})

    @bp.route("/api/alerts/<int:alert_id>", methods=["PATCH"])
    def patch_alert(alert_id: int):
        data = request.get_json(silent=True) or {}
        status = data.get("status")
        if status not in ALERT_STATUSES:
            return _err("invalid status", 400)
        by = getattr(current_user, "id", None) or "unknown"
        try:
            store = AlertStore()
            try:
                found = store.set_status(alert_id, status, by=str(by))
            finally:
                store.close()
        except Exception as exc:
            return _err_with_log("alerts_api", exc, lang=_lang())
        if not found:
            return _err("alert not found", 404)
        return jsonify({"ok": True})

    @bp.route("/api/alerts/<int:alert_id>/traffic_query")
    def traffic_query(alert_id: int):
        try:
            store = AlertStore()
            try:
                row = store.get(alert_id)
            finally:
                store.close()
        except Exception as exc:
            return _err_with_log("alerts_api", exc, lang=_lang())
        if row is None:
            return _err("alert not found", 404)
        if row["type"] not in ("traffic", "bandwidth"):
            return jsonify({"ok": False, "code": "not_traffic",
                            "error": "only traffic and bandwidth alerts carry a flow query"}), 400
        rule_id = row.get("rule_id")
        rule = None
        if rule_id is not None:
            cm.load()
            # ids may be ints on older configs; the store keeps them as text.
            rule = next((r for r in cm.config.get("rules", []) if str(r.get("id")) == str(rule_id)), None)
        if rule is None or rule.get("type") not in _FLOW_RULE_TYPES:
            return jsonify({"ok": False, "code": "rule_missing",
                            "error": "the rule behind this alert no longer exists"}), 404
        query = {k: rule[k] for k in _FLOW_RULE_QUERY_KEYS if k in rule}
        return jsonify({
            "ok": True,
            "rule": {"id": rule.get("id"), "name": rule.get("name", ""), "type": rule.get("type")},
            "query": query,
        })

    return bp
