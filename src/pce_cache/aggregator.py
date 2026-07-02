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
        # bucket_day 是 TEXT 欄位，SQLite 用字串比較做 range query，格式必須跟
        # reader 端 SQLAlchemy 綁的 datetime 逐字元一致（含微秒），否則
        # "...00:00:00" < "...00:00:00.000000"，午夜 start 會漏讀當日 bucket。
        # 用 strftime 直接輸出目標格式，取代舊的 datetime(..., 'start of day')。
        day_col = func.strftime(
            "%Y-%m-%d 00:00:00.000000", PceTrafficFlowRaw.last_detected
        )
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
        # MAX(existing, recomputed) instead of plain overwrite. Raw has 7-day
        # retention but agg keeps 90 days, so agg outlives the raw rows it was
        # built from. As retention deletes a bucket's raw rows, a re-aggregation
        # recomputes that bucket from only the surviving sliver; a plain
        # overwrite would shrink the previously-correct full sum downward and,
        # once all the day's raw is gone, freeze the bucket at that corrupted
        # value. MAX keeps the historical peak while still letting a same-day
        # bucket grow as new raw arrives, and stays idempotent (MAX(x,x)=x).
        agg_cols = PceTrafficFlowAgg.__table__.c
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                "bucket_day", "src_workload", "dst_workload",
                "port", "protocol", "action",
            ],
            set_={
                "flow_count": func.max(agg_cols.flow_count, stmt.excluded.flow_count),
                "bytes_total": func.max(agg_cols.bytes_total, stmt.excluded.bytes_total),
            },
        )
        with self._sf.begin() as s:
            result = s.execute(stmt)
            return result.rowcount or 0
