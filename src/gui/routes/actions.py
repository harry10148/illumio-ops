"""Actions Blueprint: quarantine, workloads, and actions routes."""
from __future__ import annotations

import io
import ipaddress
from contextlib import redirect_stdout

from flask import Blueprint, jsonify, request

from src.alerts import PLUGIN_METADATA
from src.config import ConfigManager
from src.gui._helpers import (
    _err,
    _err_with_log,
    _is_workload_href,
    _normalize_quarantine_hrefs,
    _strip_ansi,
)
from src.i18n import t


def make_actions_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance (unused here, kept for consistent signature)
    login_required,  # flask_login.login_required decorator (unused here, kept for consistent signature)
) -> Blueprint:
    bp = Blueprint("actions", __name__)

    @bp.route('/api/init_quarantine', methods=['POST'])
    def api_init_quarantine():
        """Ensure Quarantine labels exist on the PCE upon loading the new UI module."""
        cm.load()
        from src.api_client import ApiClient
        api = ApiClient(cm)
        api.check_and_create_quarantine_labels()
        return jsonify({"ok": True})

    @bp.route('/api/quarantine/search', methods=['POST'])
    def api_quarantine_search():
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

            # policy_decision now accepts string values: "blocked", "potentially_blocked", "allowed", or "-1"/""=all
            pd_val = str(d.get("policy_decision", "-1")).strip()
            if pd_val == "blocked": pds = ["blocked"]
            elif pd_val == "potentially_blocked": pds = ["potentially_blocked"]
            elif pd_val == "allowed": pds = ["allowed"]
            # legacy integer values kept for backwards compat
            elif pd_val == "2": pds = ["blocked"]
            elif pd_val == "1": pds = ["potentially_blocked"]
            elif pd_val == "0": pds = ["allowed"]
            else: pds = ["blocked", "potentially_blocked", "allowed"]

            # Map the inbound payload to the analyzer's query
            params = {
                "start_time": start_time,
                "end_time": end_time,
                "policy_decisions": pds,
                "draft_policy_decision": d.get("draft_policy_decision", ""),
                "sort_by": d.get("sort_by", "bandwidth"),
                "search": d.get("search", ""),
                "src_label": d.get("src_label", ""),
                "src_ip_in": d.get("src_ip_in", ""),
                "dst_label": d.get("dst_label", ""),
                "dst_ip_in": d.get("dst_ip_in", ""),
                "ex_src_label": d.get("ex_src_label", ""),
                "ex_src_ip": d.get("ex_src_ip", ""),
                "ex_dst_label": d.get("ex_dst_label", ""),
                "ex_dst_ip": d.get("ex_dst_ip", ""),
                "port": d.get("port", ""),
                "ex_port": d.get("ex_port", ""),
                "proto": d.get("proto", ""),
                "any_label": d.get("any_label", ""),
                "any_ip": d.get("any_ip", ""),
                "ex_any_label": d.get("ex_any_label", ""),
                "ex_any_ip": d.get("ex_any_ip", ""),
            }
            results = base_ana.query_flows(params)

            for r in results:
                flow_pd = r.get("policy_decision", "")
                if flow_pd == "allowed": r["pd"] = 0
                elif flow_pd == "potentially_blocked": r["pd"] = 1
                else: r["pd"] = 2

            return jsonify({"ok": True, "data": results})
        except Exception as e:
            return _err_with_log("quarantine_search", e)

    @bp.route('/api/workloads', methods=['GET', 'POST'])
    def api_search_workloads():
        if request.method == 'POST':
            d = request.json or {}
        else:
            d = request.args.to_dict()
        try:
            from src.api_client import ApiClient
            api = ApiClient(cm)

            # API query parameters mapping
            params = {}
            if "name" in d and d["name"]: params["name"] = d["name"]
            if "hostname" in d and d["hostname"]: params["hostname"] = d["hostname"]

            ip_query = d.get("ip_address", "").strip()
            local_ip_filter = False
            target_networks = []

            if ip_query:
                if "," in ip_query or "/" in ip_query:
                    local_ip_filter = True
                    parts = [p.strip() for p in ip_query.split(",") if p.strip()]
                    for p in parts:
                        try:
                            if "/" in p:
                                target_networks.append(ipaddress.ip_network(p, strict=False))
                            else:
                                target_networks.append(ipaddress.ip_address(p))
                        except ValueError:
                            pass
                else:
                    params["ip_address"] = ip_query

            if "max_results" in d:
                params["max_results"] = d["max_results"]
            else:
                params["max_results"] = 100000 if local_ip_filter else 500

            workloads = api.search_workloads(params)

            if local_ip_filter and target_networks:
                filtered_workloads = []
                for wl in workloads:
                    interfaces = wl.get("interfaces", [])
                    matched = False
                    for iface in interfaces:
                        ip_str = iface.get("address")
                        if ip_str:
                            try:
                                ip_obj = ipaddress.ip_address(ip_str)
                                for target in target_networks:
                                    if isinstance(target, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
                                        if ip_obj in target:
                                            matched = True
                                            break
                                    else:
                                        if ip_obj == target:
                                            matched = True
                                            break
                            except ValueError:
                                pass
                        if matched:
                            break
                    if matched:
                        filtered_workloads.append(wl)
                workloads = filtered_workloads

            return jsonify({"ok": True, "data": workloads})
        except Exception as e:
            return _err_with_log("workloads_search", e)

    @bp.route('/api/quarantine/apply', methods=['POST'])
    def api_quarantine_apply():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        href = d.get('href')
        level = d.get('level')  # Mild, Moderate, Severe
        try:
            if not _is_workload_href(href):
                return jsonify({"ok": False, "error": t("gui_q_invalid_target", lang=lang)})
            from src.api_client import ApiClient
            api = ApiClient(cm)

            # 1. Fetch labels to get target Href
            q_hrefs = api.check_and_create_quarantine_labels()
            target_label_href = q_hrefs.get(level)
            if not target_label_href:
                return jsonify({"ok": False, "error": t("gui_label_fetch_failed", lang=lang, level=level)})

            # 2. Fetch Workload's current labels
            wl = api.get_workload(href)
            if not wl:
                return jsonify({"ok": False, "error": t("gui_workload_not_found", lang=lang)})

            # 3. Filter out existing Quarantine labels and append the new one
            current_labels = wl.get("labels", [])
            new_labels = [{"href": l.get("href")} for l in current_labels if l.get("href") not in q_hrefs.values()]
            new_labels.append({"href": target_label_href})

            # 4. Commit
            success = api.update_workload_labels(href, new_labels)
            if success:
                return jsonify({"ok": True, "level": level})
            else:
                return jsonify({"ok": False, "error": t("gui_api_update_failed", lang=lang)})
        except Exception as e:
            return _err_with_log("quarantine_apply", e)

    @bp.route('/api/quarantine/bulk_apply', methods=['POST'])
    def api_quarantine_bulk_apply():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        raw_hrefs = d.get('hrefs', [])
        hrefs = _normalize_quarantine_hrefs(raw_hrefs)
        level = d.get('level')
        try:
            if not hrefs:
                return jsonify({"ok": False, "error": t("gui_q_no_targets", lang=lang)})
            from src.api_client import ApiClient
            api = ApiClient(cm)
            q_hrefs = api.check_and_create_quarantine_labels()
            target_label_href = q_hrefs.get(level)

            invalid_count = sum(1 for h in (raw_hrefs or []) if str(h or "").strip() and not _is_workload_href(h))
            results = {"success": 0, "failed": [], "skipped_invalid": invalid_count}
            import concurrent.futures

            def process_wl(href):
                if not _is_workload_href(href):
                    return href, False
                wl = api.get_workload(href)
                if not wl: return href, False
                current_labels = wl.get("labels", [])
                new_labels = [{"href": l.get("href")} for l in current_labels if l.get("href") not in q_hrefs.values()]
                new_labels.append({"href": target_label_href})
                return href, api.update_workload_labels(href, new_labels)

            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futures = {ex.submit(process_wl, h): h for h in hrefs}
                for f in concurrent.futures.as_completed(futures):
                    h, ok = f.result()
                    if ok:
                        results["success"] = int(results["success"]) + 1
                    else:
                        failed_list = results["failed"]
                        if isinstance(failed_list, list):
                            failed_list.append(h)

            return jsonify({"ok": True, "results": results})
        except Exception as e:
            return _err_with_log("quarantine_bulk_apply", e)

    @bp.route('/api/actions/run', methods=['POST'])
    def api_run_once():
        lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Manually triggered monitoring analysis")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        from src.api_client import ApiClient
        from src.reporter import Reporter
        from src.analyzer import Analyzer
        from src.main import _make_cache_reader
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep, cache_reader=_make_cache_reader(cm))
        ana.run_analysis()
        rep.send_alerts()
        return jsonify({"ok": True, "output": t("gui_action_run_completed", lang=lang)})

    @bp.route('/api/actions/debug', methods=['POST'])
    def api_debug():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        mins = int(d.get('mins', 30))
        pd_sel = int(d.get('pd_sel', 3))
        from src.api_client import ApiClient
        from src.reporter import Reporter
        from src.analyzer import Analyzer
        from src.main import _make_cache_reader
        api = ApiClient(cm)
        rep = Reporter(cm)
        ana = Analyzer(cm, api, rep, cache_reader=_make_cache_reader(cm))
        buf = io.StringIO()
        with redirect_stdout(buf):
            ana.run_debug_mode(mins=mins, pd_sel=pd_sel, interactive=False)
        return jsonify({"ok": True, "output": _strip_ansi(buf.getvalue()).strip() or t("gui_action_debug_completed", lang=lang)})

    @bp.route('/api/actions/test-alert', methods=['POST'])
    def api_test_alert():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Manually triggered test alert")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        data = request.json or {}
        lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        channel = str(data.get("channel", "") or "").strip()
        channels = [channel] if channel else None
        if channel and channel not in PLUGIN_METADATA:
            return _err(t("gui_err_unknown_alert_channel", lang=lang, channel=channel), 400)

        from src.reporter import Reporter
        results = Reporter(cm).send_alerts(force_test=True, channels=channels)
        if channel and not results:
            return _err(t("gui_err_channel_inactive", lang=lang, channel=channel), 400)
        status_text = ", ".join(
            f"{item.get('channel', 'channel')}={item.get('status', 'unknown')}"
            for item in results
        ) or t("gui_test_alert_no_dispatch", lang=lang)
        return jsonify({
            "ok": True,
            "output": t("gui_test_alert_sent_summary", lang=lang, status_text=status_text),
            "results": results,
        })

    @bp.route('/api/actions/best-practices', methods=['POST'])
    def api_best_practices():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Load best practice rules")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        data = request.json or {}
        lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        mode = str(data.get("mode", "append_missing") or "append_missing")
        result = cm.apply_best_practices(mode=mode)
        output = t(
            'best_practice_loaded_summary',
            lang=lang,
            default='Best practices applied: mode={mode}, added={added}, replaced={replaced}, skipped={skipped}, total={total}.',
            mode=result["mode"],
            added=result["added_count"],
            replaced=result["replaced_count"],
            skipped=result["skipped_count"],
            total=result["total_rules"],
        )
        return jsonify({"ok": True, "output": output, "summary": result})

    @bp.route('/api/actions/test-connection', methods=['POST'])
    def api_test_conn():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Testing PCE connection")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        try:
            from src.api_client import ApiClient
            api = ApiClient(cm)
            status, body = api.check_health()
            body_text = str(body)
            clean_body = _strip_ansi(body_text)
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("actions").info(f"Connection result: status={status}")
            except Exception:
                pass  # intentional: audit-log best-effort, must not block primary action
            return jsonify({"ok": status == 200, "status": status, "body": clean_body[:500]})
        except Exception as e:
            try:
                from src.module_log import ModuleLog as _ML
                _ML.get("actions").error(f"Connection failed: {e}")
            except Exception:
                pass  # intentional: audit-log best-effort, must not block primary action
            return _err_with_log("pce_test_connection", e)

    return bp
