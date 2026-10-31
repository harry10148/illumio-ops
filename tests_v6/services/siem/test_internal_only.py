"""'Exclude public addresses' for new connections (user 2026-10-31: lab's new connections were mostly internet scans
of the firewall's public address)."""
import json
from dataclasses import replace

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.netaddr import is_public
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.siem.dispatch import run_siem
from illumio_ops.services.siem.status import siem_status
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.store.test_siem_sources import FIXTURE

from .conftest import NOW, FakeTransport, configure, destination


@pytest.mark.parametrize(("ip", "public"), [
    ("10.1.2.3", False), ("172.16.15.106", False), ("192.168.10.44", False), ("100.64.0.9", False),
    ("169.254.1.1", False), ("127.0.0.1", False), ("fd00::1", False), ("::ffff:10.0.0.1", False),
    ("114.35.37.162", True), ("8.8.8.8", True), ("2001:4860:4860::8888", True), (None, False), ("", False),
    ("FILTERED", False)])
def test_public_means_a_globally_routed_address(ip, public):
    assert is_public(ip) is public


def _log(ctx, *pairs):
    base = normalize_flow(json.loads(FIXTURE.read_text())[0])
    recs = [replace(base, src_ip=s, dst_ip=d, src_href=None, dst_href=None, port=1000 + i)
            for i, (s, d) in enumerate(pairs)]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW, increments="cycle", log_new_connections=True)
        conn.commit()
        return [dict(r) for r in conn.execute("SELECT src_ip, dst_ip, public FROM new_connection_log ORDER BY id")]


def test_the_log_says_whether_an_end_is_public(ctx):
    rows = _log(ctx, ("10.0.0.1", "10.0.0.2"), ("66.132.186.241", "114.35.37.162"), ("10.0.0.1", "8.8.8.8"))
    assert {r["dst_ip"]: r["public"] for r in rows} == {"10.0.0.2": 0, "114.35.37.162": 1, "8.8.8.8": 1}


def test_internal_only_sends_the_east_west_ones_and_counts_only_them(ctx):
    configure(ctx, destination(sources=["new_connections"], new_connection_internal_only=True))
    run_siem(ctx, now=NOW, transport_factory=lambda d: FakeTransport())
    _log(ctx, ("10.0.0.1", "10.0.0.2"), ("66.132.186.241", "114.35.37.162"), ("10.0.0.3", "8.8.8.8"))
    assert siem_status(ctx).destinations[0].sources[0].pending == 1
    t = FakeTransport()
    run_siem(ctx, now=NOW, transport_factory=lambda d: t)
    assert [json.loads(x)["dst_ip"] for x in t.lines] == ["10.0.0.2"]


def test_without_it_every_new_connection_goes(ctx):
    configure(ctx, destination(sources=["new_connections"], new_connection_internal_only=False))
    run_siem(ctx, now=NOW, transport_factory=lambda d: FakeTransport())
    _log(ctx, ("10.0.0.1", "10.0.0.2"), ("66.132.186.241", "114.35.37.162"))
    t = FakeTransport()
    run_siem(ctx, now=NOW, transport_factory=lambda d: t)
    assert len(t.lines) == 2


def test_a_v9_destination_leaves_public_ends_out_after_the_upgrade():
    from illumio_ops.settings.schema import default_settings
    from illumio_ops.settings.store import validate_settings
    from tests_v6.settings.conftest import HASH, KEY
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 9
    dest = destination(sources=["new_connections"])
    del dest["new_connection_internal_only"]
    d["siem"]["destinations"] = [dest]
    assert validate_settings(d).siem.destinations[0].new_connection_internal_only is True


def test_a_migrated_traffic_destination_leaves_public_ends_out():
    from illumio_ops.domain.values import CollectionMode
    from illumio_ops.migrate.v5_siem import migrate_siem
    out, items = migrate_siem({"siem": {"destinations": [{"name": "g", "host": "h", "source_types": ["traffic"]}]}},
                              mode=CollectionMode.FULL)
    assert out["destinations"][0]["new_connection_internal_only"] is True
    assert any(i.reason_key == "migrate_siem_internal_only" for i in items)
