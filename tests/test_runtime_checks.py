import sqlite3

from src.runtime_checks import MIN_SQLITE_VERSION, sqlite_version_error


def test_min_version_is_returning_floor():
    # INSERT ... RETURNING (ingestor_events/ingestor_traffic) needs 3.35.0
    assert MIN_SQLITE_VERSION == (3, 35, 0)


def test_current_runtime_passes():
    # Dev machine/bundle Python SQLite all >= 3.45, healthy env must return None
    assert sqlite_version_error() is None


def test_old_sqlite_rejected(monkeypatch):
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 26, 0))
    monkeypatch.setattr(sqlite3, "sqlite_version", "3.26.0")
    msg = sqlite_version_error()
    assert msg is not None
    assert "3.26.0" in msg          # actual version appears in message
    assert "3.35.0" in msg          # required floor appears in message
    assert "python/bin/python3" in msg  # guide operator to bundle Python
