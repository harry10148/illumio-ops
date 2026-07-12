"""Dashboard Blueprint: status, chart, and query routes."""
from __future__ import annotations

import os
import json
import datetime

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager
from src import __version__
from src.gui import _helpers
from src.gui._helpers import (
    _ok, _err, _err_with_log,
    _get_cache_engine,
    _resolve_reports_dir, _resolve_state_file,
    _ui_translation_dict,
    _summarize_alert_channels,
    _get_active_pce_url,
)
from src.i18n import t
from src.dashboard_store import read_dashboard_summary


def _retranslate_kpi_labels(data: dict, lang: str) -> None:
    """Re-render KPI labels in `data` using the current language.

    Each snapshot JSON has a `kpis` list of `{label, value, label_key?}` dicts.
    The `label` field was written using the language active at report time
    (so old snapshots show old-language labels). When `label_key` is present,
    overwrite `label` with `t(label_key, lang=lang)` so the dashboard always
    matches the user's current language preference.

    Legacy snapshots without `label_key` are left as-is — they'll naturally
    refresh next time the corresponding report is regenerated.
    """
    if not isinstance(data, dict):
        return
    kpis = data.get("kpis")
    if not isinstance(kpis, list):
        return
    for kpi in kpis:
        if not isinstance(kpi, dict):
            continue
        key = kpi.get("label_key")
        if not key:
            continue
        rendered = t(key, lang=lang, default=kpi.get("label", ""))
        if rendered and not rendered.startswith("[MISSING:"):
            kpi["label"] = rendered


def _cache_session(cm):
    from sqlalchemy.orm import sessionmaker
    # Reuse a single cached Engine per db_path instead of creating (and leaking)
    # a new one per request. See _get_cache_engine() for the NullPool rationale.
    return sessionmaker(_get_cache_engine(cm.models.pce_cache.db_path))


_BLOCKED_KEYS = {"allowed": "allowed", "potentially_blocked": "potential", "blocked": "blocked"}


def _overview_blocked(cm, window_days=7):
    if not cm.models.pce_cache.enabled:
        return {"verdict": "no_cache"}
    import datetime as dt
    from sqlalchemy import func, select
    from src.pce_cache.models import PceTrafficFlowAgg
    now = dt.datetime.now(dt.timezone.utc)
    cur_start = now - dt.timedelta(days=window_days)
    prev_start = now - dt.timedelta(days=2 * window_days)
    try:
        sf = _cache_session(cm)

        def _sum(s, lo, hi):
            out = {"allowed": 0, "potential": 0, "blocked": 0}
            rows = s.execute(
                select(PceTrafficFlowAgg.action, func.sum(PceTrafficFlowAgg.flow_count))
                .where(PceTrafficFlowAgg.bucket_day >= lo)
                .where(PceTrafficFlowAgg.bucket_day < hi)
                .group_by(PceTrafficFlowAgg.action)).all()
            for action, n in rows:
                out[_BLOCKED_KEYS.get((action or "").lower(), "blocked")] += int(n or 0)
            return out

        with sf() as s:
            cur = _sum(s, cur_start, now)
            prev = _sum(s, prev_start, cur_start)
    except Exception as e:
        return {"verdict": "unknown", "note": str(e)[:120]}
    cur_flag = cur["blocked"] + cur["potential"]
    prev_flag = prev["blocked"] + prev["potential"]
    vs_prev = int(round((cur_flag - prev_flag) / prev_flag * 100)) if prev_flag else 0
    verdict = "warn" if (prev_flag and vs_prev > 50) else "ok"
    return {"window_days": window_days, **cur, "flagged": cur_flag,
            "vs_prev_pct": vs_prev, "verdict": verdict}


def _overview_pipeline(cm):
    if not cm.models.pce_cache.enabled:
        return {"verdict": "no_cache"}
    import datetime as dt
    from sqlalchemy import func, select
    try:
        from src.pce_cache.lag_monitor import check_cache_lag
        from src.pce_cache.models import SiemDispatch, DeadLetter
        from src.pce_cache.health import pipeline_verdict
        sf = _cache_session(cm)
        try:
            _cfg = cm.models.pce_cache
            _max_lag = max(_cfg.events_poll_interval_seconds,
                           _cfg.traffic_poll_interval_seconds) * 3
        except AttributeError:
            _max_lag = 300
        lag = check_cache_lag(sf, max_lag_seconds=_max_lag)
        cache_lag = [{"source": r["source"], "lag_s": int(r["lag_seconds"]),
                      "level": r["level"]} for r in lag]
        now = dt.datetime.now(dt.timezone.utc)
        hr_ago = now - dt.timedelta(hours=1)
        with sf() as s:
            sent = s.execute(select(func.count()).select_from(SiemDispatch)
                             .where(SiemDispatch.status == "sent")
                             .where(SiemDispatch.sent_at >= hr_ago)).scalar() or 0
            failed = s.execute(select(func.count()).select_from(SiemDispatch)
                               .where(SiemDispatch.status == "failed")
                               .where(SiemDispatch.queued_at >= hr_ago)).scalar() or 0
            dlq = s.execute(select(func.count()).select_from(DeadLetter)).scalar() or 0
        denom = sent + failed
        success_1h = round(sent / denom * 100, 1) if denom else 100.0
        lag_levels = [c["level"] for c in cache_lag]
        verdict = pipeline_verdict(lag_levels=lag_levels, siem_success_1h=success_1h,
                                   denom=denom, dlq=int(dlq))
        return {"cache_lag": cache_lag, "siem_success_1h": success_1h,
                "dlq": int(dlq), "verdict": verdict}
    except Exception as e:
        return {"verdict": "unknown", "note": str(e)[:120]}


def _overview_alerts(state):
    import datetime as dt
    hist = state.get("dispatch_history") or []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)

    def _recent(ts):
        try:
            return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")) >= cutoff
        except Exception:
            return True

    last24 = [h for h in hist if _recent(h.get("timestamp"))]
    failed = sum(1 for h in last24 if h.get("status") == "failed")
    suppressed = sum(int((v or {}).get("suppressed", 0))
                     for v in (state.get("throttle_state") or {}).values()
                     if isinstance(v, dict))
    verdict = "warn" if failed >= 1 else "ok"
    return {"fired_24h": len(last24), "suppressed": suppressed, "failed": failed,
            "recent": last24[-5:], "verdict": verdict}


def _overview_os_dist(state):
    vs = read_dashboard_summary().get("ven_summary") or {}
    od = vs.get("os_distribution")
    if not isinstance(od, dict) or "by_family" not in od:
        return None
    return {"by_family": od["by_family"], "total": od.get("total", 0)}


def _overview_enforcement(state):
    vs = read_dashboard_summary().get("ven_summary") or {}
    ed = vs.get("enforcement_distribution")
    if not isinstance(ed, dict) or "by_mode" not in ed:
        return None
    return {"by_mode": ed["by_mode"], "total": ed.get("total", 0)}


def _overview_posture(state):
    """Compute the posture score directly from the latest report KPI snapshot.

    Reads a tiny (~1 KB) KPI-only snapshot and runs simple arithmetic — NOT a
    traffic recompute — so it stays fast while avoiding the state-write race
    (the analyzer's monitor-cycle state merge could otherwise stomp a
    background-job-written posture_summary). Falls back to any cached
    posture_summary in state, then to {available: False}.
    """
    try:
        from src.report.snapshot_store import read_latest
        from src.report.posture import compute_posture
        from src.report.posture_advisor import build_remediation
        snap = read_latest("traffic")
        if snap:
            p = compute_posture(snap.get("kpis") or snap)
            if p.get("available"):
                p["source_date"] = snap.get("generated_at", "")
                p["remediation"] = build_remediation(p)
                return p
    except Exception:
        pass
    ps = state.get("posture_summary")
    if isinstance(ps, dict) and ("score" in ps or ps.get("available") is False):
        if ps.get("available") and "remediation" not in ps:
            try:
                from src.report.posture_advisor import build_remediation
                ps["remediation"] = build_remediation(ps)
            except Exception:
                pass
        return ps
    return {"available": False}


def _overview_ven(state):
    vs = read_dashboard_summary().get("ven_summary")
    if not isinstance(vs, dict) or "total" not in vs:
        return {"verdict": "unknown", "note": "no ven_summary yet"}
    total = int(vs.get("total", 0)); offline = int(vs.get("offline", 0))
    err_threshold = max(1, -(-total // 10))  # ceil(total*0.10)
    if offline == 0:
        verdict = "ok"
    elif offline > err_threshold:
        verdict = "error"
    else:
        verdict = "warn"
    return {"total": total, "online": int(vs.get("online", 0)), "offline": offline,
            "degraded": int(vs.get("degraded", 0)),
            "oldest_heartbeat_age_s": int(vs.get("oldest_heartbeat_age_s", 0)),
            "attention": (vs.get("attention") or [])[:20], "verdict": verdict}


def make_dashboard_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance (unused here, kept for consistent signature)
    login_required,  # flask_login.login_required decorator
) -> Blueprint:
    bp = Blueprint("dashboard", __name__)

    # ── API: Status ────────────────────────────────────────────────────────────
    @bp.route('/api/ui_translations')
    def api_ui_translations():
        lang = cm.config.get("settings", {}).get("language", "en")
        return jsonify(_ui_translation_dict(lang))

    @bp.route('/api/status')
    def api_status():
        cm.load()
        state = {}
        cooldowns = []
        try:
            STATE_FILE = _resolve_state_file()
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)

                now = datetime.datetime.now(datetime.timezone.utc)
                alert_history = state.get("alert_history", {})

                for rule in cm.config['rules']:
                    rid = str(rule['id'])
                    rem_mins = 0
                    if rid in alert_history:
                        try:
                            last_alert_str = alert_history[rid]
                            last_ts = datetime.datetime.strptime(last_alert_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                            cd_mins = int(rule.get('cooldown_minutes', 0))
                            if cd_mins > 0:
                                elapsed = (now - last_ts).total_seconds()
                                total_cd = cd_mins * 60
                                if elapsed < total_cd:
                                    rem_mins = int((total_cd - elapsed) // 60) + 1
                        except Exception as e:
                            logger.error(f"Error parsing cooldown for rule {rid}: {e}")

                    cooldowns.append({
                        "id": rule['id'],
                        "name": rule.get('name', 'Unknown Rule'),
                        "remaining_mins": rem_mins
                    })
        except Exception as e:
            logger.error(f"Error reading state file for cooldowns: {e}")

        has_health_rule = any(
            r.get("type") == "system" and r.get("filter_value") == "pce_health"
            for r in cm.config.get("rules", [])
        )
        lang = cm.config.get('settings', {}).get('language', 'en') or 'en'
        return jsonify({
            "version": __version__,
            "api_url": _get_active_pce_url(cm),
            "rules_count": len(cm.config['rules']),
            "health_check": has_health_rule,
            "language": lang,
            "theme": cm.config.get('settings', {}).get('theme', 'dark'),
            "timezone": cm.config.get('settings', {}).get('timezone', 'local'),
            "cooldowns": cooldowns,
            "event_watermark": state.get("event_watermark") or state.get("last_check"),
            "event_overflow": state.get("event_overflow", {}),
            "unknown_events": state.get("unknown_events", {}),
            "event_parser_stats": state.get("event_parser_stats", {}),
            "event_parser_samples": state.get("event_parser_samples", []),
            "pce_stats": state.get("pce_stats", {}),
            "throttle_state": state.get("throttle_state", {}),
            "dispatch_history": state.get("dispatch_history", []),
            "alert_channels": _summarize_alert_channels(cm.config, state.get("dispatch_history", []), lang=lang),
            "event_timeline": state.get("event_timeline", []),
        })

    @bp.route('/api/dashboard/overview', methods=['GET'])
    def api_dashboard_overview():
        cm.load()
        state = {}
        STATE_FILE = _helpers._resolve_state_file()
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception:
                state = {}
        return jsonify({
            "as_of": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ven": _overview_ven(state),
            "blocked": _overview_blocked(cm),
            "pipeline": _overview_pipeline(cm),
            "alerts": _overview_alerts(state),
            "os_dist": _overview_os_dist(state),
            "enforcement": _overview_enforcement(state),
            "posture": _overview_posture(state),
        })

    @bp.route('/api/dashboard/queries', methods=['GET'])
    def api_get_dashboard_queries():
        cm.load()
        queries = cm.config.get('settings', {}).get('dashboard_queries', [])
        return jsonify(queries)

    @bp.route('/api/dashboard/queries', methods=['POST'])
    def api_save_dashboard_query():
        d = request.json or {}
        name = d.get('name', 'My Query')
        rank_by = d.get('rank_by', 'count')
        pd_sel = int(d.get('pd', 3))

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

        idx = d.get('idx')
        f = d.get('filters')
        if isinstance(f, dict):
            # Phase 4b：前端 FilterBar 直送序列化 dict——照 whitelist 展平存入
            # query_def 頂層（flat，與舊 scalar 格式 key 共存；src_ip_in 舊為
            # scalar 新為 list，下游 query_flows 與前端 deserialize 兩種形狀都認）。
            # 原啟發式分支的 whitelist 丟棄 any_*（前端有送）——新分支修正此缺口。
            _fb_keys = (
                "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels",
                "src_label_groups", "dst_label_groups",
                "ex_src_label_groups", "ex_dst_label_groups",
                "src_iplists", "dst_iplists", "ex_src_iplists", "ex_dst_iplists",
                "src_workloads", "dst_workloads", "ex_src_workloads", "ex_dst_workloads",
                "src_ip_in", "dst_ip_in", "ex_src_ip", "ex_dst_ip",
                "any_label", "any_ip", "any_iplist", "any_workload",
                "ex_any_label", "ex_any_ip", "ex_any_iplist", "ex_any_workload",
                "ports", "ex_ports", "services", "ex_services",
            )
            query_def = {
                "name": name, "rank_by": rank_by, "pd": pd_sel,
                "port": port, "proto": proto, "ex_port": ex_port,
            }
            for k in _fb_keys:
                v = f.get(k)
                if v:
                    query_def[k] = v
        else:
            query_def = {
                "name": name,
                "rank_by": rank_by,
                "pd": pd_sel,
                "port": port, "proto": proto,
                "src_label": src_label, "dst_label": dst_label,
                "src_ip_in": src_ip, "dst_ip_in": dst_ip,
                "ex_port": ex_port,
                "ex_src_label": ex_src_label, "ex_dst_label": ex_dst_label,
                "ex_src_ip": ex_src_ip, "ex_dst_ip": ex_dst_ip
            }

        # Serialize load→mutate→save under the shared config lock so concurrent
        # saves (cheroot multi-thread pool) cannot lose a query.
        with cm.write_lock:
            cm.load()
            if 'settings' not in cm.config:
                cm.config['settings'] = {}
            if 'dashboard_queries' not in cm.config['settings']:
                cm.config['settings']['dashboard_queries'] = []

            if idx is not None and 0 <= int(idx) < len(cm.config['settings']['dashboard_queries']):
                cm.config['settings']['dashboard_queries'][int(idx)] = query_def
            else:
                cm.config['settings']['dashboard_queries'].append(query_def)

            cm.save()
        return jsonify({"ok": True})

    @bp.route('/api/dashboard/queries/<int:idx>', methods=['DELETE'])
    def api_delete_dashboard_query(idx):
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        if 'settings' in cm.config and 'dashboard_queries' in cm.config['settings']:
            if 0 <= idx < len(cm.config['settings']['dashboard_queries']):
                cm.config['settings']['dashboard_queries'].pop(idx)
                cm.save()
                return jsonify({"ok": True})
        return _err(t("gui_not_found", lang=lang), 404)

    @bp.route('/api/dashboard/snapshot', methods=['GET'])
    def api_dashboard_snapshot():
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        reports_dir = _resolve_reports_dir(cm)

        snapshot_path = os.path.join(reports_dir, 'latest_snapshot.json')
        if not os.path.exists(snapshot_path):
            return jsonify({"ok": False, "error": t("gui_no_snapshot", lang=lang)})

        try:
            import json
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _retranslate_kpi_labels(data, lang)
            try:
                from src.dashboard_hero import build_hero
                data["hero"] = build_hero(data, status={})
            except Exception as hero_exc:
                logger.warning("dashboard hero build failed: {}", hero_exc)
            return jsonify({"ok": True, "snapshot": data})
        except Exception as e:
            return _err_with_log("dashboard_snapshot", e, lang=lang)

    @bp.route('/api/dashboard/audit_summary', methods=['GET'])
    def api_dashboard_audit_summary():
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        reports_dir = _resolve_reports_dir(cm)
        summary_path = os.path.join(reports_dir, 'latest_audit_summary.json')
        if not os.path.exists(summary_path):
            return jsonify({"ok": False, "error": t("gui_dashboard_no_audit_summary", default="No audit report summary found.", lang=lang)})
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _retranslate_kpi_labels(data, lang)
            return jsonify({"ok": True, "summary": data})
        except Exception as e:
            return _err_with_log("dashboard_audit_summary", e, lang=lang)

    @bp.route('/api/dashboard/policy_usage_summary', methods=['GET'])
    def api_dashboard_policy_usage_summary():
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        reports_dir = _resolve_reports_dir(cm)
        summary_path = os.path.join(reports_dir, 'latest_policy_usage_summary.json')
        if not os.path.exists(summary_path):
            return jsonify({"ok": False, "error": t("gui_dashboard_no_policy_usage_summary", default="No policy usage report summary found.", lang=lang)})
        try:
            with open(summary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _retranslate_kpi_labels(data, lang)
            return jsonify({"ok": True, "summary": data})
        except Exception as e:
            return _err_with_log("dashboard_policy_usage_summary", e, lang=lang)

    @bp.route('/api/dashboard/top10', methods=['POST'])
    @limiter.limit("30 per hour")
    def api_dashboard_top10():
        d = request.json or {}
        try:
            from src.api_client import ApiClient
            from src.analyzer import Analyzer, QUERY_RESULT_CAP
            from src.exceptions import TrafficQueryError
            from src.reporter import Reporter
            import datetime

            api = ApiClient(cm)
            from src.main import _make_cache_reader
            base_ana = Analyzer(cm, api, Reporter(cm),
                                cache_reader=_make_cache_reader(cm))

            mins = int(d.get("mins", 30))
            now = datetime.datetime.now(datetime.timezone.utc)
            start_time = (now - datetime.timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")
            end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            pd_val = int(d.get("pd", 3))
            if pd_val == 1: pds = ["potentially_blocked"]
            elif pd_val == 2: pds = ["blocked"]
            elif pd_val == 0: pds = ["allowed"]
            else: pds = ["blocked", "potentially_blocked", "allowed"]

            rank_by = d.get("rank_by", "bandwidth")

            # Map the inbound payload to the analyzer's query
            params = {
                "start_time": start_time,
                "end_time": end_time,
                "policy_decisions": pds,
                "sort_by": rank_by,
                "search": d.get("search", ""),
                "src_ip_in": d.get("src_ip_in"), "dst_ip_in": d.get("dst_ip_in"),
                "src_label": d.get("src_label"), "dst_label": d.get("dst_label"),
                "ex_src_ip": d.get("ex_src_ip"), "ex_dst_ip": d.get("ex_dst_ip"),
                "ex_src_label": d.get("ex_src_label"), "ex_dst_label": d.get("ex_dst_label"),
                "port": d.get("port"), "ex_port": d.get("ex_port"),
                "proto": d.get("proto"),
                "any_label": d.get("any_label"), "any_ip": d.get("any_ip"),
                "ex_any_label": d.get("ex_any_label"), "ex_any_ip": d.get("ex_any_ip"),
                # Phase 4b：forward FilterBar 的 object/複數 key（原 params dict 漏收，
                # 會在此被靜默丟棄；下游 query_flows whitelist 已全支援）。
                "src_labels": d.get("src_labels", []),
                "dst_labels": d.get("dst_labels", []),
                "ex_src_labels": d.get("ex_src_labels", []),
                "ex_dst_labels": d.get("ex_dst_labels", []),
                "src_label_groups": d.get("src_label_groups", []),
                "dst_label_groups": d.get("dst_label_groups", []),
                "ex_src_label_groups": d.get("ex_src_label_groups", []),
                "ex_dst_label_groups": d.get("ex_dst_label_groups", []),
                "src_iplists": d.get("src_iplists", []),
                "dst_iplists": d.get("dst_iplists", []),
                "ex_src_iplists": d.get("ex_src_iplists", []),
                "ex_dst_iplists": d.get("ex_dst_iplists", []),
                "src_workloads": d.get("src_workloads", []),
                "dst_workloads": d.get("dst_workloads", []),
                "ex_src_workloads": d.get("ex_src_workloads", []),
                "ex_dst_workloads": d.get("ex_dst_workloads", []),
                "any_iplist": d.get("any_iplist", ""),
                "any_workload": d.get("any_workload", ""),
                "ex_any_iplist": d.get("ex_any_iplist", ""),
                "ex_any_workload": d.get("ex_any_workload", ""),
                "ports": d.get("ports", []),
                "ex_ports": d.get("ex_ports", []),
                "services": d.get("services", []),
                "ex_services": d.get("ex_services", []),
            }
            results = base_ana.query_flows(params)

            # Sort and get top 10
            if rank_by == "bandwidth":
                sorted_v = sorted(results, key=lambda x: x.get("max_bandwidth_mbps", 0), reverse=True)
            elif rank_by == "volume":
                sorted_v = sorted(results, key=lambda x: x.get("total_volume_mb", 0), reverse=True)
            else: # count
                sorted_v = sorted(results, key=lambda x: x.get("total_connections", 0), reverse=True)

            top10 = []
            for item in sorted_v[:10]:
                s = item.get('source', {})
                dst = item.get('destination', {})
                sv = item.get('service', {})

                s_name = s.get('name', 'N/A')
                d_name = dst.get('name', 'N/A')
                port = sv.get('port', 'All')
                proto_name = sv.get('proto', '')
                svc_name = sv.get('name') or getattr(sv, 'name', '') or ''
                svc_str = f"{proto_name}/{port}"
                if svc_name:
                    svc_str = f"{svc_name} {svc_str}"

                # Policy Decision mapping for UI
                flow_pd = item.get("policy_decision", "")
                if flow_pd == "allowed": pd_int = 0
                elif flow_pd == "potentially_blocked": pd_int = 1
                else: pd_int = 2 # default to Blocked if unknown or explicitly blocked

                if rank_by == "bandwidth": val_fmt = f"{item.get('max_bandwidth_mbps', 0):.2f} Mbps"
                elif rank_by == "volume":
                    vol_bytes = (item.get('total_volume_mb', 0) or 0) * 1024 * 1024
                    if vol_bytes >= 1024 ** 4:
                        val_fmt = f"{vol_bytes / 1024 ** 4:.2f} TB"
                    elif vol_bytes >= 1024 ** 3:
                        val_fmt = f"{vol_bytes / 1024 ** 3:.2f} GB"
                    elif vol_bytes >= 1024 ** 2:
                        val_fmt = f"{vol_bytes / 1024 ** 2:.1f} MB"
                    elif vol_bytes >= 1024:
                        val_fmt = f"{vol_bytes / 1024:.1f} KB"
                    else:
                        val_fmt = f"{int(vol_bytes)} B"
                else: val_fmt = f"{item.get('total_connections', 0)}"

                first_seen = item.get("first_seen", "")
                last_seen = item.get("last_seen", "")

                top10.append({
                    "val_fmt": val_fmt,
                    "first_seen": first_seen,
                    "last_seen": last_seen,
                    "dir": "<->",
                    "s_name": s_name,
                    "s_ip": s.get('ip', ''),
                    "s_href": s.get('href', ''),
                    "s_process": s.get('process', ''),
                    "s_user": s.get('user', ''),
                    "s_labels": s.get('labels', []),
                    "d_name": d_name,
                    "d_ip": dst.get('ip', ''),
                    "d_href": dst.get('href', ''),
                    "d_process": dst.get('process', ''),
                    "d_user": dst.get('user', ''),
                    "d_labels": dst.get('labels', []),
                    "svc": svc_str,
                    "svc_process": sv.get('process', ''),
                    "svc_user": sv.get('user', ''),
                    "pd": pd_int,
                    "draft_pd": item.get('draft_policy_decision', ''),
                })

            stats = getattr(base_ana, "last_query_stats", {}) or {}
            return jsonify({
                "ok": True,
                "data": top10,
                "total": len(sorted_v),
                "source": getattr(base_ana, "last_query_source", "api"),
                "truncated": bool(stats.get("truncated")),
                "cap": int(stats.get("cap", QUERY_RESULT_CAP)),
            })
        except TrafficQueryError as e:
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return jsonify({"ok": False, "error": t(
                "gui_err_traffic_query_failed", detail=str(e), lang=lang)}), 502
        except Exception as e:
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return _err_with_log("dashboard_top10", e, lang=lang)

    return bp
