from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import orjson
from loguru import logger
from sqlalchemy.exc import IntegrityError
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
                    self._wm.advance(self.SOURCE)
                    events = self._api.get_events_async(since=since, rate_limit=True)
        except Exception as exc:
            logger.exception("Events ingest failed: {}", exc)
            self._wm.record_error(self.SOURCE, str(exc))
            return 0

        inserted = self._insert_batch(events)
        if events:
            last = max(e["timestamp"] for e in events)
            last_href = events[-1].get("href", "")
            self._wm.advance(self.SOURCE, last_timestamp=_parse_iso(last), last_href=last_href)
        return inserted

    def _since_cursor(self) -> str:
        # PCE rejects timestamps without a tz marker (HTTP 406 invalid_timestamp).
        # SQLite + SQLAlchemy DateTime(timezone=True) returns naive datetimes on
        # read, so always re-attach UTC. Cold start defaults to 24h ago to mirror
        # get_traffic_flows_async.
        wm = self._wm.get(self.SOURCE)
        last = wm.last_timestamp if wm else None
        if last is None:
            last = datetime.now(timezone.utc) - timedelta(hours=24)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last.replace(microsecond=0).isoformat()

    def _insert_batch(self, events: list[dict]) -> int:
        now = datetime.now(timezone.utc)
        count = 0
        for ev in events:
            try:
                with self._sf.begin() as s:
                    row = PceEvent(
                        pce_href=ev.get("href", ""),
                        pce_event_id=ev.get("uuid", ev.get("href", ""))[-64:],
                        timestamp=_parse_iso(ev["timestamp"]),
                        event_type=ev.get("event_type", "unknown"),
                        severity=ev.get("severity", "info"),
                        status=ev.get("status", "success"),
                        pce_fqdn=ev.get("pce_fqdn", ""),
                        raw_json=orjson.dumps(ev).decode("utf-8"),
                        ingested_at=now,
                    )
                    s.add(row)
                    if self._siem_dests:
                        s.flush()
                        for dest in self._siem_dests:
                            s.add(SiemDispatch(
                                source_table="pce_events",
                                source_id=row.id,
                                destination=dest,
                                status="pending",
                                retries=0,
                                queued_at=now,
                            ))
            except IntegrityError:
                continue
            count += 1
        return count


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)
