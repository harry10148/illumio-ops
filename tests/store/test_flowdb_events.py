import json
from datetime import UTC, datetime
from pathlib import Path

from illumio_ops.domain.events import normalize_event
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.events import upsert_events

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "events_tamper.json"
NOW = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)


def test_events_upsert_idempotent(tmp_path):
    recs = [normalize_event(e) for e in json.loads(FIXTURE.read_text())]
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        assert upsert_events(conn, recs, origin=DataOrigin.INGEST, now=NOW) == 4
        assert upsert_events(conn, recs, origin=DataOrigin.BACKFILL, now=NOW) == 0
        rows = [dict(r) for r in conn.execute("SELECT * FROM events ORDER BY timestamp")]
        assert [r["tamper_classification"] for r in rows] == ["signal", "signal", "confirmed", "confirmed"]
        assert {r["origin"] for r in rows} == {"ingest"}
        assert rows[0]["timestamp"].endswith("+00:00")
