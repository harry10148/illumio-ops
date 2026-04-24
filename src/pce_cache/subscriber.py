from __future__ import annotations

from datetime import datetime, timezone

import orjson
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import (
    IngestionCursor, PceEvent, PceTrafficFlowRaw,
)

_MODEL_MAP = {
    "pce_events": PceEvent,
    "pce_traffic_flows_raw": PceTrafficFlowRaw,
}


class CacheSubscriber:
    def __init__(self, session_factory: sessionmaker, consumer: str, source_table: str):
        if source_table not in _MODEL_MAP:
            raise ValueError(f"Unknown source_table: {source_table}")
        self._sf = session_factory
        self._consumer = consumer
        self._source = source_table
        self._model = _MODEL_MAP[source_table]

    def poll_new_rows(self, limit: int = 1000) -> list[dict]:
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
        self._write_cursor(last_row.ingested_at, last_row.id)
        return [_row_to_dict(r) for r in rows]

    def _read_cursor(self) -> tuple[datetime | None, int | None]:
        with self._sf() as s:
            row = s.get(IngestionCursor, (self._consumer, self._source))
        if row is None:
            return (None, None)
        return (row.last_ingested_at, row.last_row_id)

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
            pass
    # Fallback minimal projection
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
