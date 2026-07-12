"""Rules Blueprint: CRUD for alert rules (/api/rules*)."""
from __future__ import annotations

import datetime
import json
import os

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager
from src.i18n import t
from src.rule_id import gen_rule_id
from src.gui._helpers import (
    _err,
    _normalize_rule_throttle,
    _normalize_match_fields,
    _resolve_state_file,
)


# Phase 4c：規則版 FilterBar key whitelist（= dashboard 28 key 減 label_groups 4 key）。
# label_group 在規則路徑結構性不可支援（共用未過濾 stream、無 client-side 成員展開），
# 收到一律 400 明確拒絕——不可靜默丟棄。
_RULE_FB_KEYS = (
    "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels",
    "src_iplists", "dst_iplists", "ex_src_iplists", "ex_dst_iplists",
    "src_workloads", "dst_workloads", "ex_src_workloads", "ex_dst_workloads",
    "src_ip_in", "dst_ip_in", "ex_src_ip", "ex_dst_ip",
    "any_label", "any_ip", "any_iplist", "any_workload",
    "ex_any_label", "ex_any_ip", "ex_any_iplist", "ex_any_workload",
    "services", "ex_services", "ports", "ex_ports",
    "process_name", "ex_process_name",
    "windows_service_name", "ex_windows_service_name",
    "transmission", "ex_transmission",
)
_RULE_REJECTED_KEYS = (
    "src_label_groups", "dst_label_groups", "ex_src_label_groups", "ex_dst_label_groups",
    "src_label_group", "dst_label_group", "ex_src_label_group", "ex_dst_label_group",
)
# PUT 整組替換時，連同 _RULE_FB_KEYS 一起從舊 rule 移除的 legacy scalar filter key。
_RULE_LEGACY_SCALAR_KEYS = (
    "src_label", "dst_label", "src_ip_in", "dst_ip_in",
    "ex_src_label", "ex_dst_label", "ex_src_ip", "ex_dst_ip",
)


def _extract_rule_filters(f, lang):
    """filters dict → (flat_dict, error_response|None)。label_group key 回 400。"""
    bad = [k for k in _RULE_REJECTED_KEYS if f.get(k)]
    if bad:
        return None, _err(t("gui_rule_label_group_unsupported", lang=lang), 400)
    out = {}
    for k in _RULE_FB_KEYS:
        v = f.get(k)
        if v:
            out[k] = v
    return out, None


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
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            throttle = _normalize_rule_throttle(d.get('throttle', ''))
            match_fields = _normalize_match_fields(d.get('match_fields'))
        except ValueError as exc:
            return _err(str(exc), 400)
        filter_value = d.get('filter_value', '')
        if filter_value == 'pce_health':
            return _err(t("gui_err_pce_health_use_system_form", lang=lang), 400)
        try:
            threshold_count = int(d.get('threshold_count', 1))
            threshold_window = int(d.get('threshold_window', 10))
            cooldown_minutes = int(d.get('cooldown_minutes', 10))
        except (TypeError, ValueError):
            return _err(t("gui_err_invalid_number", lang=lang), 400)
        cm.add_or_update_rule({
            "id": gen_rule_id(),
            "type": "event",
            "filter_key": "event_type",
            "name": d.get('name', ''),
            "filter_value": filter_value,
            "filter_status": d.get('filter_status', 'all'),
            "filter_severity": d.get('filter_severity', 'all'),
            "desc": d.get('name', ''),
            "rec": t("gui_rule_default_rec_check_logs", lang=lang, default="Check Logs"),
            "threshold_type": d.get('threshold_type', 'immediate'),
            "threshold_count": threshold_count,
            "threshold_window": threshold_window,
            "cooldown_minutes": cooldown_minutes,
            "throttle": throttle,
            "match_fields": match_fields,
        })
        return jsonify({"ok": True})

    @bp.route('/api/rules/system', methods=['POST'])
    def api_add_system_rule():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            throttle = _normalize_rule_throttle(d.get('throttle', ''))
        except ValueError as exc:
            return _err(str(exc), 400)
        filter_value = str(d.get('filter_value') or 'pce_health').strip() or 'pce_health'
        if filter_value != 'pce_health':
            return _err(t("gui_err_unsupported_system_rule_type", lang=lang), 400)
        cm.add_or_update_rule({
            "id": gen_rule_id(),
            "type": "system",
            "name": d.get('name') or t('rule_pce_health', lang=lang),
            "filter_value": "pce_health",
            "desc": t('rule_pce_health_desc', lang=lang, default='PCE health check failed.'),
            "rec": t('rule_pce_health_rec', lang=lang, default='Check PCE service status and network connectivity.'),
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
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
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

        f = d.get('filters')
        if isinstance(f, dict):
            # Phase 4c：前端 FilterBar 直送 filters dict——照 whitelist 展平存入，
            # label_group key 明確拒絕（見 _extract_rule_filters）。
            flat, err_resp = _extract_rule_filters(f, lang)
            if err_resp is not None:
                return err_resp
            cm.add_or_update_rule({
                "id": gen_rule_id(),
                "type": "traffic",
                "name": d.get('name', ''),
                "pd": int(d.get('pd', 2)),
                "port": port, "proto": proto,
                "ex_port": ex_port,
                "desc": d.get('name', ''), "rec": t("gui_rule_default_rec_check_policy", lang=lang, default="Check Policy"),
                "threshold_type": "count",
                "threshold_count": int(d.get('threshold_count', 10)),
                "threshold_window": int(d.get('threshold_window', 10)),
                "cooldown_minutes": int(d.get('cooldown_minutes', 10)),
                "throttle": throttle,
                **flat,
            })
        else:
            cm.add_or_update_rule({
                "id": gen_rule_id(),
                "type": "traffic",
                "name": d.get('name', ''),
                "pd": int(d.get('pd', 2)),
                "port": port, "proto": proto,
                "src_label": src_label, "dst_label": dst_label,
                "src_ip_in": src_ip, "dst_ip_in": dst_ip,
                "ex_port": ex_port,
                "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
                "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip,
                "desc": d.get('name', ''), "rec": t("gui_rule_default_rec_check_policy", lang=lang, default="Check Policy"),
                "threshold_type": "count",
                "threshold_count": int(d.get('threshold_count', 10)),
                "threshold_window": int(d.get('threshold_window', 10)),
                "cooldown_minutes": int(d.get('cooldown_minutes', 10)),
                "throttle": throttle,
            })
        return jsonify({"ok": True})

    @bp.route('/api/rules/bandwidth', methods=['POST'])
    def api_add_bw_rule():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
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

        f = d.get('filters')
        if isinstance(f, dict):
            # Phase 4c：前端 FilterBar 直送 filters dict——照 whitelist 展平存入，
            # label_group key 明確拒絕（見 _extract_rule_filters）。
            flat, err_resp = _extract_rule_filters(f, lang)
            if err_resp is not None:
                return err_resp
            cm.add_or_update_rule({
                "id": gen_rule_id(),
                "type": d.get('rule_type', 'bandwidth'),
                "name": d.get('name', ''),
                "pd": int(d.get('pd', -1)),
                "port": port, "proto": None,
                "ex_port": ex_port,
                "desc": d.get('name', ''), "rec": t("gui_rule_default_rec_check_logs", lang=lang, default="Check Logs"),
                "threshold_type": "count",
                "threshold_count": float(d.get('threshold_count', 100)),
                "threshold_window": int(d.get('threshold_window', 10)),
                "cooldown_minutes": int(d.get('cooldown_minutes', 30)),
                "throttle": throttle,
                **flat,
            })
        else:
            cm.add_or_update_rule({
                "id": gen_rule_id(),
                "type": d.get('rule_type', 'bandwidth'),
                "name": d.get('name', ''),
                "pd": int(d.get('pd', -1)),
                "port": port, "proto": None,
                "src_label": src_label, "dst_label": dst_label,
                "src_ip_in": src_ip, "dst_ip_in": dst_ip,
                "ex_port": ex_port,
                "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
                "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip,
                "desc": d.get('name', ''), "rec": t("gui_rule_default_rec_check_logs", lang=lang, default="Check Logs"),
                "threshold_type": "count",
                "threshold_count": float(d.get('threshold_count', 100)),
                "threshold_window": int(d.get('threshold_window', 10)),
                "cooldown_minutes": int(d.get('cooldown_minutes', 30)),
                "throttle": throttle,
            })
        return jsonify({"ok": True})

    @bp.route('/api/rules/<int:idx>')
    def api_get_rule(idx):
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        cm.load()
        if 0 <= idx < len(cm.config['rules']):
            return jsonify({"index": idx, **cm.config['rules'][idx]})
        return _err(t("gui_not_found", lang=lang), 404)

    @bp.route('/api/rules/<int:idx>', methods=['PUT'])
    def api_update_rule(idx):
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        # Re-load and save under the shared config lock so a concurrent writer
        # (or the background scheduler's cm.load()) cannot interleave and either
        # lose this update or expose a half-updated rules list.
        with cm.write_lock:
            cm.load()
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
                # Phase 4c final review Finding 1：label_group 拒絕檢查除了 filters
                # dict 外，也要擋 d 頂層直注入（PUT body 把 src_label_groups 等放在
                # filters 外層），否則會繞過白名單經 old.update(d) 存進 rule——
                # 檢查同樣須在動到 old 之前完成，400 時 old 完全未被動過。
                bad_top = [k for k in _RULE_REJECTED_KEYS if d.get(k)]
                if bad_top:
                    return _err(t("gui_rule_label_group_unsupported", lang=lang), 400)
                # Phase 4c：filters dict 另外處理（整組替換），不隨 old.update(d) 混入。
                # label_group 拒絕檢查須在動到 old 之前完成——400 時 old 必須完全未被
                # 動過（見 filter-selector Phase 4c review：動了才拒絕會讓共用的 rule
                # dict 在 monitor 執行緒讀到的瞬間被改壞，造成靜默漏告警）。
                f = d.pop('filters', None)
                flat = None
                if isinstance(f, dict):
                    flat, err_resp = _extract_rule_filters(f, lang)
                    if err_resp is not None:
                        return err_resp
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
                if flat is not None:
                    # 整組替換：先清掉舊 rule 中所有 filter key（object/複數 + legacy
                    # scalar + label_group 歷史注入殘留），避免新舊混存，再套用新的
                    # flat 值。_RULE_REJECTED_KEYS 加入是為了讓帶 filters 的 PUT 能
                    # 順便清掉過去頂層注入留下的殘留值（見 Finding 1）。
                    for k in _RULE_FB_KEYS + _RULE_LEGACY_SCALAR_KEYS + _RULE_REJECTED_KEYS:
                        old.pop(k, None)
                    old.update(flat)
                # Cast numeric fields
                for k in ('port', 'ex_port', 'proto', 'threshold_count', 'threshold_window', 'cooldown_minutes', 'pd'):
                    if k in old and old[k] is not None:
                        try: old[k] = int(old[k]) if k != 'threshold_count' else float(old[k])
                        except (ValueError, TypeError): pass  # intentional fallback: keep raw value if numeric cast fails
                cm.save()
                return jsonify({"ok": True})
            return _err(t("gui_not_found", lang=lang), 404)

    @bp.route('/api/rules/<int:idx>', methods=['DELETE'])
    def api_delete_rule(idx):
        # Re-load and delete under the shared config lock so a concurrent writer
        # cannot lose this deletion (or a parallel update).
        with cm.write_lock:
            cm.load()
            cm.remove_rules_by_index([idx])
        return jsonify({"ok": True})

    @bp.route('/api/rules/<int:idx>/highlight')
    def api_rule_highlight(idx: int):
        import json as _json
        from src.report.exporters.code_highlighter import highlight_json
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        cm.load()
        rules = cm.config.get("rules", [])
        if idx < 0 or idx >= len(rules):
            return _err(t("gui_not_found", lang=lang), 404)
        html = highlight_json(_json.dumps(rules[idx], indent=2, ensure_ascii=False))
        return jsonify({"html": html})

    return bp
