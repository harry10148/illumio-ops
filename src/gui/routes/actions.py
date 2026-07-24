"""Actions Blueprint: quarantine, workloads, and actions routes."""
from __future__ import annotations

import io
import ipaddress
import threading
from contextlib import redirect_stdout

from flask import Blueprint, jsonify, request

from src.alerts import PLUGIN_METADATA
from src.analyzer import QUERY_RESULT_CAP
from src.config import ConfigManager
from src.gui._helpers import (
    _err,
    _err_with_log,
    _is_workload_href,
    _normalize_quarantine_hrefs,
    _resolve_state_file,
    _strip_ansi,
)
from src.i18n import t
from src.state_store import update_state_file

# GUI 觸發的分析／debug 執行序列化：
# - api_run_once：Analyzer.save_state 的 _merge 假設同時只有一個分析 cycle
#   在跑（analyzer 自有 key 是整包覆蓋）——併發 GUI 觸發互相蓋掉
#   alert_history/history 會造成重複告警或計數錯亂。
# - api_debug：contextlib.redirect_stdout 換的是 process 全域 stdout，兩個
#   debug 同時跑會互相污染輸出緩衝；共用同一把鎖也讓 GUI 觸發的分析 print
#   不會被併發 debug 擷取走。
# 注意：與排程器的 monitor cycle（scheduler/jobs.py）之間仍無互斥——那屬於
# 排程器側的變更範圍，此鎖只序列化 GUI 端的觸發。
_analysis_lock = threading.Lock()


def make_actions_blueprint(
    cm: ConfigManager,
    csrf,           # flask_wtf.csrf.CSRFProtect instance (unused here, kept for consistent signature)
    limiter,        # flask_limiter.Limiter instance (unused here, kept for consistent signature)
    login_required,  # flask_login.login_required decorator (unused here, kept for consistent signature)
) -> Blueprint:
    bp = Blueprint("actions", __name__)

    def _audit_action(action, **fields):
        """隔離/解除隔離審計 log——best-effort，絕不阻斷主操作（spec §11.1）。"""
        try:
            from src.module_log import ModuleLog as _ML
            try:
                from flask_login import current_user
                user = current_user.get_id() if getattr(current_user, "is_authenticated", False) else "?"
            except Exception:
                user = "?"
            parts = " ".join(f"{k}={v}" for k, v in fields.items())
            _ML.get("actions").info(f"{action}: user={user} {parts}")
        except Exception:
            pass

    @bp.route('/api/init_quarantine', methods=['POST'])
    def api_init_quarantine():
        """Ensure Quarantine labels exist on the PCE upon loading the new UI module."""
        cm.load()
        from src.api_client import ApiClient
        with ApiClient(cm) as api:
            api.check_and_create_quarantine_labels()
            return jsonify({"ok": True})

    @bp.route('/api/quarantine/search', methods=['POST'])
    def api_quarantine_search():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            from src.api_client import ApiClient
            from src.analyzer import Analyzer
            from src.exceptions import TrafficQueryError
            from src.reporter import Reporter
            import datetime

            with ApiClient(cm) as api:
                from src.main import _make_cache_reader
                # 資料來源：live（即時快取）預設，archive 則查已載入的 review DB。
                source = d.get("source", "live")
                reader_db = None
                if source == "archive":
                    from src.pce_cache.archive_import import review_db_path
                    reader_db = review_db_path(cm.models.pce_cache)
                cache_reader = _make_cache_reader(cm, db_path=reader_db)
                base_ana = Analyzer(cm, api, Reporter(cm), cache_reader=cache_reader)

                now = datetime.datetime.now(datetime.timezone.utc)
                if source == "archive":
                    # archive 查閱：查詢窗設為 [review 最早資料, now]，讓 cover_state 判 full、
                    # 只讀 review DB，不 fallback 打即時 PCE API。review 空則直接回空。
                    earliest = cache_reader.earliest_data_timestamp("traffic") if cache_reader else None
                    if earliest is None:
                        # not_loaded 旗標讓前端區分「未載入 review DB」與「查無流量」
                        return jsonify({"ok": True, "data": [], "not_loaded": True})
                    start_time = earliest.strftime("%Y-%m-%dT%H:%M:%SZ")
                    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    try:
                        mins = int(d.get("mins", 30))
                    except (TypeError, ValueError):
                        return _err(t("gui_err_invalid_number", lang=lang), 400)
                    # 同 debug/events 端點基線夾限：避免超大/負數 mins 觸發
                    # 超大 PCE 查詢或時間窗反轉（2026-07-24 審查 F1）
                    mins = max(5, min(mins, 10080))
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
                # 「全部」須含 unknown（vendor 值域四值；涵蓋 idle/快照模式與 Flowlink 流量）
                else: pds = ["blocked", "potentially_blocked", "allowed", "unknown"]

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
                    # 物件 filter key（Phase 1 analyzer 已支援；FilterBar 送複數 list）
                    "src_labels": d.get("src_labels", []),
                    "dst_labels": d.get("dst_labels", []),
                    "ex_src_labels": d.get("ex_src_labels", []),
                    "ex_dst_labels": d.get("ex_dst_labels", []),
                    # Task 11：qt-port/qt-proto/qt-expt scalar 欄位移除，FilterBar 的
                    # service/port pill 序列化 key 需直通到 analyzer（同 query_flows whitelist）。
                    "services": d.get("services", []),
                    "ex_services": d.get("ex_services", []),
                    "ports": d.get("ports", []),
                    "ex_ports": d.get("ex_ports", []),
                    "process_name": d.get("process_name", []),
                    "ex_process_name": d.get("ex_process_name", []),
                    "windows_service_name": d.get("windows_service_name", []),
                    "ex_windows_service_name": d.get("ex_windows_service_name", []),
                    "transmission": d.get("transmission", []),
                    "ex_transmission": d.get("ex_transmission", []),
                    # FilterBar 的 label group pill 序列化 key，須與 analyzer.py query_flows
                    # whitelist（~1053-1064）及 _TRAFFIC_FILTER_CAPABILITIES（traffic_query.py ~90-96）保持一致
                    "src_label_groups": d.get("src_label_groups", []),
                    "dst_label_groups": d.get("dst_label_groups", []),
                    "ex_src_label_groups": d.get("ex_src_label_groups", []),
                    "ex_dst_label_groups": d.get("ex_dst_label_groups", []),
                    "src_iplist": d.get("src_iplist", ""),
                    "src_iplists": d.get("src_iplists", []),
                    "dst_iplist": d.get("dst_iplist", ""),
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
                }
                results = base_ana.query_flows(params)

                for r in results:
                    flow_pd = r.get("policy_decision", "")
                    if flow_pd == "allowed": r["pd"] = 0
                    elif flow_pd == "potentially_blocked": r["pd"] = 1
                    else: r["pd"] = 2

                stats = getattr(base_ana, "last_query_stats", {}) or {}
                return jsonify({
                    "ok": True,
                    "data": results,
                    "total_matches": int(stats.get("total_matches", len(results))),
                    "truncated": bool(stats.get("truncated")),
                    "cap": int(stats.get("cap", QUERY_RESULT_CAP)),
                })
        except TrafficQueryError as e:
            return jsonify({"ok": False, "error": t(
                "gui_err_traffic_query_failed", detail=str(e), lang=lang)}), 502
        except Exception as e:
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return _err_with_log("quarantine_search", e, lang=lang)

    @bp.route('/api/workloads', methods=['GET', 'POST'])
    def api_search_workloads():
        if request.method == 'POST':
            d = request.json or {}
        else:
            d = request.args.to_dict()
        try:
            from src.api_client import ApiClient
            with ApiClient(cm) as api:

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

                # PCE 同步集合 GET 硬上限 500 且靜默截斷（api_client
                # _get_collection 的真機驗證事實）：帶 >500 沒有意義還會掩蓋
                # 截斷。錨定 500 讓「拿滿 500」成為可偵測的截斷訊號，並夾限
                # 使用者自帶的 max_results。
                if "max_results" in d:
                    try:
                        params["max_results"] = max(1, min(int(d["max_results"]), 500))
                    except (TypeError, ValueError):
                        params["max_results"] = 500
                else:
                    params["max_results"] = 500

                workloads = api.search_workloads(params)
                # 拿滿上限＝可能截斷；CIDR/多 IP 本地過濾是對「截斷後子集」
                # 過濾，結果可能靜默缺漏——把旗標交給前端呈現。
                truncated = len(workloads) >= 500

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

                return jsonify({"ok": True, "data": workloads, "truncated": truncated})
        except Exception as e:
            lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return _err_with_log("workloads_search", e, lang=lang)

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
            with ApiClient(cm) as api:

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
                _audit_action("quarantine_apply", href=href, level=level,
                              result=("ok" if success else "update_failed"))
                if success:
                    return jsonify({"ok": True, "level": level})
                else:
                    return jsonify({"ok": False, "error": t("gui_api_update_failed", lang=lang)})
        except Exception as e:
            return _err_with_log("quarantine_apply", e, lang=lang)

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
            with ApiClient(cm) as api:
                q_hrefs = api.check_and_create_quarantine_labels()
                target_label_href = q_hrefs.get(level)
                # 同單筆 apply 的防護：level 無效或標籤建立失敗（create_label
                # 對非 201 靜默回 {}，如 API key 只有唯讀權限）時 href 為
                # None——不擋下去會對每個 workload PUT {"href": None}，全數
                # 失敗卻回 ok:True，操作者看到成功 toast 而 0 台被隔離。
                if not target_label_href:
                    return jsonify({"ok": False, "error": t("gui_label_fetch_failed", lang=lang, level=level)})

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

                _audit_action("quarantine_bulk_apply", level=level,
                              success=results["success"], failed=len(results["failed"]),
                              skipped_invalid=results["skipped_invalid"],
                              hrefs=",".join(hrefs))
                return jsonify({"ok": True, "results": results})
        except Exception as e:
            return _err_with_log("quarantine_bulk_apply", e, lang=lang)

    @bp.route('/api/quarantine/lift', methods=['POST'])
    def api_quarantine_lift():
        """解除隔離：移除 Quarantine 標籤、保留其餘標籤（spec §11.2）。

        隔離是「附加」標籤（見 api_quarantine_apply 第 3 步），原標籤
        未被動過，故解除＝過濾掉 q_hrefs 即可，無需還原機制。
        """
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        raw_hrefs = d.get('hrefs', [])
        hrefs = _normalize_quarantine_hrefs(raw_hrefs)
        try:
            if not hrefs:
                return jsonify({"ok": False, "error": t("gui_q_no_targets", lang=lang)})
            from src.api_client import ApiClient
            with ApiClient(cm) as api:
                q_hrefs = set(api.check_and_create_quarantine_labels().values())

                invalid_count = sum(1 for h in (raw_hrefs or [])
                                    if str(h or "").strip() and not _is_workload_href(h))
                results = {"success": 0, "failed": [], "skipped_invalid": invalid_count,
                           "not_quarantined": 0}
                import concurrent.futures

                def process_wl(href):
                    if not _is_workload_href(href):
                        return href, "invalid"
                    wl = api.get_workload(href)
                    if not wl:
                        return href, "failed"
                    current = wl.get("labels", [])
                    kept = [{"href": l.get("href")} for l in current
                            if l.get("href") not in q_hrefs]
                    if len(kept) == len(current):
                        return href, "not_quarantined"
                    return href, ("ok" if api.update_workload_labels(href, kept) else "failed")

                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                    futures = {ex.submit(process_wl, h): h for h in hrefs}
                    for f in concurrent.futures.as_completed(futures):
                        h, st = f.result()
                        if st == "ok":
                            results["success"] += 1
                        elif st == "not_quarantined":
                            results["not_quarantined"] += 1
                        elif st == "failed":
                            results["failed"].append(h)

                _audit_action("quarantine_lift", success=results["success"],
                              failed=len(results["failed"]),
                              not_quarantined=results["not_quarantined"],
                              hrefs=",".join(hrefs))
                return jsonify({"ok": True, "results": results})
        except Exception as e:
            return _err_with_log("quarantine_lift", e, lang=lang)

    @bp.route('/api/workloads/accelerate', methods=['POST'])
    def api_workloads_accelerate():
        """Increase traffic update rate for the given workload hrefs.

        Backend is stateless: it issues exactly one PCE call per request.
        Persistent mode (re-issue every 10 min) is handled by the frontend
        via setInterval. Invalid hrefs are dropped and counted in
        skipped_invalid.
        """
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        raw_hrefs = d.get('hrefs', []) or []
        try:
            duration = int(d.get('duration_minutes', 0) or 0)  # logged only
        except (TypeError, ValueError):
            return _err(t("gui_err_invalid_number", lang=lang), 400)
        hrefs = [h for h in raw_hrefs if _is_workload_href(h)]
        skipped_invalid = len(raw_hrefs) - len(hrefs)

        if not hrefs:
            return jsonify({"ok": False, "error": t("gui_accel_no_targets", lang=lang)})

        try:
            from src.api_client import ApiClient
            with ApiClient(cm) as api:
                success, fail = api.set_flow_reporting_frequency(hrefs)
                try:
                    from src.module_log import ModuleLog as _ML
                    _ML.get("actions").info(
                        f"Accelerate: success={success}, fail={fail}, "
                        f"skipped_invalid={skipped_invalid}, duration_minutes={duration}"
                    )
                except Exception:
                    pass  # audit-log best-effort, must not block primary action
                return jsonify({
                    "ok": True,
                    "success": success,
                    "failed": fail,
                    "skipped_invalid": skipped_invalid,
                })
        except Exception as e:
            return _err_with_log("workloads_accelerate", e, lang=lang)

    @bp.route('/api/actions/run', methods=['POST'])
    @limiter.limit("10 per hour")
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
        with ApiClient(cm) as api:
            rep = Reporter(cm)
            # 見 _analysis_lock 註解：序列化 GUI 觸發的分析，避免併發 cycle
            # 的 save_state 互相覆蓋 analyzer 自有 state key。
            with _analysis_lock:
                ana = Analyzer(cm, api, rep, cache_reader=_make_cache_reader(cm))
                ana.run_analysis()
                rep.send_alerts(lang=lang)
            return jsonify({"ok": True, "output": t("gui_action_run_completed", lang=lang)})

    @bp.route('/api/actions/debug', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_debug():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            mins = int(d.get('mins', 30))
            pd_sel = int(d.get('pd_sel', 3))
        except (TypeError, ValueError):
            return _err(t("gui_err_invalid_number", lang=lang), 400)
        # clamp 到與手動流量/事件查詢（gui/routes/events.py）相同的時間窗，
        # 避免惡意或誤填的超大 `mins` 觸發過大的 PCE 查詢。
        mins = max(5, min(mins, 10080))
        from src.api_client import ApiClient
        from src.reporter import Reporter
        from src.analyzer import Analyzer
        from src.main import _make_cache_reader
        with ApiClient(cm) as api:
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep, cache_reader=_make_cache_reader(cm))
            buf = io.StringIO()
            # redirect_stdout 換的是 process 全域 stdout（非 thread-local）：
            # 以 _analysis_lock 序列化，避免併發 debug run 互相污染輸出、或
            # 擷取到 GUI 觸發分析的 print。其他執行緒（scheduler 等）的
            # print 在 debug 期間仍可能被吸進來——根治需 run_debug_mode 改收
            # 明確 output stream（analyzer 側變更）。
            with _analysis_lock:
                with redirect_stdout(buf):
                    ana.run_debug_mode(mins=mins, pd_sel=pd_sel, interactive=False)
            return jsonify({"ok": True, "output": _strip_ansi(buf.getvalue()).strip() or t("gui_action_debug_completed", lang=lang)})

    @bp.route('/api/actions/test-alert', methods=['POST'])
    @limiter.limit("30 per hour")
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

    @bp.route('/api/actions/reset-watermark', methods=['POST'])
    @limiter.limit("10 per hour")
    def api_reset_watermark():
        """Debug helper: clear the event watermark + alert cooldown (alert_history)
        + seen-event dedup so the next analysis re-pulls events and re-fires alerts."""
        data = request.json or {}
        lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Debug: reset event_watermark + alert_history + event_seen")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        cleared: list[str] = []

        def _clear(state: dict) -> dict:
            for key in ("event_watermark", "alert_history", "event_seen"):
                if key in state:
                    state.pop(key, None)
                    cleared.append(key)
            return state

        try:
            update_state_file(_resolve_state_file(), _clear)
        except Exception as exc:
            return _err_with_log("reset_watermark", exc, lang=lang)
        return jsonify({
            "ok": True,
            "cleared": cleared,
            "output": t("gui_reset_watermark_done", lang=lang, keys=", ".join(cleared) or "—"),
        })

    @bp.route('/api/actions/best-practices', methods=['POST'])
    @limiter.limit("5 per hour")
    def api_best_practices():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Load best practice rules")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        data = request.json or {}
        lang = data.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        mode = str(data.get("mode", "append_missing") or "append_missing")
        # 比照 rules.py 各寫入端點：load→mutate→save 以共用鎖序列化——
        # apply_best_practices 可能改寫整份 rules list，無鎖時與併發寫入者
        # 交錯會丟失更新。
        with cm.write_lock:
            cm.load()
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
    @limiter.limit("20 per hour")
    def api_test_conn():
        try:
            from src.module_log import ModuleLog as _ML
            _ML.get("actions").info("Testing PCE connection")
        except Exception:
            pass  # intentional: audit-log best-effort, must not block primary action
        try:
            from src.api_client import ApiClient
            with ApiClient(cm) as api:
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
            lang = (request.get_json(silent=True) or {}).get('lang') or cm.config.get('settings', {}).get('language', 'en')
            return _err_with_log("pce_test_connection", e, lang=lang)

    return bp
