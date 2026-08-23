"""Actions Blueprint: quarantine, workloads, and actions routes."""
from __future__ import annotations

import io
import ipaddress
from contextlib import redirect_stdout

from flask import Blueprint, jsonify, request
from loguru import logger

from src.alerts import PLUGIN_METADATA
from src.analyzer import QUERY_RESULT_CAP, analysis_lock as _analysis_lock
from src.config import ConfigManager
from src.file_lock import file_lock as _file_lock
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

# _analysis_lock（= analyzer.analysis_lock，於 import 區取得）由 GUI 觸發的
# api_run_once / api_debug 與排程器的 run_monitor_cycle 共用——`--monitor-gui`
# 下兩者是同一行程的不同 thread，只鎖 GUI 側防不到排程器。詳見該處註解。
#
# 外面再包一層跨行程檔案鎖（src.main.analysis_lock_path）：互動式 CLI 選單是
# **另一個行程**，也會跑完整分析 cycle，兩邊的 state 快照會互相覆寫（告警冷卻
# 被抹掉 → 同一則告警重寄）。取鎖順序固定為 file_lock → _analysis_lock。
_ANALYSIS_LOCK_WAIT_S = 600.0

# /api/quarantine/search 的 data_source 白名單（live 分支專用；archive 分支
# 有自己的 source=="archive" 早退，data_source 從不影響它）。只列這條路徑
# 真的實作的值：未帶／空字串（=自動判斷），以及 resolve_data_source 會對應
# 到 hybrid 或 live 的字串（含別名）。刻意不含 "cache-only"——analyzer 端
# 沒有實作 clip-to-cache 語意，讓它悄悄降級成 hybrid 正是這個功能要防的
# 「操作者偏好被默默改寫」缺陷，所以在端點就擋掉，不要往下傳給
# resolve_data_source 自己吸收成 hybrid。
_TRAFFIC_DATA_SOURCE_VALUES = {"hybrid", "cache", "live", "no-cache", "api"}


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
        d = request.get_json(silent=True) or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        from src.api_client import ApiClient
        from src.exceptions import APIError
        with ApiClient(cm) as api:
            # check_and_create_quarantine_labels 對非 200 的標籤查詢改以 APIError
            # 表達（不再退化成空 dict）。這裡只是開啟 UI 模組時的預備動作，PCE
            # 一次抽風不該讓整頁載入變成 500——回可讀的錯誤，讓實際的隔離操作
            # （apply/lift）自己再判一次。
            try:
                api.check_and_create_quarantine_labels()
            except APIError as exc:
                logger.warning(f"[GUI:init_quarantine] Quarantine label lookup failed: {exc}")
                return jsonify({"ok": False, "error": t(
                    "gui_label_fetch_failed", lang=lang, level="Quarantine")})
            return jsonify({"ok": True})

    @bp.route('/api/quarantine/search', methods=['POST'])
    def api_quarantine_search():
        d = request.json or {}
        lang = d.get('lang') or cm.config.get('settings', {}).get('language', 'en')
        try:
            from src.api_client import ApiClient
            from src.analyzer import Analyzer
            from src.exceptions import TrafficQueryError
            from src.pce_cache.archive_query import stream_query, unsupported_filters
            from src.reporter import Reporter
            import datetime

            with ApiClient(cm) as api:
                # 資料來源：live（即時快取）預設；archive 直接串流封存日檔
                # （Task 4 起不再經 review DB／cache_reader）。
                source = d.get("source", "live")

                if source == "archive":
                    try:
                        archive_start = datetime.date.fromisoformat(str(d.get("archive_start") or ""))
                        archive_end = datetime.date.fromisoformat(str(d.get("archive_end") or ""))
                    except ValueError:
                        return _err(t("gui_err_archive_range_required", lang=lang), 400)
                    if archive_end < archive_start:
                        # 反轉的窗：stream_query 的 `while day <= end` 一次都不會
                        # 跑，會靜默回 200 空結果——同一類缺陷 2026-07-24 審查
                        # F1 在 live mins 分支抓過一次，這裡在解析後就擋掉。
                        return _err(t("gui_err_archive_range_required", lang=lang), 400)

                    # 與 query_flows 的 query_filters 白名單同一份 key 集合
                    # （analyzer.py 約 :2219-2289），值改讀 d——archive 跟 live
                    # 共用 Analyzer._match_flow_filters 同一套比對器，不另建
                    # 第二套；照抄這份白名單才能保證兩邊對「filter 是什麼意思」
                    # 的認知一致。
                    query_filters = {
                        "port": d.get("port"),
                        "proto": d.get("proto"),
                        "port_range": d.get("port_range"),
                        "ex_port": d.get("ex_port"),
                        "ex_port_range": d.get("ex_port_range"),
                        "services": d.get("services", []),
                        "ex_services": d.get("ex_services", []),
                        "ports": d.get("ports", []),
                        "ex_ports": d.get("ex_ports", []),
                        "process_name": d.get("process_name"),
                        "ex_process_name": d.get("ex_process_name"),
                        "windows_service_name": d.get("windows_service_name"),
                        "ex_windows_service_name": d.get("ex_windows_service_name"),
                        "src_label": d.get("src_label"),
                        "src_label_group": d.get("src_label_group"),
                        "src_label_groups": d.get("src_label_groups"),
                        "dst_label": d.get("dst_label"),
                        "dst_label_group": d.get("dst_label_group"),
                        "dst_label_groups": d.get("dst_label_groups"),
                        "src_ip_in": d.get("src_ip_in"),
                        "dst_ip_in": d.get("dst_ip_in"),
                        "ex_src_label": d.get("ex_src_label"),
                        "ex_src_label_group": d.get("ex_src_label_group"),
                        "ex_src_label_groups": d.get("ex_src_label_groups"),
                        "ex_dst_label": d.get("ex_dst_label"),
                        "ex_dst_label_group": d.get("ex_dst_label_group"),
                        "ex_dst_label_groups": d.get("ex_dst_label_groups"),
                        "ex_src_ip": d.get("ex_src_ip"),
                        "ex_dst_ip": d.get("ex_dst_ip"),
                        "any_label": d.get("any_label"),
                        "any_ip": d.get("any_ip"),
                        "ex_any_label": d.get("ex_any_label"),
                        "ex_any_ip": d.get("ex_any_ip"),
                        "src_ams": d.get("src_ams"),
                        "dst_ams": d.get("dst_ams"),
                        "ex_src_ams": d.get("ex_src_ams"),
                        "ex_dst_ams": d.get("ex_dst_ams"),
                        "transmission_excludes": d.get("transmission_excludes") or d.get("ex_transmission"),
                        "transmission": d.get("transmission"),
                        "src_include_groups": d.get("src_include_groups"),
                        "dst_include_groups": d.get("dst_include_groups"),
                        "search": d.get("search"),
                        "draft_policy_decision": d.get("draft_policy_decision"),
                        "src_labels": d.get("src_labels", []),
                        "dst_labels": d.get("dst_labels", []),
                        "ex_src_labels": d.get("ex_src_labels", []),
                        "ex_dst_labels": d.get("ex_dst_labels", []),
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

                    unsupported = unsupported_filters(query_filters)
                    # search 的全文子字串比對只存在於 query_flows 事後那道手動
                    # 掃描（比對 s_name/d_name/s_ip/d_ip/port/svc_proc/svc_user/
                    # svc_name，見 analyzer.py 的 search_query 那段），不在
                    # _match_flow_filters 裡——archive 只共用 _match_flow_filters，
                    # 不另建第二套比對器，所以評估不了 search。放著不管會靜默
                    # 忽略操作者打的字，回一個看似有搜尋、其實沒有的結果，正是
                    # 這整個功能要防的那種缺陷，所以比照 unsupported filter 明講
                    # 拒絕（不論是不是跟其他能評估的條件一起送）。
                    if query_filters.get("search") not in (None, "", []):
                        unsupported = sorted(set(unsupported) | {"search"})
                    if unsupported:
                        error = (t("gui_err_archive_search_unsupported", lang=lang)
                                 if "search" in unsupported else
                                 t("gui_err_archive_filter_unsupported", lang=lang,
                                   keys=", ".join(unsupported)))
                        return jsonify({
                            "ok": False,
                            "unsupported": unsupported,
                            "error": error,
                        }), 400

                    base_ana = Analyzer(cm, api, Reporter(cm))
                    query_spec = api.build_traffic_query_spec(query_filters)
                    requested_sort_by = d.get("sort_by", "bandwidth")
                    # 封存列沒有算速率(bandwidth)需要的 ddms/tdms（見
                    # archive_query.py 的 _SORT_FIELD 註解，真機驗證過）：
                    # bandwidth 轉譯成 volume。其餘未知值比照下面 rule["type"]
                    # 那行 live 分支的既有 fallback 退到 connections——兩者都是
                    # stream_query 認得的排序鍵，這樣它就不會再因為 sort_by
                    # 拋 ValueError，唯一還可能冒出的 ValueError 只剩「沒給
                    # 縮小範圍條件」那個。
                    if requested_sort_by == "bandwidth":
                        archive_sort_by = "volume"
                    elif requested_sort_by in ("volume", "connections"):
                        archive_sort_by = requested_sort_by
                    else:
                        archive_sort_by = "connections"
                    sort_by_substituted = archive_sort_by != requested_sort_by

                    # policy_decision → rule["pd"]：跟下面 live 分支（本檔
                    # :288 附近）的 pd_val 轉換同一個形狀，UI 只送單一 scalar
                    # policy_decision（investigate.mjs），不是 query_flows
                    # 內部才會展開的四值 policy_decisions 清單，所以不會重開
                    # 「守門吃到預設全選」那個洞。check_flow_match 直接讀
                    # raw 的 policy_decision 字串做 blocked/potentially_
                    # blocked/allowed 判斷（analyzer.py :697-704），不需要
                    # 額外轉換。
                    pd_val = str(d.get("policy_decision", "-1")).strip()
                    if pd_val in ("blocked", "2"):
                        archive_pd = 2
                    elif pd_val in ("potentially_blocked", "1"):
                        archive_pd = 1
                    elif pd_val in ("allowed", "0"):
                        archive_pd = 0
                    else:
                        archive_pd = -1

                    # rule 組法照抄 query_flows（analyzer.py 約 :2328）。
                    rule = {**query_spec.native_filters, **query_spec.fallback_filters}
                    rule["type"] = requested_sort_by if requested_sort_by in ["bandwidth", "volume"] else "connections"
                    rule["pd"] = archive_pd

                    start_dt = datetime.datetime.combine(
                        archive_start, datetime.time.min, tzinfo=datetime.timezone.utc)
                    matcher = lambda row: base_ana._match_flow_filters(
                        rule, row.get("raw") or {}, start_dt)

                    try:
                        result = stream_query(
                            cm.models.pce_cache.archive_dir, "traffic",
                            archive_start, archive_end, query_filters,
                            QUERY_RESULT_CAP, archive_sort_by, matcher)
                    except ValueError:
                        # sort_by 已在上面被強制成 stream_query 認得的兩個值
                        # 之一，search 已在上面被明講拒絕、不會再靠「沒給窄化
                        # 條件」這條路混過去——這裡唯一還能冒出的 ValueError
                        # 是守門條件：query_filters 裡沒有任何縮小範圍的條件。
                        return _err(t("gui_err_archive_filter_required", lang=lang), 400)

                    # 終審 F1：封存列是攤平的封存紀錄（src_ip/dst_ip/port/...），
                    # 前端 trafficRows() 讀的是 live 形狀（item.source/
                    # destination/service/formatted_*/timestamp_range）——原樣
                    # 回傳會讓表格每一格都是空白、KPI 把 0 當成量測值呈現。
                    # `raw` 就是原始 PCE flow payload（ingestor_traffic.py
                    # 存進 raw_json 時未經改動），跟 live 的 `f` 是同一種形狀，
                    # 所以投影用 Analyzer._shape_traffic_row 這同一份、不另建
                    # 第二套。
                    #
                    # 指標必須來自 merge_row() 合併後的頂層計數器（MAX across
                    # 重複快照），不能用 raw 自己的 byte 欄位重算——raw 只是
                    # 較新那次快照，用它算會悄悄把合併撤銷掉，重現合併原本
                    # 要防的低估（終審 F1/F6）。bandwidth 傳 None：封存從不
                    # 記錄 ddms/tdms，沒有速率可言，讓下游（KPI 尖峰頻寬、
                    # fmtBw）維持既有的「—」呈現，不要印出一個看似量測到、
                    # 其實是 0 的頻寬。
                    shaped_rows = [
                        base_ana._shape_traffic_row(
                            row.get("raw") or {},
                            bw_val=None, bw_note="",
                            vol_val=((row.get("bytes_in") or 0)
                                     + (row.get("bytes_out") or 0)) / 1024 / 1024,
                            vol_note="(Total)",
                            conn_val=row.get("flow_count") or 0,
                        )
                        for row in result.rows
                    ]

                    return jsonify({
                        "ok": True,
                        "rows": shaped_rows,
                        "summary": result.summary,
                        "summary_omitted": result.summary_omitted,
                        "truncated": result.truncated,
                        "matched": result.matched,
                        "scanned": result.scanned,
                        # 終審 F3：略過的列數（結構不合法或 JSON 語法壞掉）
                        # 與整個檔案（片段）讀不到的次數，分開回傳——單位
                        # 不同，混在一起是另一種不誠實。
                        "skipped": result.skipped,
                        "files_incomplete": result.files_incomplete,
                        "actual_source": "archive",
                        "sort_by": archive_sort_by,
                        # 終審 F7：GUI 已經到不了「送 bandwidth 給封存」這個
                        # 狀態（切到 archive 時前端自己把 sort 從 bandwidth
                        # 挪開），所以這個旗標目前沒有 GUI 消費端——但直接打
                        # API 的呼叫端還是可能送 bandwidth，這個欄位仍要誠實
                        # 回報「你要的排序被換掉了」。保留欄位，不要為它加
                        # UI。
                        "sort_by_substituted": sort_by_substituted,
                        "incomplete_after": (result.incomplete_after.isoformat()
                                              if result.incomplete_after else None),
                        # 終審 F5：incomplete_after 為真時，是被 deadline 還是
                        # size cap 打斷的——兩個不同的事實，前端得分開講。
                        "stop_reason": result.stop_reason,
                    })

                raw_data_source = d.get("data_source")
                if raw_data_source not in (None, ""):
                    norm_data_source = str(raw_data_source).strip().lower()
                    if norm_data_source not in _TRAFFIC_DATA_SOURCE_VALUES:
                        return _err(t("gui_err_traffic_data_source_invalid", lang=lang), 400)

                from src.main import _make_cache_reader
                cache_reader = _make_cache_reader(cm)
                base_ana = Analyzer(cm, api, Reporter(cm), cache_reader=cache_reader)

                now = datetime.datetime.now(datetime.timezone.utc)
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
                    "data_source": d.get("data_source"),
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
                    "actual_source": stats.get("actual_source", base_ana.last_query_source),
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
            from src.exceptions import APIError
            with ApiClient(cm) as api:

                # 1. Fetch labels to get target Href
                # 標籤查詢失敗（非 200）以 APIError 表達；就地攔下換成
                # gui_label_fetch_failed，別讓操作者只看到泛用 500＋request_id。
                try:
                    q_hrefs = api.check_and_create_quarantine_labels()
                except APIError as exc:
                    logger.warning(f"[GUI:quarantine_apply] label lookup failed: {exc}")
                    return jsonify({"ok": False, "error": t("gui_label_fetch_failed", lang=lang, level=level)})
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
            from src.exceptions import APIError
            with ApiClient(cm) as api:
                # 同單筆 apply：標籤查詢失敗以 APIError 表達，就地換成可讀訊息。
                try:
                    q_hrefs = api.check_and_create_quarantine_labels()
                except APIError as exc:
                    logger.warning(f"[GUI:quarantine_bulk_apply] label lookup failed: {exc}")
                    return jsonify({"ok": False, "error": t("gui_label_fetch_failed", lang=lang, level=level)})
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
        from src.main import _make_cache_reader, analysis_lock_path
        with ApiClient(cm) as api:
            rep = Reporter(cm)
            # 見 _analysis_lock 註解：序列化 GUI 觸發的分析，避免併發 cycle
            # 的 save_state 互相覆蓋 analyzer 自有 state key。
            try:
                with _file_lock(analysis_lock_path(), timeout=_ANALYSIS_LOCK_WAIT_S):
                    with _analysis_lock:
                        ana = Analyzer(cm, api, rep, cache_reader=_make_cache_reader(cm))
                        ana.run_analysis()
                        rep.send_alerts(lang=lang)
            except TimeoutError:
                return _err(t("gui_err_analysis_in_progress", lang=lang), 409)
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
        from src.main import _make_cache_reader, analysis_lock_path
        with ApiClient(cm) as api:
            rep = Reporter(cm)
            ana = Analyzer(cm, api, rep, cache_reader=_make_cache_reader(cm))
            buf = io.StringIO()
            # redirect_stdout 換的是 process 全域 stdout（非 thread-local）：
            # 以 _analysis_lock 序列化，避免併發 debug run 互相污染輸出、或
            # 擷取到 GUI 觸發分析的 print。其他執行緒（scheduler 等）的
            # print 在 debug 期間仍可能被吸進來——根治需 run_debug_mode 改收
            # 明確 output stream（analyzer 側變更）。
            try:
                with _file_lock(analysis_lock_path(), timeout=_ANALYSIS_LOCK_WAIT_S):
                    with _analysis_lock:
                        with redirect_stdout(buf):
                            ana.run_debug_mode(mins=mins, pd_sel=pd_sel, interactive=False)
            except TimeoutError:
                return _err(t("gui_err_analysis_in_progress", lang=lang), 409)
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
            # 必須在 _analysis_lock 內清除：monitor cycle 的 Analyzer 在
            # load_state() 時取整份 state 快照，save_state() 再以
            # merged.update(self.state) 把 event_watermark / alert_history /
            # event_seen 從快照寫回。若這裡的 pop 落在別人 cycle 的
            # load→save 窗口內，端點會回報成功但實際被原樣還原（alert 冷卻
            # 仍在、已看過的事件仍被跳過），操作者只會看到「debug 工具沒用」。
            with _analysis_lock:
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
