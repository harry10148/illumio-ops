from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import orjson
from sqlalchemy import func, or_, select
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent, PceTrafficFlowAgg, PceTrafficFlowRaw

CoverState = Literal["full", "partial", "miss"]


def _sqlite_dt(dt: datetime) -> str:
    """Format a datetime as the string SQLAlchemy's SQLite DateTime stores
    (UTC-naive, 6-digit microseconds), so raw-cursor text comparisons against
    last_detected match what the ORM bound. tz-aware inputs are converted to UTC
    first (the app works in UTC); naive inputs are used as-is."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


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
                      workload_hrefs: list[str] | None = None,
                      policy_decisions: list[str] | None = None):
        """Build the unified report DataFrame directly from the cache.

        Uses the precomputed report_json (flatten cached at ingest) to skip the
        per-row re-flatten; rows ingested before report_json existed fall back to
        flattening their raw_json. Same assembly (build_unified_df) as the live
        APIParser, so the frame is identical regardless of source.

        policy_decisions: when given, filter to those action/policy-decision
        values in SQL — both correctness (cache must honour the report's decision
        filter like the live API does) and perf (read only matching rows).

        Fetch goes through a raw DBAPI cursor (not the SQLAlchemy session): the
        ORM result-row wrapping costs ~40% extra over a plain sqlite3 cursor on a
        240k-row read (measured 19.8s vs 12.0s). The cursor comes from the same
        engine, so the connect-listener PRAGMAs (cache_size/mmap/busy_timeout/WAL)
        still apply. See docs/superpowers/specs/2026-06-14-cache-read-raw-cursor.md.
        """
        from src.report.parsers.api_parser import flatten_flow_record, build_unified_df

        # Shared WHERE for both queries. Datetime bounds are formatted to the
        # exact string SQLite stores (UTC-naive, 6-digit microseconds) so the
        # text comparison matches what SQLAlchemy bound before — and we pass
        # strings, sidestepping the Python 3.12 sqlite3 datetime-adapter warning.
        where = ["last_detected >= ?", "last_detected <= ?"]
        params: list = [_sqlite_dt(start), _sqlite_dt(end)]
        if workload_hrefs:
            hrefs = list(workload_hrefs)
            ph = ",".join("?" * len(hrefs))
            where.append(f"(src_workload IN ({ph}) OR dst_workload IN ({ph}))")
            params.extend(hrefs)
            params.extend(hrefs)
        if policy_decisions:
            decs = list(policy_decisions)
            ph = ",".join("?" * len(decs))
            where.append(f"action IN ({ph})")
            params.extend(decs)
        where_sql = " AND ".join(where)

        rows = []
        with self._sf() as s:
            cur = s.connection().connection.cursor()
            try:
                # Fast path: only read report_json (avoids transferring the ~1.2KB
                # raw_json blob per row when the flatten is already cached).
                cur.execute(
                    f"SELECT report_json FROM pce_traffic_flows_raw "
                    f"WHERE {where_sql} AND report_json IS NOT NULL "
                    f"ORDER BY last_detected", params)
                for (rj,) in cur:
                    rows.append(orjson.loads(rj))
                # Fallback: pre-Tier-2a rows without report_json → flatten raw_json.
                cur.execute(
                    f"SELECT raw_json FROM pce_traffic_flows_raw "
                    f"WHERE {where_sql} AND report_json IS NULL "
                    f"ORDER BY last_detected", params)
                for (raw,) in cur:
                    rows.append(flatten_flow_record(orjson.loads(raw)))
            finally:
                cur.close()
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
