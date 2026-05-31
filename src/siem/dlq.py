from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import DeadLetter, SiemDispatch


class DeadLetterQueue:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def list_entries(self, destination: str, limit: int = 50) -> list[DeadLetter]:
        with self._sf() as s:
            return s.execute(
                select(DeadLetter)
                .where(DeadLetter.destination == destination)
                .order_by(DeadLetter.quarantined_at.desc())
                .limit(limit)
            ).scalars().all()

    def replay(self, destination: str, limit: int = 100) -> int:
        """Requeue DLQ entries as new pending dispatch rows."""
        entries = self.list_entries(destination, limit=limit)
        if not entries:
            return 0
        now = datetime.now(timezone.utc)
        requeued = 0
        with self._sf.begin() as s:
            for entry in entries:
                s.add(SiemDispatch(
                    source_table=entry.source_table,
                    source_id=entry.source_id,
                    destination=destination,
                    status="pending",
                    retries=0,
                    queued_at=now,
                ))
                requeued += 1
        return requeued

    def replay_ids(self, ids: list[int]) -> list[dict]:
        """Requeue specific DLQ entries by id, returning per-item results."""
        now = datetime.now(timezone.utc)
        out = []
        with self._sf.begin() as s:
            for dl_id in ids:
                dl = s.get(DeadLetter, dl_id)
                if dl is None:
                    out.append({"id": dl_id, "ok": False, "error": "not found"})
                    continue
                s.add(SiemDispatch(
                    source_table=dl.source_table,
                    source_id=dl.source_id,
                    destination=dl.destination,
                    status="pending",
                    retries=0,
                    queued_at=now,
                ))
                out.append({"id": dl_id, "ok": True})
        return out

    def purge(self, destination: str, older_than_days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        with self._sf.begin() as s:
            r = s.execute(
                delete(DeadLetter)
                .where(DeadLetter.destination == destination)
                .where(DeadLetter.quarantined_at < cutoff)
            )
        return r.rowcount
