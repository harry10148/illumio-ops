"""The write path's per-connection lookups must use the conn_key index: a plan that scans every
primary row makes each collection cycle cost grow with the size of the store (P2 Task 14)."""
from illumio_ops.store.flowdb import flows
from illumio_ops.store.flowdb.db import FlowDb


def _plan(conn, sql, args):
    return " ".join(str(r[-1]) for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}", args))


def test_primary_row_of_a_connection_is_found_by_conn_key(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        plan = _plan(conn, flows.PRIMARY_OF_CONNECTION, ("k",))
    assert "ix_flows_conn" in plan, plan


def _indexes(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'flows'")}


def test_flows_carries_only_indexes_with_readers(tmp_path):
    """Every index costs a random write per stored record; P6 adds what its measured queries need."""
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        names = {n for n in _indexes(conn) if not n.startswith("sqlite_autoindex")}
    assert names == {"ix_flows_conn", "ix_flows_tuple", "ix_flows_last"}


def test_time_range_reads_use_the_time_index(tmp_path):
    from illumio_ops.domain.filter import FilterSpec, sql_functions, to_sql
    from tests_v6.services.collect.conftest import NOW, minutes
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        for name, fn in sql_functions().items():
            conn.create_function(name, -1, fn, deterministic=True)
        where, params = to_sql(FilterSpec(start=NOW - minutes(60), end=NOW))
        assert "ix_flows_last" in _plan(conn, f"SELECT * FROM flows f WHERE {where}", params)
        assert "ix_flows_last" in _plan(conn, flows.ROLLUP_INSERT, ("d", -1, "2026-10-24", "2026-10-25", -1))


def test_record_keys_are_128_bit():
    from illumio_ops.domain.flows import normalize_flow, record_key
    from tests_v6.services.collect.conftest import NOW, minutes, raw_flow
    assert len(record_key(normalize_flow(raw_flow(1, NOW - minutes(2), NOW)))) == 32


def test_composite_key_tables_are_one_tree(tmp_path):
    """A rowid table with a composite primary key is two trees (rows + key index): two random writes
    per upsert. WITHOUT ROWID keeps one, and clusters the daily tables by day."""
    names = ("flow_rollup_daily", "connection_baseline", "user_baseline", "workload_snapshot_daily",
             "ransomware_snapshot_daily")
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        sql = dict(conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall())
    assert [n for n in names if "WITHOUT ROWID" not in sql[n].upper()] == []


def test_increment_tuple_reads_use_the_tuple_index(tmp_path):
    # Read before and after every written tuple, inside the write lock (P4 Task 4).
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        plan = _plan(conn, flows.TUPLE_TOTALS, ("a", "b", 22, 6, "2026-10-24"))
    assert "ix_flows_tuple" in plan, plan


def test_increment_window_uses_observed_index(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        plan = _plan(conn, "SELECT * FROM flow_increments i JOIN flows f ON f.conn_key = i.conn_key AND f.is_primary = 1 "
                           "WHERE i.late = 0 AND i.observed_at > ? AND i.observed_at <= ?", ("a", "b"))
    assert "ix_increments_observed" in plan and "ix_flows_conn" in plan, plan
