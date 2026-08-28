from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import DeadLetter, SiemDispatch


class DeadLetterQueue:
    def __init__(self, session_factory: sessionmaker):
        self._sf = session_factory

    def list_entries(self, destination: str = "", limit: int = 50) -> list[DeadLetter]:
        """Entries for one destination — or for every destination when
        `destination` is blank.

        The GUI's destination filter and the CLI both carry "" for "all", and
        dlq_export (src/siem/web.py) already reads a blank dest that way. This
        used to filter on `destination == ""` instead, which matches no real
        row, so the DLQ page's DEFAULT "All" view showed nothing at all.
        """
        q = select(DeadLetter)
        if destination:
            q = q.where(DeadLetter.destination == destination)
        with self._sf() as s:
            return s.execute(
                q.order_by(DeadLetter.quarantined_at.desc()).limit(limit)
            ).scalars().all()

    def replay(self, destination: str, limit: int = 100) -> int:
        """Requeue DLQ entries as new pending dispatch rows."""
        # replay() reads its rows through list_entries(), which now treats a
        # blank destination as "every destination". Replay must NOT inherit
        # that: both callers (POST /api/siem/dlq/replay's dest branch and
        # `siem replay --dest`) are destination-scoped, so a blank dest is a
        # caller mistake — keep it the no-op it has always been rather than
        # silently mass-requeuing the whole queue.
        if not destination:
            return 0
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
            # Remove the replayed DLQ entries in the same transaction so the
            # queue reflects reality and a second replay can't re-enqueue them
            # (avoids double-forwarding the same source record to the SIEM).
            s.execute(
                delete(DeadLetter).where(
                    DeadLetter.id.in_([entry.id for entry in entries])
                )
            )
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
                # Delete the replayed entry so a repeat replay is a no-op
                # ('not found') instead of re-enqueuing a duplicate dispatch.
                s.delete(dl)
                out.append({"id": dl_id, "ok": True})
        return out

    def purge_ids(self, ids: list[int]) -> list[dict]:
        """Delete specific DLQ entries by id, returning per-item results.

        The symmetric twin of replay_ids(): the GUI's "Purge Selected" now
        purges exactly the rows the operator ticked, so an id that someone
        else already removed has to say so per item rather than disappear
        into an aggregate count.
        """
        out = []
        with self._sf.begin() as s:
            for dl_id in ids:
                dl = s.get(DeadLetter, dl_id)
                if dl is None:
                    out.append({"id": dl_id, "ok": False, "error": "not found"})
                    continue
                s.delete(dl)
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
