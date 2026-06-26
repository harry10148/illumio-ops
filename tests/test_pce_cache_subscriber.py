# tests/test_pce_cache_subscriber.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.pce_cache.models import PceEvent


@pytest.fixture
def session_factory(tmp_path):
    from src.pce_cache.schema import init_schema
    engine = create_engine(f"sqlite:///{tmp_path/'c.sqlite'}")
    init_schema(engine)
    return sessionmaker(engine)


def _seed(sf, uuid, ingested_at):
    with sf.begin() as s:
        s.add(PceEvent(
            pce_href=f"/orgs/1/events/{uuid}",
            pce_event_id=uuid, timestamp=ingested_at,
            event_type="policy.update", severity="info", status="success",
            pce_fqdn="pce.example.com", raw_json="{}", ingested_at=ingested_at,
        ))


def test_first_poll_returns_all_rows(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    _seed(session_factory, "b", datetime(2026, 4, 19, 10, 1, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, consumer="analyzer", source_table="pce_events")
    rows = sub.poll_new_rows()
    assert len(rows) == 2


def test_second_poll_returns_only_new_rows(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, consumer="analyzer", source_table="pce_events")
    assert len(sub.poll_new_rows()) == 1
    assert len(sub.poll_new_rows()) == 0
    _seed(session_factory, "b", datetime(2026, 4, 19, 10, 1, tzinfo=timezone.utc))
    assert len(sub.poll_new_rows()) == 1


def test_cursor_persists_across_subscriber_restart(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    CacheSubscriber(session_factory, "analyzer", "pce_events").poll_new_rows()
    # Fresh subscriber instance should not re-read "a"
    assert len(CacheSubscriber(session_factory, "analyzer", "pce_events")
              .poll_new_rows()) == 0


def test_independent_consumers_have_independent_cursors(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    CacheSubscriber(session_factory, "analyzer", "pce_events").poll_new_rows()
    # Other consumer is still at zero — reads everything
    assert len(CacheSubscriber(session_factory, "exporter", "pce_events")
              .poll_new_rows()) == 1


def test_processor_failure_does_not_advance_cursor(session_factory):
    """At-least-once: when the processor callback raises, the cursor must NOT
    advance, so the same rows are re-delivered on the next poll instead of being
    silently skipped on consumer failure."""
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")

    def boom(rows):
        raise RuntimeError("consumer crashed")

    with pytest.raises(RuntimeError):
        sub.poll_new_rows(processor=boom)
    # Cursor stayed put → row still pending on the next (plain) poll.
    rows = sub.poll_new_rows()
    assert len(rows) == 1
    assert rows[0]["pce_event_id"] == "a"


def test_processor_success_advances_cursor(session_factory):
    """When the processor returns cleanly the batch is acknowledged and the
    cursor advances, so the next poll is empty."""
    from src.pce_cache.subscriber import CacheSubscriber
    _seed(session_factory, "a", datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc))
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")
    seen = []
    out = sub.poll_new_rows(processor=seen.extend)
    assert len(out) == 1 and len(seen) == 1
    assert sub.poll_new_rows() == []


def test_ties_on_ingested_at_broken_by_row_id(session_factory):
    from src.pce_cache.subscriber import CacheSubscriber
    same_ts = datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc)
    _seed(session_factory, "a", same_ts)
    _seed(session_factory, "b", same_ts)  # same ingested_at, different id
    sub = CacheSubscriber(session_factory, "analyzer", "pce_events")
    rows = sub.poll_new_rows(limit=1)
    assert len(rows) == 1
    rows2 = sub.poll_new_rows(limit=1)
    assert len(rows2) == 1
    assert rows[0]["pce_event_id"] != rows2[0]["pce_event_id"]
