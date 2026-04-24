"""Safe event polling with watermark and dedup semantics."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import Any

def parse_event_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(dt.timezone.utc)
    except ValueError:
        return None

def format_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def event_identity(event: dict[str, Any]) -> str:
    href = str(event.get("href") or "").strip()
    if href:
        return href

    fingerprint = {
        "event_type": event.get("event_type"),
        "timestamp": event.get("timestamp"),
        "status": event.get("status"),
        "severity": event.get("severity"),
        "created_by": event.get("created_by"),
        "resource": event.get("resource"),
        "message": event.get("message"),
    }
    encoded = json.dumps(fingerprint, sort_keys=True, ensure_ascii=True, default=str)
    return "sha1:" + hashlib.sha1(encoded.encode("utf-8")).hexdigest()

@dataclass
class EventBatch:
    events: list[dict[str, Any]]
    next_watermark: str
    query_since: str
    query_until: str
    raw_count: int
    overflow_risk: bool
    seen_events: dict[str, str]

class EventPoller:
    def __init__(self, api_client, max_results: int = 5000, overlap_seconds: int = 60,
                 subscriber=None):
        self.api = api_client
        self.max_results = max_results
        self.overlap_seconds = overlap_seconds
        self._subscriber = subscriber

    def poll(self) -> list[dict[str, Any]]:
        """Return new events from either the cache subscriber or the legacy API path."""
        if self._subscriber is not None:
            return self._subscriber.poll_new_rows(limit=self.max_results)
        return self._legacy_poll()

    def _legacy_poll(self) -> list[dict[str, Any]]:
        """Thin wrapper kept for testability; real logic lives in fetch_batch."""
        batch = self.fetch_batch(watermark=None)
        return batch.events

    def fetch_batch(self, watermark: str | None, seen_events: dict[str, str] | None = None) -> EventBatch:
        poll_started_at = dt.datetime.now(dt.timezone.utc)
        watermark_dt = parse_event_timestamp(watermark) or poll_started_at
        query_since_dt = watermark_dt - dt.timedelta(seconds=self.overlap_seconds)
        query_since = format_utc(query_since_dt)
        query_until = format_utc(poll_started_at)

        raw_events = self.api.fetch_events_strict(
            start_time_str=query_since,
            end_time_str=query_until,
            max_results=self.max_results,
        )
        overflow_risk = len(raw_events) >= self.max_results

        seen = dict(seen_events or {})
        deduped: list[dict[str, Any]] = []
        for event in sorted(
            raw_events,
            key=lambda item: parse_event_timestamp(item.get("timestamp")) or poll_started_at,
        ):
            identity = event_identity(event)
            if identity in seen:
                continue
            event_ts = parse_event_timestamp(event.get("timestamp")) or poll_started_at
            seen[identity] = format_utc(event_ts)
            deduped.append(event)

        latest_event_ts = max(
            (parse_event_timestamp(item.get("timestamp")) for item in raw_events),
            default=None,
        )
        watermark_candidates = [poll_started_at, watermark_dt]
        if latest_event_ts is not None:
            watermark_candidates.append(latest_event_ts)
        next_watermark = format_utc(max(watermark_candidates))

        return EventBatch(
            events=deduped,
            next_watermark=next_watermark,
            query_since=query_since,
            query_until=query_until,
            raw_count=len(raw_events),
            overflow_risk=overflow_risk,
            seen_events=seen,
        )
