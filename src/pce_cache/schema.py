from __future__ import annotations

import threading

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


# init_schema 本身雖然冪等，但每次呼叫仍要跑完整套 PRAGMA + create_all 反射
# + table_info + 3 CREATE INDEX + 5 DROP INDEX 等十幾條 DDL/metadata 語句。
# src/main.py 的 _make_cache_reader、_make_subscribers 與 archive_import.py
# 的 review_session_factory 都是 per-request/per-query 熱路徑呼叫點，這筆
# 開銷不該每次重付——用 db_path 記錄「這個 db 這個 process 生命週期內已
# 確保過 schema」，之後同一個 db_path 直接略過，即使是不同 engine 物件。
_schema_ensured_paths: set[str] = set()
_schema_ensured_lock = threading.Lock()


def _ensure_schema_once(engine: Engine, db_path: str) -> None:
    """對同一個 db_path，在本 process 生命週期內只跑一次 init_schema。

    邊界：若 db_path 對應的檔案被外部（非經本模組管理的流程，例如手動刪除
    後重建）繞過，ensured-set 仍會誤以為該 db_path 已確保過，之後不會再跑
    init_schema。這與 src/gui/_helpers.py 的 _get_cache_engine（process 快
    取 Engine 物件）本來就有的既有假設暴露一致，不在本次範圍內額外處理。
    """
    with _schema_ensured_lock:
        if db_path in _schema_ensured_paths:
            return
        init_schema(engine)
        _schema_ensured_paths.add(db_path)


# Columns added to a table after it first shipped. create_all() never ALTERs
# an existing table, so add missing columns explicitly (idempotently). SQLite
# ADD COLUMN is a cheap metadata-only op. Entries are (table, column, sqltype)
# so future additions to ANY table only need a new tuple here — forgetting to
# register a new model column is caught by tests/test_schema_drift_guard.py.
_ADDED_COLUMNS = (
    # Tier-2a report-ready flatten cache.
    ("pce_traffic_flows_raw", "report_json", "TEXT"),
)


def _ensure_added_columns(engine: Engine) -> None:
    from sqlalchemy.exc import OperationalError

    with engine.begin() as conn:
        for table, name, sqltype in _ADDED_COLUMNS:
            existing = {
                r[1] for r in conn.execute(
                    text(f"PRAGMA table_info({table})")
                )
            }
            if name in existing:
                continue
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"
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


# 一次性資料遷移的完成標記。init_schema 被 per-request/per-query 呼叫
# （src/main.py 的 _make_cache_reader、archive_import 的 review_session_factory），
# 升級鏈裡其他步驟都是便宜的 metadata 檢查，但 bucket_day 正規化的
# NOT LIKE '%.%' 是 leading-wildcard、無法用索引，會全表掃描 agg 表——
# 用 PRAGMA user_version 守衛，遷移完成後穩態成本降回 O(1)。
# （repo 內 user_version 無其他用途；日後要加新的一次性遷移時把此值 +1，
# 並在對應遷移函式比對新值。）
_MIGRATION_AGG_BUCKET_DAY = 1


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

    守衛：user_version 已達標就直接返回，省掉每次 init_schema 的全表掃描
    （穩態 O(1)）。兩執行緒併發時可能都通過守衛、各跑一次正規化——
    正規化本身冪等，守衛只是省成本，競態下多跑一次無害。
    """
    with engine.begin() as conn:
        version = conn.execute(text("PRAGMA user_version")).scalar()
        if version >= _MIGRATION_AGG_BUCKET_DAY:
            return
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
        # PRAGMA 不吃 bind 參數；值來自模組常數（int），無注入疑慮。
        conn.execute(text(f"PRAGMA user_version = {_MIGRATION_AGG_BUCKET_DAY}"))


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
