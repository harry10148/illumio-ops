from __future__ import annotations

import datetime
import functools
import heapq
import ipaddress
import json
import gc
import os
import sys
import threading
from dataclasses import dataclass
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
from src.report.cache_support import resolve_data_source
# flow 上的三個累計計數器 (bytes_out, bytes_in, conn_count)。ingest 端存進
# 觀測表的值必須與 analyzer 算出的當下值取自同一組欄位，否則相減毫無意義
# ——因此只准有一份實作。
from src.pce_cache.flow_deltas import cumulative_metrics as _cumulative_metrics

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
# threshold_window 上限（分鐘）：history 保留隨最大 count 視窗動態延長至此上限，
# 超過即在輸入層拒絕——否則視窗被 prune 靜默低估（2026-07-24 審查 A3）
MAX_THRESHOLD_WINDOW_MINUTES = 1440

WATCHDOG_FAILURE_THRESHOLD = 3
WATCHDOG_COOLDOWN_MINUTES = 60

# Meta-alert cooldown for event polling overflow: when the sync events API
# hits max_results it returns only the newest rows, so older events in the
# window are permanently lost. Own cooldown keeps a persistent burst source
# to one alert per hour instead of one per cycle.
OVERFLOW_ALERT_COOLDOWN_MINUTES = 60

# cache 路徑單次視窗查詢的列數上限。超過即代表視窗內「最舊」的列被丟掉
# （CacheSubscriber.fetch_window_rows 是 last_detected DESC + LIMIT），
# threshold 加總會低估——不可只留一行 log，必須升級成 meta-alert（同
# event_overflow / traffic_overflow 的處理方式）。
TRAFFIC_WINDOW_ROW_LIMIT = 10000

# save_state() 的白名單：只有這些 key 由 Analyzer 自己的 cycle 擁有，才可以
# 用 self.state（cycle 起始時的快照）覆蓋磁碟。state.json 是多寫入者共用的
# 單一檔案（report_scheduler / rule_scheduler / GUI adhoc jobs / async_query
# jobs / Reporter DLQ 與 dispatch 記錄 / ingest jobs 各自 update_state_file），
# 舊版用「黑名單」列舉少數共用 key、其餘整包覆蓋，等於每新增一個外部 key
# 就靜默回滾它在本 cycle 期間的寫入（重複寄出排程報表、adhoc job 消失、
# dispatch 稽核列不見）。白名單讓未知的新 key 預設安全。
# event_timeline 不在此列：它由 Analyzer 與 Reporter 同時附加，走 append 合併
# （見 _merge）。pce_stats / watchdog_last_alert_at / event_overflow 亦另行處理
# （dirty flag）。
_ANALYZER_OWNED_STATE_KEYS = (
    "last_check",
    "event_watermark",
    "history",
    "alert_history",
    "event_seen",
    "unknown_events",
    "event_parser_stats",
    "event_parser_samples",
    "throttle_state",
    "overflow_last_alert_at",
    "traffic_overflow_last_alert_at",
    "window_truncation",
    "window_truncation_last_alert_at",
    "basis_mismatch",
    "basis_mismatch_last_alert_at",
)

# record_local_read()/record_event_batch() 在純 cache-read cycle 寫入的
# pce_stats 欄位。這些欄位的擁有者是本 cycle（dashboard 顯示用），必須逐欄
# 覆蓋到磁碟；其餘欄位（consecutive_failures/last_success/health_*）在沒有
# 真正 PCE 探測時屬於排程 ingest job，要讓給磁碟值。
_PCE_STATS_LOCAL_FIELDS = (
    "event_poll_status",
    "last_event_poll",
    "last_error",
    "last_error_stage",
    "last_batch_total",
    "last_batch_unknown",
    "last_batch_notes",
    "last_batch_overflow",
)

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
    # actor groups / ams 為 PCE native-only：兩套 client 比對器
    # （check_flow_match、_flow_matches_filters）都不評估——帶這些 key 時
    # cache 命中會靜默回未過濾資料（2026-07-24 審查 M4）
    "src_include_groups", "dst_include_groups",
    "src_ams", "dst_ams", "ex_src_ams", "ex_dst_ams",
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort ``float()``: mirror of _safe_int for the byte/duration
    fields. A non-numeric value (e.g. dst_tbi='1,234' from a hand-edited
    archive or an odd PCE build) must not raise out of the per-flow hot loop
    and abort the whole monitor cycle.
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def rule_enabled(rule: dict[str, Any]) -> bool:
    """規則的啟用旗標。GUI/CLI 會寫入 ``enabled=False`` 代表停用；缺欄位
    （既有規則）一律視為啟用。語意對齊前端 rules.js 的 ``r.enabled !== false``。

    **所有規則挑選點都必須經過這裡過濾**——少一處，操作者關掉的規則就照樣
    告警，而 UI/CLI 仍顯示為停用。
    """
    return rule.get("enabled", True) is not False


# 任一 byte 遙測欄位存在與否：PCE 未開 Enhanced Data Collection 時 flow 完全
# 不帶 byte 欄，volume/bandwidth 一律算出 0——與「真的沒有流量」無法區分。
_BYTE_FIELD_KEYS = (
    "dst_dbo", "dbo", "dst_dbi", "dbi",
    "dst_tbo", "tbo", "dst_bo", "dst_tbi", "tbi", "dst_bi",
)


def flow_has_byte_fields(flow: dict[str, Any]) -> bool:
    """該 flow 是否帶有任何 byte 遙測欄位（見 _BYTE_FIELD_KEYS）。呼叫端據此
    在 cycle 層級（非逐 flow）記一次警告，避免「量測到 0」與「沒有量測」被
    當成同一件事。"""
    return any(flow.get(k) is not None for k in _BYTE_FIELD_KEYS)


# ─── Bucket-basis guard（聚合基準守門）───────────────────────────────────────
#
# 真機事實（2026-07-25，對同一批 flow 分別以 5 / 30 / 120 分鐘視窗查詢比對）：
# PCE 把 flow 聚合成「日」級 bucket，回傳的 dst_b*/num_connections 是**整個
# bucket 的累計值，不會裁切到查詢視窗**——三個視窗拿到完全相同的
# dst_bo/dst_bi/num_connections，且 first_detected 一律落在當日午夜。
#
# 後果：check_flow_match 只看 last_detected 在不在視窗內，所以 flow 會被收下，
# 但它帶的量是整個 bucket 的。threshold_window=10 分鐘的規則在 08:27 評估時，
# 等於拿 8.5 小時的累計量去比 10 分鐘的門檻——誤報幅度隨當日時間推移放大、
# 午夜歸零。traffic（num_connections）、bandwidth、volume 三型全中。
#
# Phase 1（守門）的處置：偵測到「flow 的聚合區間起點早於規則視窗起點」時，
# 該規則本 cycle 不告警，並以 WARNING + meta-alert 讓操作者知道規則沒被評估
# ——沉默比誤報更糟，操作者絕不可以以為規則還在保護他。
#
# Phase 2（視窗增量）：traffic ingest 每跑一次就把每筆 flow 當下的三個累計
# 計數器記進 pce_traffic_flow_obs（src/pce_cache/flow_deltas.py）。規則評估
# 時取「視窗起點之前最近的一筆觀測」當基準，value(now) - value(baseline)
# 就是真正落在視窗內的量，於是短視窗規則可以正常評估。守門只保留在推導不
# 出增量的殘餘情況：沒有 cache／沒有基準（flow 第一次出現）／基準太舊
# （ingest 間隔遠大於視窗）／計數器歸零。
#
# 兩個必然的近似，都是刻意選擇：
#   1. 基準只能落在「視窗起點之前最近的一次 ingest」，所以增量涵蓋的區間
#      是視窗的**超集**（多算 window_start - baseline_at 這段）。多算會讓
#      告警偏積極而非偏沉默，但不能無上限——超出 DELTA_BASELINE_TOLERANCE
#      就判定推導不出、退回守門，並在 log 裡指出要調小 ingest 間隔。
#   2. 增量算不出負數：計數器歸零（PCE 換 bucket）時 t2 - t1 為負，那是
#      歸零不是負流量。無法得知歸零落在視窗內或視窗前，因此不猜——退回守門
#      （下一次 ingest 就會在新 bucket 內留下基準，訊號自癒）。

# 視窗增量的量測基準註記（比照 calculate_mbps/calculate_volume_mb 的
# "(Interval)"/"(Total)"/"(Avg)"）：值來自兩次 cache 觀測相減。
DELTA_BASIS_NOTE = "(Window)"

# 基準時間可以早於視窗起點多久：取 max(視窗長度 × 比例, 下限秒數)。
# 超過就代表增量涵蓋的區間比視窗長太多、失去「短視窗」的意義。
DELTA_BASELINE_TOLERANCE_RATIO = 0.25
DELTA_BASELINE_MIN_TOLERANCE_SECONDS = 60.0


@dataclass(frozen=True)
class WindowDelta:
    """一筆 flow 在規則視窗內的實際增量（由兩次 cache 觀測相減得出）。

    span_seconds 是增量真正涵蓋的秒數（now - baseline_at），一定 >= 視窗長度；
    bandwidth 用它當分母才不會把「多算的那段」算成更高的速率。
    """
    bytes_total: float
    conn: int
    span_seconds: float
    baseline_at: datetime.datetime

    @property
    def mbps(self) -> float:
        return (self.bytes_total * 8.0) / self.span_seconds / 1_000_000.0

    @property
    def volume_mb(self) -> float:
        return self.bytes_total / 1024 / 1024



def _format_delta_reasons(reasons: Counter) -> str:
    """把「推導不出視窗增量」的原因計數整理成一行可讀字串。"""
    return ", ".join(f"{k}={v}" for k, v in sorted(reasons.items()))


def flow_aggregation_start(flow: dict[str, Any]) -> datetime.datetime | None:
    """flow 聚合區間的起點（PCE ``timestamp_range.first_detected``）。

    cache 列與 API 回傳都可能把它放在頂層或巢狀 timestamp_range 下（比照
    ``src/pce_cache/ingestor_traffic._ts``），兩處都認。欄位缺漏或無法解析時
    回 None——呼叫端必須據此**放行**，不可以把「沒有證據」當成違規證據。
    """
    ts = flow.get("first_detected")
    if not ts:
        tr = flow.get("timestamp_range")
        ts = tr.get("first_detected") if isinstance(tr, dict) else None
    if not ts:
        return None
    return parse_event_timestamp(str(ts))


def calculate_mbps(flow: dict[str, Any]) -> tuple[float, str, float, float]:
    """
    Compute bandwidth in Mbps from a PCE traffic flow record.
    Priority 1: delta bytes (dst_dbo+dst_dbi) / ddms  → Mbps (Interval)
    Priority 2: total bytes (dst_tbo+dst_tbi) / tdms   → Mbps (Avg)
                — when tdms is absent the denominator is an assumed sampling
                  interval, so the basis is reported as (Avg est.)
    Fallback:   returns (0.0, '', 0.0, 0.0)

    Importable independently:
        from src.analyzer import calculate_mbps
    """
    delta_bytes = _safe_float(flow.get("dst_dbo") or flow.get("dbo") or 0) + \
                  _safe_float(flow.get("dst_dbi") or flow.get("dbi") or 0)
    ddms = _safe_float(flow.get("ddms") or 0)

    if delta_bytes > 0 and ddms > 0:
        if ddms < 1000:
            ddms = 1000.0
        val = (delta_bytes * 8.0) / (ddms / 1000.0) / 1000000.0
        return val, "(Interval)", delta_bytes, ddms

    tbo = _safe_float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
    tbi = _safe_float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
    total_bytes = tbo + tbi
    tdms = _safe_float(flow.get("tdms") or 0)
    note = "(Avg)"
    if tdms <= 0:
        # 缺 tdms：只能用 PCE 提供的取樣間隔（無則假設 600s）當分母。分子是
        # 「flow 存活至今的累積量」、分母是「一個取樣間隔」，算出來的速率並非
        # 真實發生過的速率——note 標為 (Avg est.) 讓操作者看得出分母是推估的。
        tdms = _safe_float(flow.get("interval_sec", 600)) * 1000
        note = "(Avg est.)"
    elif tdms < 1000:
        # 真實但不足 1 秒的持續時間：比照 delta 分支往上夾到 1000ms，不可
        # 換成 600 秒——那會把 80 Mbps 的短連線報成 0.07 Mbps（1200 倍低估）
        tdms = 1000.0
    if total_bytes > 0 and tdms > 0:
        val = (total_bytes * 8.0) / (tdms / 1000.0) / 1000000.0
        return val, note, total_bytes, tdms
    return 0.0, "", 0.0, 0.0

def calculate_volume_mb(flow: dict[str, Any]) -> tuple[float, str]:
    """
    Compute data volume in MB from a PCE traffic flow record.
    Priority 1: delta bytes (dst_dbo+dst_dbi)  → MB (Interval)
    Priority 2: total bytes (dst_tbo+dst_tbi)  → MB (Total)

    Importable independently:
        from src.analyzer import calculate_volume_mb
    """
    delta_bytes = _safe_float(flow.get("dst_dbo") or flow.get("dbo") or 0) + \
                  _safe_float(flow.get("dst_dbi") or flow.get("dbi") or 0)
    if delta_bytes > 0:
        return delta_bytes / 1024 / 1024, "(Interval)"
    tbo = _safe_float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
    tbi = _safe_float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
    return (tbo + tbi) / 1024 / 1024, "(Total)"

QUERY_RESULT_CAP = 500  # query_flows 單次回傳上限（截斷需回報，不可無聲）

# 分析 cycle 序列化：Analyzer.save_state 的 _merge 假設同時只有一個 cycle
# 在跑（analyzer 自有 key 是整包覆蓋）——併發 cycle 互相蓋掉 alert_history/
# history 會造成重複告警或計數錯亂。`--monitor-gui` 下 APScheduler 的
# run_monitor_cycle 與 GUI 的 /api/actions/run|debug 在同一行程的不同 thread，
# 因此鎖住在 Analyzer 所在模組、兩側共用；只放在 GUI 側等於沒防到排程器。
# 一併涵蓋 run_debug_mode：它用 contextlib.redirect_stdout 換 process 全域
# stdout，與併發分析的 print 會互相污染。
analysis_lock = threading.Lock()

# ─── Analyzer Class ───────────────────────────────────────────────────────────

class Analyzer:
    def __init__(self, config_manager: Any, api_client: IApiClient, reporter: IReporter,
                 subscriber_events: Any = None, subscriber_flows: Any = None,
                 cache_reader: Any = None, flow_delta_reader: Any = None) -> None:
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
        # 視窗增量（phase 2，見模組上方「Bucket-basis guard」與
        # src/pce_cache/flow_deltas.py）。None 時規則引擎完全退回 phase-1 守門。
        self._delta_reader: Any = flow_delta_reader
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
        # overlap 可調（events.overlap_seconds，預設 300、夾 [60, 900]）：
        # PCE 事件索引延遲的唯一補抓保險（2026-07-24 審查 D1）
        _overlap_cfg = None
        try:
            _overlap_cfg = (self.cm.config.get("events") or {}).get("overlap_seconds")
        except Exception:
            _overlap_cfg = None
        self.event_poller = EventPoller(
            self.api, subscriber=subscriber_events,
            overlap_seconds=_overlap_cfg if _overlap_cfg is not None else None,
        )
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
        # Set True when this cycle wrote the dashboard-facing pce_stats fields
        # through StatsTracker.record_local_read/record_event_batch (a pure
        # cache read). Those fields must reach disk even when _pce_stats_dirty
        # stays False, otherwise a failed cache event poll is recorded and then
        # thrown away by the merge, leaving the dashboard "Event Poll" card
        # green while event analysis is dead.
        self._pce_stats_local_dirty = False
        # event_overflow 與排程器的 events ingest job 共同擁有（cache 部署上
        # 只有 run_events_ingest 看得到 PCE 端的截斷，見 jobs._record_event_overflow）。
        # 只有本 cycle 真的寫過這個 key（legacy pull 的 _fetch_event_batch，或
        # cache 分支清掉 legacy 殘留）才可以把記憶體值落盤；否則整包覆蓋會把
        # ingest job 剛寫的訊號用 cycle 起始快照靜默回滾（＝訊號永遠不發告警）。
        self._event_overflow_dirty = False
        # event_timeline is co-owned: the Reporter appends dispatch rows from
        # its own update_state_file call. Keep the load-time entries (and their
        # identities) so save_state can append ONLY this cycle's new entries on
        # top of whatever is on disk now, instead of overlaying a stale list.
        # The list reference is retained deliberately: it keeps the baseline
        # entry objects alive so their id() values cannot be recycled.
        self._timeline_baseline: list = self.state.get("event_timeline") or []
        self._timeline_baseline_ids = {id(e) for e in self._timeline_baseline}

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

        # history 保留期跟著最大 count 視窗走（下限 2h、上限 24h＋10min 緩衝），
        # 否則 >2h 的 threshold_window 會被裁剪靜默低估（2026-07-24 審查 A3）
        try:
            _max_win = max(
                (int(r.get("threshold_window", 10))
                 for r in self.cm.config.get("rules", [])
                 if r.get("type") == "event" and r.get("threshold_type") == "count"),
                default=0,
            )
        except (TypeError, ValueError):
            _max_win = 0
        _max_win = min(_max_win, MAX_THRESHOLD_WINDOW_MINUTES)
        cutoff = now - datetime.timedelta(minutes=max(120, _max_win + 10))
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

        # alert_history 只對「還存在的規則」有意義。刪除規則後殘留的冷卻時戳
        # 會永久累積，並在 id 被回收時（載入最佳實踐規則用連號整數 id）誤壓
        # 新規則的第一則告警。規則清單讀不到／為空時完全不清——設定載入異常
        # 時把冷卻狀態整包清掉會造成告警風暴。
        try:
            _live_rule_ids = {str(r.get("id")) for r in self.cm.config.get("rules", [])
                              if r.get("id") is not None}
        except (AttributeError, TypeError):
            _live_rule_ids = set()
        alert_history = self.state.get("alert_history")
        if _live_rule_ids and isinstance(alert_history, dict):
            for _stale_rid in [k for k in alert_history if k not in _live_rule_ids]:
                alert_history.pop(_stale_rid, None)

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
                # 白名單覆蓋（不是黑名單）：self.state 是 cycle 起始時載入的
                # 快照，state.json 卻是八個以上寫入者共用的單一檔案
                # （report_scheduler 的 report_schedule_states、rule_scheduler
                # 的 rule_schedule_states、GUI 的 adhoc_report_jobs、
                # api/async_jobs 的 async_query_jobs、Reporter 的 alert_dlq /
                # dispatch_history、ingest jobs 的 traffic_overflow / pce_stats、
                # dashboard 的 ven_summary / posture_summary…）。舊版
                # `merged.update(self.state)` 會把整份載入時的快照蓋回磁碟，
                # 只豁免少數列舉過的 key——任何沒被列舉到的外部 key（含未來
                # 新增的）都會被靜默回滾成 cycle 起始值，實測後果包含：排程
                # 報表的 last_run 倒退而重複寄送、adhoc job 記錄消失導致
                # /api/reports/jobs/<id> 回 404、dispatch 稽核列不見。
                # 因此改成只覆蓋 Analyzer 自己擁有的 key，未知的 key 預設安全。
                merged = dict(existing)
                for _k in _ANALYZER_OWNED_STATE_KEYS:
                    if _k in self.state:
                        merged[_k] = self.state[_k]
                # event_timeline: Analyzer（record_timeline）與 Reporter
                # （persist_dispatch_results）都會附加。整包覆蓋會吃掉本 cycle
                # 期間 Reporter 寫入的派送稽核列，整包讓給磁碟又會丟掉本 cycle
                # 自己記的 pce_error/rule_trigger——故採 append 合併：以磁碟值
                # 為底，只補上本 cycle 新增的項目，再套用同一個上限裁剪。
                _new_timeline = [e for e in self.state.get("event_timeline", [])
                                 if id(e) not in self._timeline_baseline_ids]
                if _new_timeline:
                    _timeline = list(existing.get("event_timeline", []))
                    _timeline.extend(_new_timeline)
                    merged["event_timeline"] = _timeline[-self.stats.timeline_limit:]
                # dispatch_history 完全由 Reporter 擁有（Analyzer 只在 prune
                # 時動到記憶體副本），一律讓給磁碟；磁碟上還沒有這兩個 key 時
                # 才用記憶體值建立初值，避免全新的 state.json 缺欄。
                for _k in ("event_timeline", "dispatch_history"):
                    if _k not in merged and _k in self.state:
                        merged[_k] = self.state[_k]
                # pce_stats: co-owned with the scheduler's ingest jobs, which
                # maintain pce_stats.consecutive_failures (the watchdog
                # counter) via the same StatsTracker shape on cache-ingest
                # deployments (jobs.py:_record_ingest_pce_result). This
                # cycle's in-memory pce_stats is only trustworthy as a whole
                # when this instance performed a real PCE probe this cycle
                # (record_pce_success/record_pce_error — health check or
                # legacy event pull, marked via self._pce_stats_dirty).
                # 否則逐欄合併：本 cycle 透過 record_local_read /
                # record_event_batch 寫的是「dashboard 顯示欄」，必須落盤
                # （否則 cache event poll 失敗被整包丟棄，面板永遠是綠的），
                # 其餘欄位讓給磁碟上 ingest job 累積的值（C1）。
                if self._pce_stats_dirty or "pce_stats" not in existing:
                    merged["pce_stats"] = self.state.get("pce_stats", {})
                else:
                    _disk_stats = existing["pce_stats"]
                    if self._pce_stats_local_dirty and isinstance(_disk_stats, dict):
                        _mem_stats = self.state.get("pce_stats", {}) or {}
                        _disk_stats = dict(_disk_stats)
                        for _f in _PCE_STATS_LOCAL_FIELDS:
                            if _f in _mem_stats:
                                _disk_stats[_f] = _mem_stats[_f]
                    merged["pce_stats"] = _disk_stats
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
                if self._watchdog_dirty or "watchdog_last_alert_at" not in existing:
                    if "watchdog_last_alert_at" in self.state:
                        merged["watchdog_last_alert_at"] = self.state["watchdog_last_alert_at"]
                # event_overflow: co-owned with the scheduler's events ingest
                # job (jobs._record_event_overflow). 同 watchdog 的判準——只有
                # 本 cycle 自己寫過才落盤，否則讓給磁碟，避免把 ingest job 在
                # 本 cycle 期間寫入的截斷訊號用載入時的快照蓋回去。
                if self._event_overflow_dirty or "event_overflow" not in existing:
                    if "event_overflow" in self.state:
                        merged["event_overflow"] = self.state["event_overflow"]
                return merged

            self.state = update_state_file(STATE_FILE, _merge)
        except (IOError, OSError) as e:
            # fail-loud：alert_history（冷卻時戳）只活在這個檔案裡，而呼叫端
            # 在 run_analysis() 返回後才 send_alerts()。若在這裡吞掉錯誤，
            # 告警照送但冷卻沒落盤，下個 cycle 會用全新 Analyzer 重讀舊檔、
            # 判定沒冷卻過，於是同一則告警每個 cycle（cache 部署 30 秒）重送
            # 一次。往上拋讓 run_monitor_cycle 略過 send_alerts 並把 job_health
            # 標成 error——抑制狀態必須 fail-closed。
            logger.error(f"Error saving state: {e}")
            raise

    def calculate_mbps(self, flow: dict[str, Any]) -> tuple[float, str, float, float]:
        """Delegate to module-level calculate_mbps(). See src.analyzer.calculate_mbps."""
        return calculate_mbps(flow)

    def calculate_volume_mb(self, flow: dict[str, Any]) -> tuple[float, str]:
        """Delegate to module-level calculate_volume_mb(). See src.analyzer.calculate_volume_mb."""
        return calculate_volume_mb(flow)

    def check_flow_match(self, rule: dict[str, Any], f: dict[str, Any], start_time_limit: datetime.datetime | None,
                         *, strict_window: bool = False) -> bool:
        # Dynamic Sliding Window Check
        if start_time_limit:
            ts_str = f.get("timestamp")
            if not ts_str and "timestamp_range" in f:
                ts_str = f["timestamp_range"].get("last_detected") or f["timestamp_range"].get("first_detected")

            f_time = None
            if ts_str:
                try:
                    f_time = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
                except ValueError:
                    try:
                        f_time = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    except ValueError:
                        f_time = None

            # strict_window（規則引擎加總路徑）fail-closed：無/不可解析時戳
            # 的 flow 不得計入門檻加總（2026-07-24 審查 A4）。query/報表路徑
            # （strict_window=False）維持舊語意——那些 flow 已由 SQL/上游過窗，
            # cache/archive 投影常無 timestamp 欄，fail-closed 會整批誤殺。
            if f_time is not None and f_time < start_time_limit:
                return False
            if f_time is None and strict_window:
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

    def _match_flow_filters(self, rule: dict[str, Any], f: dict[str, Any], window_start: datetime.datetime | None,
                            *, strict_window: bool = False) -> bool:
        """統一的 flow×filter 比對：legacy 純量 key 走 check_flow_match（含
        pd/時間窗/port/proto/list 形 IP），物件/複數 key 投影委派給報表路徑
        同一套 _flow_matches_filters（兩者 AND）。三個呼叫點共用：規則引擎、
        規則測試預覽、dashboard query_flows。label_groups 類 key 無 client-side
        成員展開——規則端點拒收、query_flows 走 cache-bypass；此處防禦性忽略
        （不影響比對結果）。此函式在 per-flow 熱迴圈內被逐筆呼叫，故不在此記
        debug log（會被洗版）；只有手改 alerts.json 繞過端點拒收才會走到這個
        分支，屬邊角情境。"""
        if not self.check_flow_match(rule, f, window_start, strict_window=strict_window):
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
                # 來源標記：cache 分支只清掉這一種（legacy/ad-hoc pull 的殘留），
                # 不可連 events ingest job 寫的訊號一起清（見 _run_event_analysis）。
                "source": "legacy_pull",
            }
        else:
            self.state["event_overflow"] = {}
        self._event_overflow_dirty = True
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

    def _select_rules(self, predicate: Any) -> list:
        """規則挑選的唯一入口——所有派送路徑都必須經過這裡。

        兩道共用的把關：
        1. ``enabled=False`` 的規則不得進入任何派送路徑。GUI 的每列開關與
           CLI 的 Enabled? 都寫得進這個欄位，引擎卻從來沒讀過，等於「關不掉」
           ——操作者以為靜音了，告警照樣送。
        2. 缺 ``id`` 的規則（手改 alerts.json 就會出現，Rule schema 只要求
           ``type``）以前會讓 ``{r['id']: ...}`` 直接 KeyError，連帶讓整個
           cycle（含已算好的事件告警、watermark 與 state 落盤）一起陣亡。改成
           略過並記一次 warning，比照 GUI 規則列表既有的防禦。
        """
        selected: list = []
        skipped_no_id = 0
        try:
            all_rules = self.cm.config.get("rules", []) or []
        except AttributeError:
            all_rules = []
        for r in all_rules:
            if not predicate(r):
                continue
            if not rule_enabled(r):
                continue
            if not r.get("id"):
                skipped_no_id += 1
                continue
            selected.append(r)
        if skipped_no_id:
            logger.warning(
                "Skipped {} alert rule(s) with no 'id' (hand-edited alerts.json?) — "
                "such a rule cannot be cooldown-tracked and would abort the whole cycle",
                skipped_no_id,
            )
        return selected

    def _run_health_check(self) -> bool:
        """Run the PCE health check if any system/pce_health rules are configured.

        Records stats and fires health alerts as needed. The analysis cycle
        always continues regardless of PCE health status; health failure is
        informational, not a gate.

        Returns:
            True always — no health-check rules configured (skipped) or check
            completed (passed or failed). False is reserved for future use.
        """
        pce_health_rules = self._select_rules(
            lambda r: r.get("type") == "system" and r.get("filter_value") == "pce_health")

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
                # /health 過再探官方 SLB 端點 /node_available（200/202=健康；
                # 404/502/連線失敗=節點不可服務——Illumio 官方判準）。Protocol
                # stub 可能沒實作此方法，缺就跳過。
                na_check = getattr(self.api, "check_node_available", None)
                na_status = None
                if callable(na_check):
                    na_status, _na_msg = na_check()
                if na_status is not None and na_status not in (200, 202):
                    logger.warning(f"PCE node_available check failed: HTTP {na_status}")
                    self.stats.record_pce_error(
                        "health", f"node_available: HTTP {na_status}", status=na_status)
                    self._pce_stats_dirty = True
                    for rule in pce_health_rules:
                        if self._check_cooldown(rule):
                            self.reporter.add_health_alert({
                                "time": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                                "rule": rule["name"],
                                "status": str(na_status),
                                "details": t('health_node_unavailable_details', status=na_status),
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
        # cache 視窗查詢截斷：fetch_window_rows 撞到列數上限時丟掉的是視窗內
        # 「最舊」的列，threshold 加總會低估、門檻告警可能漏發。原本只有一行
        # WARNING，操作者無從把「沒收到告警」與這件事連起來——升級成同一套
        # meta-alert 機制（自有 state key 與 cooldown key）。
        self._maybe_alert_single_overflow(
            state_key="window_truncation",
            cooldown_key="window_truncation_last_alert_at",
            rule_key="alert_window_truncation_rule",
            details_key="alert_window_truncation_details",
            log_label="Traffic window truncation",
        )
        # bucket-basis 守門觸發＝有規則本 cycle 根本沒被評估。只留一行 log 的話
        # 操作者無從得知「沒收到告警」其實是「規則沒在跑」——升級成同一套
        # meta-alert 機制（自有 state key 與 cooldown key）。
        self._maybe_alert_single_overflow(
            state_key="basis_mismatch",
            cooldown_key="basis_mismatch_last_alert_at",
            rule_key="alert_aggregation_basis_rule",
            details_key="alert_aggregation_basis_details",
            log_label="Traffic aggregation basis mismatch",
        )

    def _maybe_alert_single_overflow(
        self, *, state_key: str, cooldown_key: str, rule_key: str, details_key: str, log_label: str
    ) -> None:
        overflow = self.state.get(state_key) or {}
        if not overflow:
            # 事件已解除：清掉冷卻時戳，否則下一次「不同的」資料遺失事件會被
            # 前一次的時戳壓制到最多 OVERFLOW_ALERT_COOLDOWN_MINUTES 之久而
            # 完全不通知。與 watchdog 的作法一致（StatsTracker.record_pce_success
            # 在 PCE 復原時把 watchdog_last_alert_at 清成 None）。
            if self.state.get(cooldown_key):
                self.state[cooldown_key] = None
            return
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last = parse_event_timestamp(self.state.get(cooldown_key))
        if last and (now_utc - last).total_seconds() < OVERFLOW_ALERT_COOLDOWN_MINUTES * 60:
            return
        self.state[cooldown_key] = format_utc(now_utc)
        # overflow 類訊號的四個共用 placeholder，外加訊號 state 裡的所有純量
        # 欄位——讓後來的訊號（如 basis_mismatch）能用自己的 placeholder，而
        # 不必硬塞進 raw/cap/since/until 這四個語意不合的欄位。str.format 會
        # 忽略模板沒用到的 kwargs，故舊訊號逐位不變。
        details_kwargs: dict[str, Any] = {
            "raw": overflow.get("raw_count", "?"),
            "cap": overflow.get("max_results", "?"),
            "since": overflow.get("query_since", "?"),
            "until": overflow.get("query_until", "?"),
        }
        details_kwargs.update(
            {k: v for k, v in overflow.items() if isinstance(v, (str, int, float))}
        )
        self.reporter.add_health_alert({
            "time": now_utc.strftime('%Y-%m-%d %H:%M:%S'),
            "rule": t(rule_key),
            "status": "warning",
            "details": t(details_key, **details_kwargs),
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
        event_triggers: list = []
        events: list = []
        event_batch = None
        if self._sub_events is not None:
            # event_overflow 有兩個寫入者：legacy pull（_fetch_event_batch，
            # source=legacy_pull）與 cache 部署的 events ingest job
            # （jobs._record_event_overflow，source=cache_ingest）。GUI 的
            # 「立即執行」/debug 端點是不帶 subscriber 建構 Analyzer 的，因此在
            # cache 部署上也會走 legacy pull 而留下 event_overflow；沒有人清它
            # 的話，之後每個 cache cycle 都會依那筆陳舊紀錄每小時重發一次
            # 「事件永久漏失」告警。此處只清 legacy 來源（等同「本 cycle 的
            # cache 路徑沒有觀察到截斷」）——ingest 寫的訊號是 PCE 端真實的
            # 截斷觀測，清掉就等於把剛偵測到的資料遺失靜默吃掉。
            _ovf = self.state.get("event_overflow") or {}
            if _ovf and _ovf.get("source") != "cache_ingest":
                logger.info("Clearing stale event_overflow left by a legacy/ad-hoc event pull")
                self.state["event_overflow"] = {}
                self._event_overflow_dirty = True
            try:
                # processor=：at-least-once。cursor 只有在 batch 完成比對／
                # 告警建構後才前進；中途丟例外時 cursor 留在原地，下個 cycle
                # 重送這批列，而不是靜默跳過（cache 的 events ingestor 用
                # on_conflict_do_nothing，被跳過的列永遠不會再出現）。
                def _process(rows: list) -> None:
                    events.extend(rows)
                    event_triggers.extend(self._analyze_event_batch(rows, None))

                self._sub_events.poll_new_rows(limit=5000, processor=_process)
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
                self._pce_stats_local_dirty = True
            except Exception as e:
                logger.error(f"Cache event poll failed: {e}")
                logger.error(t('api_fetch_events_error', error=str(e)))
                self.stats.record_local_read("events", success=False, error=str(e))
                self._pce_stats_local_dirty = True
            return event_triggers

        try:
            events, event_batch = self._legacy_event_pull()
        except Exception as e:
            logger.error(f"Event polling failed; watermark preserved at {self.state.get('event_watermark')}: {e}")
            logger.error(t('api_fetch_events_error', error=str(e)))
            self.stats.record_pce_error("events", str(e))
            self._pce_stats_dirty = True

        return self._analyze_event_batch(events, event_batch)

    def _analyze_event_batch(self, events: list, event_batch: Any) -> list:
        """Normalise one batch of events, match every enabled event rule and
        dispatch the resulting alerts. Returns the trigger dicts.

        Split out of _run_event_analysis so the cache path can hand it to
        CacheSubscriber.poll_new_rows(processor=...) — the subscriber only
        advances its cursor after this returns without raising.
        """
        event_triggers: list = []
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
            self._pce_stats_local_dirty = True

            for rule in self._select_rules(lambda r: r.get("type") == "event"):
                matches = [e for e in events if matches_event_rule(rule, e)]

                is_count_rule = rule.get("threshold_type") == "count"
                # history 只有 count 型規則會讀回（_event_count_in_window）。
                # 以前每條 event 規則（含 immediate 型，佔最佳實踐目錄多數）
                # 都逐筆寫入，那些紀錄沒有任何讀者，卻要在每個 cycle 被
                # strptime 重新解析、跟著整份 state.json 重新序列化＋fsync，
                # 而 state.json 的鎖是全域共用的。改成只有 count 型才記錄。
                # 代價：規則從 immediate 改成 count 後視窗要重新累積。
                if matches and is_count_rule:
                    self._record_event_matches(rule["id"], matches, now_utc)

                # Check Threshold
                count_val = len(matches)
                if is_count_rule:
                    win_minutes = rule.get("threshold_window", 10)
                    win_start = now_utc - datetime.timedelta(minutes=win_minutes)
                    count_val = self._event_count_in_window(rule["id"], win_start)

                # count 型須有本 cycle 新事件（matches 非空）才告警：視窗計數
                # 只作門檻；無新證據時發出的告警必然是 time=N/A 的空殼
                # （2026-07-24 審查 A2）
                if count_val >= _safe_float(rule.get("threshold_count", 1)) and count_val > 0 and matches:
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

    def _legacy_fetch_traffic(self, tr_rules: list | None = None) -> tuple[Any, datetime.datetime]:
        """Fetch traffic from the PCE API (legacy path used when no cache subscriber).

        tr_rules 由 _fetch_traffic 傳入（已套用啟用旗標與 id 把關）——不可在
        這裡重新掃 cm.config['rules']，否則停用的規則仍會撐大查詢視窗。
        """
        logger.warning(
            "[deprecated] _legacy_fetch_traffic called — pce_cache path should be "
            "preferred; remove after pce_cache.enabled becomes the default."
        )
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if tr_rules is None:
            tr_rules = self._select_rules(
                lambda r: r.get("type") in ("traffic", "bandwidth", "volume"))
        max_win = max((r.get('threshold_window', 10) for r in tr_rules), default=10)
        start_dt = now_utc - datetime.timedelta(minutes=max_win + 2)
        traffic_stream = self.api.execute_traffic_query_stream(
            start_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
            # vendor 值域四值：unknown 涵蓋 idle/快照模式與 Flowlink 未管理流量
            ["blocked", "potentially_blocked", "allowed", "unknown"]
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
        # 每個 cycle 先歸零截斷訊號（下方 cache 分支才會重新設定）——否則
        # 規則全部停用或改走 legacy 路徑後，舊訊號會永遠留著每小時重發一次。
        self.state["window_truncation"] = {}
        # 同理歸零 bucket-basis 守門訊號：它由 _run_rule_engine 在本 cycle
        # 重新寫入；規則停用或不再命中時訊號必須自癒，不可永久黏著。
        self.state["basis_mismatch"] = {}
        tr_rules = self._select_rules(
            lambda r: r.get("type") in ("traffic", "bandwidth", "volume"))
        if not tr_rules:
            return None, tr_rules, datetime.datetime.now(datetime.timezone.utc)

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        self._warm_service_lookup_cache(tr_rules)

        if self._sub_flows is not None:
            # 全視窗查詢（同 legacy API 語意：max_win + 2 分鐘）——cursor 增量
            # 會把 count/volume 規則的視窗退化成輪詢間隔（2026-07-24 審查 A1）
            max_win = max(r.get('threshold_window', 10) for r in tr_rules)
            since = now_utc - datetime.timedelta(minutes=max_win + 2)
            flows = self._sub_flows.fetch_window_rows(since, limit=TRAFFIC_WINDOW_ROW_LIMIT)
            logger.info("Analyzer flow path: cache window ({} rows)", len(flows))
            # 撞到列數上限＝視窗內最舊的列被丟掉，加總必然低估。寫進 state 讓
            # _maybe_alert_overflow 發 meta-alert；未截斷時清成 {} 讓訊號自癒。
            if len(flows) >= TRAFFIC_WINDOW_ROW_LIMIT:
                self.state["window_truncation"] = {
                    "detected_at": format_utc(now_utc),
                    "query_since": format_utc(since),
                    "query_until": format_utc(now_utc),
                    "raw_count": len(flows),
                    "max_results": TRAFFIC_WINDOW_ROW_LIMIT,
                }
            return flows, tr_rules, now_utc

        traffic_stream, now_utc = self._legacy_fetch_traffic(tr_rules)
        return traffic_stream, tr_rules, now_utc

    def _warm_service_lookup_cache(self, tr_rules: list) -> None:
        """規則帶 services/ex_services 時，先把 service_ports_cache 暖起來。

        規則引擎用 LabelResolver.resolve_service_entries 把 service href 展開
        成 port/proto 條目，而那個函式是「純查表、查不到就回 None」——不像
        label/IP 的 resolver 會自己觸發 lazy refresh。監控 cycle 每輪都新建
        ApiClient（快取是 instance 層級的空 TTLCache），且整個 cycle 沒有任何
        地方會去填它，於是 include 側每一筆 flow 都不命中（規則永遠不告警）、
        exclude 側則等於排除條件沒生效——兩邊都是靜默的。
        """
        svc_rules = [r for r in tr_rules if r.get("services") or r.get("ex_services")]
        if not svc_rules:
            return
        labels = getattr(self.api, "_labels", None)
        ensure = getattr(self.api, "_ensure_query_lookup_cache", None)
        if callable(ensure):
            try:
                ensure()
            except Exception as exc:  # PCE 不可達時不得中斷整個 cycle
                logger.warning("Service lookup cache warm-up failed: {}", exc)
        resolve = getattr(labels, "resolve_service_entries", None)
        if not callable(resolve):
            return
        # 展開失敗要吵一次（每規則每 cycle 一次，不在 per-flow 熱迴圈裡）：
        # 永遠不會觸發的規則不可以看起來像「這段時間沒有符合的流量」。
        for rule in svc_rules:
            unresolved = []
            for key in ("services", "ex_services"):
                for href in (rule.get(key) or []):
                    try:
                        if not resolve(href):
                            unresolved.append(href)
                    except Exception:
                        unresolved.append(href)
            if unresolved:
                logger.warning(
                    "Rule '{}': {} service reference(s) could not be resolved ({}) — "
                    "an unresolvable services filter never matches and an "
                    "ex_services filter never excludes",
                    rule.get("name", rule.get("id")), len(unresolved), unresolved[:3],
                )

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

    def _prefetch_window_baselines(
        self, traffic_stream: Any, tr_rules: list, now_utc: datetime.datetime
    ) -> tuple[list[str | None] | None, dict[Any, dict[str, Any]]]:
        """替本批 flow 取得每個規則視窗起點的基準觀測。

        回傳 ``(flow_keys, {threshold_window: {flow_hash: FlowObservation}})``。
        flow_keys 與 traffic_stream 同序；為 None 代表本 cycle 不走增量路徑
        （沒有 delta reader、或串流不可重複走訪）——呼叫端一律退回守門。

        只在 traffic_stream 已是 list 時啟用：增量要先掃過整批算出 flow_hash
        才能一次查完基準，而 legacy API 路徑給的是 generator（且那條路徑的
        flow 本來就沒有對應的 cache 觀測）。查詢按「不同的 threshold_window」
        各做一次，而非每條規則一次——同長度的視窗共用同一份基準。
        """
        if self._delta_reader is None or not tr_rules:
            return None, {}
        if not isinstance(traffic_stream, list):
            return None, {}
        try:
            from src.pce_cache.ingestor_traffic import flow_hash as _flow_key

            def _key(flow: Any) -> str | None:
                # 單筆畸形 payload（例如 raw_json 損毀後退化成欄位投影的列，
                # 其 first_detected 是 datetime 而非字串）不得讓整批失去增量
                # ——該筆自己退回守門即可。
                try:
                    return _flow_key(flow)
                except Exception:  # noqa: BLE001
                    return None

            keys = [_key(f) for f in traffic_stream]
            present = [k for k in keys if k is not None]
            baselines: dict[Any, dict[str, Any]] = {}
            for r_win in {r.get("threshold_window", 10) for r in tr_rules}:
                r_start = now_utc - datetime.timedelta(minutes=r_win)
                baselines[r_win] = self._delta_reader.baselines(present, r_start)
            return keys, baselines
        except Exception as exc:  # noqa: BLE001
            # 查不到基準不是致命錯誤：整個 cycle 退回 phase-1 守門（規則不評估
            # 但操作者會收到 meta-alert），比讓 monitor cycle 整個掛掉好。
            logger.warning(
                "Window-delta baselines unavailable ({}); falling back to the "
                "aggregation-basis guard for this cycle", exc,
            )
            return None, {}

    def _basis_decision(
        self,
        rule: dict,
        r_win: float,
        r_start: datetime.datetime,
        now_utc: datetime.datetime,
        f_span_start: datetime.datetime | None,
        bw_note: str,
        vol_note: str,
        f_key: str | None,
        f_cum: tuple[int, int, int] | None,
        baselines_by_window: dict[Any, dict[str, Any]],
    ) -> tuple[WindowDelta | None, str | None]:
        """一筆 flow 對一條規則的量測基準判定（規則引擎與 debug 模擬共用）。

        回傳 ``(delta, reason)``：
          * ``(None, None)``  —— flow 的聚合區間本來就落在視窗內（或值本身
            就是 EDC 區間增量），直接用 flow 上的原始值。
          * ``(delta, None)`` —— 用連續觀測推導出的視窗增量取代原始值。
          * ``(None, reason)``—— 兩者皆不可行，退回聚合基準守門（不評估）。
        """
        if f_span_start is None or f_span_start >= r_start:
            return None, None
        if rule["type"] == "bandwidth":
            interval_scoped = bw_note == "(Interval)"
        elif rule["type"] == "volume":
            interval_scoped = vol_note == "(Interval)"
        else:
            # traffic count：PCE 沒有「增量連線數」欄位，num_connections
            # 一律是整個 bucket 的累計值。
            interval_scoped = False
        if interval_scoped:
            return None, None
        delta, reason = self._window_delta(
            f_key, f_cum, r_win, r_start, now_utc, baselines_by_window)
        if delta is None:
            return None, reason
        return delta, None

    def _window_delta(
        self,
        f_key: str | None,
        f_cum: tuple[int, int, int] | None,
        r_win: float,
        r_start: datetime.datetime,
        now_utc: datetime.datetime,
        baselines_by_window: dict[Any, dict[str, Any]],
    ) -> tuple[WindowDelta | None, str]:
        """由基準觀測推導視窗增量。回傳 ``(delta, reason)``；delta 為 None 時
        reason 說明為什麼推導不出來（呼叫端據此退回守門並計數）。"""
        if f_key is None or f_cum is None:
            return None, "no_cache"
        base = (baselines_by_window.get(r_win) or {}).get(f_key)
        if base is None:
            # 視窗起點之前沒有任何觀測：flow 是這個視窗內才第一次被看到的，
            # 或觀測已被 flow_obs_retention_hours 修剪掉。
            return None, "no_baseline"
        lag = (r_start - base.observed_at).total_seconds()
        tolerance = max(DELTA_BASELINE_MIN_TOLERANCE_SECONDS,
                        float(r_win) * 60.0 * DELTA_BASELINE_TOLERANCE_RATIO)
        if lag > tolerance:
            # 基準太舊＝增量涵蓋的區間比視窗長太多，還原不出「短視窗」語意。
            # 解法是把 traffic_poll_interval_seconds 調到遠小於視窗長度。
            return None, "stale_baseline"
        d_out = f_cum[0] - base.bytes_out
        d_in = f_cum[1] - base.bytes_in
        d_conn = f_cum[2] - base.conn_count
        if d_out < 0 or d_in < 0 or d_conn < 0:
            # 計數器歸零（PCE 換 bucket，或亂序重拉回報了較小的累計值）。
            # 負增量不是負流量——但歸零發生在視窗內或視窗前無從得知，
            # 猜哪一種都可能誤報／漏報，因此退回守門。下一次 ingest 就會在
            # 新 bucket 內留下基準，訊號自癒。
            return None, "counter_reset"
        span = max((now_utc - base.observed_at).total_seconds(), 1.0)
        return WindowDelta(float(d_out + d_in), int(d_conn), span, base.observed_at), ""

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
        # bucket-basis 守門的每規則彙總（見模組上方「Bucket-basis guard」）。
        # per-flow 迴圈是熱路徑，因此這裡只累積數字，log 與 meta-alert 一律
        # 放到迴圈外——每條規則每 cycle 最多吵一次。
        basis_mismatch: dict[Any, dict[str, Any]] = {}
        # 本 cycle 有多少「flow × 規則」實際採用了視窗增量（供操作者確認
        # phase 2 真的在運作，而不是全靠守門硬撐）。
        delta_applied = 0

        flow_keys, baselines_by_window = self._prefetch_window_baselines(
            traffic_stream, tr_rules, now_utc)

        count_processed = 0
        no_byte_fields = 0
        for f in traffic_stream:
            count_processed += 1
            if not flow_has_byte_fields(f):
                no_byte_fields += 1

            bw_val, bw_note, _, _ = self.calculate_mbps(f)
            vol_val, vol_note = self.calculate_volume_mb(f)
            conn_val = _safe_int(f.get("num_connections") or f.get("count", 1))
            # 每 flow 解析一次（規則迴圈內重複解析同一個字串是白工）
            f_span_start = flow_aggregation_start(f)
            # 同理：flow_hash 與累計計數器每 flow 只取一次
            f_key = flow_keys[count_processed - 1] if flow_keys is not None else None
            f_cum = _cumulative_metrics(f) if f_key is not None else None

            for rule in tr_rules:
                rid = rule['id']
                r_win = rule.get("threshold_window", 10)
                r_start = now_utc - datetime.timedelta(minutes=r_win)

                if not self._match_flow_filters(rule, f, r_start, strict_window=True):
                    continue

                # 本規則實際採用的量測值：預設就是 flow 上的原始（bucket 累計）
                # 值；下面的守門若能用視窗增量取代，就換成增量值。
                m_bw, m_bw_note = bw_val, bw_note
                m_vol, m_vol_note = vol_val, vol_note
                m_conn = conn_val

                # bucket-basis 守門：flow 的聚合區間起點早於本規則視窗起點時，
                # 它帶的 byte/連線數涵蓋視窗外的流量，拿來比門檻必然高估。
                # phase 2 先試著用連續觀測推導視窗增量，推導不出來才守門。
                delta, reason = self._basis_decision(
                    rule, r_win, r_start, now_utc, f_span_start, bw_note, vol_note,
                    f_key, f_cum, baselines_by_window)
                if reason:
                    # reason 只會在 f_span_start 已知且早於視窗起點時產生
                    # （見 _basis_decision 的第一個分支）；None 分支只是給
                    # 型別檢查器的保底，實際不會走到。
                    span_min = (0.0 if f_span_start is None
                                else (now_utc - f_span_start).total_seconds() / 60.0)
                    info = basis_mismatch.get(rid)
                    if info is None:
                        basis_mismatch[rid] = {
                            "rule_id": rid,
                            "rule_name": rule.get("name", str(rid)),
                            "window_minutes": r_win,
                            "span_minutes": span_min,
                            "flows": 1,
                            "reasons": Counter([reason]),
                        }
                    else:
                        info["flows"] += 1
                        info["reasons"][reason] += 1
                        if span_min > info["span_minutes"]:
                            info["span_minutes"] = span_min
                    continue
                if delta is not None:
                    delta_applied += 1
                    if rule["type"] == "bandwidth":
                        m_bw, m_bw_note = delta.mbps, DELTA_BASIS_NOTE
                    elif rule["type"] == "volume":
                        m_vol, m_vol_note = delta.volume_mb, DELTA_BASIS_NOTE
                    else:
                        m_conn = delta.conn

                res = rule_results[rid]
                heap = top_heaps[rid]

                if rule["type"] == "bandwidth":
                    if m_bw > res['max_val']:
                        res['max_val'] = m_bw
                    if m_bw > float(rule.get("threshold_count", 0)):
                        f_copy = f.copy()
                        f_copy['_metric_val'] = m_bw
                        f_copy['_metric_fmt'] = f"{format_unit(m_bw, 'bandwidth')} {m_bw_note}"
                        self._push_bounded_top_match(heap, m_bw, count_processed, f_copy, TOP_MATCHES_LIMIT)

                elif rule["type"] == "volume":
                    res['max_val'] += m_vol
                    f_copy = f.copy()
                    f_copy['_metric_val'] = m_vol
                    f_copy['_metric_fmt'] = f"{format_unit(m_vol, 'volume')} {m_vol_note}"
                    self._push_bounded_top_match(heap, m_vol, count_processed, f_copy, TOP_MATCHES_LIMIT)

                else:  # Traffic Count
                    res['max_val'] += m_conn
                    f_copy = f.copy()
                    f_copy['_metric_val'] = m_conn
                    f_copy['_metric_fmt'] = str(m_conn)
                    self._push_bounded_top_match(heap, m_conn, count_processed, f_copy, TOP_MATCHES_LIMIT)

        logger.info(t('found_traffic', count=count_processed))

        # 「量測到 0」與「根本沒有量測」必須分得出來：PCE 未啟用 Enhanced
        # Data Collection 時 flow 完全不帶 byte 欄位，volume/bandwidth 規則
        # 一律算出 0、永遠不會觸發，而畫面上只會看到 0.00 MB——像是沒有流量。
        # 每 cycle 記一次（不在 per-flow 熱迴圈內）。
        if (count_processed and no_byte_fields == count_processed
                and any(r.get("type") in ("bandwidth", "volume") for r in tr_rules)):
            logger.warning(
                "All {} flows in this window carry no byte telemetry (dst_db*/dst_tb*) — "
                "volume/bandwidth rules will evaluate to 0 and can never fire. "
                "Check that the PCE visibility level is Enhanced Data Collection.",
                count_processed,
            )

        # bucket-basis 守門的收斂：每條受影響的規則吵一次 WARNING（迴圈外），
        # 把結果掛回 rule_results 讓 _dispatch_alerts 擋掉告警，並寫進 state
        # 讓 _maybe_alert_overflow 發 meta-alert。三者缺一不可：只 suppress 不
        # 出聲＝操作者以為規則還在保護他，那比誤報更糟。
        if delta_applied:
            logger.info(
                "Window-delta basis applied to {} flow/rule pair(s) this cycle "
                "(cache observations differenced across each rule's window)",
                delta_applied,
            )
        for rid, info in basis_mismatch.items():
            info["reason_summary"] = _format_delta_reasons(info["reasons"])
            rule_results[rid]['basis_mismatch'] = info
            logger.warning(
                "Rule '{}' NOT evaluated this cycle (aggregation-basis guard): {} matched "
                "flow(s) carry aggregate totals reaching back {:.0f} min, but the rule's "
                "threshold_window is only {} min. This PCE returns whole-bucket byte and "
                "connection totals that are NOT clipped to the query window, so evaluating "
                "the rule would compare bucket-wide traffic against a short-window threshold "
                "and raise a false alert. The per-window delta could not be derived from "
                "cache observations either ({}). Fix by: keeping pce_cache enabled with "
                "flow_delta_enabled=true, setting traffic_poll_interval_seconds well below "
                "this rule's threshold_window, widening threshold_window to cover the "
                "aggregation span, or enabling Enhanced Data Collection so the PCE reports "
                "interval deltas.",
                info["rule_name"], info["flows"], info["span_minutes"], info["window_minutes"],
                info["reason_summary"],
            )
        if basis_mismatch:
            worst = max(basis_mismatch.values(), key=lambda i: i["span_minutes"])
            self.state["basis_mismatch"] = {
                "detected_at": format_utc(now_utc),
                "rules": [
                    {
                        "id": i["rule_id"],
                        "name": i["rule_name"],
                        "window_minutes": i["window_minutes"],
                        "span_minutes": round(i["span_minutes"], 1),
                        "flows": i["flows"],
                        "reasons": i["reason_summary"],
                    }
                    for i in basis_mismatch.values()
                ],
                # 以下純量欄位供 meta-alert 的 details 模板取用（見
                # _maybe_alert_single_overflow：state 內的純量會成為 placeholder）
                "rule_count": len(basis_mismatch),
                "rule_names": ", ".join(i["rule_name"] for i in basis_mismatch.values()),
                "worst_window_minutes": worst["window_minutes"],
                "worst_span_minutes": round(worst["span_minutes"], 1),
                # 為何推導不出視窗增量（no_cache / no_baseline / stale_baseline /
                # counter_reset）——決定操作者該調哪一個旋鈕
                "delta_reasons": _format_delta_reasons(
                    sum((i["reasons"] for i in basis_mismatch.values()), Counter())),
            }

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
            # bucket-basis 守門（見 _run_rule_engine）：本 cycle 這條規則的加總
            # 涵蓋視窗外的流量、已知會高估——寧可漏發，也不送一則已知錯誤的
            # 告警。WARNING 與 meta-alert 已在規則引擎/overflow 路徑發出。
            if res.get('basis_mismatch'):
                mismatch = res['basis_mismatch']
                self.stats.record_suppression(
                    rule,
                    "aggregation_basis",
                    window_minutes=mismatch["window_minutes"],
                    span_minutes=round(mismatch["span_minutes"], 1),
                    flows=mismatch["flows"],
                )
                continue

            val = res['max_val']
            threshold = float(rule.get("threshold_count", 0))

            is_trigger = False
            if rule["type"] == "bandwidth":
                if len(res['top_matches']) > 0:
                    is_trigger = True
            else:
                # 與 event 路徑同一道守門（2026-07-24 審查 A2）：門檻達標還
                # 不夠，必須真的有匹配的 flow 當證據。threshold_count 被填成
                # 0（GUI 的 Count 欄沒有 min、端點也不擋）時 0.0 >= 0.0 恆真，
                # 舊版每個冷卻週期就送出一則 count=0、details 空白的空殼告警。
                if val >= threshold and res['top_matches']:
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
        """冷卻＋節流閘門。cooldown_minutes=0 是刻意語意：停用冷卻
        （每個 cycle 都可再告警，僅剩 throttle 限制）——GUI/CLI hint 與
        monitoring-alerts.md 已明文（審查 A5 確認項）。"""
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
                # intentional fallback：損壞的 last_alert 時戳讓冷卻放行一次
                # （隨後以正確格式覆寫、自癒）——但要留下可見證據（審查 A5）
                logger.warning(
                    "corrupt alert_history timestamp for rule {} ({!r}) — cooldown bypassed once",
                    rid, last_alert,
                )

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
        data_source: str | None = None,
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

        data_source: operator-facing preference ('live' | 'hybrid' | None),
        resolved through the same resolve_data_source() the report path uses
        so the two paths cannot drift on what each mode means. An explicit
        'live' bypasses the cache entirely — not even cover_state is checked
        — regardless of coverage. None/'hybrid' leaves today's automatic
        cache/API/hybrid decision untouched.
        """
        # Without a cache reader, behaviour is identical to the pre-cache path.
        if self._cache_reader is None:
            stream = self.api.execute_traffic_query_stream(
                start_time, end_time, query_pds,
                filters=query_spec, compute_draft=needs_draft,
            )
            return stream, "api"

        use_cache, _clip_to_cache, _warning = resolve_data_source(data_source, cache_ok=True)
        if not use_cache:
            # 操作者明示 live：直接走 API，連 cover_state 都不查，
            # 即使該視窗其實 cache 全覆蓋。
            logger.info("query_flows: live data source requested — bypassing cache")
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
                        gap_list: list | None = list(gap_stream) if gap_stream is not None else []
                        # gap API 靜默失敗（yield 0 + last_fetch_error）不可標成
                        # cache 成功吞掉歷史段遺失（審查 H2）——退 full API，其
                        # source="api" 讓 _raise_if_query_fetch_failed 生效。
                        # isinstance(str) 防 MagicMock 測試 stub 誤觸。
                        _gap_err = getattr(self.api, "last_fetch_error", None)
                        if isinstance(_gap_err, str) and _gap_err:
                            logger.warning(
                                "query_flows hybrid: gap fetch reported error ({}); "
                                "falling back to full API", _gap_err)
                            gap_list = None
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
                        # 跨界 flow（first_detected<cache_start<=last_detected）若
                        # PCE 以 overlap 語意回，會同時落在 gap 與 cache——按 flow
                        # 身分去重，cache 端優先保留（審查 M3）
                        merged = self._merge_dedup_flows(gap_list, cached)
                        return merged, source

        # miss / partial-with-conflict / hybrid-failure: fall through to API
        stream = self.api.execute_traffic_query_stream(
            start_time, end_time, query_pds,
            filters=query_spec, compute_draft=needs_draft,
        )
        return stream, "api"

    @staticmethod
    def _flow_identity(f: dict) -> tuple:
        """hybrid 合併去重用的 flow 身分：src/dst IP＋service＋活動區間。"""
        src = f.get("src") or {}
        dst = f.get("dst") or {}
        svc = f.get("service") or {}
        return (
            src.get("ip"), dst.get("ip"),
            svc.get("port"), svc.get("proto"),
            f.get("first_detected"), f.get("last_detected"),
        )

    def _merge_dedup_flows(self, gap: list, cached: list) -> list:
        """cached 端優先（較完整），gap 只補 cache 未見的 flow。"""
        seen = {self._flow_identity(f) for f in cached}
        return cached + [f for f in gap if self._flow_identity(f) not in seen]

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
        # 預設含 unknown（vendor 值域四值；涵蓋 idle/快照模式與 Flowlink 流量）
        pds = params.get("policy_decisions", ["blocked", "potentially_blocked", "allowed", "unknown"])

        strict_pd: set[str] = set()
        for p in pds:
            if p == "potentially_blocked": strict_pd.add("potentially_blocked")
            elif p == "blocked": strict_pd.add("blocked")
            elif p == "allowed": strict_pd.add("allowed")
            elif p == "unknown": strict_pd.add("unknown")
        
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
        query_pds = pds if not needs_draft else ["blocked", "potentially_blocked", "allowed", "unknown"]

        # label_groups 類 key 無法在 client 端比對（成員展開只在 PCE 端）——
        # 帶這些 filter 時不可使用 cache（cache 資料未過濾），強制走 API。
        cache_bypass_keys = [
            k for k in _CACHE_UNEVALUABLE_FILTER_KEYS if query_filters.get(k)
        ]
        if needs_draft:
            # draft_policy_decision 只在 compute_draft async 查詢的 flow 上存在；
            # cache 從不算 draft，client 端無從評估——強制走 API，否則 cache
            # 全覆蓋時 :1586 的 draft 過濾把每筆都丟掉→靜默空結果（審查 H1）
            cache_bypass_keys = cache_bypass_keys + ["draft_policy_decision"]
        traffic_stream, self.last_query_source = self._fetch_query_flows(
            start_time, end_time, query_pds, query_spec, needs_draft,
            cache_bypass_keys=cache_bypass_keys,
            data_source=params.get("data_source"),
        )
        # 記到 stats 上讓端點能回傳——即使下面 early-return（空結果）也要有；
        # 底下的完整分支會在收尾時把整份 dict 重建、一併帶上這欄。
        self.last_query_stats["actual_source"] = self.last_query_source
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
            "actual_source": self.last_query_source,
        }
        return matches[:QUERY_RESULT_CAP]

    def run_debug_mode(self, mins: int | None = None, pd_sel: int | None = None, interactive: bool | None = None) -> None:
        # Interactive debug REPL: stdout is the contract here. The CLI menu
        # streams it to the user; the GUI debug API captures it via
        # redirect_stdout. Keep print() (do not swap to logger).
        print(f"\n{Colors.HEADER}{t('debug_mode_title')}{Colors.ENDC}")

        # Auto-detect minutes if not provided
        # 模擬必須與引擎看到的規則集合一致：停用的規則不參與（既不撐大查詢
        # 視窗，也不出現在模擬報告裡），否則 debug 會宣稱一條關掉的規則
        # 「Would Trigger」。
        sim_rules = self._select_rules(lambda r: True)
        max_win = 10
        for r in sim_rules:
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
            print(f"3. {t('pd_3_all', default='All (Blocked + Potential + Allowed + Unknown)')} [{t('nav_default', default='Default')}]")
            pd_input = safe_input(t('please_select'), int, range(0, 4), allow_cancel=True)
            if pd_input is None: return  # user pressed 0 to go back
            if pd_input == '' or pd_input == 0:
                pd_sel = 3  # default: All
            else:
                pd_sel = int(pd_input)

        # 「全部」須含 unknown（vendor 值域四值；涵蓋 idle/快照模式與 Flowlink 流量）
        pds = ["blocked", "potentially_blocked", "allowed", "unknown"]
        if pd_sel == 1: pds = ["blocked"]
        elif pd_sel == 2: pds = ["allowed"]

        traffic_gen = self.api.execute_traffic_query_stream(start_str, end_str, pds)
        traffic = list(traffic_gen) if traffic_gen else []
        print(f"  -> {t('fetched_records', count=len(traffic), mins=mins)}")

        # 模擬與引擎共用視窗增量基準（見 _basis_decision）：debug 只是「不派送
        # 的一次評估」，量測基準必須逐字相同，否則畫面上的 Would Trigger 與
        # 真實 cycle 的行為會分岔。
        flow_keys, baselines_by_window = self._prefetch_window_baselines(
            traffic, [r for r in sim_rules if r.get("type") in ("traffic", "bandwidth", "volume")],
            now)
        flow_key_by_id: dict[int, str] = (
            {id(f): k for f, k in zip(traffic, flow_keys) if k is not None}
            if flow_keys is not None else {})

        print(f"\n{Colors.HEADER}{t('simulation_report')}{Colors.ENDC}")
        _skipped = len([r for r in (self.cm.config.get('rules') or []) if not rule_enabled(r)])
        if _skipped:
            # 停用的規則不參與模擬，但要說出來——否則操作者會以為規則不見了
            print(f"  ({t('gui_disabled')}: {_skipped})")

        for rule in sim_rules:
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
                # 模擬必須跟引擎用同一套量測基準（_basis_decision）：以前這裡
                # 直接拿 bucket 累計值算 "Would Trigger"，而引擎其實根本沒評估
                # 那條規則——畫面對操作者說謊。
                guarded: Counter = Counter()
                delta_used = 0
                for f in traffic:
                    if self._match_flow_filters(rule, f, rule_start):
                        f_key = flow_key_by_id.get(id(f))
                        f_cum = _cumulative_metrics(f) if f_key is not None else None
                        bw_v, bw_n, _, _ = self.calculate_mbps(f)
                        vol_v, vol_n = self.calculate_volume_mb(f)
                        delta, reason = self._basis_decision(
                            rule, rule_win, rule_start, now, flow_aggregation_start(f),
                            bw_n, vol_n, f_key, f_cum, baselines_by_window)
                        if reason:
                            guarded[reason] += 1
                            continue
                        if delta is not None:
                            delta_used += 1
                        f_copy = f.copy()
                        if rtype == "bandwidth":
                            v = delta.mbps if delta is not None else bw_v
                            note = DELTA_BASIS_NOTE if delta is not None else bw_n
                            f_copy['_metric_val'] = v
                            f_copy['_metric_fmt'] = f"{format_unit(v, 'bandwidth')} {note}"
                        elif rtype == "volume":
                            v = delta.volume_mb if delta is not None else vol_v
                            note = DELTA_BASIS_NOTE if delta is not None else vol_n
                            f_copy['_metric_val'] = v
                            f_copy['_metric_fmt'] = f"{format_unit(v, 'volume')} {note}"
                        else:
                            c = (delta.conn if delta is not None
                                 else _safe_int(f.get("num_connections") or f.get("count", 1)))
                            f_copy['_metric_val'] = c
                            f_copy['_metric_fmt'] = str(c)
                        matches.append(f_copy)

                print(t('time_filter_results', total=len(traffic), win=rule_win, rem=len(matches)))
                if delta_used:
                    print("  -> " + t(
                        'debug_basis_window_delta',
                        default="Basis: per-window delta derived from cache observations "
                                "({n} flow(s)) — the same basis the rule engine uses.",
                        n=delta_used))
                if guarded:
                    # 引擎會因此**完全不評估**這條規則；模擬不可以照樣印
                    # "Would Trigger"，否則操作者會以為規則有在保護他。
                    print("  -> " + t(
                        'debug_basis_guard_suppressed',
                        default="Aggregation-basis guard: {n} matched flow(s) excluded "
                                "({reasons}). This PCE returns whole-bucket totals that are "
                                "NOT clipped to the query window and no per-window delta "
                                "could be derived, so the rule engine SUPPRESSES this rule "
                                "instead of alerting.",
                        n=sum(guarded.values()), reasons=_format_delta_reasons(guarded)))
                    if not matches:
                        print("  -> " + t(
                            'debug_basis_rule_not_evaluated',
                            default="Rule NOT evaluated this cycle — the result below is "
                                    "what the engine would report (no alert), not a "
                                    "measurement of the traffic."))
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
