from __future__ import annotations

import datetime
import functools
import heapq
import ipaddress
import json
import gc
import os
import sys
from typing import Any, Iterator
from loguru import logger
from collections import Counter
from src.api.labels import LabelResolver
from src.events import (
    AlertThrottler,
    EventPoller,
    StatsTracker,
    ensure_monitoring_state,
    event_identity,
    format_utc,
    is_known_event_type,
    matches_event_rule,
    normalize_event,
    parse_event_timestamp,
)
from src.events.catalog import classify_unknown_event_type
from src.exceptions import TrafficQueryError
from src.utils import Colors, format_unit, safe_input
from src.i18n import t
from src.state_store import load_state_file, update_state_file
from src.interfaces import IApiClient, IReporter
from src.api.traffic_query import TrafficQueryBuilder
from src.pce_cache.reader import CacheReadTooLarge

# Refine Root Dir for State File
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
STATE_FILE = os.path.join(ROOT_DIR, "logs", "state.json")

# _dispatch_alerts 對每條觸發規則實際保留的 top matches 筆數（見其
# `top_10 = res['top_matches'][:10]`）。_run_rule_engine 以同一個 N 對
# 每條規則的累積量設上界，確保累積永遠不超過 dispatch 端實際使用的筆數。
TOP_MATCHES_LIMIT = 10

# Dead-man's switch: after this many consecutive PCE polling failures the
# analyzer self-alerts (via _check_watchdog), because a dead poller otherwise
# fails silent — no events polled, no alerts fired. Own cooldown keeps a
# long outage to one alert per hour instead of one per cycle.
WATCHDOG_FAILURE_THRESHOLD = 3
WATCHDOG_COOLDOWN_MINUTES = 60

# Meta-alert cooldown for event polling overflow: when the sync events API
# hits max_results it returns only the newest rows, so older events in the
# window are permanently lost. Own cooldown keeps a persistent burst source
# to one alert per hour instead of one per cycle.
OVERFLOW_ALERT_COOLDOWN_MINUTES = 60

# query_flows 殘餘比對的委派範圍：check_flow_match 只認 legacy scalar key，
# 下列物件/複數 key（Phase 3 FilterBar）委派給報表路徑同一套比對器
# TrafficQueryBuilder._flow_matches_filters 評估——cache 命中時 client 端
# 比對是唯一一道過濾，這些 key 不得靜默 pass-through。
_OBJECT_FILTER_KEYS = (
    "src_labels", "dst_labels", "ex_src_labels", "ex_dst_labels",
    "src_iplist", "src_iplists", "dst_iplist", "dst_iplists",
    "ex_src_iplist", "ex_src_iplists", "ex_dst_iplist", "ex_dst_iplists",
    "src_workload", "src_workloads", "dst_workload", "dst_workloads",
    "ex_src_workload", "ex_src_workloads", "ex_dst_workload", "ex_dst_workloads",
    "any_iplist", "any_workload", "ex_any_iplist", "ex_any_workload",
    "services", "ex_services", "ports", "ex_ports",
    "process_name", "ex_process_name",
    "windows_service_name", "ex_windows_service_name",
    "transmission", "ex_transmission", "transmission_excludes",
)

# 兩套 client-side 比對器（check_flow_match 與 _flow_matches_filters）都無法
# 評估的 filter key：label group 成員展開只存在於 PCE 端。帶這些 key 時
# cache 路徑必須讓路給 API（PCE native 過濾），否則 cache 全覆蓋時會靜默
# 回傳未過濾資料。
_CACHE_UNEVALUABLE_FILTER_KEYS = (
    "src_label_group", "src_label_groups", "dst_label_group", "dst_label_groups",
    "ex_src_label_group", "ex_src_label_groups",
    "ex_dst_label_group", "ex_dst_label_groups",
)

# ─── Standalone Calculators (shared by Analyzer and Report modules) ──────────

def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort ``int()``: return *default* instead of raising on
    None / empty / non-numeric input. PCE and cache flow records occasionally
    carry malformed numeric fields; one bad row must not abort the monitor cycle.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def calculate_mbps(flow: dict[str, Any]) -> tuple[float, str, float, float]:
    """
    Compute bandwidth in Mbps from a PCE traffic flow record.
    Priority 1: delta bytes (dst_dbo+dst_dbi) / ddms  → Mbps (Interval)
    Priority 2: total bytes (dst_tbo+dst_tbi) / tdms   → Mbps (Avg)
    Fallback:   returns (0.0, '', 0.0, 0.0)

    Importable independently:
        from src.analyzer import calculate_mbps
    """
    delta_bytes = float(flow.get("dst_dbo") or flow.get("dbo") or 0) + \
                  float(flow.get("dst_dbi") or flow.get("dbi") or 0)
    ddms = float(flow.get("ddms") or 0)

    if delta_bytes > 0 and ddms > 0:
        if ddms < 1000:
            ddms = 1000.0
        val = (delta_bytes * 8.0) / (ddms / 1000.0) / 1000000.0
        return val, "(Interval)", delta_bytes, ddms

    tbo = float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
    tbi = float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
    total_bytes = tbo + tbi
    tdms = float(flow.get("tdms") or 0)
    if tdms < 1000:
        tdms = float(flow.get("interval_sec", 600)) * 1000
    if total_bytes > 0 and tdms > 0:
        val = (total_bytes * 8.0) / (tdms / 1000.0) / 1000000.0
        return val, "(Avg)", total_bytes, tdms
    return 0.0, "", 0.0, 0.0

def calculate_volume_mb(flow: dict[str, Any]) -> tuple[float, str]:
    """
    Compute data volume in MB from a PCE traffic flow record.
    Priority 1: delta bytes (dst_dbo+dst_dbi)  → MB (Interval)
    Priority 2: total bytes (dst_tbo+dst_tbi)  → MB (Total)

    Importable independently:
        from src.analyzer import calculate_volume_mb
    """
    delta_bytes = float(flow.get("dst_dbo") or flow.get("dbo") or 0) + \
                  float(flow.get("dst_dbi") or flow.get("dbi") or 0)
    if delta_bytes > 0:
        return delta_bytes / 1024 / 1024, "(Interval)"
    tbo = float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
    tbi = float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
    return (tbo + tbi) / 1024 / 1024, "(Total)"

QUERY_RESULT_CAP = 500  # query_flows 單次回傳上限（截斷需回報，不可無聲）

# ─── Analyzer Class ───────────────────────────────────────────────────────────

class Analyzer:
    def __init__(self, config_manager: Any, api_client: IApiClient, reporter: IReporter,
                 subscriber_events: Any = None, subscriber_flows: Any = None,
                 cache_reader: Any = None) -> None:
        self.cm = config_manager
        # Resolve the configured UI language once so alert criteria text (which
        # is built here and dispatched verbatim through the reporter) localizes
        # explicitly instead of relying on the process-global language under the
        # concurrent monitor cycle.
        _cfg = config_manager.config if isinstance(config_manager.config, dict) else {}
        self._lang: str = (_cfg.get("settings", {}).get("language", "en") or "en")
        # Stored as Any: IApiClient/IReporter Protocols only declare a subset
        # of the methods Analyzer actually calls (e.g. execute_traffic_query_stream,
        # add_traffic_alert). TODO: expand the Protocols if we want stricter checking.
        self.api: Any = api_client
        self.reporter: Any = reporter
        self._sub_events = subscriber_events
        self._sub_flows = subscriber_flows
        # Optional cache reader for time-range traffic queries (Top10, dashboard
        # widgets). When None, query_flows always hits the PCE API. When set
        # and the requested window is fully covered, reads from cache instead
        # — same hybrid pattern as ReportGenerator._fetch_traffic.
        self._cache_reader: Any = cache_reader
        # Records the data origin of the most recent query_flows() call:
        # "cache" | "mixed" | "api". Useful for dashboard UI badges.
        self.last_query_source: str = "api"
        # 記錄最近一次 query_flows() 的截斷統計：
        # {"total_matches": int, "cap": int, "truncated": bool}
        self.last_query_stats: dict[str, Any] = {}
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.state: dict[str, Any] = {
            "last_check": now_str,
            "event_watermark": now_str,
            "history": {},
            "alert_history": {},
            "event_seen": {},
            "event_overflow": {},
            "unknown_events": {},
            "event_parser_stats": {},
            "event_parser_samples": [],
        }
        ensure_monitoring_state(self.state)
        self.event_poller = EventPoller(self.api, subscriber=subscriber_events)
        self.load_state()
        ensure_monitoring_state(self.state)
        self.stats = StatsTracker(self.state)
        self.alert_throttler = AlertThrottler(self.state)
        # Set True only when this cycle performed a real PCE probe
        # (record_pce_success/record_pce_error from _run_health_check or
        # _legacy_event_pull) — never by cache-local reads
        # (StatsTracker.record_local_read). save_state()'s _merge uses this
        # to decide whether self.state.pce_stats is trustworthy enough to
        # write, or whether it must defer to the on-disk value written by
        # the scheduler's ingest jobs. See watchdog-overflow-fix-report.md (C1).
        self._pce_stats_dirty = False
        # Set True only when THIS instance actually wrote watchdog_last_alert_at
        # this cycle (record_pce_success clearing it to None on recovery, or
        # _check_watchdog setting a fresh cooldown timestamp). Deliberately a
        # separate flag from _pce_stats_dirty: on a cache-only deployment with
        # no health-check rule, _check_watchdog can fire (and write this key)
        # in a cycle where _pce_stats_dirty stays False (no real PCE probe ran
        # here) — sharing the flag would make save_state()'s _merge defer to
        # disk and immediately erase the timestamp this cycle just wrote,
        # causing a re-alert every cycle. See H-Task 3 scheduler-side finding.
        self._watchdog_dirty = False

    def load_state(self) -> None:
        try:
            data = load_state_file(STATE_FILE)
            if not data:
                logger.info("State file not found, starting fresh.")
                return
            self.state.update(data)
            if not self.state.get("event_watermark"):
                self.state["event_watermark"] = self.state.get("last_check")
            if not isinstance(self.state.get("history"), dict):
                self.state["history"] = {}
            if not isinstance(self.state.get("alert_history"), dict):
                self.state["alert_history"] = {}
            if not isinstance(self.state.get("event_seen"), dict):
                self.state["event_seen"] = {}
            if not isinstance(self.state.get("event_overflow"), dict):
                self.state["event_overflow"] = {}
            if not isinstance(self.state.get("unknown_events"), dict):
                self.state["unknown_events"] = {}
            # Startup-time purge: drop entries whose event_type is now in
            # KNOWN_EVENT_TYPES (i.e. a previous build saw it as unknown but
            # a catalog update has since covered it). Prevents stale findings
            # from accumulating forever on long-running deployments.
            unk = self.state["unknown_events"]
            stale = [et for et in unk if is_known_event_type(et)]
            if stale:
                logger.info(f"Purging {len(stale)} stale unknown_events entries now covered by catalog: {stale[:5]}{'…' if len(stale) > 5 else ''}")
                for et in stale:
                    unk.pop(et, None)
            if not isinstance(self.state.get("event_parser_stats"), dict):
                self.state["event_parser_stats"] = {}
            if not isinstance(self.state.get("event_parser_samples"), list):
                self.state["event_parser_samples"] = []
            ensure_monitoring_state(self.state)
            # Strip keys owned by external scheduler jobs; the analyzer must not
            # overwrite them in save_state() with stale startup-time copies.
            self.state.pop("ven_summary", None)
        except Exception as e:
            logger.warning(f"Error loading state file: {e}. Starting fresh.")

    def save_state(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        self.state["last_check"] = self.state.get("event_watermark") or format_utc(now)

        cutoff = now - datetime.timedelta(hours=2)
        new_history = {}
        for rid, records in self.state.get("history", {}).items():
            valid = []
            for rec in records:
                try:
                    ts = datetime.datetime.strptime(rec['t'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    if ts > cutoff:
                        valid.append(rec)
                except (KeyError, ValueError):
                    pass  # intentional fallback: skip malformed history records with missing/unparseable timestamp
            if valid:
                new_history[rid] = valid
        self.state["history"] = new_history

        seen_cutoff = now - datetime.timedelta(hours=4)
        new_seen = {}
        for event_id, ts_str in self.state.get("event_seen", {}).items():
            try:
                ts = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                if ts > seen_cutoff:
                    new_seen[event_id] = ts_str
            except (TypeError, ValueError):
                continue
        self.state["event_seen"] = new_seen
        self.state["event_parser_samples"] = list(self.state.get("event_parser_samples", []))[-10:]
        self.stats.prune(now)
        self.alert_throttler.prune(now)

        unknown_events = self.state.get("unknown_events", {})
        if isinstance(unknown_events, dict) and len(unknown_events) > 100:
            ranked = sorted(
                unknown_events.items(),
                key=lambda item: (item[1].get("last_seen", ""), item[1].get("count", 0)),
                reverse=True,
            )
            self.state["unknown_events"] = dict(ranked[:100])

        try:
            def _merge(existing: dict[str, Any]) -> dict[str, Any]:
                # externally co-owned keys: self.state is a snapshot loaded at
                # cycle start (or, for pce_stats, only reliable when this
                # cycle actually performed a real PCE probe — see
                # self._pce_stats_dirty). Other processes/background jobs may
                # write these same keys between this cycle's load_state() and
                # this save_state() call, so blindly overlaying self.state
                # would stomp their freshest on-disk values. Add new co-owned
                # keys here (never to the merged.update(self.state) overlay
                # below) whenever a key is written by code outside this
                # Analyzer instance's own cycle. See
                # .superpowers/sdd/watchdog-overflow-fix-report.md (C1/C2).
                merged = dict(existing)
                merged.update(self.state)
                # ven_summary/posture_summary: written by other background
                # jobs (dashboard summary refreshers) — always defer to disk.
                for _k in ("ven_summary", "posture_summary"):
                    if _k in existing:
                        merged[_k] = existing[_k]
                # traffic_overflow: Analyzer only ever reads this (via
                # _maybe_alert_overflow); it is written exclusively by the
                # scheduler's run_traffic_ingest job
                # (src/scheduler/jobs.py:_record_traffic_overflow). Always
                # defer to disk so a stale in-memory snapshot never wipes a
                # value the ingest job wrote mid-cycle (C2).
                if "traffic_overflow" in existing:
                    merged["traffic_overflow"] = existing["traffic_overflow"]
                # alert_dlq: Analyzer never reads or writes this; it is
                # written exclusively by the Reporter's DLQ push/pop (see
                # Reporter._push_alert_dlq/_pop_alert_dlq in
                # src/reporter.py, both via update_state_file). Always defer
                # to disk so a stale in-memory snapshot never resurrects
                # entries the Reporter already drained mid-cycle.
                if "alert_dlq" in existing:
                    merged["alert_dlq"] = existing["alert_dlq"]
                # pce_stats: co-owned with the scheduler's ingest jobs, which
                # maintain pce_stats.consecutive_failures (the watchdog
                # counter) via the same StatsTracker shape on cache-ingest
                # deployments (jobs.py:_record_ingest_pce_result). This
                # cycle's in-memory pce_stats is only trustworthy when this
                # instance performed a real PCE probe this cycle
                # (record_pce_success/record_pce_error — health check or
                # legacy event pull, marked via self._pce_stats_dirty); a
                # pure cache-read cycle never legitimately touches it (see
                # StatsTracker.record_local_read) and must defer to disk,
                # else it clobbers counts the ingest jobs accumulated between
                # this cycle's load_state() and now (C1).
                if not self._pce_stats_dirty and "pce_stats" in existing:
                    merged["pce_stats"] = existing["pce_stats"]
                # watchdog_last_alert_at: co-owned with the scheduler's
                # cache-ingest jobs, whose _record_ingest_pce_result ->
                # StatsTracker.record_pce_success clears this key to None on
                # disk directly when a real PCE probe recovers (d75170e).
                # This cycle's in-memory value is only trustworthy when THIS
                # instance actually wrote it this cycle (self._watchdog_dirty:
                # a recovery via record_pce_success, or _check_watchdog
                # setting a fresh cooldown timestamp) — never share
                # _pce_stats_dirty here (see its init comment): a cache-only
                # cycle with no health rule can have _check_watchdog fire
                # while _pce_stats_dirty stays False, and deferring in that
                # case would erase the alert this cycle just recorded. A
                # cycle that didn't touch this key at all must defer to disk
                # so a concurrent scheduler-side recovery isn't stomped by
                # this cycle's stale load-time snapshot — otherwise a new
                # incident's first alert can be suppressed for up to
                # WATCHDOG_COOLDOWN_MINUTES by the previous incident's
                # timestamp (H-Task 3 scheduler-side finding).
                if not self._watchdog_dirty and "watchdog_last_alert_at" in existing:
                    merged["watchdog_last_alert_at"] = existing["watchdog_last_alert_at"]
                return merged

            self.state = update_state_file(STATE_FILE, _merge)
        except (IOError, OSError) as e:
            logger.error(f"Error saving state: {e}")

    def calculate_mbps(self, flow: dict[str, Any]) -> tuple[float, str, float, float]:
        """Delegate to module-level calculate_mbps(). See src.analyzer.calculate_mbps."""
        return calculate_mbps(flow)

    def calculate_volume_mb(self, flow: dict[str, Any]) -> tuple[float, str]:
        """Delegate to module-level calculate_volume_mb(). See src.analyzer.calculate_volume_mb."""
        return calculate_volume_mb(flow)

    def check_flow_match(self, rule: dict[str, Any], f: dict[str, Any], start_time_limit: datetime.datetime | None) -> bool:
        # Dynamic Sliding Window Check
        if start_time_limit:
            ts_str = f.get("timestamp")
            if not ts_str and "timestamp_range" in f:
                ts_str = f["timestamp_range"].get("last_detected") or f["timestamp_range"].get("first_detected")
                
            if ts_str:
                try:
                    f_time = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
                except ValueError:
                    try:
                        f_time = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    except ValueError:
                        f_time = None

                if f_time and f_time < start_time_limit:
                    return False

        # Criteria Check
        p = f.get("pd")
        raw_dec = str(f.get("policy_decision", "")).lower()
        flow_pd = -1
        if p is not None:
            flow_pd = _safe_int(p, -1)
        elif "blocked" in raw_dec and "potentially" not in raw_dec:
            flow_pd = 2
        elif "potentially" in raw_dec:
            flow_pd = 1
        elif "allowed" in raw_dec:
            flow_pd = 0

        target_pd = rule.get("pd", 3 if rule.get("type") == "traffic" else -1)
        if target_pd != -1 and target_pd != 3 and flow_pd != target_pd:
            return False

        if rule.get("port"):
            f_port = f.get("dst_port") or f.get("service", {}).get("port")
            try:
                if not f_port or int(f_port) != int(rule["port"]):
                    return False
            except (ValueError, TypeError):
                return False

        if rule.get("proto"):
            f_proto = f.get("proto") or f.get("service", {}).get("proto")
            try:
                if not f_proto or int(f_proto) != int(rule["proto"]):
                    return False
            except (ValueError, TypeError):
                return False

        # Labels & IPs
        if rule.get("src_label") and not self._check_flow_labels(f.get('src', {}), rule["src_label"]):
            return False
        if rule.get("dst_label") and not self._check_flow_labels(f.get('dst', {}), rule["dst_label"]):
            return False
        if rule.get("src_ip_in") and not self._check_ip_filter(f.get('src', {}), rule["src_ip_in"]):
            return False
        if rule.get("dst_ip_in") and not self._check_ip_filter(f.get('dst', {}), rule["dst_ip_in"]):
            return False

        # Any-side include filters (src OR dst must match)
        if rule.get("any_label"):
            src_match = self._check_flow_labels(f.get('src', {}), rule["any_label"])
            dst_match = self._check_flow_labels(f.get('dst', {}), rule["any_label"])
            if not (src_match or dst_match):
                return False
        if rule.get("any_ip"):
            src_match = self._check_ip_filter(f.get('src', {}), rule["any_ip"])
            dst_match = self._check_ip_filter(f.get('dst', {}), rule["any_ip"])
            if not (src_match or dst_match):
                return False

        # Excludes
        if rule.get("ex_port"):
            f_port = f.get("dst_port") or f.get("service", {}).get("port")
            try:
                if f_port and int(f_port) == int(rule["ex_port"]):
                    return False
            except (ValueError, TypeError):
                pass  # intentional fallback: skip exclude-port filter if port values are not numeric
        if rule.get("ex_src_label") and self._check_flow_labels(f.get('src', {}), rule["ex_src_label"]):
            return False
        if rule.get("ex_dst_label") and self._check_flow_labels(f.get('dst', {}), rule["ex_dst_label"]):
            return False
        if rule.get("ex_src_ip") and self._check_ip_filter(f.get('src', {}), rule["ex_src_ip"]):
            return False
        if rule.get("ex_dst_ip") and self._check_ip_filter(f.get('dst', {}), rule["ex_dst_ip"]):
            return False

        # Any-side exclude filters (exclude if src OR dst matches)
        if rule.get("ex_any_label"):
            if (self._check_flow_labels(f.get('src', {}), rule["ex_any_label"]) or
                    self._check_flow_labels(f.get('dst', {}), rule["ex_any_label"])):
                return False
        if rule.get("ex_any_ip"):
            if (self._check_ip_filter(f.get('src', {}), rule["ex_any_ip"]) or
                    self._check_ip_filter(f.get('dst', {}), rule["ex_any_ip"])):
                return False

        return True

    def _match_flow_filters(self, rule: dict[str, Any], f: dict[str, Any], window_start: datetime.datetime | None) -> bool:
        """統一的 flow×filter 比對：legacy 純量 key 走 check_flow_match（含
        pd/時間窗/port/proto/list 形 IP），物件/複數 key 投影委派給報表路徑
        同一套 _flow_matches_filters（兩者 AND）。三個呼叫點共用：規則引擎、
        規則測試預覽、dashboard query_flows。label_groups 類 key 無 client-side
        成員展開——規則端點拒收、query_flows 走 cache-bypass；此處防禦性忽略
        （不影響比對結果）。此函式在 per-flow 熱迴圈內被逐筆呼叫，故不在此記
        debug log（會被洗版）；只有手改 alerts.json 繞過端點拒收才會走到這個
        分支，屬邊角情境。"""
        if not self.check_flow_match(rule, f, window_start):
            return False
        object_rule = {k: rule[k] for k in _OBJECT_FILTER_KEYS if rule.get(k)}
        if object_rule:
            # services/ex_services 的 href→entries 展開需要 client 端
            # service_ports_cache（LabelResolver.resolve_service_entries）；
            # 未傳時 _flow_matches_filters 會把 services fail-closed（include
            # 全不命中）——比照 traffic_query.fetch_traffic_for_report 的接法，
            # 用 getattr 防禦 self.api 可能是無 _labels 的測試 stub。
            labels = getattr(self.api, "_labels", None)
            resolve_service = getattr(labels, "resolve_service_entries", None)
            if not TrafficQueryBuilder._flow_matches_filters(f, object_rule, resolve_service):
                return False
        return True

    def _check_flow_labels(self, flow_side: dict[str, Any], filter_str: str) -> bool:
        if not filter_str:
            return True
        # Support both "key=value" and "key:value" separators
        for sep in ('=', ':'):
            if sep in filter_str:
                fk, fv = filter_str.split(sep, 1)
                fk, fv = fk.strip(), fv.strip()
                for lbl in flow_side.get('workload', {}).get('labels', []):
                    if lbl.get('key') == fk and lbl.get('value') == fv:
                        return True
                return False
        return False

    def _check_ip_filter(self, flow_side: dict[str, Any], filter_val: str | list) -> bool:
        if not filter_val:
            return True
        # list 形（Phase 4b FilterBar 新儲存格式）：任一值命中即 match；
        # scalar 行為逐位不變。exclude 呼叫端以「命中即排除」使用同一語意。
        # 每值依序判斷：bare IP 等值 → CIDR containment（'/'）→ IPv4 range
        # containment（'-'）→ ip_lists 名稱等值。containment 語意對齊
        # src.report.df_filter._ip_mask；range 解析委用 LabelResolver.
        # _parse_ip_range，不重寫第三份。
        vals = filter_val if isinstance(filter_val, list) else [filter_val]
        flow_ip = flow_side.get('ip')
        for val in vals:
            if not val:
                continue
            if flow_ip == val:
                return True
            if self._ip_value_contains(flow_ip, val):
                return True
            for ipl in flow_side.get('ip_lists', []):
                if ipl.get('name') == val:
                    return True
        return False

    @staticmethod
    @functools.lru_cache(maxsize=2048)
    def _parse_ip_filter_value(text: str) -> tuple | None:
        """把 CIDR/range 的解析結果快取起來——同一個 filter 值在 per-flow
        熱迴圈裡會被重複呼叫上千次（每個 flow × 每個 side 都重跑一次
        ip_network/_parse_ip_range），但值本身只有規則設定裡那幾個，快取後
        對同一 val 只解析一次。回傳 ("cidr", network) / ("range", frm, to) /
        None（bare IP 或非法格式，呼叫端各自處理）。純函式、無 flow_ip 參與，
        快取安全。"""
        if "/" in text:
            try:
                return ("cidr", ipaddress.ip_network(text, strict=False))
            except ValueError:
                return None
        if "-" in text:
            ip_range = LabelResolver._parse_ip_range(text)
            if ip_range is None:
                return None
            return ("range", ip_range[0], ip_range[1])
        return None

    @staticmethod
    def _ip_value_contains(flow_ip: Any, val: str) -> bool:
        """CIDR ('/') 或 IPv4 range ('-') containment：flow_ip 是否落在
        filter 值 val 所描述的範圍內。非法 CIDR/range → 不命中（fail-closed；
        此函式把關 live 查詢/告警結果，不套用 df_filter._ip_mask 的 cache
        顯示 fail-open 慣例）。值本身的解析交給 _parse_ip_filter_value（有
        lru_cache），這裡只做逐 flow 不同的 containment 判斷。"""
        parsed = Analyzer._parse_ip_filter_value(str(val))
        if parsed is None:
            return False
        try:
            if parsed[0] == "cidr":
                return ipaddress.ip_address(str(flow_ip)) in parsed[1]
            _, frm, to = parsed
            return frm <= ipaddress.IPv4Address(str(flow_ip)) <= to
        except ValueError:
            return False

    def get_traffic_details_key(self, flow: dict[str, Any]) -> str:
        src = flow.get('src', {})
        dst = flow.get('dst', {})
        svc = flow.get('service', {})
        s_name = src.get('workload', {}).get('name') or src.get('ip', 'N/A')
        d_name = dst.get('workload', {}).get('name') or dst.get('ip', 'N/A')
        port = svc.get('port', 'All') or flow.get('dst_port', 'All')
        return f"{s_name} -> {d_name} [{port}]"

    def _record_event_matches(self, rule_id: Any, events: list[dict[str, Any]], now_utc: datetime.datetime) -> None:
        rid = str(rule_id)
        if rid not in self.state["history"]:
            self.state["history"][rid] = []

        for event in events:
            event_ts = parse_event_timestamp(event.get("timestamp")) or now_utc
            self.state["history"][rid].append({
                "t": format_utc(event_ts),
                "event_id": event_identity(event),
            })

    def _event_count_in_window(self, rule_id: Any, window_start: datetime.datetime) -> int:
        total = 0
        for rec in self.state.get("history", {}).get(str(rule_id), []):
            try:
                ts = datetime.datetime.strptime(rec['t'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
            except (KeyError, ValueError):
                continue
            if ts <= window_start:
                continue
            # Each history record represents exactly one event (records only ever
            # store {'t', 'event_id'}; there is no count-compression field).
            total += 1
        return total

    def _fetch_event_batch(self) -> Any:
        watermark = self.state.get("event_watermark") or self.state.get("last_check")
        seen_events = self.state.get("event_seen", {})
        batch = self.event_poller.fetch_batch(watermark, seen_events=seen_events)
        self.state["event_seen"] = batch.seen_events
        self.state["event_watermark"] = batch.next_watermark
        if batch.overflow_risk:
            self.state["event_overflow"] = {
                "detected_at": format_utc(datetime.datetime.now(datetime.timezone.utc)),
                "query_since": batch.query_since,
                "query_until": batch.query_until,
                "raw_count": batch.raw_count,
                "max_results": self.event_poller.max_results,
            }
        else:
            self.state["event_overflow"] = {}
        return batch

    def _update_parser_observability(self, normalized_events: list[dict[str, Any]]) -> None:
        total = len(normalized_events)
        known = sum(1 for event in normalized_events if event.get("known_event_type"))
        stats = {
            "last_batch_total": total,
            "last_batch_known": known,
            "last_batch_unknown": total - known,
            "actor_resolved": sum(1 for event in normalized_events if event.get("actor") and event.get("actor") != "System"),
            "target_resolved": sum(1 for event in normalized_events if event.get("target_name")),
            "resource_resolved": sum(1 for event in normalized_events if event.get("resource_name")),
            "action_resolved": sum(1 for event in normalized_events if event.get("action")),
            "source_ip_resolved": sum(1 for event in normalized_events if event.get("source_ip")),
            "parser_note_count": sum(len(event.get("parser_notes") or []) for event in normalized_events),
        }
        self.state["event_parser_stats"] = stats
        pce_stats = self.state.setdefault("pce_stats", {})
        pce_stats["last_batch_unknown"] = stats["last_batch_unknown"]
        pce_stats["last_batch_notes"] = stats["parser_note_count"]

        samples = list(self.state.get("event_parser_samples", []))
        for event in normalized_events:
            samples.append({
                "timestamp": event.get("timestamp"),
                "event_type": event.get("event_type"),
                "actor": event.get("actor"),
                "source_ip": event.get("source_ip"),
                "target_type": event.get("target_type"),
                "target_name": event.get("target_name"),
                "resource_type": event.get("resource_type"),
                "resource_name": event.get("resource_name"),
                "action": event.get("action"),
                "known_event_type": event.get("known_event_type"),
                "parser_notes": event.get("parser_notes") or [],
            })
        self.state["event_parser_samples"] = samples[-10:]

        unknown_events = self.state.setdefault("unknown_events", {})
        for event in normalized_events:
            event_type = event.get("event_type") or "(missing)"
            if is_known_event_type(event_type):
                continue
            # Resource-family lenient classification: if the resource prefix
            # matches a known family (e.g. deny_rule.bulk_delete on the
            # known deny_rule resource), record the event type but tag it
            # with category so downstream can distinguish "uncatalogued
            # action on known resource" from "truly novel resource".
            # Third fallback: when event_type is malformed but the payload
            # carries resource_changes[0].resource, use that resource_type
            # hint (preserved by normalizer in event['resource_type']).
            payload_resource_type = event.get("resource_type") or None
            category = classify_unknown_event_type(
                event_type, resource_type=payload_resource_type
            )
            lenient_known = category != "unclassified"
            entry = unknown_events.get(event_type, {
                "count": 0,
                "first_seen": event.get("timestamp"),
                "last_seen": event.get("timestamp"),
                "sample": {},
                "category": category,
                "lenient_known": lenient_known,
            })
            entry["count"] += 1
            entry["last_seen"] = event.get("timestamp") or entry.get("last_seen")
            entry["category"] = category
            entry["lenient_known"] = lenient_known
            entry["sample"] = {
                "actor": event.get("actor"),
                "source_ip": event.get("source_ip"),
                "target_name": event.get("target_name"),
                "resource_type": event.get("resource_type"),
                "resource_name": event.get("resource_name"),
                "action": event.get("action"),
                "parser_notes": event.get("parser_notes") or [],
            }
            unknown_events[event_type] = entry

    def _run_health_check(self) -> bool:
        """Run the PCE health check if any system/pce_health rules are configured.

        Records stats and fires health alerts as needed. The analysis cycle
        always continues regardless of PCE health status; health failure is
        informational, not a gate.

        Returns:
            True always — no health-check rules configured (skipped) or check
            completed (passed or failed). False is reserved for future use.
        """
        pce_health_rules = [r for r in self.cm.config["rules"] if r.get("type") == "system" and r.get("filter_value") == "pce_health"]

        if not pce_health_rules:
            return True

        logger.debug(t('checking_pce_health'))
        h_status, h_msg = self.api.check_health()
        if h_status != 200:
            logger.error(t('status_error'))
            logger.warning(f"PCE health check failed: {h_status} - {h_msg[:200]}")
            self.stats.record_pce_error("health", h_msg[:200], status=h_status)
            self._pce_stats_dirty = True
            for rule in pce_health_rules:
                if self._check_cooldown(rule):
                    self.reporter.add_health_alert({
                        "time": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                        "rule": rule["name"],
                        "status": str(h_status),
                        "details": h_msg[:200]
                    })
        else:
            from src.api_client import health_status_from_body
            body_status = health_status_from_body(h_msg)
            if body_status in {"warning", "degraded", "error", "critical"}:
                logger.warning(f"PCE health degraded: status={body_status}")
                self.stats.record_pce_error("health", f"degraded: status={body_status}", status=h_status)
                self._pce_stats_dirty = True
                for rule in pce_health_rules:
                    if self._check_cooldown(rule):
                        self.reporter.add_health_alert({
                            "time": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                            "rule": rule["name"],
                            "status": body_status,
                            "details": t('health_degraded_details', status=body_status),
                        })
            else:
                logger.info(t('status_ok'))
                logger.info("PCE health check OK.")
                self.stats.record_pce_success("health", status=h_status, message=h_msg[:120])
                self._pce_stats_dirty = True
                self._watchdog_dirty = True
        return True

    def _check_watchdog(self) -> None:
        """Self-alert when the PCE has been unreachable for N consecutive cycles.

        Without this, a dead poller fails silent: no events, no alerts, and the
        operator assumes all is well. Uses its own cooldown so a long outage
        produces one alert per hour instead of one per cycle.
        """
        failures = int(self.state.get("pce_stats", {}).get("consecutive_failures", 0))
        if failures < WATCHDOG_FAILURE_THRESHOLD:
            return
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last = parse_event_timestamp(self.state.get("watchdog_last_alert_at"))
        if last and (now_utc - last).total_seconds() < WATCHDOG_COOLDOWN_MINUTES * 60:
            return
        self.state["watchdog_last_alert_at"] = format_utc(now_utc)
        self._watchdog_dirty = True
        last_error = self.state.get("pce_stats", {}).get("last_error", "")
        self.reporter.add_health_alert({
            "time": now_utc.strftime('%Y-%m-%d %H:%M:%S'),
            "rule": t('alert_watchdog_rule'),
            "status": "critical",
            "details": t('alert_watchdog_details', count=failures, error=last_error[:120]),
        })
        logger.error(f"Watchdog: {failures} consecutive PCE failures — self-alert dispatched")

    def _maybe_alert_overflow(self) -> None:
        """Meta-alert on any data-loss overflow signal: oldest events were lost
        (event_overflow, legacy live event polling) or a minute of traffic
        flows may be incomplete (traffic_overflow, cache-ingest bisection
        floor — written by run_traffic_ingest, see scheduler/jobs.py).

        Generalized (was event_overflow-only, and was only ever called from
        the legacy no-cache-subscriber branch of _run_event_analysis) because
        under pce_cache.enabled=true that legacy branch never runs — this is
        now called unconditionally from run_analysis() every cycle so the
        cache-ingest path's traffic_overflow actually gets checked. See
        live-verification-report.md finding #7.

        Each signal has its own state key and cooldown key so a persistent
        one alerting doesn't suppress the other, and vice versa.
        """
        self._maybe_alert_single_overflow(
            state_key="event_overflow",
            cooldown_key="overflow_last_alert_at",
            rule_key="alert_overflow_rule",
            details_key="alert_overflow_details",
            log_label="Event overflow",
        )
        self._maybe_alert_single_overflow(
            state_key="traffic_overflow",
            cooldown_key="traffic_overflow_last_alert_at",
            rule_key="alert_traffic_overflow_rule",
            details_key="alert_traffic_overflow_details",
            log_label="Traffic ingest overflow",
        )

    def _maybe_alert_single_overflow(
        self, *, state_key: str, cooldown_key: str, rule_key: str, details_key: str, log_label: str
    ) -> None:
        overflow = self.state.get(state_key) or {}
        if not overflow:
            return
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last = parse_event_timestamp(self.state.get(cooldown_key))
        if last and (now_utc - last).total_seconds() < OVERFLOW_ALERT_COOLDOWN_MINUTES * 60:
            return
        self.state[cooldown_key] = format_utc(now_utc)
        self.reporter.add_health_alert({
            "time": now_utc.strftime('%Y-%m-%d %H:%M:%S'),
            "rule": t(rule_key),
            "status": "warning",
            "details": t(details_key,
                         raw=overflow.get("raw_count", "?"),
                         cap=overflow.get("max_results", "?"),
                         since=overflow.get("query_since", "?"),
                         until=overflow.get("query_until", "?")),
        })
        logger.warning(f"{log_label} meta-alert dispatched")

    def run_analysis(self) -> None:
        logger.info("Starting analysis cycle.")
        # 1. Health Check (only runs when a system rule with filter_value=pce_health is configured)
        self._run_health_check()

        # 2. Events pipeline
        event_triggers = self._run_event_analysis()

        # 3. Traffic pipeline
        traffic_stream, tr_rules, now_utc = self._fetch_traffic()
        triggers = []
        if traffic_stream is not None:
            triggers = self._run_rule_engine(traffic_stream, tr_rules, now_utc)

        # 4. Dispatch alerts for traffic triggers
        self._dispatch_alerts(triggers, tr_rules)

        # Overflow meta-alerts (event polling / traffic ingest) — must run
        # unconditionally every cycle, not just on the legacy event-poll
        # branch, so the pce_cache-ingest path's traffic_overflow is checked
        # even when _run_event_analysis took the cache-subscriber branch.
        self._maybe_alert_overflow()

        self._check_watchdog()

        self.save_state()
        logger.info("Analysis cycle completed.")
        gc.collect()

    def _legacy_event_pull(self) -> tuple[list[dict[str, Any]], Any]:
        """Fetch events from the PCE API (legacy path used when no cache subscriber)."""
        logger.warning(
            "[deprecated] _legacy_event_pull called — pce_cache path should be "
            "preferred; remove after pce_cache.enabled becomes the default."
        )
        event_batch = self._fetch_event_batch()
        events = event_batch.events
        self.stats.record_pce_success("events", status=200, message=f"fetched={len(events)}")
        self._pce_stats_dirty = True
        self._watchdog_dirty = True
        if event_batch.overflow_risk:
            logger.warning(
                "Event polling reached max_results=%s between %s and %s; additional events may exist.",
                self.event_poller.max_results,
                event_batch.query_since,
                event_batch.query_until,
            )
        return events, event_batch

    def _run_event_analysis(self) -> list:
        """Poll events, normalise, run rule matching, and fire event alerts.

        Returns a list of event-trigger dicts (one per triggered rule) so that
        _dispatch_alerts can handle them if needed in the future.  Currently,
        event alerts are dispatched directly inside this method for cohesion
        with the existing reporter.add_event_alert() call site.
        """
        logger.info(t('checking_events'))
        event_triggers = []
        events = []
        event_batch = None
        if self._sub_events is not None:
            try:
                events = self._sub_events.poll_new_rows(limit=5000)
                logger.info("Analyzer event path: cache ({} rows)", len(events))
                # Record poll health like the legacy path does — the dashboard
                # "Event Poll" card reads pce_stats.event_poll_status, which would
                # otherwise stay 'unknown' forever on the cache path. Uses
                # record_local_read (NOT record_pce_success): a local cache
                # read says nothing about live PCE reachability, so it must
                # never reset pce_stats.consecutive_failures — on this
                # deployment shape that counter is owned exclusively by the
                # scheduler's ingest jobs (see _check_watchdog docstring and
                # .superpowers/sdd/watchdog-overflow-fix-report.md, C1).
                self.stats.record_local_read("events", success=True, message=f"cache rows={len(events)}")
            except Exception as e:
                logger.error(f"Cache event poll failed: {e}")
                logger.error(t('api_fetch_events_error', error=str(e)))
                self.stats.record_local_read("events", success=False, error=str(e))
        else:
            try:
                events, event_batch = self._legacy_event_pull()
            except Exception as e:
                logger.error(f"Event polling failed; watermark preserved at {self.state.get('event_watermark')}: {e}")
                logger.error(t('api_fetch_events_error', error=str(e)))
                self.stats.record_pce_error("events", str(e))
                self._pce_stats_dirty = True

        if events:
            logger.info(t('found_events', count=len(events)))
            logger.info(f"Found {len(events)} events.")
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            normalized_by_id = {}
            for event in events:
                normalized = normalize_event(event)
                normalized_by_id[event_identity(event)] = normalized
            self._update_parser_observability(list(normalized_by_id.values()))
            self.stats.record_event_batch(
                events,
                unknown_count=self.state.get("event_parser_stats", {}).get("last_batch_unknown", 0),
                parser_note_count=self.state.get("event_parser_stats", {}).get("parser_note_count", 0),
                overflow_risk=bool(self.state.get("event_overflow")),
                query_since=event_batch.query_since if event_batch is not None else "",
                query_until=event_batch.query_until if event_batch is not None else "",
            )

            for rule in [r for r in self.cm.config["rules"] if r["type"] == "event"]:
                matches = [e for e in events if matches_event_rule(rule, e)]

                if matches:
                    self._record_event_matches(rule["id"], matches, now_utc)

                # Check Threshold
                count_val = len(matches)
                if rule["threshold_type"] == "count":
                    win_minutes = rule.get("threshold_window", 10)
                    win_start = now_utc - datetime.timedelta(minutes=win_minutes)
                    count_val = self._event_count_in_window(rule["id"], win_start)

                if count_val >= rule["threshold_count"] and count_val > 0:
                    if self._check_cooldown(rule):
                        self.stats.record_rule_trigger(rule, match_count=count_val, metric_value=count_val)
                        first = matches[0] if matches else {}
                        first_norm = normalized_by_id.get(event_identity(first)) or normalize_event(first)
                        alert_data = {
                            "time": first.get("timestamp", "N/A"),
                            "rule": rule["name"],
                            "desc": rule.get("desc"),
                            "severity": first_norm.get("severity") or first.get("severity", "info"),
                            "count": count_val,
                            "source": first_norm.get("source", ""),
                            "target": first_norm.get("target_name", ""),
                            "resource_type": first_norm.get("resource_type", ""),
                            "resource_name": first_norm.get("resource_name", ""),
                            "action": first_norm.get("action", ""),
                            "raw_data": matches[:5],
                            "parsed_data": [
                                normalized_by_id.get(event_identity(event)) or normalize_event(event)
                                for event in matches[:5]
                            ],
                        }
                        self.reporter.add_event_alert(alert_data)
                        event_triggers.append(alert_data)

        return event_triggers

    def _legacy_fetch_traffic(self) -> tuple[Any, datetime.datetime]:
        """Fetch traffic from the PCE API (legacy path used when no cache subscriber)."""
        logger.warning(
            "[deprecated] _legacy_fetch_traffic called — pce_cache path should be "
            "preferred; remove after pce_cache.enabled becomes the default."
        )
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        max_win = max([r.get('threshold_window', 10) for r in self.cm.config["rules"]
                       if r["type"] in ["traffic", "bandwidth", "volume"]])
        start_dt = now_utc - datetime.timedelta(minutes=max_win + 2)
        traffic_stream = self.api.execute_traffic_query_stream(
            start_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
            ["blocked", "potentially_blocked", "allowed"]
        )
        return traffic_stream, now_utc

    def _fetch_traffic(self) -> tuple:
        """Determine traffic rules, query the API or cache, and return the raw stream.

        Returns:
            (traffic_stream, tr_rules, now_utc) where traffic_stream is the
            generator/iterable from the API or cache (or None if no rules or no data),
            tr_rules is the filtered list of traffic/bandwidth/volume rules, and
            now_utc is the datetime used as the query end boundary.
        """
        tr_rules = [r for r in self.cm.config["rules"] if r["type"] in ["traffic", "bandwidth", "volume"]]
        if not tr_rules:
            return None, tr_rules, datetime.datetime.now(datetime.timezone.utc)

        now_utc = datetime.datetime.now(datetime.timezone.utc)

        if self._sub_flows is not None:
            flows = self._sub_flows.poll_new_rows(limit=10000)
            logger.info("Analyzer flow path: cache ({} rows)", len(flows))
            return flows, tr_rules, now_utc

        traffic_stream, now_utc = self._legacy_fetch_traffic()
        return traffic_stream, tr_rules, now_utc

    @staticmethod
    def _push_bounded_top_match(heap: list, metric_val: float, idx: int, item: dict, limit: int) -> None:
        """以 metric_val 為鍵，將 `heap` 維持為有界的 top-`limit` 匹配集合。

        tie-break 與原始「全量累積後 stable sort 降冪」行為一致：
        metric_val 相同時，較早 append 的 flow（idx 較小）優先保留。
        heap 元素為 (metric_val, -idx, item)，使 heapq min-heap 的
        root 永遠是目前最差的一筆（metric_val 最低；同值時取最晚
        append 的），正好就是新進的更佳（或同值但更早）項目該淘汰的對象。
        """
        entry = (metric_val, -idx, item)
        if len(heap) < limit:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)

    def _run_rule_engine(self, traffic_stream: Any, tr_rules: list, now_utc: datetime.datetime) -> list:
        """Iterate over traffic flows and accumulate per-rule match results.

        Args:
            traffic_stream: Iterable of raw traffic flow dicts from the API.
            tr_rules: List of traffic/bandwidth/volume rule dicts.
            now_utc: Reference datetime for sliding-window calculations.

        Returns:
            List of (rule, result_dict) pairs for ALL rules, each paired with
            its accumulated result containing max_val and top_matches.

        top_matches 的累積以每規則 TOP_MATCHES_LIMIT 為上界（min-heap），
        不再收集所有匹配的 flow —— dispatch 端本來就只保留前 10 筆，
        無界累積只是 O(flows) 記憶體卻無任何可觀察效益。有界結構產出的
        top-N 集合與順序，與 dispatch 從全量累積推導出的結果完全一致
        （tie-break 見 _push_bounded_top_match）。
        """
        rule_results: dict[Any, dict[str, Any]] = {r['id']: {'max_val': 0.0, 'top_matches': []} for r in tr_rules}
        top_heaps: dict[Any, list] = {r['id']: [] for r in tr_rules}

        count_processed = 0
        for f in traffic_stream:
            count_processed += 1

            bw_val, bw_note, _, _ = self.calculate_mbps(f)
            vol_val, vol_note = self.calculate_volume_mb(f)
            conn_val = _safe_int(f.get("num_connections") or f.get("count", 1))

            for rule in tr_rules:
                rid = rule['id']
                r_win = rule.get("threshold_window", 10)
                r_start = now_utc - datetime.timedelta(minutes=r_win)

                if not self._match_flow_filters(rule, f, r_start):
                    continue

                res = rule_results[rid]
                heap = top_heaps[rid]

                if rule["type"] == "bandwidth":
                    if bw_val > res['max_val']:
                        res['max_val'] = bw_val
                    if bw_val > float(rule.get("threshold_count", 0)):
                        f_copy = f.copy()
                        f_copy['_metric_val'] = bw_val
                        f_copy['_metric_fmt'] = f"{format_unit(bw_val, 'bandwidth')} {bw_note}"
                        self._push_bounded_top_match(heap, bw_val, count_processed, f_copy, TOP_MATCHES_LIMIT)

                elif rule["type"] == "volume":
                    res['max_val'] += vol_val
                    f_copy = f.copy()
                    f_copy['_metric_val'] = vol_val
                    f_copy['_metric_fmt'] = f"{format_unit(vol_val, 'volume')} {vol_note}"
                    self._push_bounded_top_match(heap, vol_val, count_processed, f_copy, TOP_MATCHES_LIMIT)

                else:  # Traffic Count
                    res['max_val'] += conn_val
                    f_copy = f.copy()
                    f_copy['_metric_val'] = conn_val
                    f_copy['_metric_fmt'] = str(conn_val)
                    self._push_bounded_top_match(heap, conn_val, count_processed, f_copy, TOP_MATCHES_LIMIT)

        logger.info(t('found_traffic', count=count_processed))

        # 將每條規則的有界集合還原為原始 append 順序（idx 升冪），
        # 使下游（_dispatch_alerts 自己的 stable sort）看到的 tie-break
        # 行為與原始無界累積完全相同。
        for rid, heap in top_heaps.items():
            rule_results[rid]['top_matches'] = [
                item for (_, _, item) in sorted(heap, key=lambda e: -e[1])
            ]

        # Return a flat list of (rule, result) pairs for all rules
        return [(rule, rule_results[rule['id']]) for rule in tr_rules]

    def _dispatch_alerts(self, triggers: list, tr_rules: list) -> None:
        """Evaluate threshold conditions and send traffic alerts to the reporter.

        Args:
            triggers: List of (rule, result_dict) pairs produced by _run_rule_engine.
            tr_rules: The original list of traffic/bandwidth/volume rule dicts
                      (used only for type information; mirrors the rules in triggers).
        """
        for rule, res in triggers:
            val = res['max_val']
            threshold = float(rule.get("threshold_count", 0))

            is_trigger = False
            if rule["type"] == "bandwidth":
                if len(res['top_matches']) > 0:
                    is_trigger = True
            else:
                if val >= threshold:
                    is_trigger = True

            if is_trigger and self._check_cooldown(rule):
                res['top_matches'].sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
                top_10 = res['top_matches'][:TOP_MATCHES_LIMIT]
                self.stats.record_rule_trigger(rule, match_count=len(top_10), metric_value=val)

                ctr = Counter([self.get_traffic_details_key(m) for m in top_10])
                details = "<br>".join([f"{k}: {v}" for k, v in ctr.most_common(10)])

                alert_data = {
                    "rule": rule["name"],
                    "count": f"{val:.2f}" if rule['type'] != 'traffic' else str(int(val)),
                    "criteria": self._build_criteria_str(rule),
                    "details": details,
                    "raw_data": top_10
                }

                if rule["type"] in ["bandwidth", "volume"]:
                    self.reporter.add_metric_alert(alert_data)
                else:
                    self.reporter.add_traffic_alert(alert_data)

    def _check_cooldown(self, rule: dict[str, Any]) -> bool:
        rid = str(rule["id"])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last_alert = self.state.get("alert_history", {}).get(rid)

        cd_minutes = rule.get("cooldown_minutes", rule.get("threshold_window", 10))

        if last_alert:
            try:
                last_dt = datetime.datetime.strptime(last_alert, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                if (now_utc - last_dt).total_seconds() < (cd_minutes * 60):
                    next_allowed_at = last_dt + datetime.timedelta(minutes=cd_minutes)
                    self.alert_throttler.record_cooldown_suppressed(rule, now_utc, next_allowed_at=next_allowed_at)
                    self.stats.record_suppression(
                        rule,
                        "cooldown",
                        cooldown_minutes=cd_minutes,
                        next_allowed_at=format_utc(next_allowed_at),
                    )
                    logger.warning(t('alert_cooldown', rule=rule['name']))
                    logger.info(f"Rule '{rule['name']}' in cooldown.")
                    return False
            except ValueError:
                pass  # intentional fallback: unparseable last_alert timestamp means cooldown is not enforced

        allowed, throttle_meta = self.alert_throttler.allow(rule, now_utc)
        if not allowed:
            self.stats.record_suppression(
                rule,
                "throttle",
                throttle=throttle_meta.get("throttle", ""),
                next_allowed_at=throttle_meta.get("next_allowed_at", ""),
                suppressed=throttle_meta.get("suppressed", 0),
            )
            logger.warning(f"{rule['name']} suppressed by throttle {throttle_meta.get('throttle', '')}")
            logger.info("Rule '%s' suppressed by throttle %s.", rule["name"], throttle_meta.get("throttle"))
            return False

        logger.warning(t('alert_trigger', rule=rule['name']))
        logger.warning(f"Alert triggered: {rule['name']}")
        if "alert_history" not in self.state:
            self.state["alert_history"] = {}
        self.state["alert_history"][rid] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        return True

    def _build_criteria_str(self, rule: dict[str, Any], *, lang: str | None = None) -> str:
        # Bandwidth fires on a strict '>' threshold; traffic/volume fire on '>='
        # (see _dispatch_alerts), so the advertised operator must match the type.
        op = ">" if rule.get("type") == "bandwidth" else ">="
        _lang = lang or self._lang
        crit = [t('alert_criteria_threshold', lang=_lang, op=op, n=rule['threshold_count'])]
        if rule.get('port'):
            crit.append(t('alert_criteria_port', lang=_lang, p=rule['port']))
        return ", ".join(crit)

    def _fetch_query_flows(
        self,
        start_time: str,
        end_time: str,
        query_pds: list[str],
        query_spec: Any,
        needs_draft: bool,
        cache_bypass_keys: list[str] | None = None,
    ) -> tuple[Any, str]:
        """Cache-aware fetch for query_flows. Returns (flow_iterable, source).

        Mirrors ReportGenerator._fetch_traffic: full cache hit → cache;
        partial → API fills the gap, cache covers the rest; otherwise → API.
        Note: cache rows are pre-decoded PCE flow dicts, so they are drop-in
        compatible with the downstream pipeline that consumes the API stream.
        Client-side filtering still happens in query_flows below（legacy scalar
        key 走 check_flow_match、物件/複數 key 委派 _flow_matches_filters），
        so cache returning unfiltered flows is safe——前提是 filters 全部可在
        client 端評估；無法評估的 key（label_groups 類）由 caller 透過
        cache_bypass_keys 要求跳過 cache、改走 API（PCE native 過濾）。
        """
        # Without a cache reader, behaviour is identical to the pre-cache path.
        if self._cache_reader is None:
            stream = self.api.execute_traffic_query_stream(
                start_time, end_time, query_pds,
                filters=query_spec, compute_draft=needs_draft,
            )
            return stream, "api"

        if cache_bypass_keys:
            # client 端比對器無法評估這些 key——cache 資料未經 PCE 過濾，
            # 用了會靜默回傳未過濾結果，故強制走 API。
            logger.debug(
                "query_flows: cache bypassed — filters {} cannot be evaluated "
                "client-side; using API so the PCE applies them natively",
                cache_bypass_keys,
            )
            stream = self.api.execute_traffic_query_stream(
                start_time, end_time, query_pds,
                filters=query_spec, compute_draft=needs_draft,
            )
            return stream, "api"

        try:
            start_dt = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=datetime.timezone.utc,
            )
            end_dt = datetime.datetime.strptime(end_time, '%Y-%m-%dT%H:%M:%SZ').replace(
                tzinfo=datetime.timezone.utc,
            )
        except (ValueError, TypeError):
            stream = self.api.execute_traffic_query_stream(
                start_time, end_time, query_pds,
                filters=query_spec, compute_draft=needs_draft,
            )
            return stream, "api"

        try:
            state = self._cache_reader.cover_state("traffic", start_dt, end_dt)
        except Exception as exc:
            logger.warning("query_flows: cache cover_state failed ({}); using API", exc)
            stream = self.api.execute_traffic_query_stream(
                start_time, end_time, query_pds,
                filters=query_spec, compute_draft=needs_draft,
            )
            return stream, "api"

        if state == "full":
            try:
                logger.info("query_flows: flows from cache ({} → {})", start_dt, end_dt)
                return self._cache_reader.read_flows_raw(start_dt, end_dt), "cache"
            except CacheReadTooLarge as exc:
                logger.warning(
                    "query_flows: {} — falling back to live API (bounded)", exc)
                state = "cache_too_large"  # 落到函式底部的 API 路徑

        if state == "partial":
            cache_start = self._cache_reader.earliest_data_timestamp("traffic")
            if cache_start is not None and cache_start > start_dt:
                # 半開的 gap 視窗：cache.read_flows_raw 兩端皆含端點
                # （'last_detected >= cache_start'），若 API gap 查詢
                # 恰好以 cache_start 結束，落在 cache_start 精確時間戳
                # 上的 flow 會被兩側各算一次。將 API gap 的結束時間
                # 回退 1 秒（API 時間字串的解析度），使 gap 覆蓋
                # [start_dt, cache_start)、cache 覆蓋 [cache_start,
                # end_dt] —— 每筆 flow 恰好計一次。
                #
                # 假設與殘餘風險：此修法假設 PCE API 的 end_date 在
                # 秒解析度下為 inclusive。實際支持證據是原本的雙算
                # 確實存在（兩側皆含 cache_start 端點才會重複），反推
                # API 端亦為 inclusive。此假設無法離線驗證；若 API
                # end 實為 exclusive，則 cache_start-1s 那一整秒的
                # flow 會被漏掉 —— 1 秒視窗的窄幅少算，屬已知取捨，
                # 嚴格優於先前的雙算。
                gap_end_dt = cache_start - datetime.timedelta(seconds=1)
                logger.info(
                    "query_flows: hybrid fetch — API gap [{} → {}], cache [{} → {}]",
                    start_dt, gap_end_dt, cache_start, end_dt,
                )
                try:
                    if gap_end_dt >= start_dt:
                        gap_end = gap_end_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                        gap_stream = self.api.execute_traffic_query_stream(
                            start_time, gap_end, query_pds,
                            filters=query_spec, compute_draft=needs_draft,
                        )
                        gap_list = list(gap_stream) if gap_stream is not None else []
                    else:
                        # 次秒級 gap：回退 1 秒後已無有意義的窗口
                        # 可向 API 查詢。
                        gap_list = []
                except Exception as exc:
                    logger.warning(
                        "query_flows hybrid: API gap fetch failed ({}); falling back to full API path", exc,
                    )
                    gap_list = None
                if gap_list is not None:
                    try:
                        cached = self._cache_reader.read_flows_raw(cache_start, end_dt)
                    except CacheReadTooLarge as exc:
                        logger.warning(
                            "query_flows hybrid: {} — falling back to full API path", exc)
                    else:
                        source = "mixed" if gap_list else "cache"
                        return gap_list + cached, source

        # miss / partial-with-conflict / hybrid-failure: fall through to API
        stream = self.api.execute_traffic_query_stream(
            start_time, end_time, query_pds,
            filters=query_spec, compute_draft=needs_draft,
        )
        return stream, "api"

    def _raise_if_query_fetch_failed(self) -> None:
        """互動查詢失敗須可分辨（spec §B）：API/混合來源在串流耗盡後，
        last_fetch_error 非空即代表本次查詢在 PCE 側失敗（submit 406、
        poll failed/timeout、download 失敗、stream 例外），不得與 0 筆
        同形回傳。cache/archive 來源不打 PCE，不檢查。"""
        if self.last_query_source in ("api", "mixed"):
            err = getattr(self.api, "last_fetch_error", None)
            if err:
                raise TrafficQueryError(str(err))

    def query_flows(self, params: dict) -> list[dict[str, Any]]:
        """
        Generic traffic flow query utilizing identical metrics logic to run_debug_mode.
        params schema:
        {
          "start_time": "2026-02-23T00:00:00Z",
          "end_time": "2026-02-23T23:59:59Z",
          "policy_decisions": ["blocked", "allowed"],
          "sort_by": "bandwidth", # bandwidth, volume, connections
          "search": "192.168.1.1" # optional text filter
        }
        """
        # 每次查詢先重設統計——含 early-return 路徑（空結果不得殘留上次統計）
        self.last_query_stats = {"total_matches": 0, "cap": QUERY_RESULT_CAP, "truncated": False}

        start_time = params.get("start_time")
        end_time = params.get("end_time")
        if not isinstance(start_time, str) or not isinstance(end_time, str):
            raise TypeError(
                "query_flows: 'start_time' and 'end_time' must be ISO-format strings "
                "(e.g. '2026-02-23T00:00:00Z')"
            )
        pds = params.get("policy_decisions", ["blocked", "potentially_blocked", "allowed"])
        
        strict_pd: set[str] = set()
        for p in pds:
            if p == "potentially_blocked": strict_pd.add("potentially_blocked")
            elif p == "blocked": strict_pd.add("blocked")
            elif p == "allowed": strict_pd.add("allowed")
        
        query_filters = {
            "port": params.get("port"),
            "proto": params.get("proto"),
            "port_range": params.get("port_range"),
            "ex_port": params.get("ex_port"),
            "ex_port_range": params.get("ex_port_range"),
            # Task 11：FilterBar 的 service/port pill 序列化 key（qt-port/qt-proto/
            # qt-expt scalar 欄位移除後改走 pill）——與 actions.py 的 params dict
            # 保持一致，否則會在這個 whitelist 被靜默丟棄。
            "services": params.get("services", []),
            "ex_services": params.get("ex_services", []),
            "ports": params.get("ports", []),
            "ex_ports": params.get("ex_ports", []),
            "process_name": params.get("process_name"),
            "ex_process_name": params.get("ex_process_name"),
            "windows_service_name": params.get("windows_service_name"),
            "ex_windows_service_name": params.get("ex_windows_service_name"),
            "src_label": params.get("src_label"),
            "src_label_group": params.get("src_label_group"),
            "src_label_groups": params.get("src_label_groups"),
            "dst_label": params.get("dst_label"),
            "dst_label_group": params.get("dst_label_group"),
            "dst_label_groups": params.get("dst_label_groups"),
            "src_ip_in": params.get("src_ip_in"),
            "dst_ip_in": params.get("dst_ip_in"),
            "ex_src_label": params.get("ex_src_label"),
            "ex_src_label_group": params.get("ex_src_label_group"),
            "ex_src_label_groups": params.get("ex_src_label_groups"),
            "ex_dst_label": params.get("ex_dst_label"),
            "ex_dst_label_group": params.get("ex_dst_label_group"),
            "ex_dst_label_groups": params.get("ex_dst_label_groups"),
            "ex_src_ip": params.get("ex_src_ip"),
            "ex_dst_ip": params.get("ex_dst_ip"),
            "any_label": params.get("any_label"),
            "any_ip": params.get("any_ip"),
            "ex_any_label": params.get("ex_any_label"),
            "ex_any_ip": params.get("ex_any_ip"),
            "src_ams": params.get("src_ams"),
            "dst_ams": params.get("dst_ams"),
            "ex_src_ams": params.get("ex_src_ams"),
            "ex_dst_ams": params.get("ex_dst_ams"),
            "transmission_excludes": params.get("transmission_excludes") or params.get("ex_transmission"),
            "transmission": params.get("transmission"),
            "src_include_groups": params.get("src_include_groups"),
            "dst_include_groups": params.get("dst_include_groups"),
            "search": params.get("search"),
            "sort_by": params.get("sort_by"),
            "draft_policy_decision": params.get("draft_policy_decision"),
            # Phase 3 FilterBar 送來的物件/複數 filter key——需與 actions.py
            # 的 params dict 及 _TRAFFIC_FILTER_CAPABILITIES 的鍵名一致，
            # 否則會在這個 whitelist 被靜默丟棄，永遠到不了
            # build_traffic_query_spec / _flow_matches_filters。
            "src_labels": params.get("src_labels", []),
            "dst_labels": params.get("dst_labels", []),
            "ex_src_labels": params.get("ex_src_labels", []),
            "ex_dst_labels": params.get("ex_dst_labels", []),
            "src_iplist": params.get("src_iplist", ""),
            "src_iplists": params.get("src_iplists", []),
            "dst_iplist": params.get("dst_iplist", ""),
            "dst_iplists": params.get("dst_iplists", []),
            "ex_src_iplists": params.get("ex_src_iplists", []),
            "ex_dst_iplists": params.get("ex_dst_iplists", []),
            "src_workloads": params.get("src_workloads", []),
            "dst_workloads": params.get("dst_workloads", []),
            "ex_src_workloads": params.get("ex_src_workloads", []),
            "ex_dst_workloads": params.get("ex_dst_workloads", []),
            "any_iplist": params.get("any_iplist", ""),
            "any_workload": params.get("any_workload", ""),
            "ex_any_iplist": params.get("ex_any_iplist", ""),
            "ex_any_workload": params.get("ex_any_workload", ""),
        }
        query_spec = self.api.build_traffic_query_spec(query_filters)
        draft_pd_filter = (query_spec.report_only_filters.get("draft_policy_decision") or "").strip().lower()
        needs_draft = (bool(draft_pd_filter)
                       or getattr(query_spec, "requires_draft_pd", False)
                       or bool(params.get("requires_draft_pd", False)))

        # When filtering by draft policy decision, always query all reported PDs
        # because the draft EB may affect flows whose reported PD is "allowed".
        query_pds = pds if not needs_draft else ["blocked", "potentially_blocked", "allowed"]

        # label_groups 類 key 無法在 client 端比對（成員展開只在 PCE 端）——
        # 帶這些 filter 時不可使用 cache（cache 資料未過濾），強制走 API。
        cache_bypass_keys = [
            k for k in _CACHE_UNEVALUABLE_FILTER_KEYS if query_filters.get(k)
        ]
        traffic_stream, self.last_query_source = self._fetch_query_flows(
            start_time, end_time, query_pds, query_spec, needs_draft,
            cache_bypass_keys=cache_bypass_keys,
        )
        if not traffic_stream:
            self._raise_if_query_fetch_failed()
            return []

        search_query = str(query_spec.report_only_filters.get("search", "") or "").lower()

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        try:
            start_dt = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        except (ValueError, TypeError):
            start_dt = now_dt - datetime.timedelta(minutes=30)
            
        matches = []
        sort_by = query_spec.report_only_filters.get("sort_by", "bandwidth")
        rule = {**query_spec.native_filters, **query_spec.fallback_filters}
        rule["type"] = sort_by if sort_by in ["bandwidth", "volume"] else "connections"
        rule["pd"] = -1

        # 殘餘比對分工（legacy scalar key 走 check_flow_match、物件/複數 key
        # 委派報表路徑同一套比對器 _flow_matches_filters，同 key OR、跨 key
        # AND，與 native 語意一致）統一由 _match_flow_filters 處理——cache
        # 命中時 PCE 未過濾，這是唯一的 client 端過濾。
        for f in traffic_stream:
            if strict_pd and f.get("policy_decision") not in strict_pd:
                continue

            if draft_pd_filter and (f.get("draft_policy_decision") or "").lower() != draft_pd_filter:
                continue

            if not self._match_flow_filters(rule, f, start_dt):
                continue


            src = f.get('src', {})
            dst = f.get('dst', {})
            svc = f.get('service', {})

            s_name = src.get('workload', {}).get('name') or src.get('ip', 'N/A')
            d_name = dst.get('workload', {}).get('name') or dst.get('ip', 'N/A')
            port = svc.get('port', 'All') or f.get('dst_port', 'All')

            # Detailed Attribution
            # process_name / user_name come from the service object (source-side VEN telemetry)
            # They do NOT live in src or dst objects
            svc_proc = (svc.get('process_name') or "").lower()
            svc_user = (svc.get('user_name') or "").lower()
            svc_name = (svc.get("name") or "").lower()

            if search_query:
                s_ip = str(src.get('ip', '')).lower()
                d_ip = str(dst.get('ip', '')).lower()

                matches_search = (
                    search_query in s_name.lower() or
                    search_query in d_name.lower() or
                    search_query in s_ip or
                    search_query in d_ip or
                    search_query == str(port).lower() or
                    search_query in svc_proc or
                    search_query in svc_user or
                    search_query in svc_name
                )
                
                if not matches_search:
                    continue

            f_copy = f.copy()
            
            # Format Protocol Name
            proto = f.get('proto') or svc.get('proto', '')
            try:
                p_int = int(proto)
                if p_int == 6: proto = "TCP"
                elif p_int == 17: proto = "UDP"
                elif p_int == 1: proto = "ICMP"
            except (ValueError, TypeError): pass  # intentional fallback: leave proto as raw string if not parseable

            # Determine process/user attribution via flow_direction:
            # - "inbound"  → captured by dst VEN → belongs to dst
            # - "outbound" → captured by src VEN → belongs to src
            svc_proc = svc.get('process_name') or ""
            svc_user = svc.get('user_name') or ""
            flow_dir = (f.get('flow_direction') or "").lower()
            if flow_dir == "inbound":
                src_proc, src_user = "", ""
                dst_proc, dst_user = svc_proc, svc_user
            elif flow_dir == "outbound":
                src_proc, src_user = svc_proc, svc_user
                dst_proc, dst_user = "", ""
            else:
                # Unknown direction: surface in service cell as fallback
                src_proc, src_user = "", ""
                dst_proc, dst_user = "", ""

            f_copy['source'] = {
                "name": s_name,
                "ip": src.get('ip'),
                "href": src.get('workload', {}).get('href'),
                "labels": src.get('workload', {}).get('labels', []),
                "process": src_proc,
                "user": src_user,
            }
            f_copy['destination'] = {
                "name": d_name,
                "ip": dst.get('ip'),
                "href": dst.get('workload', {}).get('href'),
                "labels": dst.get('workload', {}).get('labels', []),
                "process": dst_proc,
                "user": dst_user,
            }
            f_copy['service'] = {
                "port": port,
                "proto": proto,
                "name": svc.get("name") or getattr(svc, 'name', '') or f.get("sn") or "",
                # Fallback: surface process/user in service cell when direction unknown
                "process": svc_proc if not flow_dir else "",
                "user": svc_user if not flow_dir else "",
            }

            bw_val, bw_note, _, _ = self.calculate_mbps(f)
            vol_val, vol_note = self.calculate_volume_mb(f)
            conn_val = _safe_int(f.get("num_connections") or f.get("count", 1))

            if rule["type"] == "bandwidth":
                f_copy['_metric_val'] = bw_val
            elif rule["type"] == "volume":
                f_copy['_metric_val'] = vol_val
            else:
                f_copy['_metric_val'] = conn_val
                
            f_copy["max_bandwidth_mbps"] = bw_val
            f_copy["total_volume_mb"] = vol_val
            f_copy["total_connections"] = conn_val
            
            f_copy["formatted_bandwidth"] = f"{format_unit(bw_val, 'bandwidth')} {bw_note}".strip()
            f_copy["formatted_volume"] = f"{format_unit(vol_val, 'volume')} {vol_note}".strip()
            f_copy["formatted_connections"] = f"{conn_val}"
            
            ts = f.get('timestamp_range', {})
            f_copy["first_seen"] = ts.get('first_detected')
            f_copy["last_seen"] = ts.get('last_detected')
            f_copy["policy_decision"] = f.get("policy_decision")

            matches.append(f_copy)

        self._raise_if_query_fetch_failed()

        matches.sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
        total = len(matches)
        # 截斷統計：仿 ApiClient.last_traffic_query_diagnostics 的屬性樣式，
        # 回傳型別不變、既有呼叫者零影響（spec §11.3）
        self.last_query_stats = {
            "total_matches": total,
            "cap": QUERY_RESULT_CAP,
            "truncated": total > QUERY_RESULT_CAP,
        }
        return matches[:QUERY_RESULT_CAP]

    def run_debug_mode(self, mins: int | None = None, pd_sel: int | None = None, interactive: bool | None = None) -> None:
        # Interactive debug REPL: stdout is the contract here. The CLI menu
        # streams it to the user; the GUI debug API captures it via
        # redirect_stdout. Keep print() (do not swap to logger).
        print(f"\n{Colors.HEADER}{t('debug_mode_title')}{Colors.ENDC}")

        # Auto-detect minutes if not provided
        max_win = 10
        for r in self.cm.config['rules']:
            w = r.get('threshold_window', 10)
            if w > max_win:
                max_win = w

        if mins is None:
            mins_input = safe_input(t('query_past_mins'), int, allow_cancel=True)
            if mins_input is None:  # user pressed 0 to go back
                return
            if mins_input == '' or mins_input == 0:  # user pressed Enter or typed 0 → use default
                mins = max_win + 2
            else:
                mins = int(mins_input)

        now = datetime.datetime.now(datetime.timezone.utc)
        start_dt = now - datetime.timedelta(minutes=mins)
        start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

        # 1. Fetch Events
        print(f"\n{Colors.CYAN}[1/2] {t('checking_events')}...{Colors.ENDC}")
        events = self.api.fetch_events(start_str)
        print(f"  -> {t('found_events', count=len(events))}")

        # 2. Fetch Traffic
        print(f"\n{Colors.CYAN}[2/2] {t('submitting_query', start=start_dt.strftime('%H:%M'), end=now.strftime('%H:%M'))}{Colors.ENDC}")

        # Determine PDs for traffic query
        if pd_sel is None:
            print(f"\n{t('policy_decision')}")
            print(f"1. {t('pd_1_blocked_only', default='Blocked Only')}")
            print(f"2. {t('pd_2_allowed_only', default='Allowed Only')}")
            print(f"3. {t('pd_3_all', default='All (Blocked + Potential + Allowed)')} [{t('nav_default', default='Default')}]")
            pd_input = safe_input(t('please_select'), int, range(0, 4), allow_cancel=True)
            if pd_input is None: return  # user pressed 0 to go back
            if pd_input == '' or pd_input == 0:
                pd_sel = 3  # default: All
            else:
                pd_sel = int(pd_input)

        pds = ["blocked", "potentially_blocked", "allowed"]
        if pd_sel == 1: pds = ["blocked"]
        elif pd_sel == 2: pds = ["allowed"]

        traffic_gen = self.api.execute_traffic_query_stream(start_str, end_str, pds)
        traffic = list(traffic_gen) if traffic_gen else []
        print(f"  -> {t('fetched_records', count=len(traffic), mins=mins)}")

        print(f"\n{Colors.HEADER}{t('simulation_report')}{Colors.ENDC}")

        for rule in self.cm.config["rules"]:
            rtype = rule.get("type", "event")
            if rtype == "event":
                r_label = t('event_rule')
            elif rtype == "system":
                r_label = t('gui_system_health_type', default='System Rule')
            else:
                r_label = t('traffic_rule')
            print(f"\n{Colors.CYAN}--- {r_label}: {rule['name']} ({rtype.upper()}) ---{Colors.ENDC}")
            
            rule_win = rule.get("threshold_window", 10)
            rule_start = now - datetime.timedelta(minutes=rule_win)
            matches = []

            if rtype == "event":
                # Event Logic
                for e in events:
                    # Time check for events
                    pts = e.get('timestamp')
                    e_time = None
                    if pts:
                        try: e_time = datetime.datetime.strptime(pts, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
                        except ValueError:
                            try: e_time = datetime.datetime.strptime(pts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                            except ValueError: pass  # intentional fallback: e_time stays None, event is not time-filtered

                    if e_time and e_time < rule_start: continue

                    if not matches_event_rule(rule, e):
                        continue

                    matches.append(e)
                
                print(t('time_filter_results', total=len(events), win=rule_win, rem=len(matches)))
                val: float = len(matches)
                threshold = float(rule.get("threshold_count", 1))
                is_trigger = val >= threshold

                status = f"{Colors.FAIL}{t('would_trigger')}{Colors.ENDC}" if is_trigger else f"{Colors.GREEN}{t('pass')}{Colors.ENDC}"
                print(t('eval_result', status=status, threshold=int(threshold)))

                if matches:
                    print(t('samples_top10'))
                    for i, m in enumerate(matches[:10]):
                        parsed = normalize_event(m)
                        msg = parsed.get('action') or m.get('message', 'No message')
                        actor = parsed.get('actor') or m.get('created_by', {}).get('user', {}).get('username', '')
                        target = parsed.get('target_name') or ''
                        m_status = m.get('status', 'N/A')
                        m_ts = m.get('timestamp', 'N/A')[-13:-1] # Show HH:MM:SS.ms
                        context = f" | {actor}" if actor else ""
                        if target:
                            context += f" -> {target}"
                        print(f"     [{i+1}] {m_ts} | {m_status}{context} | {msg[:80]}")

            elif rtype == "system":
                health_type = rule.get("filter_value", "pce_health")
                h_status = None
                h_msg = ""
                if health_type == "pce_health" and hasattr(self.api, "check_health"):
                    h_status, h_msg = self.api.check_health()
                is_trigger = h_status not in (200, "200")
                threshold = float(rule.get("threshold_count", 1))
                status = f"{Colors.FAIL}{t('would_trigger')}{Colors.ENDC}" if is_trigger else f"{Colors.GREEN}{t('pass')}{Colors.ENDC}"
                print(f"  -> {t('checking_health')}")
                print(f"  -> {t('rule_health_check')}: {health_type}")
                print(f"  -> {t('health_status')}: {h_status if h_status is not None else 'N/A'}")
                print(t('eval_result', status=status, threshold=int(threshold)))
                if h_msg:
                    print(f"  -> {t('health_details')}: {h_msg[:200]}")

            else:
                # Traffic / BW / Vol Logic
                for f in traffic:
                    if self._match_flow_filters(rule, f, rule_start):
                        f_copy = f.copy()
                        if rtype == "bandwidth":
                            v, note, _, _ = self.calculate_mbps(f)
                            f_copy['_metric_val'] = v
                            f_copy['_metric_fmt'] = f"{format_unit(v, 'bandwidth')} {note}"
                        elif rtype == "volume":
                            v, note = self.calculate_volume_mb(f)
                            f_copy['_metric_val'] = v
                            f_copy['_metric_fmt'] = f"{format_unit(v, 'volume')} {note}"
                        else:
                            c = _safe_int(f.get("num_connections") or f.get("count", 1))
                            f_copy['_metric_val'] = c
                            f_copy['_metric_fmt'] = str(c)
                        matches.append(f_copy)

                print(t('time_filter_results', total=len(traffic), win=rule_win, rem=len(matches)))
                val = 0.0
                if rtype == "bandwidth":
                    val = max([m['_metric_val'] for m in matches]) if matches else 0.0
                    print(t('calc_max_bw', val=val))
                elif rtype == "volume":
                    val = sum([m['_metric_val'] for m in matches])
                    print(t('calc_sum_vol', val=val))
                else:
                    val = sum([m['_metric_val'] for m in matches])
                    print(t('calc_sum_count', val=int(val)))

                threshold = float(rule.get("threshold_count", 0))
                is_trigger = val > threshold if rtype == "bandwidth" else val >= threshold

                status = f"{Colors.FAIL}{t('would_trigger')}{Colors.ENDC}" if is_trigger else f"{Colors.GREEN}{t('pass')}{Colors.ENDC}"
                print(t('eval_result', status=status, threshold=threshold))

                if matches:
                    print(t('samples_top10'))
                    if rtype in ["bandwidth", "volume"]:
                        matches.sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
                    for i, m in enumerate(matches[:10]):
                        key = self.get_traffic_details_key(m)
                        print(f"     [{i+1}] {key} {t('alert_field_metric_value')}: {m.get('_metric_fmt')} (PD:{m.get('policy_decision')})")

        if interactive is None:
            interactive = not hasattr(sys.stdout, 'getvalue')

        if interactive:
            save_sel = safe_input(f"\n{t('save_debug_query')}", str, allow_cancel=True)
            if save_sel and save_sel.lower() == 'y':
                dump = {
                    "timestamp": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "mins": mins,
                    "events_count": len(events),
                    "traffic_count": len(traffic),
                    "events": events,
                    "traffic": traffic
                }
                path = os.path.join(ROOT_DIR, "debug_dump.json")
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(dump, f, indent=2, ensure_ascii=False)
                print(f"\n{Colors.GREEN}{t('file_saved', path=path)}{Colors.ENDC}")

        if interactive:
            print(f"\n{Colors.GREEN}{t('debug_done')}{Colors.ENDC}")
