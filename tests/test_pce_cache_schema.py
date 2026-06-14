import os
import tempfile

import pytest
from sqlalchemy import create_engine, inspect


def test_schema_creates_all_seven_tables():
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        names = set(inspect(engine).get_table_names())
        assert names == {
            "pce_events",
            "pce_traffic_flows_raw",
            "pce_traffic_flows_agg",
            "ingestion_watermarks",
            "ingestion_cursors",
            "siem_dispatch",
            "dead_letter",
        }


def test_schema_is_idempotent():
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        init_schema(engine)  # must not raise


def test_schema_enables_wal_mode():
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        with engine.connect() as conn:
            from sqlalchemy import text
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert mode.lower() == "wal"


def test_schema_creates_dispatch_source_anti_join_index():
    """The (source_table, source_id) index backing the SIEM backfill anti-join
    must exist. It was added after siem_dispatch first shipped, so it relies on
    the explicit CREATE INDEX IF NOT EXISTS path (create_all won't add an index
    to an already-existing table)."""
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        init_schema(engine)  # idempotent: CREATE INDEX IF NOT EXISTS
        idx = {i["name"] for i in inspect(engine).get_indexes("siem_dispatch")}
        assert "ix_dispatch_source" in idx


def test_schema_sets_busy_timeout():
    """busy_timeout must be set so concurrent writers wait for the lock instead
    of failing immediately with 'database is locked' (SQLite serialises writers;
    ingestor + aggregator + SIEM all write the same DB)."""
    from sqlalchemy import text
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 30000


def test_schema_prunes_deprecated_raw_indexes():
    """src_ip/dst_ip/port/action/first_detected indexes are dropped (no query
    uses them; they only slowed ingest). Kept: last_detected, src/dst_workload,
    flow_hash, ingested_at. DROP must also apply idempotently to existing DBs."""
    from sqlalchemy import create_engine, inspect
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        init_schema(engine)  # idempotent
        idx_cols = {tuple(i["column_names"]) for i in
                    inspect(engine).get_indexes("pce_traffic_flows_raw")}
        assert ("last_detected",) in idx_cols
        assert ("src_workload",) in idx_cols
        assert ("dst_workload",) in idx_cols
        # composite (last_detected, action) backs decision-filtered reads (Tier-2b)
        assert ("last_detected", "action") in idx_cols
        # the deprecated SINGLE-column indexes must be gone (action only survives
        # inside the composite above, not on its own)
        for gone in (("src_ip",), ("dst_ip",), ("port",), ("action",), ("first_detected",)):
            assert gone not in idx_cols, f"{gone} should not have a single-column index"
