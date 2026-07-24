"""Rule Scheduler Blueprint: /api/rule_scheduler/* routes."""
from __future__ import annotations

import datetime
import os
import threading

from contextlib import contextmanager

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

# ScheduleDB 寫入序列化：ScheduleDB 是「整檔覆寫」（load→改記憶體 dict→save
# 全量重寫 rule_schedules.json），本身無任何跨 instance 鎖，而每個 GUI route
# 都各自新建 instance——任何兩個寫入者交錯，後存檔的一方會用自己「請求開始
# 時」的過期快照整檔蓋掉前者（新建的 schedule 憑空消失、到期已刪的 one_time
# 復活）。所有 GUI 端寫入一律：持這把 module 級鎖 → 鎖內 db.load() 重讀 →
# 改動 → save。（APScheduler tick 的 engine.check 在排程器行程側，不在此鎖
# 範圍；GUI 的 /check 端點有納入。）
_rs_db_lock = threading.Lock()


def _rs_db_set_status(db, href, status):
    """pce_status 對帳寫回：鎖內 re-load 後只改該 entry 的 pce_status。
    條目已被併發刪除時直接略過——不得用過期快照把它復活。"""
    with _rs_db_lock:
        db.load()
        fresh = db.db.get(href)
        if fresh is not None and fresh.get('pce_status') != status:
            fresh['pce_status'] = status
            db.save()


def make_rule_scheduler_blueprint(
    cm: ConfigManager,
    login_required,
) -> Blueprint:
    bp = Blueprint("rule_scheduler", __name__)

    @contextmanager
    def _get_rs_components():
        """Lazy-init Rule Scheduler components.

        Context manager：內部的 ApiClient 用 `with` 持有，離開時自動 close()，
        供每個 route handler 用 `with _get_rs_components() as (db, api, engine):`
        取用，避免每個呼叫點各自重複管連線生命週期。
        """
        from src.rule_scheduler import ScheduleDB, ScheduleEngine
        from src.api_client import ApiClient
        db_path = os.path.join(_resolve_config_dir(), "rule_schedules.json")
        db = ScheduleDB(db_path)
        db.load()
        with ApiClient(cm) as api:
            engine = ScheduleEngine(db, api)
            yield db, api, engine

    @bp.route('/api/rule_scheduler/status')
    def rs_status():
        rs_cfg = cm.config.get("rule_scheduler", {})
        from src.rule_scheduler import ScheduleDB, compute_next_trigger
        db = ScheduleDB(os.path.join(_resolve_config_dir(), "rule_schedules.json"))
        db.load()
        schedules = db.get_all()
        next_at = compute_next_trigger(schedules)

        # timeline_24h: bucket [ACTION] toggles from the in-memory log deque into
        # the last 24 hours by UTC hour. Empty list → frontend shows empty state.
        import src.gui as _gui_module
        with _gui_module._rs_log_lock:
            history = list(_gui_module._rs_log_history)
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now_utc - datetime.timedelta(hours=24)
        timeline_24h = []
        for entry in history:
            ts_raw = entry.get("timestamp")
            if not ts_raw:
                continue
            try:
                ts = datetime.datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=datetime.timezone.utc
                )
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue
            count = sum(1 for line in entry.get("logs", []) if "[ACTION]" in line)
            if count:
                timeline_24h.append({"hour": ts.hour, "count": count})

        return jsonify({
            "check_interval_seconds": rs_cfg.get("check_interval_seconds", 300),
            "schedule_count": len(schedules),
            "next_trigger_at": next_at,
            "timeline_24h": timeline_24h,
        })

    @bp.route('/api/rule_scheduler/rulesets')
    def rs_rulesets():
        with _get_rs_components() as (db, api, _):
            q = request.args.get('q', '').strip()
            # Guard against non-numeric query params (?page=abc) → 400-style default
            # instead of an unhandled int() ValueError surfacing as a 500.
            try:
                page = int(request.args.get('page', 1))
            except (TypeError, ValueError):
                page = 1
            try:
                size = int(request.args.get('size', 50))
            except (TypeError, ValueError):
                size = 50
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
        with _get_rs_components() as (db, api, _):
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
        with _get_rs_components() as (db, api, _):
            try:
                api.update_label_cache(silent=True)
            except Exception as _e:
                logger.debug(f"[GUI:label_cache_refresh] swallowed: {_e}")  # best-effort cache warm-up
            try:
                rs = api.get_ruleset_by_id(rs_id)
            except Exception as e:
                return _err(f"PCE API error: {e}", 502)
            if not rs:
                lang = cm.config.get('settings', {}).get('language', 'en')
                return _err(t("gui_err_not_found", lang=lang), 404)

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
        with _get_rs_components() as (db, api, _):
            db_data = db.get_all()
            from src.state_store import load_state_file
            from src.rule_scheduler import _resolve_rule_state_file, _RULE_STATE_KEY
            states = load_state_file(_resolve_rule_state_file()).get(_RULE_STATE_KEY, {})
            # N+1 修正：原本每個 schedule 各打 1-2 個 15s-timeout 的
            # get_live_item PCE GET（串行），慢速/不通的 PCE 下整個 GET 分鐘級
            # 卡死 worker（cheroot 只有 10 條 thread），也拉長 ScheduleDB 的
            # 過期快照窗口。改為單次 get_all_rulesets（draft 視圖含全部
            # ruleset 與 inline rules），本地解析 live enabled/name。
            live_map = None  # None = 抓取失敗 → live 狀態未知，不做 pce_status 對帳
            try:
                live_map = {}
                for rs in api.get_all_rulesets(raise_on_error=True):
                    live_map[rs['href']] = rs
                    for r in (rs.get('sec_rules', []) + rs.get('rules', [])
                              + rs.get('deny_rules', [])):
                        live_map[r['href']] = r
            except Exception as e:
                logger.warning(f"[GUI:rs_schedules_live] rulesets fetch failed, "
                               f"live status unknown: {e}")
                live_map = None
            result = []
            for href, conf in db_data.items():
                entry = dict(conf)
                entry['href'] = href
                entry['id'] = _extract_id_href(href)
                st = states.get(href) or {}
                entry['last_checked'] = st.get('last_checked')
                entry['last_action'] = st.get('last_action')
                entry['last_result'] = st.get('last_result')
                entry['last_error'] = st.get('error')
                # Live status resolution（來源見上方單次抓取）
                if live_map is None:
                    entry['live_enabled'] = None
                    entry['live_name'] = conf.get('name', '')
                else:
                    item = live_map.get(href.replace('/active/', '/draft/'))
                    if item is not None:
                        entry['live_enabled'] = item.get('enabled')
                        entry['live_name'] = item.get('name', conf.get('name', ''))
                        if conf.get('pce_status') == 'deleted':
                            _rs_db_set_status(db, href, 'active')
                            entry['pce_status'] = 'active'
                    else:
                        entry['live_enabled'] = None
                        entry['live_name'] = conf.get('name', '')
                        if conf.get('pce_status') != 'deleted':
                            _rs_db_set_status(db, href, 'deleted')
                        entry['pce_status'] = 'deleted'
                result.append(entry)
            return jsonify(result)

    @bp.route('/api/rule_scheduler/schedules', methods=['POST'])
    def rs_schedule_create():
        with _get_rs_components() as (db, api, _):
            data = request.get_json() or {}
            lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            href = data.get('href', '')
            if not href:
                return _err("href required", 400)

            # Block draft-only scheduling natively for GUI
            if api.has_draft_changes(href) or not api.is_provisioned(href):
                return jsonify({"ok": False, "error": t("rs_sch_draft_block", lang=lang)}), 400

            # type 前置驗證：預設 'recurring' 與精確比對的組裝分支不一致，缺/畸形
            # type 會存成無 days/start/end 的畸形 recurring→check 每 tick KeyError，
            # 或缺 expire_at→500（2026-07-24 審查 BUG-3）
            rtype = data.get('type')
            if rtype not in ('recurring', 'one_time'):
                return _err(t("gui_err_invalid_rule_sched_type", lang=lang), 400)

            # Validate time format for recurring
            if data.get('type') == 'recurring':
                try:
                    datetime.datetime.strptime(data['start'], "%H:%M")
                    datetime.datetime.strptime(data['end'], "%H:%M")
                except (ValueError, KeyError):
                    return _err(t("gui_err_invalid_time_hhmm", lang=lang), 400)
            elif data.get('type') == 'one_time':
                try:
                    ex = data['expire_at'].replace(' ', 'T')
                    datetime.datetime.fromisoformat(ex)
                    data['expire_at'] = ex
                except (ValueError, KeyError):
                    return _err(t("gui_err_invalid_expire_fmt", lang=lang), 400)

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
                # Force English for PCE-stored annotation. The note ends up inside
                # the PCE rule's description field, where it is opaque data that
                # later report runs surface verbatim — embedding Chinese here would
                # leak into EN-mode audit / policy-usage reports.
                days_str = ",".join([d[:3] for d in db_entry['days']]) if len(db_entry['days']) < 7 else t('rs_action_everyday', lang='en')
                act_str = t('rs_action_enable_in_window', lang='en') if db_entry['action'] == 'allow' else t('rs_action_disable_in_window', lang='en')
                tz_display = db_entry['timezone'] if db_entry['timezone'] != 'local' else 'Local'
                note = f"[📅 {t('rs_sch_tag_recurring', lang='en')}: {days_str} {db_entry['start']}-{db_entry['end']} ({tz_display}) {act_str}]"
            else:
                db_entry['expire_at'] = data['expire_at']
                db_entry['timezone'] = data.get('timezone', 'local')
                note = f"[⏰ {t('rs_sch_tag_expire', lang='en')}: {data['expire_at'].replace('T', ' ')}]"

            with _rs_db_lock:
                db.load()
                prev = db.db.get(href)
                db.put(href, db_entry)
            # PCE 註記寫入失敗（update_rule_note 以回傳 False 表示，不 raise）
            # 不得靜默：規則會被排程器悄悄開關，但 PCE 上其他管理者看不到任何
            # 註記。回滾剛寫入的 schedule 並回報錯誤，讓操作者重試。
            if not api.update_rule_note(href, note):
                logger.warning(f"[GUI:rs_schedule_create] PCE note write failed for {href}; "
                               "rolling back schedule entry")
                with _rs_db_lock:
                    db.load()
                    if prev is None:
                        if href in db.db:
                            del db.db[href]
                            db.save()
                    else:
                        db.put(href, prev)
                return _err(t("gui_api_update_failed", lang=lang), 502)
            return jsonify({"ok": True, "id": _extract_id_href(href)})

    @bp.route('/api/rule_scheduler/schedules/<path:href>')
    def rs_schedule_detail(href):
        with _get_rs_components() as (db, _, _):
            lang = cm.config.get('settings', {}).get('language', 'en')
            href = '/' + href if not href.startswith('/') else href
            conf = db.get(href)
            if not conf:
                return _err(t("gui_err_not_found", lang=lang), 404)
            entry = dict(conf)
            entry['href'] = href
            entry['id'] = _extract_id_href(href)
            return jsonify(entry)

    @bp.route('/api/rule_scheduler/schedules/delete', methods=['POST'])
    def rs_schedule_delete():
        with _get_rs_components() as (db, api, _):
            data = request.get_json(silent=True) or {}
            hrefs = data.get('hrefs', [])
            deleted = []
            # 註記清除失敗（回 False 或 raise）要記 warning 並回報 href 清單：
            # 本地 entry 刪掉後不會再有人清這個 PCE 註記，靜默吞掉＝永久殘留。
            note_clear_failed = []
            for href in hrefs:
                try:
                    if not api.update_rule_note(href, "", remove=True):
                        note_clear_failed.append(href)
                        logger.warning(f"[GUI:rule_note_clear] PCE note clear failed for {href}")
                except Exception as _e:
                    note_clear_failed.append(href)
                    logger.warning(f"[GUI:rule_note_clear] PCE note clear raised for {href}: {_e}")
                with _rs_db_lock:
                    db.load()
                    if db.delete(href):
                        deleted.append(_extract_id_href(href))
            return jsonify({"ok": True, "deleted": deleted,
                            "note_clear_failed": note_clear_failed})

    @bp.route('/api/rule_scheduler/check', methods=['POST'])
    def rs_check():
        with _get_rs_components() as (db, _, engine):
            tz_str = cm.config.get('settings', {}).get('timezone', 'local')
            # engine.check 內部會 db.put/db.delete：納入同一把寫入鎖並先重讀，
            # 避免與其他 GUI 寫入路由的整檔覆寫互相清掉。
            with _rs_db_lock:
                db.load()
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
