from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowRaw, SiemDispatch
from src.pce_cache.traffic_filter import TrafficFilter, TrafficSampler
from src.pce_cache.watermark import WatermarkStore


class TrafficIngestor:
    SOURCE = "traffic"

    def __init__(
        self,
        api,
        session_factory: sessionmaker,
        watermark: WatermarkStore,
        traffic_filter: Optional[TrafficFilter] = None,
        sample_ratio_allowed: int = 1,
        max_results: int = 200000,
        siem_destinations: Optional[list[str]] = None,
    ):
        self._api = api
        self._sf = session_factory
        self._wm = watermark
        self._filter = traffic_filter or TrafficFilter()
        self._sampler = TrafficSampler(ratio_allowed=sample_ratio_allowed)
        self._max_results = max_results
        self._siem_dests = list(siem_destinations or [])

    # 二分抽乾參數：深度 6 → 最小窗 = 原窗/64；再配 _MIN_BISECT_SPAN 硬下限，
    # 保證遞迴有界。碰頂但無法再分時記 warning（該窗資料可能不完整）。
    _MAX_BISECT_DEPTH = 6
    _MIN_BISECT_SPAN = timedelta(minutes=1)

    def run_once(self) -> int:
        since = self._since_cursor()
        try:
            flows = self._fetch_all(since)
        except Exception as exc:
            logger.exception("Traffic ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        inserted = 0
        watermark_advanced = False
        try:
            inserted = self._insert_batch(flows)
            if flows:
                last = max(_ts(f, "last_detected") for f in flows)
                if last:
                    self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last))
                    watermark_advanced = True
            return inserted
        except Exception as exc:
            # insert/advance 失敗（如 database is locked）：記 error 讓 last_status
            # 反映真實，再 re-raise（run_traffic_ingest 仍以 logger.exception 記錄）。
            self._wm.record_error(self.SOURCE, str(exc))
            raise
        finally:
            logger.info(
                "Traffic ingest poll: fetched={} inserted={} watermark_advanced={} since={}",
                len(flows), inserted, watermark_advanced, since,
            )

    def _fetch_all(self, since: Optional[str]) -> list[dict]:
        until_dt = datetime.now(timezone.utc).replace(microsecond=0)
        if since is not None:
            since_dt = datetime.fromisoformat(since)
        else:
            # 鏡射 api_client 的預設：無 watermark 時往回抓 24 小時
            since_dt = until_dt - timedelta(hours=24)
        return self._fetch_window(since_dt, until_dt, depth=0)

    def _fetch_window(self, since_dt: datetime, until_dt: datetime, depth: int) -> list[dict]:
        flows = self._api.get_traffic_flows_async(
            max_results=self._max_results,
            rate_limit=True,
            since=since_dt.isoformat(),
            until=until_dt.isoformat(),
        )
        if len(flows) < self._max_results:
            return flows
        span = until_dt - since_dt
        if depth >= self._MAX_BISECT_DEPTH or span <= self._MIN_BISECT_SPAN:
            logger.warning(
                "Traffic ingest hit max_results cap ({}) in window {} → {} at depth {}; "
                "cannot bisect further — data in this window may be incomplete",
                self._max_results, since_dt, until_dt, depth,
            )
            return flows
        mid = since_dt + span / 2
        logger.warning(
            "Traffic ingest hit max_results cap ({}); bisecting {} → {} at {}",
            self._max_results, since_dt, until_dt, mid,
        )
        return (self._fetch_window(since_dt, mid, depth + 1)
                + self._fetch_window(mid, until_dt, depth + 1))

    def _since_cursor(self) -> Optional[str]:
        wm = self._wm.get(self.SOURCE)
        if wm and wm.last_timestamp:
            # Grace window: re-pull 5 minutes back to catch late-arriving flows
            grace = wm.last_timestamp - timedelta(minutes=5)
            # SQLite + DateTime(timezone=True) reads back NAIVE, so an offset-less
            # ISO string would make the PCE reject the query (HTTP 406
            # invalid_timestamp). Re-attach UTC, mirroring EventsIngestor.
            if grace.tzinfo is None:
                grace = grace.replace(tzinfo=timezone.utc)
            return grace.isoformat()
        return None

    _CHUNK = 500

    # Volatile columns refreshed when a re-pulled flow conflicts on flow_hash.
    _VOLATILE = ("last_detected", "bytes_in", "bytes_out", "flow_count")

    def _insert_batch(self, flows: list[dict]) -> int:
        """Bulk-upsert flows in chunks (dedup by flow_hash). One transaction per
        chunk instead of one per row — at 100k+ flows the per-row commit/fsync
        was the dominant ingest cost and a major source of SQLite write-lock
        contention.

        flow_hash includes first_detected, and _since_cursor re-pulls a 5-minute
        grace window, so an active long-lived flow re-appears with the SAME
        flow_hash but a LARGER last_detected and higher byte/flow counters. The
        previous ON CONFLICT DO NOTHING froze every flow at its first sighting —
        undercounting bandwidth/volume and under-reporting recency. Instead,
        refresh the volatile columns on conflict, taking GREATEST so an
        out-of-order re-pull never shrinks a counter (MAX(x,x)=x stays
        idempotent). The SIEM enqueue must still fire ONLY for genuinely new
        rows, so a pre-upsert snapshot of existing flow_hashes splits new inserts
        from refreshed re-pulls (an upsert's RETURNING covers both).

        conflict 時也把 ingested_at bump 到本次 ingest 時間（excluded.ingested_at）
        ——archiver（archive.py 的 ArchiveExporter）的匯出游標依 (ingested_at, id)
        增量前進，若不 bump，一筆 flow 一旦被匯出過，之後即使在這裡持續刷新
        volatile 欄位，archiver 也不會再撿到它，造成長壽 flow 的 archive 計數
        系統性低於 live cache（根因修復見 archive.py docstring 與 F6 report）。
        bump 的副作用（皆已評估為可接受，見 F6 report）：
          - subscriber（CacheSubscriber，同樣依 (ingested_at, id) 游標）會重讀
            這筆列——at-least-once 語意本就允許重讀。
          - SIEM enqueue 不會重複派送：安全網補登（siem/dispatcher.py 的
            enqueue_new_records）以 (source_table, source_id, destination) 判斷
            anti-join，bump 不改 id，該 pair 已有 dispatch row 就不會再補登。
          - retention（依 ingested_at 刪除）：bump 會延長這筆列的存活——語意上
            合理，活躍 flow 不該被當成陳舊資料清掉。
        """
        from src.report.parsers.api_parser import flatten_flow_record
        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        seen: set[str] = set()
        for flow in flows:
            flat = _flatten_flow(flow)
            if not self._filter.passes(flat):
                continue
            if not self._sampler.keep(flat):
                continue
            fh = _flow_hash(flow)
            if fh in seen:          # collapse duplicates within this batch
                continue
            seen.add(fh)
            # Precompute the report-ready flatten once, store verbatim so reports
            # skip the per-row re-flatten. Best-effort: never block ingest on it.
            try:
                report_json = orjson.dumps(flatten_flow_record(flow)).decode("utf-8")
            except Exception:  # noqa: BLE001
                report_json = None
            src_wl = (flow.get("src") or {}).get("workload") or {}
            dst_wl = (flow.get("dst") or {}).get("workload") or {}
            svc = flow.get("service") or {}
            src_ip = flow.get("src_ip", "") or (flow.get("src") or {}).get("ip", "")
            dst_ip = flow.get("dst_ip", "") or (flow.get("dst") or {}).get("ip", "")
            port = svc.get("port") if svc else flow.get("port", 0)
            protocol = _proto_to_str(svc.get("proto") if svc else flow.get("protocol", "tcp"))
            action = flow.get("action") or flow.get("policy_decision", "unknown")
            flow_count = flow.get("flow_count") or flow.get("num_connections", 1)
            first_raw = _ts(flow, "first_detected")
            last_raw = _ts(flow, "last_detected")
            rows.append({
                "flow_hash": fh,
                "first_detected": _parse_iso(first_raw) if first_raw else now,
                "last_detected": _parse_iso(last_raw) if last_raw else now,
                "src_ip": src_ip,
                "src_workload": src_wl.get("href") or flow.get("src_workload"),
                "dst_ip": dst_ip,
                "dst_workload": dst_wl.get("href") or flow.get("dst_workload"),
                "port": port or 0,
                "protocol": protocol,
                "action": action,
                "flow_count": flow_count,
                "bytes_in": flow.get("bytes_in") or flow.get("dst_bi", 0),
                "bytes_out": flow.get("bytes_out") or flow.get("dst_bo", 0),
                "raw_json": orjson.dumps(flow).decode("utf-8"),
                "report_json": report_json,
                "ingested_at": now,
            })
        raw_cols = PceTrafficFlowRaw.__table__.c
        inserted = 0
        for i in range(0, len(rows), self._CHUNK):
            chunk = rows[i:i + self._CHUNK]
            with self._sf.begin() as s:
                # Pre-upsert snapshot: which of these flow_hashes already exist?
                # Used below to fire the SIEM enqueue only for genuinely new rows.
                hashes = [r["flow_hash"] for r in chunk]
                existing = set(s.execute(
                    select(PceTrafficFlowRaw.flow_hash)
                    .where(PceTrafficFlowRaw.flow_hash.in_(hashes))
                ).scalars())
                base = sqlite_insert(PceTrafficFlowRaw).values(chunk)
                set_ = {c: func.max(raw_cols[c], base.excluded[c]) for c in self._VOLATILE}
                # report_json reflects the (refreshed) counters; take the latest.
                set_["report_json"] = base.excluded.report_json
                # re-pull 一律 bump 到本次 ingest 時間，讓 archiver 游標重新看到本列。
                set_["ingested_at"] = base.excluded.ingested_at
                stmt = (
                    base
                    .on_conflict_do_update(index_elements=["flow_hash"], set_=set_)
                    .returning(PceTrafficFlowRaw.id, PceTrafficFlowRaw.flow_hash)
                )
                # RETURNING covers inserts AND updates; new rows = those whose
                # flow_hash was absent in the pre-upsert snapshot.
                new_ids = [rid for rid, fh in s.execute(stmt) if fh not in existing]
                inserted += len(new_ids)
                if self._siem_dests and new_ids:
                    s.execute(
                        sqlite_insert(SiemDispatch),
                        [
                            {
                                "source_table": "pce_traffic_flows_raw",
                                "source_id": rid,
                                "destination": dest,
                                "status": "pending",
                                "retries": 0,
                                "queued_at": now,
                            }
                            for rid in new_ids for dest in self._siem_dests
                        ],
                    )
        return inserted


def _flow_hash(flow: dict) -> str:
    src_wl = (flow.get("src") or {}).get("workload") or {}
    dst_wl = (flow.get("dst") or {}).get("workload") or {}
    svc = flow.get("service") or {}
    key = "|".join([
        flow.get("src_ip", "") or src_wl.get("href", ""),
        flow.get("dst_ip", "") or dst_wl.get("href", ""),
        str(svc.get("port", "") or flow.get("port", "")),
        str(svc.get("proto", "") or flow.get("protocol", "")),
        _ts(flow, "first_detected"),
    ])
    return hashlib.sha1(key.encode("utf-8"), usedforsecurity=False).hexdigest()


def _ts(flow: dict, key: str) -> str:
    """Extract first/last_detected from top-level or nested timestamp_range."""
    return flow.get(key) or (flow.get("timestamp_range") or {}).get(key, "")


def _proto_to_str(proto) -> str:
    if proto is None:
        return "tcp"
    if isinstance(proto, str):
        return proto
    _MAP = {6: "tcp", 17: "udp", 1: "icmp"}
    return _MAP.get(int(proto), str(proto))


def _flatten_flow(flow: dict) -> dict:
    """Return a flat-field view of flow for filter/sampler checks (handles nested PCE API format)."""
    svc = flow.get("service") or {}
    src = flow.get("src") or {}
    return {
        "action": flow.get("action") or flow.get("policy_decision", "unknown"),
        "src_ip": flow.get("src_ip", "") or src.get("ip", ""),
        "port": svc.get("port") if svc else flow.get("port"),
        "protocol": _proto_to_str(svc.get("proto") if svc else flow.get("protocol")),
    }


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
