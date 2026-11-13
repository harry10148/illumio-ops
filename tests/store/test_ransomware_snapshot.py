"""The daily snapshot of the PCE's ransomware services, read for one day: the ransomware report's trend, and what the
security risk report works the previous period's ransomware part from (UI redesign spec §9.1)."""
from datetime import UTC, datetime

from illumio_ops.store.flowdb import ransomware
from illumio_ops.store.flowdb.db import FlowDb

NOW = datetime(2026, 10, 27, 1, 0, tzinfo=UTC)
DAY = "2026-10-19"


def _svc(i, severity, state):
    return {"name": f"svc{i}", "port": 1000 + i, "proto": 6, "severity": severity, "protection_state": state,
            "port_status": "listening"}


def _snapshot(conn, services, day=DAY):
    ransomware.upsert_services(conn, "/orgs/1/workloads/a", services, source_updated_at=None, at=NOW)
    ransomware.snapshot_day(conn, day)
    conn.commit()


def test_a_protection_state_counts_whatever_its_case(tmp_path):
    """The PCE writes the states in lower case. The count does not rest on that: "Unprotected" is an unprotected
    service here as it is where the hourly analysis reads it (domain.ransomware.service_coverage), so the two
    counts of one set of services cannot drift apart on a spelling."""
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        _snapshot(conn, [_svc(1, "critical", "unprotected"), _svc(2, "high", "Unprotected"),
                         _svc(3, "HIGH", "UNPROTECTED"), _svc(4, "critical", "protected_open"),
                         _svc(5, "Critical", "Protected_Closed"),
                         _svc(6, "low", "unprotected"),        # not critical or high
                         _svc(7, "critical", None),            # the PCE gave no state: neither protected nor not
                         _svc(8, "high", "pending")])          # a state that is neither
        # five critical or high services with a known state, two of them protected
        assert ransomware.protected_by_day(conn, DAY, DAY) == {DAY: (5, 2)}


def test_a_day_with_nothing_rated_is_told_from_a_day_without_a_snapshot(tmp_path):
    """protected_by_day gives nothing for both: a day whose snapshot holds no critical or high service of a known
    state, and a day with no snapshot at all. snapshot_taken tells them apart."""
    with FlowDb(tmp_path / "flows.sqlite").connect() as conn:
        _snapshot(conn, [_svc(1, "low", "unprotected"), _svc(2, "critical", None)])
        assert ransomware.protected_by_day(conn, DAY, DAY) == {}
        assert ransomware.snapshot_taken(conn, DAY) is True
        assert ransomware.protected_by_day(conn, "2026-10-18", "2026-10-18") == {}
        assert ransomware.snapshot_taken(conn, "2026-10-18") is False
