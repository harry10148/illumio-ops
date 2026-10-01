from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.events_fetch import EventsFetchError, fetch_events_drained
from src.pce_cache.models import PceEvent, SiemDispatch
from src.pce_cache.watermark import WatermarkStore


class EventsIngestor:
    SOURCE = "events"

    def __init__(
        self,
        api,
        session_factory: sessionmaker,
        watermark: WatermarkStore,
        async_threshold: int = 10000,
        siem_destinations: Optional[list[str]] = None,
        write_lock=None,
        overlap: timedelta = timedelta(minutes=20),
    ):
        self._api = api
        self._sf = session_factory
        self._wm = watermark
        self._async_threshold = async_threshold
        self._siem_dests = list(siem_destinations or [])
        self._write_lock = write_lock
        self._overlap = overlap
        # Set by run_once() when the sync events pull hit max_results and the
        # async fallback did not drain the window — the PCE returns only the
        # NEWEST rows at the cap, so older events in that window are lost for
        # good. Shape mirrors TrafficIngestor.last_run_overflow /
        # Analyzer.state["event_overflow"] so run_events_ingest can persist it
        # and Analyzer._maybe_alert_overflow can alert on it unchanged.
        self.last_run_overflow: Optional[dict] = None

    def run_once(self, *, force_async: bool = False) -> int:
        """拉 [watermark − overlap, now] 的事件寫入 cache。

        force_async 僅為簽名相容保留（舊版走 get_events_async stub）；現在一律
        以 fetch_events_drained 帶明確結束時間抓取，碰上限就二分抽乾。
        """
        until_dt = datetime.now(timezone.utc).replace(microsecond=0)
        since_dt = self._since_dt()
        self.last_run_overflow = None
        try:
            result = fetch_events_drained(
                self._api, since_dt, until_dt, max_results=self._async_threshold)
        except EventsFetchError as exc:
            # ApiClient 把連線層失敗（DNS/refused/timeout）吞成空清單、只寫
            # last_fetch_error——`events == []` 分不出「PCE 不可達」與「真的
            # 沒有新事件」，所以視同失敗記錄（見 watchdog-live-reverify-report.md）。
            logger.error("Events ingest: PCE fetch reported an error — {}", exc)
            with self._write_context():
                self._wm.record_error(self.SOURCE, str(exc))
            return 0
        except Exception as exc:
            logger.exception("Events ingest failed: {}", exc)
            with self._write_context():
                self._wm.record_error(self.SOURCE, str(exc))
            return 0

        events = result.events
        if result.truncated:
            windows = result.truncated_windows
            self.last_run_overflow = {
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "query_since": min(w["since"] for w in windows),
                "query_until": max(w["until"] for w in windows),
                "raw_count": sum(w["count"] for w in windows),
                "max_results": self._async_threshold,
                "window_count": len(windows),
                # 來源標記：Analyzer 的 cache 分支只清「legacy pull 留下的」
                # 陳舊紀錄，看到這個來源就不清（見 _run_event_analysis）。
                "source": "cache_ingest",
            }

        try:
            with self._write_context():
                inserted = self._insert_batch(events)
                if events:
                    last = max(_parse_iso(e["timestamp"]) for e in events)
                    # 不超過這次查詢的結束時間：VEN 時鐘偏快送來「未來」時間戳
                    # 時，watermark 若被推到未來，overlap 也蓋不回這段期間。
                    last = min(_aware(last), until_dt)
                    self._wm.advance(
                        self.SOURCE,
                        last_timestamp=last,
                        last_href=events[-1].get("href", ""),
                    )
            return inserted
        except Exception as exc:
            # insert/advance 失敗：記 error 再 re-raise（run_events_ingest 會 logger.exception）。
            with self._write_context():
                self._wm.record_error(self.SOURCE, str(exc))
            raise

    def _write_context(self):
        return self._write_lock if self._write_lock is not None else nullcontext()

    def _since_dt(self) -> datetime:
        # SQLite + SQLAlchemy DateTime(timezone=True) 讀回 naive datetime，一律補
        # UTC（PCE 拒收沒有時區的時間戳：HTTP 406 invalid_timestamp）。
        # 冷啟動往回 24 小時，比照 get_traffic_flows_async。
        wm = self._wm.get(self.SOURCE)
        last = wm.last_timestamp if wm else None
        if last is None:
            last = datetime.now(timezone.utc) - timedelta(hours=24)
        else:
            # Overlap：事件時間戳是「發生時間」不是「寫入 PCE 的時間」，VEN 離線
            # 期間的事件重連後才上送；多節點 PCE 的事件也可能亂序晚到。往回重抓
            # overlap（預設 20 分鐘＝兩個 VEN 上報週期）；pce_href unique +
            # ON CONFLICT DO NOTHING 讓重抓完全冪等。
            last = _aware(last) - self._overlap
        return _aware(last).replace(microsecond=0)

    def _since_cursor(self) -> str:
        return self._since_dt().isoformat()

    _CHUNK = 500

    def _insert_batch(self, events: list[dict]) -> int:
        """Bulk-insert events in chunks with ON CONFLICT DO NOTHING (dedup by
        pce_href) — one transaction per chunk, not per row. RETURNING yields the
        newly-inserted ids that drive the per-event SIEM enqueue."""
        now = datetime.now(timezone.utc)
        rows: list[dict] = []
        seen: set[str] = set()
        for ev in events:
            href = ev.get("href", "")
            if href in seen:        # collapse duplicates within this batch
                continue
            seen.add(href)
            rows.append({
                "pce_href": href,
                "pce_event_id": ev.get("uuid", ev.get("href", ""))[-64:],
                "timestamp": _parse_iso(ev["timestamp"]),
                "event_type": ev.get("event_type", "unknown"),
                "severity": ev.get("severity", "info"),
                "status": ev.get("status") or "success",  # coerce explicit null/"" → NOT NULL col
                "pce_fqdn": ev.get("pce_fqdn", ""),
                "raw_json": orjson.dumps(ev).decode("utf-8"),
                "ingested_at": now,
            })
        inserted = 0
        for i in range(0, len(rows), self._CHUNK):
            chunk = rows[i:i + self._CHUNK]
            with self._sf.begin() as s:
                stmt = (
                    sqlite_insert(PceEvent)
                    .values(chunk)
                    .on_conflict_do_nothing(index_elements=["pce_href"])
                    .returning(PceEvent.id)
                )
                new_ids = [r[0] for r in s.execute(stmt)]
                inserted += len(new_ids)
                if self._siem_dests and new_ids:
                    s.execute(
                        sqlite_insert(SiemDispatch),
                        [
                            {
                                "source_table": "pce_events",
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


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
