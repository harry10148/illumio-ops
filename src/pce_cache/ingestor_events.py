from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

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
    ):
        self._api = api
        self._sf = session_factory
        self._wm = watermark
        self._async_threshold = async_threshold
        self._siem_dests = list(siem_destinations or [])

    def run_once(self, *, force_async: bool = False) -> int:
        since = self._since_cursor()
        try:
            if force_async:
                events = self._api.get_events_async(since=since, rate_limit=True)
            else:
                events = self._api.get_events(
                    max_results=self._async_threshold,
                    since=since,
                    rate_limit=True,
                )
                if len(events) >= self._async_threshold:
                    logger.info(
                        "Events sync pull hit cap ({}), switching to async",
                        self._async_threshold,
                    )
                    events_async = self._api.get_events_async(since=since, rate_limit=True)
                    # get_events_async is an unimplemented stub returning [] (Phase
                    # 13). Never let its empty result clobber the already-fetched
                    # sync batch: discarding it loses up to `cap` events, and with
                    # no max timestamp the watermark can't advance, so the next
                    # poll re-fetches and re-discards forever (permanent stall +
                    # total loss above the threshold). Keep the sync batch; the
                    # advance below pages forward to its max timestamp.
                    if events_async:
                        events = events_async
        except Exception as exc:
            logger.exception("Events ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        # get_events()/get_events_async() route through ApiClient.fetch_events(),
        # which swallows connection-layer PCE failures (DNS/refused/timeout)
        # into an empty list instead of raising — so `events == []` alone can't
        # tell "PCE unreachable" apart from "genuinely no new events". ApiClient
        # surfaces the swallowed failure on last_fetch_error; treat it the same
        # as the except-branch above (see watchdog-live-reverify-report.md step 2).
        fetch_error = getattr(self._api, "last_fetch_error", None)
        # isinstance guard: many tests pass a bare MagicMock() as `api`, whose
        # unconfigured attributes auto-vivify into truthy child Mocks rather
        # than None — without this guard every such test would spuriously
        # trip the error path. The real ApiClient contract is always str|None.
        if isinstance(fetch_error, str) and fetch_error:
            logger.error("Events ingest: PCE fetch reported an error — {}", fetch_error)
            self._wm.record_error(self.SOURCE, fetch_error)
            return 0

        try:
            inserted = self._insert_batch(events)
            if events:
                last = max(e["timestamp"] for e in events)
                last_href = events[-1].get("href", "")
                self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last), last_href=last_href)
            return inserted
        except Exception as exc:
            # insert/advance 失敗：記 error 再 re-raise（run_events_ingest 會 logger.exception）。
            self._wm.record_error(self.SOURCE, str(exc))
            raise

    def _since_cursor(self) -> str:
        # PCE rejects timestamps without a tz marker (HTTP 406 invalid_timestamp).
        # SQLite + SQLAlchemy DateTime(timezone=True) returns naive datetimes on
        # read, so always re-attach UTC. Cold start defaults to 24h ago to mirror
        # get_traffic_flows_async.
        wm = self._wm.get(self.SOURCE)
        last = wm.last_timestamp if wm else None
        if last is None:
            last = datetime.now(timezone.utc) - timedelta(hours=24)
        else:
            # Grace window：多節點 PCE（schema 逐事件記 pce_fqdn）的事件可能
            # 亂序晚到；watermark 只有秒級 flooring（~1s 容忍），比照 traffic
            # ingestor 的 5 分鐘 re-pull。pce_href unique + ON CONFLICT DO
            # NOTHING 讓重拉完全冪等。
            last = last - timedelta(minutes=5)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last.replace(microsecond=0).isoformat()

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


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
