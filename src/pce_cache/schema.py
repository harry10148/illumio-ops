from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from src.pce_cache.models import Base


def init_schema(engine: Engine) -> None:
    """Create all tables + indexes if missing. Idempotent."""
    _enable_wal_pragma(engine)
    Base.metadata.create_all(engine)
    _ensure_added_columns(engine)
    _ensure_added_indexes(engine)
    _drop_deprecated_indexes(engine)
    _normalize_agg_bucket_day(engine)


# Columns added to pce_traffic_flows_raw after it first shipped (Tier-2a
# report-ready flatten cache). create_all() never ALTERs an existing table, so
# add missing columns explicitly (idempotently). SQLite ADD COLUMN is a cheap
# metadata-only op.
_ADDED_COLUMNS = (
    ("report_json", "TEXT"),
)


def _ensure_added_columns(engine: Engine) -> None:
    from sqlalchemy.exc import OperationalError

    with engine.begin() as conn:
        existing = {
            r[1] for r in conn.execute(
                text("PRAGMA table_info(pce_traffic_flows_raw)")
            )
        }
        for name, sqltype in _ADDED_COLUMNS:
            if name not in existing:
                try:
                    conn.execute(text(
                        f"ALTER TABLE pce_traffic_flows_raw ADD COLUMN {name} {sqltype}"
                    ))
                except OperationalError as exc:
                    # SQLite has no "ADD COLUMN IF NOT EXISTS". When init_schema runs
                    # concurrently from two threads (daemon ingestion + a web request
                    # under monitor-gui), both can pass the PRAGMA check above before
                    # either ALTERs, so the loser hits "duplicate column name". The
                    # column exists either way — swallow only that race, re-raise else.
                    if "duplicate column name" not in str(exc).lower():
                        raise


# Indexes added after a table first shipped. metadata.create_all() only creates
# indexes when it creates the table itself, so a new index on an already-existing
# table must be created explicitly (idempotently) here.
_ADDED_INDEXES = (
    ("ix_dispatch_source", "siem_dispatch", "source_table, source_id"),
    # Backs the common report query: last_detected range + policy-decision
    # (action) filter pushed down in read_flows_df (Tier-2b).
    ("ix_raw_last_action", "pce_traffic_flows_raw", "last_detected, action"),
    # Partial index for read_flows_df's report_json-IS-NULL fallback query. On a
    # backfilled DB every row has report_json, so the fallback matches 0 rows —
    # but without this it still full-scanned the 242k-row last_detected range
    # checking each row (report_json isn't in any other index), costing ~8s per
    # report. This index contains ONLY null-report_json rows (none, normally), so
    # the fallback hits an empty index and returns instantly. Zero write cost:
    # ingest always sets report_json, so new rows never enter this index.
    # (4th element = partial-index WHERE predicate.)
    ("ix_raw_report_json_null", "pce_traffic_flows_raw", "last_detected",
     "report_json IS NULL"),
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
        for spec in _ADDED_INDEXES:
            name, table, cols = spec[0], spec[1], spec[2]
            where = f" WHERE {spec[3]}" if len(spec) > 3 else ""
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols}){where}"
            ))


def _drop_deprecated_indexes(engine: Engine) -> None:
    with engine.begin() as conn:
        for name in _DEPRECATED_INDEXES:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))


# bucket_day 舊格式（aggregator 以前用 SQL 'start of day' 產出，無微秒，例如
# "2026-06-30 00:00:00"）跟 reader 端 SQLAlchemy 綁的 datetime（含微秒，例如
# "2026-06-30 00:00:00.000000"）字串比較不一致，導致午夜 start 漏讀當日 bucket
# （aggregator.py 已改成輸出跟 bind 一致的格式，這裡是既有資料的一次性遷移）。
def _normalize_agg_bucket_day(engine: Engine) -> None:
    """把 pce_traffic_flows_agg 既有的舊格式 bucket_day 正規化成新格式。

    冪等：只挑 bucket_day 不含 '.' 的舊格式列處理，處理完就不再命中。
    需處理「同一分組鍵新舊格式並存」的碰撞（ix_agg_unique 涵蓋 bucket_day）：
    正規化後的 key 若已存在新格式列，直接 UPDATE 會撞 unique constraint，
    因此改用 MAX 合併（與 aggregator 的 conflict-MAX 冪等語意一致）後刪除
    舊格式列；沒有碰撞則單純 UPDATE 成新格式。
    """
    with engine.begin() as conn:
        old_rows = conn.execute(text(
            "SELECT id, bucket_day, src_workload, dst_workload, port, protocol, "
            "action, flow_count, bytes_total FROM pce_traffic_flows_agg "
            "WHERE bucket_day NOT LIKE '%.%'"
        )).fetchall()
        for row in old_rows:
            new_bucket_day = row.bucket_day + ".000000"
            existing = conn.execute(text(
                "SELECT id, flow_count, bytes_total FROM pce_traffic_flows_agg "
                "WHERE bucket_day = :bucket_day AND src_workload IS :src_workload "
                "AND dst_workload IS :dst_workload AND port = :port "
                "AND protocol = :protocol AND action = :action AND id != :id"
            ), {
                "bucket_day": new_bucket_day,
                "src_workload": row.src_workload,
                "dst_workload": row.dst_workload,
                "port": row.port,
                "protocol": row.protocol,
                "action": row.action,
                "id": row.id,
            }).fetchone()
            if existing is not None:
                conn.execute(text(
                    "UPDATE pce_traffic_flows_agg SET flow_count = :flow_count, "
                    "bytes_total = :bytes_total WHERE id = :id"
                ), {
                    "flow_count": max(existing.flow_count, row.flow_count),
                    "bytes_total": max(existing.bytes_total, row.bytes_total),
                    "id": existing.id,
                })
                conn.execute(text(
                    "DELETE FROM pce_traffic_flows_agg WHERE id = :id"
                ), {"id": row.id})
            else:
                conn.execute(text(
                    "UPDATE pce_traffic_flows_agg SET bucket_day = :bucket_day "
                    "WHERE id = :id"
                ), {"bucket_day": new_bucket_day, "id": row.id})


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
        # Read perf: default page cache is ~2MB — tiny for 240k-row scans. Give
        # it 64MB (negative = KiB) and 256MB memory-map so report reads hit RAM,
        # not repeated disk reads. Per-connection; cheap, no offline impact.
        cur.execute("PRAGMA cache_size = -65536")
        cur.execute("PRAGMA mmap_size = 268435456")
        cur.close()

    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode = WAL"))
        conn.commit()
