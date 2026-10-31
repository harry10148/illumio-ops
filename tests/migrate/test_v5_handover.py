"""P8: where a stopped 5.x got to — per SIEM destination, the audit events it had sent; for event alerts, the events
it had evaluated. Read-only, from data/pce_cache.sqlite (5.2.x shape, .106 2026-11-01) or logs/state.json."""
import json
import sqlite3
from datetime import UTC, datetime, timedelta

from illumio_ops.migrate.v5_handover import read_handover

T = datetime(2026, 10, 31, 17, 0, tzinfo=UTC)
MS = timedelta(milliseconds=1)


def _ts(t):
    return t.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def _db(root, events, dispatch=(), cursor=None):
    (root / "data").mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / "data" / "pce_cache.sqlite")
    db.execute("CREATE TABLE pce_events (id INTEGER PRIMARY KEY, timestamp DATETIME, ingested_at DATETIME)")
    db.execute("CREATE TABLE siem_dispatch (id INTEGER PRIMARY KEY, source_table VARCHAR, source_id BIGINT, "
               "destination VARCHAR, status VARCHAR)")
    db.execute("CREATE TABLE ingestion_cursors (consumer VARCHAR, source_table VARCHAR, last_ingested_at DATETIME, "
               "last_row_id BIGINT, updated_at DATETIME)")
    db.executemany("INSERT INTO pce_events VALUES (?, ?, ?)", [(i, _ts(t), _ts(at)) for i, t, at in events])
    db.executemany("INSERT INTO siem_dispatch (source_table, source_id, destination, status) VALUES "
                   "('pce_events', ?, ?, ?)", dispatch)
    if cursor:
        db.execute("INSERT INTO ingestion_cursors VALUES ('analyzer', 'pce_events', ?, ?, ?)",
                   (_ts(cursor[0]), cursor[1], _ts(T)))
    db.commit()
    db.close()


RAW = {"pce_cache": {"enabled": True}, "siem": {"destinations": [{"name": "graylog"}, {"name": "splunk"},
                                                                  {"name": "new"}]}}
EVENTS = [(1, T, T), (2, T + timedelta(minutes=1), T + timedelta(minutes=5)),
          (3, T + timedelta(minutes=2), T + timedelta(minutes=5))]


def test_a_destination_continues_after_what_it_sent(tmp_path):
    _db(tmp_path, EVENTS, [(1, "graylog", "sent"), (2, "graylog", "sent"), (3, "graylog", "sent")])
    h = read_handover(tmp_path, RAW)
    assert h.audit_floors["graylog"] == T + timedelta(minutes=2)


def test_a_destination_continues_from_its_oldest_unsent_event(tmp_path):
    # sent in queue order, not event order: an older event still pending must be sent (at least once)
    _db(tmp_path, EVENTS, [(1, "splunk", "pending"), (2, "splunk", "sent"), (3, "splunk", "pending")])
    assert read_handover(tmp_path, RAW).audit_floors["splunk"] == T - MS


def test_events_5x_gave_up_on_are_counted_not_resent(tmp_path):
    _db(tmp_path, EVENTS, [(1, "graylog", "failed"), (2, "graylog", "sent"), (3, "graylog", "sent")])
    h = read_handover(tmp_path, RAW)
    assert h.audit_floors["graylog"] == T + timedelta(minutes=2) and h.dlq_counts["graylog"] == 1


def test_a_destination_5x_never_sent_to_has_no_floor(tmp_path):
    _db(tmp_path, EVENTS)
    assert read_handover(tmp_path, RAW).audit_floors["new"] is None


def test_event_alerts_continue_after_the_analyzer_cursor(tmp_path):
    _db(tmp_path, EVENTS, cursor=(T + timedelta(minutes=5), 2))  # event 3 shares the ingest time, not evaluated
    assert read_handover(tmp_path, RAW).event_alert_floor == T + timedelta(minutes=2) - MS


def test_event_alerts_all_evaluated(tmp_path):
    _db(tmp_path, EVENTS, cursor=(T + timedelta(minutes=5), 3))
    assert read_handover(tmp_path, RAW).event_alert_floor == T + timedelta(minutes=2)


def test_without_the_cache_event_alerts_continue_from_state_json(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "state.json").write_text(json.dumps({"event_watermark": "2026-10-24T22:28:14Z"}))
    h = read_handover(tmp_path, {"siem": {"destinations": [{"name": "g"}]}})
    assert h.event_alert_floor == datetime(2026, 10, 24, 22, 28, 14, tzinfo=UTC) and h.audit_floors == {"g": None}


def test_nothing_to_read_means_no_floors(tmp_path):
    h = read_handover(tmp_path, RAW)
    assert h.event_alert_floor is None and set(h.audit_floors.values()) == {None}


def test_the_5x_store_is_opened_read_only(tmp_path):
    _db(tmp_path, EVENTS)
    before = (tmp_path / "data" / "pce_cache.sqlite").read_bytes()
    read_handover(tmp_path, RAW)
    assert (tmp_path / "data" / "pce_cache.sqlite").read_bytes() == before


def test_without_an_analyzer_cursor_every_cached_event_is_still_to_alert(tmp_path):
    # final review: 5.x's subscriber starts from the beginning when it has no cursor — none was evaluated
    _db(tmp_path, EVENTS)
    assert read_handover(tmp_path, RAW).event_alert_floor == T - MS


def test_an_absolute_cache_path_inside_a_moved_5x_follows_it(tmp_path):
    moved = tmp_path / "opt" / "illumio-ops.5x-1"
    _db(moved, EVENTS, [(1, "graylog", "sent")])
    raw = {**RAW, "pce_cache": {"enabled": True, "db_path": str(tmp_path / "opt" / "illumio-ops" / "data" /
                                                                   "pce_cache.sqlite")}}
    h = read_handover(moved, raw, original=tmp_path / "opt" / "illumio-ops")
    assert h.audit_floors["graylog"] == T
