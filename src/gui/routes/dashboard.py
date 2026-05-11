"""Dashboard Blueprint: status, chart, and query routes."""
from __future__ import annotations

import os
import json
import datetime

from flask import Blueprint, jsonify, request
from loguru import logger

from src.config import ConfigManager
from src import __version__
from src.gui._helpers import (
    _ok, _err, _err_with_log,
    _resolve_reports_dir, _resolve_state_file,
    _ui_translation_dict,
    _summarize_alert_channels,
    _get_active_pce_url,
    _spec_to_plotly_figure,
    _load_state_for_charts,
    _build_traffic_timeline_spec,
    _build_policy_decisions_spec,
    _build_ven_status_spec,
    _build_rule_hits_spec,
)
from src.i18n import t


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

    @bp.route('/api/dashboard/queries', methods=['GET'])
    def api_get_dashboard_queries():
        cm.load()
        queries = cm.config.get('settings', {}).get('dashboard_queries', [])
        return jsonify(queries)

    @bp.route('/api/dashboard/queries', methods=['POST'])
    def api_save_dashboard_query():
        d = request.json or {}
        cm.load()
        if 'settings' not in cm.config:
            cm.config['settings'] = {}
        if 'dashboard_queries' not in cm.config['settings']:
            cm.config['settings']['dashboard_queries'] = []

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

    @bp.route('/api/dashboard/chart/<chart_id>')
    def api_dashboard_chart(chart_id: str):
        cm.load()
        lang = cm.config.get('settings', {}).get('language', 'en')
        _builders = {
            "traffic_timeline": _build_traffic_timeline_spec,
            "policy_decisions": _build_policy_decisions_spec,
            "ven_status": _build_ven_status_spec,
            "rule_hits": _build_rule_hits_spec,
        }
        builder = _builders.get(chart_id)
        if not builder:
            return _err(f"Unknown chart_id: {chart_id}", 404)
        try:
            spec = builder(cm, lang=lang)
            fig = _spec_to_plotly_figure(spec)
            return jsonify(fig.to_plotly_json())
        except Exception as exc:
            logger.warning("Dashboard chart {} error: {}", chart_id, exc)
            return _err("Chart unavailable", 500)

    @bp.route('/api/dashboard/top10', methods=['POST'])
    def api_dashboard_top10():
        d = request.json or {}
        try:
            from src.api_client import ApiClient
            from src.analyzer import Analyzer
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

            return jsonify({
                "ok": True,
                "data": top10,
                "total": len(sorted_v),
                "source": getattr(base_ana, "last_query_source", "api"),
            })
        except Exception as e:
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return _err_with_log("dashboard_top10", e, lang=lang)

    return bp
