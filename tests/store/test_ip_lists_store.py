"""The PCE's IP lists in the flow store: names to pick from, networks a filter matches, replaced whole."""
from datetime import UTC, datetime

from illumio_ops.store.flowdb import ip_lists
from illumio_ops.store.flowdb.db import FlowDb

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


def test_replace_all_keeps_only_the_latest_lists(tmp_path):
    conn = FlowDb(tmp_path / "flows.sqlite").connect()
    ip_lists.replace_all(conn, [ip_lists.IpListRow("/l/1", "Scanners", ("10.9.0.0/16",)),
                                ip_lists.IpListRow("/l/2", "Any", ("0.0.0.0/0", "::/0"))], at=NOW)
    ip_lists.replace_all(conn, [ip_lists.IpListRow("/l/2", "Any (0.0.0.0/0)", ("0.0.0.0/0",))], at=NOW)
    assert ip_lists.names(conn) == [("/l/2", "Any (0.0.0.0/0)")]
    assert ip_lists.networks(conn) == {"/l/2": ("0.0.0.0/0",)}
    assert ip_lists.networks(conn, ["/l/1"]) == {} and ip_lists.networks(conn, []) == {}
    conn.close()
