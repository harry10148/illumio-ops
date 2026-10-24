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
