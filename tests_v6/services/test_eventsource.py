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
