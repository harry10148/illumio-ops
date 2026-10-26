"""Flow DB 0006 (P4.5, spec §6.5.8): the account and process baselines, and each source's hourly activity."""
from datetime import timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.store.flowdb.db import FlowDb, db_time
from illumio_ops.store.flowdb.flows import delete_baselines_before, upsert_flows
from tests_v6.services.collect.conftest import NOW, raw_flow


@pytest.fixture
def conn(tmp_path):
    c = FlowDb(tmp_path / "flows.sqlite").connect()
    yield c
    c.close()


def rec(i=1, *, port=445, user=None, process=None, conns=1, decision="potentially_blocked", minutes_ago=1,
        bytes_=None):
    raw = raw_flow(i, NOW - timedelta(minutes=minutes_ago + 5), NOW - timedelta(minutes=minutes_ago), port=port,
                   user=user)
    raw["num_connections"] = conns
    raw["policy_decision"] = decision
    if process:
        raw["service"]["process_name"] = process
    if bytes_ is not None:
        raw["dst_bi"], raw["dst_bo"] = bytes_, 0
    return normalize_flow(raw)


def rows(conn, table):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")]


def test_0006_seeds_baselines_from_rollup(tmp_path, monkeypatch):
    from illumio_ops.store import db as storedb
    from illumio_ops.store.flowdb import db as flowdb

    path = tmp_path / "flows.sqlite"
    original = storedb._migrations
    monkeypatch.setattr(storedb, "_migrations", lambda package=storedb.APP_MIGRATIONS:
                        original(package)[:5] if package == flowdb.MIGRATIONS_PACKAGE else original(package))
    with FlowDb(path).connect() as old:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 5
        old.executemany(
            "INSERT INTO flow_rollup_daily VALUES (?, ?, 'd', 445, 6, 'allowed', ?, ?, 1, 1, 0, 0, 0)",
            [("2026-10-20", "/w/a", "CORP\\Alice", "powershell.exe"),
             ("2026-10-22", "/w/a", "corp\\alice", ""),
             ("2026-10-21", "/w/b", "", "sshd"),
             ("2026-10-21", "/w/b", "root", "")])
        old.commit()
    monkeypatch.setattr(storedb, "_migrations", original)
    with FlowDb(path).connect() as new:
        assert rows(new, "account_source_baseline") == [
            {"account": "corp\\alice", "src_key": "/w/a", "first_seen": "2026-10-20T00:00:00.000+00:00",
             "last_seen": "2026-10-22T23:59:59.000+00:00"},
            {"account": "root", "src_key": "/w/b", "first_seen": "2026-10-21T00:00:00.000+00:00",
             "last_seen": "2026-10-21T23:59:59.000+00:00"}]
        assert [(r["src_key"], r["process"]) for r in rows(new, "process_baseline")] == [
            ("/w/a", "powershell.exe"), ("/w/b", "sshd")]
        names = {r[0] for r in new.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "ix_baseline_port_src" in names and "ix_baseline_port" not in names


def test_upsert_writes_account_and_process_baselines(conn):
    upsert_flows(conn, [rec(user="CORP\\Bob", process="PowerShell.EXE")], origin=DataOrigin.INGEST, now=NOW)
    [a] = rows(conn, "account_source_baseline")
    assert (a["account"], a["src_key"]) == ("corp\\bob", "/orgs/1/workloads/src-1")
    [p] = rows(conn, "process_baseline")
    assert (p["src_key"], p["process"]) == ("/orgs/1/workloads/src-1", "powershell.exe")


def test_case_variants_are_one_account(conn):
    upsert_flows(conn, [rec(1, user="CORP\\Alice"), rec(1, port=22, user="corp\\alice", minutes_ago=30)],
                 origin=DataOrigin.INGEST, now=NOW)
    [a] = rows(conn, "account_source_baseline")
    assert a["account"] == "corp\\alice"
    assert a["first_seen"] < a["last_seen"]


def _activity(conn):
    return {(r["src_key"], r["port_class"]): (r["connections"], r["bytes"], r["bytes_known"])
            for r in conn.execute("SELECT * FROM source_activity_hourly")}


def test_activity_counts_cycle_growth_not_blocked(conn):
    src = "/orgs/1/workloads/src-1"
    upsert_flows(conn, [rec(1, conns=5)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    upsert_flows(conn, [rec(1, conns=8)], origin=DataOrigin.INGEST, now=NOW + timedelta(minutes=10),
                 increments="cycle")
    assert _activity(conn) == {(src, "all"): (8, 0, 0)}
    upsert_flows(conn, [rec(1, port=389, conns=3, bytes_=700)], origin=DataOrigin.INGEST, now=NOW,
                 increments="cycle")
    assert _activity(conn) == {(src, "all"): (11, 700, 1), (src, "directory"): (3, 700, 1)}
    upsert_flows(conn, [rec(2, conns=4, decision="blocked")], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    upsert_flows(conn, [rec(3, conns=4)], origin=DataOrigin.INGEST, now=NOW, increments="late")
    upsert_flows(conn, [rec(4, conns=4)], origin=DataOrigin.BACKFILL, now=NOW)
    assert set(_activity(conn)) == {(src, "all"), (src, "directory")}
    hours = {r[0] for r in conn.execute("SELECT hour FROM source_activity_hourly")}
    assert hours == {db_time(NOW.replace(minute=0))}


def test_activity_pruned_after_eight_days(conn):
    upsert_flows(conn, [rec(1)], origin=DataOrigin.INGEST, now=NOW - timedelta(days=9), increments="cycle")
    upsert_flows(conn, [rec(2)], origin=DataOrigin.INGEST, now=NOW, increments="cycle")
    assert {k[0] for k in _activity(conn)} == {"/orgs/1/workloads/src-2"}


def test_new_baselines_pruned_with_baseline_days(conn):
    upsert_flows(conn, [rec(1, user="corp\\a", process="sshd", minutes_ago=60 * 24 * 40)], origin=DataOrigin.BACKFILL,
                 now=NOW)
    upsert_flows(conn, [rec(2, user="corp\\b", process="ssh")], origin=DataOrigin.INGEST, now=NOW)
    delete_baselines_before(conn, NOW - timedelta(days=30))
    assert [r["account"] for r in rows(conn, "account_source_baseline")] == ["corp\\b"]
    assert [r["process"] for r in rows(conn, "process_baseline")] == ["ssh"]
