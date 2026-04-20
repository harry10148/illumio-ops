from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import IngestionWatermark


class WatermarkStore:
    def __init__(self, session_factory: sessionmaker):
        self._session_factory = session_factory

    def get(self, source: str) -> Optional[IngestionWatermark]:
        with self._session_factory() as s:
            return s.get(IngestionWatermark, source)

    def advance(
        self,
        source: str,
        last_timestamp: Optional[datetime] = None,
        last_href: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as s:
            row = s.get(IngestionWatermark, source)
            if row is None:
                row = IngestionWatermark(source=source)
                s.add(row)
            if last_timestamp is not None:
                row.last_timestamp = last_timestamp
            if last_href is not None:
                row.last_href = last_href
            row.last_sync_at = now
            row.last_status = "ok"
            row.last_error = None

    def record_error(self, source: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory.begin() as s:
            row = s.get(IngestionWatermark, source)
            if row is None:
                row = IngestionWatermark(source=source)
                s.add(row)
            row.last_sync_at = now
            row.last_status = "error"
            row.last_error = error[:4000]
