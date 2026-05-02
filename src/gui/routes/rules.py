"""Rules Blueprint: CRUD for alert rules (/api/rules*)."""
from __future__ import annotations

import datetime
import json
import os

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager
from src.i18n import t
from src.gui._helpers import (
    _err,
    _normalize_rule_throttle,
    _normalize_match_fields,
    _resolve_state_file,
)


def make_rules_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance
    login_required,  # flask_login.login_required decorator
) -> Blueprint:
    bp = Blueprint("rules", __name__)

    @bp.route('/api/rules')
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
                    logger.debug("Could not compute cooldown_remaining for rule {}: {}", rid, e)
            rule_out['cooldown_remaining'] = rem_mins
            throttle_entry = throttle_state.get(rid, {})
            rule_out['throttle_state'] = {
                "cooldown_suppressed": int(throttle_entry.get("cooldown_suppressed", 0) or 0),
                "throttle_suppressed": int(throttle_entry.get("throttle_suppressed", 0) or 0),
                "next_allowed_at": throttle_entry.get("next_allowed_at", ""),
            }
            rules.append(rule_out)

        return jsonify(rules)

    @bp.route('/api/rules/event', methods=['POST'])
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

    @bp.route('/api/rules/system', methods=['POST'])
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

    @bp.route('/api/rules/traffic', methods=['POST'])
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

    @bp.route('/api/rules/bandwidth', methods=['POST'])
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

    @bp.route('/api/rules/<int:idx>')
    def api_get_rule(idx):
        cm.load()
        if 0 <= idx < len(cm.config['rules']):
            return jsonify({"index": idx, **cm.config['rules'][idx]})
        return _err(t("gui_not_found"), 404)

    @bp.route('/api/rules/<int:idx>', methods=['PUT'])
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
                    except (ValueError, TypeError): pass  # intentional fallback: keep raw value if numeric cast fails
            cm.save()
            return jsonify({"ok": True})
        return _err(t("gui_not_found"), 404)

    @bp.route('/api/rules/<int:idx>', methods=['DELETE'])
    def api_delete_rule(idx):
        cm.remove_rules_by_index([idx])
        return jsonify({"ok": True})

    @bp.route('/api/rules/<int:idx>/highlight')
    def api_rule_highlight(idx: int):
        import json as _json
        from src.report.exporters.code_highlighter import highlight_json
        cm.load()
        rules = cm.config.get("rules", [])
        if idx < 0 or idx >= len(rules):
            return _err(t("gui_not_found"), 404)
        html = highlight_json(_json.dumps(rules[idx], indent=2, ensure_ascii=False))
        return jsonify({"html": html})

    return bp
