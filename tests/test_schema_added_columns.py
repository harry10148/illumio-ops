import sqlite3

from sqlalchemy import create_engine, inspect

from src.pce_cache.schema import _ADDED_COLUMNS, init_schema


def test_added_columns_registry_is_table_qualified():
    # 登記格式必須含表名，未來對其他表加欄位時不需要改 _ensure_added_columns
    for entry in _ADDED_COLUMNS:
        assert len(entry) == 3, (
            f"_ADDED_COLUMNS entry {entry!r} must be (table, column, sqltype)"
        )


def test_legacy_table_missing_registered_column_gets_it_back(tmp_path):
    # 模擬 Tier-2a 之前的舊 DB：先建出完整 schema，再拔掉 report_json
    db = tmp_path / "legacy.sqlite"
    engine = create_engine(f"sqlite:///{db}")
    init_schema(engine)
    engine.dispose()

    conn = sqlite3.connect(db)
    # SQLite 拒絕 DROP 被索引引用的欄位——ix_raw_report_json_null 是
    # `WHERE report_json IS NULL` 的 partial index，得先拔索引再拔欄位。
    # init_schema 的 _ensure_added_indexes 之後會把索引重建回來。
    conn.execute("DROP INDEX IF EXISTS ix_raw_report_json_null")
    conn.execute("ALTER TABLE pce_traffic_flows_raw DROP COLUMN report_json")
    conn.commit()
    conn.close()

    engine2 = create_engine(f"sqlite:///{db}")
    init_schema(engine2)
    cols = {c["name"] for c in inspect(engine2).get_columns("pce_traffic_flows_raw")}
    engine2.dispose()
    assert "report_json" in cols
