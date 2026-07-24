from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    IngestionCursor, PceTrafficFlowAgg, PceTrafficFlowRaw,
)

# aggregator 自身的 raw 消費游標（IngestionCursor 既有模式，同 archiver/
# subscriber）：記錄上一輪 run_once 已看過的 max(ingested_at)，用來偵測
# 「新進但屬於舊日期」的 backfill 列（見 run_once 的 backfill_floor）。
_AGG_CONSUMER = "aggregator"
_AGG_SOURCE = "pce_traffic_flows_raw"


class TrafficAggregator:
    # 增量視窗：agg 非空時只重算近 N 天的 bucket。更舊 bucket 的 raw 只會因
    # retention 減少，而 MAX 合併本就把它們凍結在歷史峰值——略過重算與 MAX
    # 守門結果等價，把每小時全表掃描縮成 O(近幾天)。3 天 > ingest grace(5m)
    # 與跨午夜 bucket 移動的任何情境——但前提是 agg 沒有落後太多。
    #
    # cutoff 因此錨定 agg 表自身進度：min(now - _WINDOW_DAYS, max_agg_day - 1d)。
    # 穩態下 agg 跟得上，max_agg_day - 1d 比 now - _WINDOW_DAYS 新，min 取
    # now - _WINDOW_DAYS，行為與純牆鐘視窗完全相同。但 ingest 中斷超過
    # _WINDOW_DAYS 天恢復後，ingestor 會用舊 watermark 補拉多天 backlog；這些
    # raw 列的 last_detected 比純牆鐘 cutoff 舊，若不錨定 agg 進度就會被永遠
    # 跳過（agg 非空不觸發 bootstrap full-scan），backlog 在 raw retention
    # 到期後永久遺失。錨定後視窗自動加寬到 max_agg_day 前一天，backlog 全數
    # 納入；重疊日重算由既有 MAX-merge upsert 保證安全（見下方 MAX 註解）。
    _WINDOW_DAYS = 3

    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def run_once(self, full: bool = False) -> int:
        """Rollup raw flows into daily agg in a single set-based statement.

        One INSERT…SELECT…GROUP BY…ON CONFLICT DO UPDATE — not a per-group Python
        loop (which was O(groups) round-trips and timed out on a large cache).

        src/dst_workload are coalesced to '' because the dedup unique index
        (ix_agg_unique) spans them and SQLite treats NULL as DISTINCT — so
        unmanaged endpoints (NULL workload) would never collide, and every run
        would re-insert them, ballooning the table. '' is a single value that
        dedups correctly.
        """
        # 先快照 raw 目前的 max(ingested_at)：聚合期間新 commit 的列留給
        # 下一輪（游標推進不得越過本輪實際看得到的範圍）。
        max_ingested = self._max_raw_ingested_at()
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
        if not full and self._has_agg_rows():
            window_cutoff = datetime.now(timezone.utc) - timedelta(days=self._WINDOW_DAYS)
            cutoff = min(window_cutoff, self._max_agg_day() - timedelta(days=1))
            # Backfill 防護：backfill 灌入的列 ingested_at=now 但 last_detected
            # 在數週/數月前——牆鐘視窗與 max_agg_day 錨點都照不到（max_agg_day
            # 穩態在「今天」），這些 bucket 永遠不會被聚合，raw retention 到期
            # 後永久遺失。改用 aggregator 自身游標找出「上輪之後新進」的列，
            # 把 cutoff 擴到它們的最早 last_detected；重疊日重算由 MAX-merge
            # upsert 保證冪等。不再依賴呼叫端記得帶 full=True（web.py 有帶、
            # CLI backfill 沒帶——2026-07-25 審查）。
            backfill_floor = self._min_new_last_detected()
            if backfill_floor is not None:
                cutoff = min(cutoff, backfill_floor)
            sel = sel.where(PceTrafficFlowRaw.last_detected >= cutoff)
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
            rowcount = result.rowcount or 0
        self._advance_cursor(max_ingested)
        return rowcount

    def _max_raw_ingested_at(self) -> datetime | None:
        with self._sf() as s:
            return s.execute(
                select(func.max(PceTrafficFlowRaw.ingested_at))).scalar()

    def _min_new_last_detected(self) -> datetime | None:
        """上輪游標之後新進（ingested_at 較新）的 raw 列中最早的 last_detected；
        無游標（首次跑此版程式碼）時看整表——一次性把既有未聚合的舊日期補齊。"""
        with self._sf() as s:
            cur = s.get(IngestionCursor, (_AGG_CONSUMER, _AGG_SOURCE))
            cur_ts = cur.last_ingested_at if cur else None
            q = select(func.min(PceTrafficFlowRaw.last_detected))
            if cur_ts is not None:
                q = q.where(PceTrafficFlowRaw.ingested_at > cur_ts)
            floor = s.execute(q).scalar()
        if floor is not None and floor.tzinfo is None:
            floor = floor.replace(tzinfo=timezone.utc)
        return floor

    def _advance_cursor(self, ts: datetime | None) -> None:
        if ts is None:      # raw 表為空：沒有可推進的位置，游標維持原狀
            return
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            cur = s.get(IngestionCursor, (_AGG_CONSUMER, _AGG_SOURCE))
            if cur is None:
                cur = IngestionCursor(consumer=_AGG_CONSUMER,
                                      source_table=_AGG_SOURCE, updated_at=now)
                s.add(cur)
            cur.last_ingested_at = ts
            cur.updated_at = now

    def _has_agg_rows(self) -> bool:
        with self._sf() as s:
            return s.execute(
                select(PceTrafficFlowAgg.id).limit(1)).first() is not None

    def _max_agg_day(self) -> datetime:
        with self._sf() as s:
            max_day = s.execute(
                select(func.max(PceTrafficFlowAgg.bucket_day))).scalar_one()
        if max_day.tzinfo is None:
            max_day = max_day.replace(tzinfo=timezone.utc)
        return max_day
