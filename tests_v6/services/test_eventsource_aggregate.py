"""EventSource aggregation: event segments ranked from the store, hosts joined through their VEN."""
import json
from pathlib import Path

from illumio_ops.domain.segment import EventFilter, EventSegment, GroupBy
from illumio_ops.domain.values import SegmentDimension as D
from illumio_ops.domain.values import SegmentView as V
from illumio_ops.pce.events import EventsPage
from illumio_ops.services.collect import events as ev
from illumio_ops.services.collect.events import run_events_cycle
from illumio_ops.services.eventsource import aggregate_events, event_detail
from illumio_ops.store.flowdb import workloads
from tests_v6.services.collect.conftest import NOW, configured_ctx, minutes

TAMPER = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "events_tamper.json").read_text())


def _shift(e, ts):
    e = json.loads(json.dumps(e))
    e["timestamp"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    return e


def test_event_ranking_by_type_and_host(tmp_path, monkeypatch):
    ctx = configured_ctx(tmp_path)
    items = [_shift(e, NOW - minutes(10 + i)) for i, e in enumerate(TAMPER)]
    items.append({"href": "/orgs/1/events/u1", "event_type": "user.sign_in", "timestamp":
                  (NOW - minutes(5)).strftime("%Y-%m-%dT%H:%M:%SZ"), "created_by": {"user": {"username": "a"}}})
    monkeypatch.setattr(ev, "fetch_events", lambda client, **kw: EventsPage(items=items, capped=False))
    run_events_cycle(ctx, now=NOW)
    ven = TAMPER[0]["created_by"]["ven"]["href"]
    with ctx.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/w-9", hostname="known-host", name=None, managed=1, enforcement_mode=None,
            visibility_level=None, os_id=None, ven_version=None, ven_href=ven, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
    flt = EventFilter(start=NOW - minutes(60), end=NOW)
    by_type = aggregate_events(ctx, EventSegment(filter=flt, view=V.RANKING, limit=10,
                                                 group_by=(GroupBy(dimension=D.EVENT_TYPE),)), now=NOW)
    assert {r.keys[0]: r.value for r in by_type.rows} == {"agent.tampering": 4, "user.sign_in": 1}
    by_host = aggregate_events(ctx, EventSegment(filter=flt.model_copy(update={"event_types": ("agent.tampering",)}),
                                                 view=V.RANKING, limit=10, group_by=(GroupBy(dimension=D.EVENT_HOST),)),
                               now=NOW)
    hosts = {r.display[0]: r.value for r in by_host.rows}  # P6a: keyed by href, shown by hostname
    on_ven = sum(1 for e in TAMPER if e["created_by"]["ven"]["href"] == ven)
    assert hosts["known-host"] == on_ven and sum(hosts.values()) == 4
    assert {r.display[0]: r.keys[0] for r in by_host.rows}["known-host"] == "/orgs/1/workloads/w-9"
    detail = event_detail(ctx, EventSegment(filter=flt.model_copy(update={"host_hrefs": ("/orgs/1/workloads/w-9",)}),
                                            view=V.DETAIL, limit=10), now=NOW)
    assert len(detail.rows) == on_ven and detail.coverage.gaps == []
