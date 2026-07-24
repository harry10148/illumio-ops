from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import orjson
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowRaw


@dataclass
class BackfillResult:
    total_rows: int
    inserted: int
    duplicates: int
    elapsed_seconds: float


class BackfillRunner:
    # 與 live ingestor 相同的 chunked 寫入大小：per-row commit 曾是 SQLite
    # write-lock 競爭與 ingest 成本的主因（見 ingestor_traffic._insert_batch
    # docstring）；backfill 動輒十萬列，逐列交易會跑數十分鐘並持續搶寫鎖。
    _CHUNK = 500

    # events 視窗抓取參數：單次請求上限與二分抽乾深度（鏡射 TrafficIngestor
    # 的 bisect 策略；碰頂且無法再分時記 warning——該窗資料可能不完整）。
    _EVENTS_MAX = 10000
    _MAX_BISECT_DEPTH = 6
    _MIN_BISECT_SPAN = timedelta(minutes=5)

    def __init__(self, api, session_factory: sessionmaker, rate_limit_per_minute: int = 400):
        # rate_limit_per_minute 僅保留簽名相容（pce_cache_cli 會傳入）；實際
        # 限速由 api client 端以 rate_limit=True 走其設定的全域限速器
        # （GlobalRateLimiter），與 live ingestor 相同。
        self._api = api
        self._sf = session_factory

    def run_events(self, since: datetime, until: datetime) -> BackfillResult:
        """Fetch events via API and write to pce_events. Does NOT advance watermark."""
        t0 = time.monotonic()
        events = self._fetch_events_window(since, until, depth=0)
        inserted, dups = self._insert_events(events)
        return BackfillResult(
            total_rows=len(events),
            inserted=inserted,
            duplicates=dups,
            elapsed_seconds=time.monotonic() - t0,
        )

    def _fetch_events_window(self, since_dt: datetime, until_dt: datetime, depth: int) -> list[dict]:
        """[since, until] 的完整事件抓取。

        帶明確 end（timestamp[lte]）與大 max_results；碰頂就對半二分抽乾
        （端點含重複由 pce_href unique 去重），到深度/最小跨度仍碰頂則記
        warning。舊版只把 since 丟給 get_events（預設 500 上限、無 until）
        ——超過 500 筆的視窗被靜默截斷，抓到的還可能落在視窗之外。"""
        events = self._api.fetch_events(
            _iso_z(since_dt),
            end_time_str=_iso_z(until_dt),
            max_results=self._EVENTS_MAX,
            rate_limit=True,
        )
        self._raise_on_fetch_error("events")
        if len(events) < self._EVENTS_MAX:
            return events
        span = until_dt - since_dt
        if depth >= self._MAX_BISECT_DEPTH or span <= self._MIN_BISECT_SPAN:
            logger.warning(
                "Events backfill hit max_results cap ({}) in window {} → {} at depth {}; "
                "cannot bisect further — events in this window may be incomplete",
                self._EVENTS_MAX, since_dt, until_dt, depth,
            )
            return events
        mid = since_dt + span / 2
        return (self._fetch_events_window(since_dt, mid, depth + 1)
                + self._fetch_events_window(mid, until_dt, depth + 1))

    def run_traffic(self, since: datetime, until: datetime, filters: dict | None = None) -> BackfillResult:
        """Fetch traffic via API and write to pce_traffic_flows_raw. Does NOT advance watermark."""
        t0 = time.monotonic()
        since_str = since.isoformat().replace("+00:00", "Z")
        until_str = until.isoformat().replace("+00:00", "Z")
        flows = self._api.fetch_traffic_for_report(
            start_time_str=since_str, end_time_str=until_str, rate_limit=True)
        self._raise_on_fetch_error("traffic")
        inserted, dups = self._insert_traffic(flows or [])
        return BackfillResult(
            total_rows=len(flows or []),
            inserted=inserted,
            duplicates=dups,
            elapsed_seconds=time.monotonic() - t0,
        )

    def _raise_on_fetch_error(self, what: str) -> None:
        """fetch 路徑把連線層失敗吞成空結果、只寫 api.last_fetch_error（與
        live ingestor 同一失敗通道，見 ingestor_traffic/ingestor_events）；
        backfill 若不檢查，PCE 斷線會被回報成「成功的 0 筆 backfill」，
        操作者以為視窗真的沒資料、缺口永遠不補。isinstance guard 同
        ingestor：MagicMock 測試替身的屬性會自動長出 truthy child mock。"""
        fetch_error = getattr(self._api, "last_fetch_error", None)
        if isinstance(fetch_error, str) and fetch_error:
            raise RuntimeError(f"PCE {what} backfill fetch failed: {fetch_error}")

    def _insert_events(self, events: list[dict]) -> tuple[int, int]:
        default_now = datetime.now(timezone.utc)
        rows: list[dict] = []
        seen: set[str] = set()
        for ev in events:
            href = ev.get("href", "")
            if href in seen:        # collapse duplicates within this batch
                continue
            seen.add(href)
            ts_raw = ev.get("timestamp", "")
            rows.append({
                "pce_href": href,
                "pce_event_id": ev.get("uuid", ev.get("href", ""))[-64:],
                "timestamp": _parse_iso(ts_raw) if ts_raw else default_now,
                "event_type": ev.get("event_type", "unknown"),
                "severity": ev.get("severity", "info"),
                # `or` 而非 dict default：真實 PCE 事件會帶顯式 null/""
                # （與 ingestor_events 同修）——NOT NULL 欄位不可收到 None，
                # 否則整列被 IntegrityError 靜默跳過還被誤計成 duplicate。
                "status": ev.get("status") or "success",
                "pce_fqdn": ev.get("pce_fqdn", ""),
                "raw_json": orjson.dumps(ev).decode("utf-8"),
            })
        inserted = 0
        for i in range(0, len(rows), self._CHUNK):
            chunk = rows[i:i + self._CHUNK]
            # 每個 chunk 重取 ingested_at：長跑 backfill 期間 archiver 游標
            # （依 (ingested_at, id) 前進）可能已被 live ingest 推過起跑時間，
            # 晚 commit 的列要蓋上當下時間才會排在游標之後、不被匯出永久略過。
            now = datetime.now(timezone.utc)
            for r in chunk:
                r["ingested_at"] = now
            with self._sf.begin() as s:
                stmt = (
                    sqlite_insert(PceEvent)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=["pce_href"])
                    .returning(PceEvent.id)
                )
                inserted += len(list(s.execute(stmt)))
        return inserted, len(events) - inserted

    def _insert_traffic(self, flows: list[dict]) -> tuple[int, int]:
        from src.report.parsers.api_parser import flatten_flow_record
        default_now = datetime.now(timezone.utc)
        rows: list[dict] = []
        seen: set[str] = set()
        for fl in flows:
            fh = _backfill_flow_hash(fl)
            if fh in seen:          # collapse duplicates within this batch
                continue
            seen.add(fh)
            ts_range = fl.get("timestamp_range") or {}
            last_detected_raw = fl.get("last_detected") or ts_range.get("last_detected", "")
            last_detected = _parse_iso(last_detected_raw) if last_detected_raw else default_now
            first_detected_raw = fl.get("first_detected") or ts_range.get("first_detected", "")
            first_detected = _parse_iso(first_detected_raw) if first_detected_raw else default_now
            src_wl = (fl.get("src") or {}).get("workload") or {}
            dst_wl = (fl.get("dst") or {}).get("workload") or {}
            svc = fl.get("service") or {}
            src_ip = fl.get("src_ip", "") or (fl.get("src") or {}).get("ip", "")
            dst_ip = fl.get("dst_ip", "") or (fl.get("dst") or {}).get("ip", "")
            port = svc.get("port") if svc else fl.get("port", 0)
            protocol = _proto_to_str(svc.get("proto") if svc else fl.get("protocol", "tcp"))
            action = fl.get("action") or fl.get("policy_decision", "unknown")
            flow_count = fl.get("flow_count") or fl.get("num_connections", 1)
            # Precompute the report-ready flatten like the live ingestor so
            # backfilled rows hit read_flows_df's fast path (and uphold the
            # ix_raw_report_json_null invariant documented in schema.py).
            # Best-effort: never block backfill on a flatten error.
            try:
                report_json = orjson.dumps(flatten_flow_record(fl)).decode("utf-8")
            except Exception:  # noqa: BLE001
                report_json = None
            rows.append({
                "flow_hash": fh,
                "src_ip": src_ip,
                "src_workload": src_wl.get("href") or fl.get("src_workload"),
                "dst_ip": dst_ip,
                "dst_workload": dst_wl.get("href") or fl.get("dst_workload"),
                "port": port or 0,
                "protocol": protocol,
                "action": action,
                "flow_count": flow_count,
                "bytes_in": fl.get("bytes_in") or fl.get("dst_bi", 0),
                "bytes_out": fl.get("bytes_out") or fl.get("dst_bo", 0),
                "first_detected": first_detected,
                "last_detected": last_detected,
                "raw_json": orjson.dumps(fl).decode("utf-8"),
                "report_json": report_json,
            })
        inserted = 0
        for i in range(0, len(rows), self._CHUNK):
            chunk = rows[i:i + self._CHUNK]
            # 每 chunk 重取 ingested_at——理由同 _insert_events（archiver 游標）。
            now = datetime.now(timezone.utc)
            for r in chunk:
                r["ingested_at"] = now
            with self._sf.begin() as s:
                # DO NOTHING（非 live ingestor 的 volatile-欄 upsert）：backfill
                # 的職責是補歷史缺口，既有列（通常來自 live ingest）視為 dup，
                # 保留原有語意；活躍 flow 的計數刷新仍由 live ingestor 負責。
                stmt = (
                    sqlite_insert(PceTrafficFlowRaw)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=["flow_hash"])
                    .returning(PceTrafficFlowRaw.id)
                )
                inserted += len(list(s.execute(stmt)))
        return inserted, len(flows) - inserted


def _backfill_flow_hash(flow: dict) -> str:
    """Compute flow_hash from available fields (handles both flat and nested PCE API shapes)."""
    src_wl = (flow.get("src") or {}).get("workload") or {}
    dst_wl = (flow.get("dst") or {}).get("workload") or {}
    svc = flow.get("service") or {}
    ts_range = flow.get("timestamp_range") or {}
    first_detected = flow.get("first_detected") or ts_range.get("first_detected", "")
    key = "|".join([
        flow.get("src_ip", "") or (flow.get("src") or {}).get("ip", "") or src_wl.get("href", ""),
        flow.get("dst_ip", "") or (flow.get("dst") or {}).get("ip", "") or dst_wl.get("href", ""),
        str(svc.get("port", "") or flow.get("port", "")),
        str(svc.get("proto", "") or flow.get("protocol", "")),
        first_detected,
    ])
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()


def _proto_to_str(proto) -> str:
    """Convert protocol number or string to string label."""
    if proto is None:
        return "tcp"
    if isinstance(proto, str):
        return proto
    # IANA protocol numbers: 6=TCP, 17=UDP, 1=ICMP
    _MAP = {6: "tcp", 17: "udp", 1: "icmp"}
    return _MAP.get(int(proto), str(proto))


def _iso_z(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
