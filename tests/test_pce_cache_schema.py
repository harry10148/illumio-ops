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
