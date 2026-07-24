from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

import orjson
from loguru import logger
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    IngestionCursor, PceEvent, PceTrafficFlowRaw,
)

_MODEL_MAP = {
    "pce_events": PceEvent,
    "pce_traffic_flows_raw": PceTrafficFlowRaw,
}

# fetch_window_rows 的事件時間欄（非 ingested_at：規則視窗語意看事件時間）
_TIME_COL = {
    "pce_events": "timestamp",
    "pce_traffic_flows_raw": "last_detected",
}


class CacheSubscriber:
    def __init__(self, session_factory: sessionmaker, consumer: str, source_table: str):
        if source_table not in _MODEL_MAP:
            raise ValueError(f"Unknown source_table: {source_table}")
        self._sf = session_factory
        self._consumer = consumer
        self._source = source_table
        self._model = _MODEL_MAP[source_table]

    def poll_new_rows(
        self,
        limit: int = 1000,
        processor: Optional[Callable[[list[dict]], None]] = None,
    ) -> list[dict]:
        """Return rows newer than this consumer's cursor and advance it.

        processor: optional at-least-once hook. When given, the batch is handed
        to processor() FIRST and the cursor is advanced only after it returns
        without raising — so a consumer crash mid-processing leaves the cursor
        put and the rows are re-delivered next poll instead of being silently
        skipped. When omitted, the cursor advances immediately (legacy
        at-most-once behaviour, kept for existing callers).
        """
        last_ts, last_id = self._read_cursor()
        with self._sf() as s:
            q = select(self._model).order_by(self._model.ingested_at, self._model.id).limit(limit)
            if last_ts is not None:
                q = q.where(
                    or_(
                        self._model.ingested_at > last_ts,
                        and_(self._model.ingested_at == last_ts, self._model.id > last_id),
                    )
                )
            rows = s.execute(q).scalars().all()
        if not rows:
            return []
        last_row = rows[-1]
        dicts = [_row_to_dict(r) for r in rows]
        if processor is not None:
            processor(dicts)  # may raise → cursor below is not reached
        self._write_cursor(last_row.ingested_at, last_row.id)
        return dicts

    def _read_cursor(self) -> tuple[datetime | None, int | None]:
        with self._sf() as s:
            row = s.get(IngestionCursor, (self._consumer, self._source))
        if row is None:
            return (None, None)
        return (row.last_ingested_at, row.last_row_id)

    def fetch_window_rows(self, since: datetime, limit: int = 10000) -> list[dict]:
        """全視窗查詢（**不動 cursor**）。

        規則引擎的 threshold_window 加總需要「視窗內全部列」；cursor 增量
        （poll_new_rows）會把有效視窗退化成單次輪詢間隔，在 30s cycle 的
        cache 部署上造成嚴重漏告警（2026-07-24 審查 A1）。
        """
        col = getattr(self._model, _TIME_COL[self._source])
        with self._sf() as s:
            # desc + reverse：若視窗列數超過 limit，被丟掉的是「最舊」而非
            # 「最新」的列（threshold/window 規則最關心近期）；回傳仍升冪。
            rows = s.execute(
                select(self._model).where(col >= since)
                .order_by(col.desc()).limit(limit)
            ).scalars().all()
        if len(rows) >= limit:
            # 不可靜默截斷（專案鐵則）：視窗加總會低估，門檻告警可能漏發。
            logger.warning(
                "fetch_window_rows truncated: {} window since={} hit limit={}; "
                "oldest in-window rows dropped — threshold sums may undercount",
                self._source, since, limit,
            )
        return [_row_to_dict(r) for r in reversed(rows)]

    def _write_cursor(self, ts: datetime, row_id: int) -> None:
        now = datetime.now(timezone.utc)
        with self._sf.begin() as s:
            row = s.get(IngestionCursor, (self._consumer, self._source))
            if row is None:
                row = IngestionCursor(consumer=self._consumer, source_table=self._source,
                                      updated_at=now)
                s.add(row)
            row.last_ingested_at = ts
            row.last_row_id = row_id
            row.updated_at = now


def _row_to_dict(row) -> dict:
    if hasattr(row, "raw_json") and row.raw_json:
        try:
            parsed = orjson.loads(row.raw_json)
            if parsed:
                return parsed
        except orjson.JSONDecodeError:
            # 降級成欄位投影（缺 raw payload 細節）——要留下損毀證據
            logger.warning("corrupt cached payload row id={}; falling back to column projection",
                           getattr(row, "id", "?"))
    # Fallback minimal projection
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
