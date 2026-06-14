from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceTrafficFlowAgg, PceTrafficFlowRaw


class TrafficAggregator:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def run_once(self) -> int:
        """Rollup raw flows into daily agg in a single set-based statement.

        One INSERT…SELECT…GROUP BY…ON CONFLICT DO UPDATE — not a per-group Python
        loop (which was O(groups) round-trips and timed out on a large cache).

        src/dst_workload are coalesced to '' because the dedup unique index
        (ix_agg_unique) spans them and SQLite treats NULL as DISTINCT — so
        unmanaged endpoints (NULL workload) would never collide, and every run
        would re-insert them, ballooning the table. '' is a single value that
        dedups correctly.
        """
        src_wl = func.coalesce(PceTrafficFlowRaw.src_workload, "")
        dst_wl = func.coalesce(PceTrafficFlowRaw.dst_workload, "")
        # 'start of day' yields a parseable "YYYY-MM-DD 00:00:00" datetime string
        # in pure SQL, avoiding a Python date→datetime conversion per row.
        day_col = func.datetime(PceTrafficFlowRaw.last_detected, "start of day")
        sel = (
            select(
                day_col,
                src_wl,
                dst_wl,
                PceTrafficFlowRaw.port,
                PceTrafficFlowRaw.protocol,
                PceTrafficFlowRaw.action,
                func.sum(PceTrafficFlowRaw.flow_count),
                func.sum(PceTrafficFlowRaw.bytes_in + PceTrafficFlowRaw.bytes_out),
            )
            .group_by(
                day_col,
                src_wl,
                dst_wl,
                PceTrafficFlowRaw.port,
                PceTrafficFlowRaw.protocol,
                PceTrafficFlowRaw.action,
            )
        )
        stmt = sqlite_insert(PceTrafficFlowAgg.__table__).from_select(
            ["bucket_day", "src_workload", "dst_workload", "port",
             "protocol", "action", "flow_count", "bytes_total"],
            sel,
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
        with self._sf.begin() as s:
            result = s.execute(stmt)
            return result.rowcount or 0
