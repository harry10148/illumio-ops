"""Codex final review of P7 (7 Important findings), each reproduced here first."""
import json
from datetime import timedelta

import pytest

from illumio_ops.domain.flows import normalize_flow
from illumio_ops.domain.values import DataOrigin
from illumio_ops.services.collect.reset import reset_for_new_pce
from illumio_ops.services.collect.retention import run_retention
from illumio_ops.services.siem import dispatch, sources
from illumio_ops.services.siem.dispatch import run_siem
from illumio_ops.services.siem.status import siem_status
from illumio_ops.store import siem as store
from illumio_ops.store.flowdb.flows import upsert_flows
from tests_v6.store.test_siem_sources import FIXTURE

from .conftest import (
    DEST,
    NOW,
    REFUSED,
    FakeTransport,
    add_events,
    configure,
    destination,
)


def run(ctx, t, **kw):
    return run_siem(ctx, now=NOW, transport_factory=lambda d: t, **kw)


def ids(t):
    return [json.loads(x)["pce_event_id"].rsplit("e", 1)[1] for x in t.lines]


def test_1_an_event_stored_between_saving_and_the_first_run_is_sent(ctx):
    from illumio_ops.services.siem.cursors import place_new_cursors
    place_new_cursors(ctx)  # what saving the SIEM page does
    add_events(ctx, [1])
    t = FakeTransport()
    run(ctx, t)
    assert ids(t) == ["1"]


def test_1_after_a_pce_switch_events_collected_before_the_first_run_are_sent(ctx):
    run(ctx, FakeTransport())
    ctx.settings.update(ctx.settings.current().revision, lambda d: d["pce"].update({"url": "https://b.test:8443"}))
    reset_for_new_pce(ctx, now=NOW)
    add_events(ctx, [1])  # collected for the new PCE before SIEM runs
    t = FakeTransport()
    run(ctx, t)
    assert ids(t) == ["1"]


def test_2_a_switch_during_a_run_stops_it(ctx, monkeypatch):
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2])
    real = sources.SOURCES["audit"].read

    def switching(c, s, after, limit, dest):
        out = real(c, s, after, limit, dest)
        c.flows().generation += 1  # a PCE switch lands between the read and the send
        return out
    monkeypatch.setitem(sources.SOURCES, "audit", sources.Source("audit", switching, "", "", True))
    t = FakeTransport()
    run(ctx, t)
    assert t.lines == []


def test_3_a_batch_of_one_still_probes_the_next_record(ctx):
    configure(ctx, destination(batch_size=1))
    run(ctx, FakeTransport())
    add_events(ctx, [1, 2])
    poison = FakeTransport(lambda n, line: REFUSED if "events/e1" in line else None)
    for _ in range(3):
        run(ctx, poison)
    with ctx.db() as conn:
        assert store.dlq_count(conn, DEST) == 1
    assert "2" in ids(poison)


def test_4_a_busy_destination_does_not_starve_the_next(ctx):
    configure(ctx, destination(batch_size=10), destination(id="e" * 32, name="second", batch_size=10))
    run(ctx, FakeTransport())
    add_events(ctx, range(1, 300))
    ticks = iter(range(10_000))
    second = FakeTransport()
    first = FakeTransport()
    run_siem(ctx, now=NOW, budget_seconds=20, clock=lambda: next(ticks),
             transport_factory=lambda d: second if d.name == "second" else first)
    assert first.lines and second.lines


def test_5_a_v8_file_with_350_rules_still_loads(tmp_path):
    from illumio_ops.domain.alertrules import EventRule
    from illumio_ops.settings.schema import default_settings
    from illumio_ops.settings.store import validate_settings
    from tests_v6.settings.conftest import HASH, KEY
    d = default_settings(password_hash=HASH, secret_key=KEY).model_dump(mode="json")
    d["schema_version"] = 8
    del d["siem"]
    pack = [r for r in d["alerts"]["rules"] if r.get("pack_key") != "rule_system_siem_backlog"]
    own = next(r for r in pack if r["type"] == "event")
    while len(pack) < 350:
        r = dict(own, id=f"{len(pack):032x}", name=f"own {len(pack)}", pack_key=None)
        pack.append(r)
    d["alerts"]["rules"] = pack
    assert len(validate_settings(d).alerts.rules) == 351
    _ = EventRule


def test_6_the_budget_stops_a_batch_midway(ctx):
    configure(ctx, destination(batch_size=100))
    run(ctx, FakeTransport())
    add_events(ctx, range(1, 51))
    ticks = iter(range(10_000))
    t = FakeTransport()
    run_siem(ctx, now=NOW, budget_seconds=10, clock=lambda: next(ticks), transport_factory=lambda d: t)
    assert 0 < len(t.lines) < 50


def test_7_pending_and_dropped_follow_the_decision_filter(ctx):
    configure(ctx, destination(sources=["new_connections"], new_connection_decisions=["blocked"]))
    run(ctx, FakeTransport())
    recs = [normalize_flow(r) for r in json.loads(FIXTURE.read_text())]
    with ctx.flows().connect() as conn:
        upsert_flows(conn, recs, origin=DataOrigin.INGEST, now=NOW, increments="cycle", log_new_connections=True)
        conn.commit()
        blocked = conn.execute("SELECT COUNT(*) FROM new_connection_log WHERE decision = 'blocked'").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM new_connection_log").fetchone()[0]
    assert total > blocked
    assert siem_status(ctx).destinations[0].sources[0].pending == blocked
    run_retention(ctx, now=NOW + timedelta(days=30))
    with ctx.db() as conn:
        assert store.get_cursor(conn, DEST, "new_connections").dropped == blocked


@pytest.fixture(autouse=True)
def _no_identity(monkeypatch):
    monkeypatch.setattr(dispatch, "_pce_version", lambda ctx, s: "unknown")
