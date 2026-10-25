"""EventSource: events with the same coverage semantics as FlowSource."""
import json
from pathlib import Path

import pytest

from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.events import run_events_cycle
from illumio_ops.services.eventsource import query_events
from illumio_ops.store.flowdb import workloads
from tests_v6.services.collect.conftest import NOW, configured_ctx, minutes

TAMPER = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "events_tamper.json").read_text())


def _shift(e, ts):
    e = json.loads(json.dumps(e))
    e["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return e


@pytest.fixture
def collected(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    items = [_shift(e, NOW - minutes(10 + i)) for i, e in enumerate(TAMPER)]
    items.append({"href": "/orgs/1/events/u1", "event_type": "user.sign_in", "timestamp":
                  (NOW - minutes(5)).strftime("%Y-%m-%dT%H:%M:%SZ"), "created_by": {"user": {"username": "a"}}})
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=items, capped=False))
    run_events_cycle(ctx, now=NOW)
    return ctx


def test_events_query_coverage(collected):
    q = query_events(collected, start=NOW - minutes(60), end=NOW, limit=100)
    assert q.coverage.source == "store" and q.coverage.gaps == [] and len(q.rows) == 5
    assert q.rows[0].timestamp >= q.rows[-1].timestamp
    q = query_events(collected, start=NOW - minutes(60), end=NOW, event_types=("agent.tampering",), limit=100)
    assert len(q.rows) == 4 and q.rows[0].raw["event_type"] == "agent.tampering"


def test_events_by_workload_joins_through_ven(collected):
    ven = TAMPER[0]["created_by"]["ven"]["href"]
    with collected.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/w-9", hostname="h", name=None, managed=1, enforcement_mode=None,
            visibility_level=None, os_id=None, ven_version=None, ven_href=ven, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
    q = query_events(collected, start=NOW - minutes(60), end=NOW, workload_href="/orgs/1/workloads/w-9", limit=100)
    assert len(q.rows) == sum(1 for e in TAMPER if e["created_by"]["ven"]["href"] == ven) and q.rows


def test_events_after_watermark_not_yet_collected(collected):
    q = query_events(collected, start=NOW - minutes(60), end=NOW + minutes(5), limit=100)
    assert [g[2] for g in q.coverage.gaps] == ["not_yet_collected"]


def _store_events(ctx, raws):
    from illumio_ops.domain.events import normalize_event
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.store.flowdb.events import upsert_events
    with ctx.flows().connect() as conn:
        upsert_events(conn, [normalize_event(r) for r in raws], origin=DataOrigin.INGEST, now=NOW)


def _tamper(href, ven, hostname, ts):
    return {"href": href, "event_type": "agent.tampering", "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "severity": "warning", "created_by": {"ven": {"href": ven, "hostname": hostname}},
            "notifications": [{"info": {"event_classification": "signal"}}]}


def _inventory(ctx, *rows):
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href=href, hostname=name, name=None, managed=1, enforcement_mode=None, visibility_level=None, os_id=None,
            ven_version=None, ven_href=ven, label_set=None, online=1, risk_exposure=None, risk_percent=None,
            risk_updated_at=None, fetched_at="x") for href, name, ven in rows])


def test_repaired_ven_matched_by_unique_hostname(tmp_path):
    from illumio_ops.domain.values import PrecursorKind
    from illumio_ops.services.eventsource import precursor_events
    ctx = configured_ctx(tmp_path)
    _inventory(ctx, ("/orgs/1/workloads/w-9", "host-31", "/orgs/1/vens/new"), ("/orgs/1/workloads/w-1", "a", "/v/1"))
    _store_events(ctx, [_tamper("/orgs/1/events/e1", "/orgs/1/vens/old", "host-31", NOW - minutes(30)),
                        _tamper("/orgs/1/events/e2", "/v/1", "a", NOW - minutes(20))])
    got = precursor_events(ctx, start=NOW - minutes(60), end=NOW)
    assert sorted((p.host_key, p.kind, p.signal) for p in got.items) == [
        ("/orgs/1/workloads/w-1", PrecursorKind.TAMPER, True), ("/orgs/1/workloads/w-9", PrecursorKind.TAMPER, True)]
    assert got.unmatched == 0


def test_unmatched_precursor_counted(tmp_path):
    from illumio_ops.services.eventsource import precursor_events
    ctx = configured_ctx(tmp_path)
    _inventory(ctx, ("/orgs/1/workloads/w-1", "same", "/v/1"), ("/orgs/1/workloads/w-2", "same", "/v/2"))
    _store_events(ctx, [_tamper("/orgs/1/events/e1", "/v/gone", "same", NOW - minutes(30)),  # name not unique
                        _tamper("/orgs/1/events/e2", "/v/gone2", "nobody-knows", NOW - minutes(30))])
    got = precursor_events(ctx, start=NOW - minutes(60), end=NOW)
    assert got.items == [] and got.unmatched == 2
