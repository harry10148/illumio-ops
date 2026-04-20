from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


class TrafficAggregator:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def run_once(self) -> int:
        """Rollup raw flows into daily agg. Idempotent via ON CONFLICT DO UPDATE."""
        day_col = func.date(PceTrafficFlowRaw.last_detected)
        q = (
            select(
                day_col.label("bucket_day"),
                PceTrafficFlowRaw.src_workload,
                PceTrafficFlowRaw.dst_workload,
                PceTrafficFlowRaw.port,
                PceTrafficFlowRaw.protocol,
                PceTrafficFlowRaw.action,
                func.sum(PceTrafficFlowRaw.flow_count).label("flow_count"),
                func.sum(
                    PceTrafficFlowRaw.bytes_in + PceTrafficFlowRaw.bytes_out
                ).label("bytes_total"),
            )
            .group_by(
                day_col,
                PceTrafficFlowRaw.src_workload,
                PceTrafficFlowRaw.dst_workload,
                PceTrafficFlowRaw.port,
                PceTrafficFlowRaw.protocol,
                PceTrafficFlowRaw.action,
            )
        )
        count = 0
        with self._sf.begin() as s:
            for row in s.execute(q):
                # Convert date string back to datetime at midnight UTC
                bucket_day = datetime.strptime(row.bucket_day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                stmt = sqlite_insert(PceTrafficFlowAgg.__table__).values(
                    bucket_day=bucket_day,
                    src_workload=row.src_workload,
                    dst_workload=row.dst_workload,
                    port=row.port,
                    protocol=row.protocol,
                    action=row.action,
                    flow_count=int(row.flow_count),
                    bytes_total=int(row.bytes_total),
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        "bucket_day", "src_workload", "dst_workload",
                        "port", "protocol", "action",
                    ],
                    set_={
                        "flow_count": stmt.excluded.flow_count,
                        "bytes_total": stmt.excluded.bytes_total,
                    },
                )
                s.execute(stmt)
                count += 1
        return count
