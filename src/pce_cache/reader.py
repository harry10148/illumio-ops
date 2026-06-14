from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import orjson
from sqlalchemy import func, or_, select
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
        earliest = self.earliest_data_timestamp(source)
        if earliest is None or start < earliest:
            return "partial"
        return "full"

    def earliest_ingested_at(self, source: str) -> datetime | None:
        """MIN(ingested_at). Operational metric for ingest-lag monitoring.
        NOT used by cover_state — see earliest_data_timestamp for that.
        """
        table = PceEvent if source == "events" else PceTrafficFlowRaw
        with self._sf() as s:
            result = s.execute(select(func.min(table.ingested_at))).scalar()
            if result is None:
                return None
            # SQLite aggregate functions return naive datetimes; restore UTC timezone
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
            return result

    def earliest_data_timestamp(self, source: str) -> datetime | None:
        """MIN(last_detected) for traffic, MIN(timestamp) for events.
        Used by cover_state to judge cache coverage by ACTUAL data window,
        not by when rows were inserted (which would defeat backfill workflows).
        """
        if source == "events":
            col = PceEvent.timestamp
        else:
            col = PceTrafficFlowRaw.last_detected
        with self._sf() as s:
            result = s.execute(select(func.min(col))).scalar()
            if result is None:
                return None
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

    def read_flows_raw(self, start: datetime, end: datetime,
                       workload_hrefs: list[str] | None = None) -> list[dict]:
        """Read raw flows in [start, end].

        workload_hrefs: when given, return only flows where src OR dst workload
        is in the set (indexed columns). Lets app-scoped reports read just the
        app's flows instead of the whole estate. The src/dst columns are
        indexed, so this is a fast index scan, not a full-table read.
        """
        with self._sf() as s:
            q = (
                select(PceTrafficFlowRaw)
                .where(
                    PceTrafficFlowRaw.last_detected >= start,
                    PceTrafficFlowRaw.last_detected <= end,
                )
            )
            if workload_hrefs:
                hrefs = list(workload_hrefs)
                q = q.where(or_(
                    PceTrafficFlowRaw.src_workload.in_(hrefs),
                    PceTrafficFlowRaw.dst_workload.in_(hrefs),
                ))
            q = q.order_by(PceTrafficFlowRaw.last_detected)
            return [orjson.loads(r.raw_json) for r in s.execute(q).scalars()]

    def read_flows_df(self, start: datetime, end: datetime,
                      workload_hrefs: list[str] | None = None):
        """Build the unified report DataFrame directly from the cache.

        Uses the precomputed report_json (flatten cached at ingest) to skip the
        per-row re-flatten; rows ingested before report_json existed fall back to
        flattening their raw_json. Same assembly (build_unified_df) as the live
        APIParser, so the frame is identical regardless of source.
        """
        from src.report.parsers.api_parser import flatten_flow_record, build_unified_df
        with self._sf() as s:
            q = (
                select(PceTrafficFlowRaw.report_json, PceTrafficFlowRaw.raw_json)
                .where(
                    PceTrafficFlowRaw.last_detected >= start,
                    PceTrafficFlowRaw.last_detected <= end,
                )
            )
            if workload_hrefs:
                hrefs = list(workload_hrefs)
                q = q.where(or_(
                    PceTrafficFlowRaw.src_workload.in_(hrefs),
                    PceTrafficFlowRaw.dst_workload.in_(hrefs),
                ))
            q = q.order_by(PceTrafficFlowRaw.last_detected)
            rows = []
            for report_json, raw_json in s.execute(q):
                if report_json:
                    rows.append(orjson.loads(report_json))
                else:  # transition / pre-Tier-2a row
                    rows.append(flatten_flow_record(orjson.loads(raw_json)))
        return build_unified_df(rows, "cache")

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
