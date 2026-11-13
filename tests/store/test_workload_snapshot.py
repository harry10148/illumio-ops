"""The daily snapshot of the inventory knows which hosts were managed (migration 0018, UI redesign spec §9.1): the
security risk report reads from it what share of the managed hosts was enforced on the last day of the previous
period. A day written before the column, or with no snapshot, cannot be compared and reads as None — never as
"no managed host"."""
from illumio_ops.store import db as storedb
from illumio_ops.store.flowdb import db as flowdb
from illumio_ops.store.flowdb import workloads
from illumio_ops.store.flowdb.db import FlowDb

DAY = "2026-10-19"


def _row(name, mode, *, managed=1):
    return workloads.WorkloadRow(
        href=f"/orgs/1/workloads/{name}", hostname=name, name=None, managed=managed, enforcement_mode=mode,
        visibility_level=None, os_id=None, ven_version=None, ven_href=None, label_set=None, online=1,
        risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")


MIXED = [_row("a", "full"), _row("b", "selective"), _row("c", "visibility_only"), _row("d", "idle"),
         _row("e", None),                      # managed, and the PCE gave no mode: a managed host all the same
         _row("u", "full", managed=0)]         # no VEN: not one of the managed hosts, whatever its mode says


def _snapshot(conn, rows, day=DAY):
    workloads.replace_inventory(conn, rows)
    workloads.snapshot_day(conn, day)
    conn.commit()


def test_a_snapshot_written_before_the_column_cannot_be_compared(tmp_path, monkeypatch):
    path = tmp_path / "flows.sqlite"
    original = storedb._migrations
    monkeypatch.setattr(storedb, "_migrations", lambda package=storedb.APP_MIGRATIONS:
                        original(package)[:17] if package == flowdb.MIGRATIONS_PACKAGE else original(package))
    with FlowDb(path).connect() as old:
        assert old.execute("PRAGMA user_version").fetchone()[0] == 17
        old.execute("INSERT INTO workload_snapshot_daily (day, href, enforcement_mode) VALUES (?, '/w/a', 'full')",
                    (DAY,))
        old.commit()
    monkeypatch.setattr(storedb, "_migrations", original)
    with FlowDb(path).connect() as new:
        assert new.execute("PRAGMA user_version").fetchone()[0] == 18
        assert [tuple(r) for r in new.execute("SELECT href, managed FROM workload_snapshot_daily")] == [("/w/a", None)]
        assert workloads.mode_counts_on(new, DAY) is None


def test_a_snapshot_counts_the_managed_hosts_by_mode(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        _snapshot(conn, MIXED)
        got = workloads.mode_counts_on(conn, DAY)
    # five managed hosts (the one without a mode among them); the unmanaged one is in no number
    assert got == workloads.ModeCounts(hosts=5, modes={"full": 1, "selective": 1, "visibility_only": 1, "idle": 1})


def test_a_day_without_a_snapshot_cannot_be_compared(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        _snapshot(conn, MIXED)
        assert workloads.mode_counts_on(conn, "2026-10-18") is None


def test_one_row_without_the_column_makes_its_day_not_comparable(tmp_path):
    """A day whose snapshot holds a row from before the column is not half-counted: the hosts counted would be the
    ones written since, a different set from the day's."""
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        _snapshot(conn, MIXED)
        conn.execute("INSERT INTO workload_snapshot_daily (day, href, enforcement_mode) VALUES (?, '/w/old', 'full')",
                     (DAY,))
        conn.commit()
        assert workloads.mode_counts_on(conn, DAY) is None


def test_the_days_snapshot_is_the_latest_inventory(tmp_path):
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        _snapshot(conn, MIXED)
        _snapshot(conn, [_row("a", "full"), _row("b", "full")])
        assert workloads.mode_counts_on(conn, DAY) == workloads.ModeCounts(hosts=2, modes={"full": 2})


def test_a_copied_store_keeps_which_hosts_were_managed(tmp_path):
    """An on-demand store starts from the install's inventory and snapshots (services/ondemand.py): a report built
    on it compares with the previous period as one built on the install does."""
    with FlowDb(tmp_path / "install.sqlite").connect() as conn:
        _snapshot(conn, MIXED)
        want = workloads.mode_counts_on(conn, DAY)
    with FlowDb(tmp_path / "pulled.sqlite").connect() as conn:
        conn.execute("ATTACH DATABASE ? AS install", (str(tmp_path / "install.sqlite"),))
        workloads.copy_from(conn, "install")
        conn.commit()
        conn.execute("DETACH DATABASE install")
        assert workloads.mode_counts_on(conn, DAY) == want and want is not None
