"""Rule Scheduler Blueprint: /api/rule_scheduler/* routes."""
from __future__ import annotations

import datetime
import os

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager
from src.gui._helpers import (
    _err,
    _resolve_config_dir,
    _strip_ansi,
)
from src.href_utils import extract_id as _extract_id_href
from src.i18n import t


def make_rule_scheduler_blueprint(
    cm: ConfigManager,
    login_required,
) -> Blueprint:
    bp = Blueprint("rule_scheduler", __name__)

    def _get_rs_components():
        """Lazy-init Rule Scheduler components."""
        from src.rule_scheduler import ScheduleDB, ScheduleEngine
        from src.api_client import ApiClient
        db_path = os.path.join(_resolve_config_dir(), "rule_schedules.json")
        db = ScheduleDB(db_path)
        db.load()
        api = ApiClient(cm)
        engine = ScheduleEngine(db, api)
        return db, api, engine

    @bp.route('/api/rule_scheduler/status')
    def rs_status():
        rs_cfg = cm.config.get("rule_scheduler", {})
        from src.rule_scheduler import ScheduleDB
        db = ScheduleDB(os.path.join(_resolve_config_dir(), "rule_schedules.json"))
        db.load()
        return jsonify({
            "check_interval_seconds": rs_cfg.get("check_interval_seconds", 300),
            "schedule_count": len(db.get_all())
        })

    @bp.route('/api/rule_scheduler/rulesets')
    def rs_rulesets():
        db, api, _ = _get_rs_components()
        q = request.args.get('q', '').strip()
        page = int(request.args.get('page', 1))
        size = int(request.args.get('size', 50))
        try:
            api.update_label_cache(silent=True)
        except Exception as _e:
            logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up

        try:
            if q:
                if q.isdigit():
                    rs = api.get_ruleset_by_id(q)
                    all_rs = [rs] if rs else api.search_rulesets(q)
                else:
                    all_rs = api.search_rulesets(q)
            else:
                all_rs = api.get_all_rulesets()
        except Exception as e:
            return jsonify({"items": [], "total": 0, "page": page, "size": size,
                            "error": f"PCE API error: {e}"}), 200

        total = len(all_rs)
        start = (page - 1) * size
        page_items = all_rs[start:start + size]

        results = []
        for rs in page_items:
            stype = db.get_schedule_type(rs)
            ut = rs.get('update_type')
            all_rules_count = (len(rs.get('rules', [])) + len(rs.get('sec_rules', [])) +
                               len(rs.get('deny_rules', [])))
            results.append({
                "href": rs['href'],
                "id": _extract_id_href(rs['href']),
                "name": rs.get('name', ''),
                "enabled": rs.get('enabled', False),
                "rules_count": all_rules_count,
                "schedule_type": stype,
                "provision_state": "DRAFT" if ut else "ACTIVE"
            })
        return jsonify({"items": results, "total": total, "page": page, "size": size})

    @bp.route('/api/rule_scheduler/rules/search')
    def rs_rules_search():
        db, api, _ = _get_rs_components()
        q = request.args.get('q', '').strip()
        scope = request.args.get('scope', 'desc')  # 'id' or 'desc'
        if not q:
            return jsonify({"items": []})
        try:
            api.update_label_cache(silent=True)
        except Exception as _e:
            logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up
        all_rs = api.get_all_rulesets()
        results = []
        q_lower = q.lower()
        for rs in all_rs:
            rs_id = _extract_id_href(rs['href'])
            rs_name = rs.get('name', '')
            typed_rules = []
            for r in rs.get('sec_rules', []) + rs.get('rules', []):
                typed_rules.append((r, 'allow'))
            for r in rs.get('deny_rules', []):
                rule_type = 'override_deny' if r.get('override') else 'deny'
                typed_rules.append((r, rule_type))
            # Assign no per type section
            no_counters = {'allow': 0, 'deny': 0, 'override_deny': 0}
            for r, rule_type in typed_rules:
                no_counters[rule_type] += 1
                rule_id = _extract_id_href(r['href'])
                desc = r.get('description', '') or ''
                matched = (scope == 'id' and q == rule_id) or \
                          (scope == 'desc' and q_lower in desc.lower())
                if matched:
                    dest_field = r.get('destinations', r.get('consumers', []))
                    results.append({
                        "rs_id": rs_id,
                        "rs_name": rs_name,
                        "rule_id": rule_id,
                        "rule_no": no_counters[rule_type],
                        "rule_type": rule_type,
                        "enabled": r.get('enabled', False),
                        "description": desc,
                        "source": api.resolve_actor_str(dest_field),
                        "dest": api.resolve_actor_str(r.get('providers', [])),
                        "service": api.resolve_service_str(r.get('ingress_services', [])),
                    })
        return jsonify({"items": results})

    @bp.route('/api/rule_scheduler/rulesets/<rs_id>')
    def rs_ruleset_detail(rs_id):
        db, api, _ = _get_rs_components()
        try:
            api.update_label_cache(silent=True)
        except Exception as _e:
            logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up
        try:
            rs = api.get_ruleset_by_id(rs_id)
        except Exception as e:
            return _err(f"PCE API error: {e}", 502)
        if not rs:
            return _err("Not found", 404)

        ut = rs.get('update_type')
        rs_row = {
            "href": rs['href'],
            "id": _extract_id_href(rs['href']),
            "name": rs.get('name', ''),
            "enabled": rs.get('enabled', False),
            "provision_state": "DRAFT" if ut else "ACTIVE",
            "is_scheduled": rs['href'] in db.get_all(),
            "type": "ruleset"
        }

        rules = []
        scheduled_hrefs = db.get_all()
        typed_rules = []
        for r in rs.get('sec_rules', []) + rs.get('rules', []):
            typed_rules.append((r, 'allow'))
        for r in rs.get('deny_rules', []):
            rule_type = 'override_deny' if r.get('override') else 'deny'
            typed_rules.append((r, rule_type))

        no_counters = {'allow': 0, 'deny': 0, 'override_deny': 0}
        for r, rule_type in typed_rules:
            no_counters[rule_type] += 1
            r_ut = r.get('update_type')
            dest_field = r.get('destinations', r.get('consumers', []))
            rules.append({
                "href": r['href'],
                "id": _extract_id_href(r['href']),
                "no": no_counters[rule_type],
                "enabled": r.get('enabled', False),
                "description": r.get('description', ''),
                "provision_state": "DRAFT" if r_ut else "ACTIVE",
                "is_scheduled": r['href'] in scheduled_hrefs,
                "source": api.resolve_actor_str(dest_field),
                "dest": api.resolve_actor_str(r.get('providers', [])),
                "service": api.resolve_service_str(r.get('ingress_services', [])),
                "rule_type": rule_type,
                "type": "rule"
            })
        return jsonify({"ruleset": rs_row, "rules": rules})

    @bp.route('/api/rule_scheduler/schedules')
    def rs_schedules_list():
        db, api, _ = _get_rs_components()
        db_data = db.get_all()
        result = []
        for href, conf in db_data.items():
            entry = dict(conf)
            entry['href'] = href
            entry['id'] = _extract_id_href(href)
            # Live status check
            try:
                status, data = api.get_live_item(href)
                if status == 200 and data:
                    entry['live_enabled'] = data.get('enabled')
                    entry['live_name'] = data.get('name', conf.get('name', ''))
                    if conf.get('pce_status') == 'deleted':
                        conf['pce_status'] = 'active'
                        db.put(href, conf)
                        entry['pce_status'] = 'active'
                elif status == 404:
                    entry['live_enabled'] = None
                    entry['live_name'] = conf.get('name', '')
                    if conf.get('pce_status') != 'deleted':
                        conf['pce_status'] = 'deleted'
                        db.put(href, conf)
                    entry['pce_status'] = 'deleted'
                else:
                    entry['live_enabled'] = None
                    entry['live_name'] = conf.get('name', '')
            except Exception:
                entry['live_enabled'] = None
                entry['live_name'] = conf.get('name', '')
            result.append(entry)
        return jsonify(result)

    @bp.route('/api/rule_scheduler/schedules', methods=['POST'])
    def rs_schedule_create():
        db, api, _ = _get_rs_components()
        data = request.get_json()
        href = data.get('href', '')
        if not href:
            return _err("href required", 400)

        # Block draft-only scheduling natively for GUI
        if api.has_draft_changes(href) or not api.is_provisioned(href):
            return jsonify({"ok": False, "error": t("rs_sch_draft_block")}), 400

        # Validate time format for recurring
        if data.get('type') == 'recurring':
            try:
                datetime.datetime.strptime(data['start'], "%H:%M")
                datetime.datetime.strptime(data['end'], "%H:%M")
            except (ValueError, KeyError):
                return _err("Invalid time format (use HH:MM)", 400)
        elif data.get('type') == 'one_time':
            try:
                ex = data['expire_at'].replace(' ', 'T')
                datetime.datetime.fromisoformat(ex)
                data['expire_at'] = ex
            except (ValueError, KeyError):
                return _err("Invalid expiration format", 400)

        db_entry = {
            "type": data.get('type', 'recurring'),
            "name": data.get('name', ''),
            "is_ruleset": data.get('is_ruleset', False),
            "action": data.get('action', 'allow'),
            "detail_rs": data.get('detail_rs', ''),
            "detail_src": data.get('detail_src', 'All'),
            "detail_dst": data.get('detail_dst', 'All'),
            "detail_svc": data.get('detail_svc', 'All'),
            "detail_name": data.get('detail_name', data.get('name', ''))
        }

        if data.get('type') == 'recurring':
            db_entry['days'] = data.get('days', [])
            db_entry['start'] = data['start']
            db_entry['end'] = data['end']
            db_entry['timezone'] = data.get('timezone', 'local')
            days_str = ",".join([d[:3] for d in db_entry['days']]) if len(db_entry['days']) < 7 else t('rs_action_everyday')
            act_str = t('rs_action_enable_in_window') if db_entry['action'] == 'allow' else t('rs_action_disable_in_window')
            tz_display = db_entry['timezone'] if db_entry['timezone'] != 'local' else 'Local'
            note = f"[?? {t('rs_sch_tag_recurring')}: {days_str} {db_entry['start']}-{db_entry['end']} ({tz_display}) {act_str}]"
        else:
            db_entry['expire_at'] = data['expire_at']
            db_entry['timezone'] = data.get('timezone', 'local')
            note = f"[??{t('rs_sch_tag_expire')}: {data['expire_at'].replace('T', ' ')}]"

        db.put(href, db_entry)
        api.update_rule_note(href, note)
        return jsonify({"ok": True, "id": _extract_id_href(href)})

    @bp.route('/api/rule_scheduler/schedules/<path:href>')
    def rs_schedule_detail(href):
        db, _, _ = _get_rs_components()
        href = '/' + href if not href.startswith('/') else href
        conf = db.get(href)
        if not conf:
            return _err("Not found", 404)
        entry = dict(conf)
        entry['href'] = href
        entry['id'] = _extract_id_href(href)
        return jsonify(entry)

    @bp.route('/api/rule_scheduler/schedules/delete', methods=['POST'])
    def rs_schedule_delete():
        db, api, _ = _get_rs_components()
        data = request.get_json()
        hrefs = data.get('hrefs', [])
        deleted = []
        for href in hrefs:
            try:
                api.update_rule_note(href, "", remove=True)
            except Exception as _e:
                logger.debug(f"[GUI:rule_note_clear] swallowed: {_e}")  # best-effort note removal
            if db.delete(href):
                deleted.append(_extract_id_href(href))
        return jsonify({"ok": True, "deleted": deleted})

    @bp.route('/api/rule_scheduler/check', methods=['POST'])
    def rs_check():
        _, _, engine = _get_rs_components()
        tz_str = cm.config.get('settings', {}).get('timezone', 'local')
        logs = engine.check(silent=True, tz_str=tz_str)
        import src.gui as _gui_module
        _gui_module._append_rs_logs(logs)
        cleaned = [_strip_ansi(l) for l in logs]
        return jsonify({"ok": True, "logs": cleaned})

    @bp.route('/api/rule_scheduler/logs')
    def rs_log_history_api():
        import src.gui as _gui_module
        with _gui_module._rs_log_lock:
            history = list(_gui_module._rs_log_history)
        return jsonify({"ok": True, "history": history})

    return bp
