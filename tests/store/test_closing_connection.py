"""ctx.db(): a connection is closed when its outermost `with` block ends (store/db.py ClosingConnection). sqlite3's
own `with` only ends the transaction; left to the cycle collector, the service held open files it no longer used
(31 after 80 requests, measured 2026-11-14) under a limit of 1,024."""
from __future__ import annotations

import gc
import os
import sqlite3

import pytest

from illumio_ops.store.db import ClosingConnection, connect
from tests.web.conftest import make_ctx


def _open_files() -> int:
    return len(os.listdir("/proc/self/fd"))


def test_the_outermost_with_closes_the_connection(tmp_path):
    with connect(tmp_path / "a.sqlite", factory=ClosingConnection) as conn:
        conn.execute("CREATE TABLE t (n INTEGER)")
        conn.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with connect(tmp_path / "a.sqlite", factory=ClosingConnection) as again:  # and it was committed first
        assert again.execute("SELECT n FROM t").fetchall()[0][0] == 1


def test_a_with_inside_ends_its_transaction_and_leaves_the_connection_open(tmp_path):
    """The store's functions take the connection and open a transaction with `with conn:`."""
    with connect(tmp_path / "a.sqlite", factory=ClosingConnection) as conn:
        conn.execute("CREATE TABLE t (n INTEGER)")
        with conn:
            conn.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(ZeroDivisionError), conn:
            conn.execute("INSERT INTO t VALUES (2)")
            1 / 0  # noqa: B018 - the inner block fails: its insert is rolled back, the connection stays
        assert [r[0] for r in conn.execute("SELECT n FROM t")] == [1]
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_a_failing_block_is_rolled_back_and_still_closed(tmp_path):
    with connect(tmp_path / "a.sqlite", factory=ClosingConnection) as conn:
        conn.execute("CREATE TABLE t (n INTEGER)")
    with pytest.raises(ZeroDivisionError), connect(tmp_path / "a.sqlite", factory=ClosingConnection) as conn:
        conn.execute("INSERT INTO t VALUES (1)")
        1 / 0  # noqa: B018
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
    with connect(tmp_path / "a.sqlite", factory=ClosingConnection) as again:
        assert again.execute("SELECT count(*) FROM t").fetchall()[0][0] == 0


def test_the_application_database_holds_no_file_after_its_block(tmp_path):
    """Without waiting for the cycle collector: 50 blocks leave as many files open as before them."""
    ctx = make_ctx(tmp_path)
    with ctx.db() as conn:  # the first use creates the WAL files
        conn.execute("SELECT 1")
    gc.collect()
    gc.disable()
    try:
        before = _open_files()
        for _ in range(50):
            with ctx.db() as conn:
                conn.execute("SELECT 1").fetchall()
        assert _open_files() == before
    finally:
        gc.enable()
