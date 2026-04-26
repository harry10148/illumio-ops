from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import orjson
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowAgg, PceTrafficFlowRaw

CoverState = Literal["full", "partial", "miss"]


class CacheReader:
    def __init__(
        self,
        session_factory: sessionmaker,
        events_retention_days: int,
        traffic_raw_retention_days: int,
    ):
        self._sf = session_factory
        self._events_days = events_retention_days
        self._traffic_days = traffic_raw_retention_days

    def cover_state(self, source: str, start: datetime, end: datetime) -> CoverState:
        days = self._events_days if source == "events" else self._traffic_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        if end < cutoff:
            return "miss"
        if start < cutoff:
            return "partial"
        earliest = self.earliest_ingested_at(source)
        if earliest is None or start < earliest:
            return "partial"
        return "full"

    def earliest_ingested_at(self, source: str) -> datetime | None:
        table = PceEvent if source == "events" else PceTrafficFlowRaw
        with self._sf() as s:
            result = s.execute(select(func.min(table.ingested_at))).scalar()
            if result is None:
                return None
            # SQLite aggregate functions return naive datetimes; restore UTC timezone
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
            return result

    def read_events(self, start: datetime, end: datetime) -> list[dict]:
        with self._sf() as s:
            q = (
                select(PceEvent)
                .where(PceEvent.timestamp >= start, PceEvent.timestamp <= end)
                .order_by(PceEvent.timestamp)
            )
            return [orjson.loads(r.raw_json) for r in s.execute(q).scalars()]

    def read_flows_raw(self, start: datetime, end: datetime) -> list[dict]:
        with self._sf() as s:
            q = (
                select(PceTrafficFlowRaw)
                .where(
                    PceTrafficFlowRaw.last_detected >= start,
                    PceTrafficFlowRaw.last_detected <= end,
                )
                .order_by(PceTrafficFlowRaw.last_detected)
            )
            return [orjson.loads(r.raw_json) for r in s.execute(q).scalars()]

    def read_flows_agg(self, start: datetime, end: datetime) -> list[dict]:
        with self._sf() as s:
            q = (
                select(PceTrafficFlowAgg)
                .where(
                    PceTrafficFlowAgg.bucket_day >= start,
                    PceTrafficFlowAgg.bucket_day <= end,
                )
                .order_by(PceTrafficFlowAgg.bucket_day)
            )
            return [
                {
                    "bucket_day": row.bucket_day,
                    "src_workload": row.src_workload,
                    "dst_workload": row.dst_workload,
                    "port": row.port,
                    "protocol": row.protocol,
                    "action": row.action,
                    "flow_count": row.flow_count,
                    "bytes_total": row.bytes_total,
                }
                for row in s.execute(q).scalars()
            ]
