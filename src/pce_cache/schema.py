from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from src.pce_cache.models import Base


def init_schema(engine: Engine) -> None:
    """Create all tables + indexes if missing. Idempotent."""
    _enable_wal_pragma(engine)
    Base.metadata.create_all(engine)
    _ensure_added_indexes(engine)
    _drop_deprecated_indexes(engine)


# Indexes added after a table first shipped. metadata.create_all() only creates
# indexes when it creates the table itself, so a new index on an already-existing
# table must be created explicitly (idempotently) here.
_ADDED_INDEXES = (
    ("ix_dispatch_source", "siem_dispatch", "source_table, source_id"),
)

# Single-column indexes removed because no query filters/sorts by them — they
# only added write amplification on every ingest. create_all never drops
# indexes, so drop them explicitly (idempotently) on existing DBs.
_DEPRECATED_INDEXES = (
    "ix_pce_traffic_flows_raw_first_detected",
    "ix_pce_traffic_flows_raw_src_ip",
    "ix_pce_traffic_flows_raw_dst_ip",
    "ix_pce_traffic_flows_raw_port",
    "ix_pce_traffic_flows_raw_action",
)


def _ensure_added_indexes(engine: Engine) -> None:
    with engine.begin() as conn:
        for name, table, cols in _ADDED_INDEXES:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})"
            ))


def _drop_deprecated_indexes(engine: Engine) -> None:
    with engine.begin() as conn:
        for name in _DEPRECATED_INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))


def _enable_wal_pragma(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA synchronous = NORMAL")
        # SQLite serialises writers; without busy_timeout a write that meets a
        # concurrent writer fails immediately with "database is locked". Wait
        # for the lock instead (ingestor + aggregator + SIEM all write here).
        cur.execute("PRAGMA busy_timeout = 30000")
        cur.close()

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode = WAL"))
        conn.commit()
