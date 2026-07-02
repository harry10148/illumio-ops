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


def test_schema_creates_report_json_null_partial_index():
    """Partial index on (last_detected) WHERE report_json IS NULL makes
    read_flows_df's 0-row fallback query hit an empty index instead of
    full-scanning the last_detected range. Must be created idempotently and be
    an actual PARTIAL index (carries the WHERE predicate)."""
    from sqlalchemy import text
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp,'c.sqlite')}")
        init_schema(engine)
        init_schema(engine)  # idempotent
        with engine.connect() as conn:
            sql = conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='ix_raw_report_json_null'")).scalar()
        assert sql is not None, "partial index missing"
        assert "report_json IS NULL" in sql, f"index is not partial: {sql}"


def test_schema_normalizes_agg_bucket_day_old_format():
    """一次性遷移：既有 agg 列若 bucket_day 是舊格式（aggregator 過去用 SQL
    'start of day' 產出，無微秒），init_schema 要把它正規化成跟 reader 端
    SQLAlchemy 綁的 datetime 一致的新格式（含 .000000），資料不遺失。"""
    from sqlalchemy import text
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO pce_traffic_flows_agg "
                "(bucket_day, src_workload, dst_workload, port, protocol, action, "
                "flow_count, bytes_total) VALUES "
                "('2026-06-30 00:00:00', 'web', 'db', 443, 'tcp', 'blocked', 10, 3000)"
            ))
        init_schema(engine)  # 觸發遷移
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT bucket_day, flow_count, bytes_total FROM pce_traffic_flows_agg"
            )).fetchall()
        assert len(rows) == 1
        assert rows[0].bucket_day == "2026-06-30 00:00:00.000000"
        assert rows[0].flow_count == 10
        assert rows[0].bytes_total == 3000

        init_schema(engine)  # 再跑一次必須冪等，不重複也不出錯
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT bucket_day FROM pce_traffic_flows_agg"
            )).fetchall()
        assert len(rows) == 1
        assert rows[0].bucket_day == "2026-06-30 00:00:00.000000"


def test_schema_normalizes_agg_bucket_day_merges_on_collision():
    """遷移碰撞情境：同一分組鍵舊格式與新格式列並存時，正規化不能直接
    UPDATE（會撞 ix_agg_unique），必須 MAX 合併（與 aggregator 的
    conflict-MAX 冪等語意一致）後刪除舊格式列，資料不遺失也不重複。"""
    from sqlalchemy import text
    from src.pce_cache.schema import init_schema

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cache.sqlite")
        engine = create_engine(f"sqlite:///{path}")
        init_schema(engine)
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO pce_traffic_flows_agg "
                "(bucket_day, src_workload, dst_workload, port, protocol, action, "
                "flow_count, bytes_total) VALUES "
                "('2026-06-30 00:00:00', 'web', 'db', 443, 'tcp', 'blocked', 10, 3000)"
            ))
            conn.execute(text(
                "INSERT INTO pce_traffic_flows_agg "
                "(bucket_day, src_workload, dst_workload, port, protocol, action, "
                "flow_count, bytes_total) VALUES "
                "('2026-06-30 00:00:00.000000', 'web', 'db', 443, 'tcp', 'blocked', 7, 5000)"
            ))
        init_schema(engine)  # 觸發遷移，碰撞須合併
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT bucket_day, flow_count, bytes_total FROM pce_traffic_flows_agg"
            )).fetchall()
        assert len(rows) == 1, f"expected merge to 1 row, got {len(rows)}"
        assert rows[0].bucket_day == "2026-06-30 00:00:00.000000"
        assert rows[0].flow_count == 10     # MAX(10, 7)
        assert rows[0].bytes_total == 5000  # MAX(3000, 5000)


def test_schema_sets_read_perf_pragmas():
    """cache_size (64MB) + mmap_size (256MB) speed up large 240k-row scans."""
    from sqlalchemy import text
    from src.pce_cache.schema import init_schema
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{os.path.join(tmp,'c.sqlite')}")
        init_schema(engine)
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA cache_size")).scalar() == -65536
            assert conn.execute(text("PRAGMA mmap_size")).scalar() == 268435456
