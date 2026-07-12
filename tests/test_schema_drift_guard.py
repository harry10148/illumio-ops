"""Drift guard: a legacy DB (frozen baseline DDL) run through init_schema()
must end up with every column the current models declare.

If this test fails after you added a column to src/pce_cache/models.py, the
fix is to register the column in _ADDED_COLUMNS (src/pce_cache/schema.py) —
NOT to regenerate the baseline fixture.
"""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from src.pce_cache.models import Base
from src.pce_cache.schema import init_schema

BASELINE = Path(__file__).parent / "fixtures" / "pce_cache_baseline_schema.sql"


@pytest.fixture
def upgraded_engine(tmp_path):
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(BASELINE.read_text())
    conn.commit()
    conn.close()
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    yield engine
    engine.dispose()


def test_baseline_db_upgraded_to_full_model_schema(upgraded_engine):
    insp = inspect(upgraded_engine)
    for table in Base.metadata.tables.values():
        actual = {c["name"] for c in insp.get_columns(table.name)}
        expected = {c.name for c in table.columns}
        missing = expected - actual
        assert not missing, (
            f"table {table.name} is missing columns {sorted(missing)} after "
            "init_schema on a legacy DB — register them in _ADDED_COLUMNS "
            "(src/pce_cache/schema.py); do NOT regenerate the baseline fixture"
        )


def test_baseline_db_gets_migration_marker_and_indexes(upgraded_engine):
    with upgraded_engine.connect() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
    assert version >= 1  # _MIGRATION_AGG_BUCKET_DAY ran on the legacy DB
    raw_indexes = {
        ix["name"]
        for ix in inspect(upgraded_engine).get_indexes("pce_traffic_flows_raw")
    }
    assert "ix_raw_last_action" in raw_indexes


def test_newer_db_user_version_logs_downgrade_warning(tmp_path):
    from loguru import logger

    from src.pce_cache.schema import _normalize_agg_bucket_day

    db = tmp_path / "newer.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    with engine.begin() as conn:
        conn.execute(text("PRAGMA user_version = 99"))

    messages: list[str] = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        _normalize_agg_bucket_day(engine)
    finally:
        logger.remove(sink_id)
    engine.dispose()
    assert any("user_version=99" in m for m in messages), messages
