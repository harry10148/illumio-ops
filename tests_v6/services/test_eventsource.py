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


def test_each_host_of_a_batch_event_resolved_on_its_own(tmp_path):
    # Final review #12: one host matched directly kept the others from the hostname fallback.
    from illumio_ops.services.eventsource import precursor_events
    ctx = configured_ctx(tmp_path)
    _inventory(ctx, ("/orgs/1/workloads/a", "a", "/v/a"), ("/orgs/1/workloads/b-new", "b", "/v/b"))

    def lost(href, name):
        return {"resource": {"workload": {"href": href, "hostname": name}},
                "changes": {"online": {"before": True, "after": False}}}
    _store_events(ctx, [{"href": "/orgs/1/events/o1", "event_type": "system_task.agent_offline_check",
                         "timestamp": (NOW - minutes(10)).strftime("%Y-%m-%dT%H:%M:%SZ"), "severity": "info",
                         "created_by": {"system": {}},
                         "resource_changes": [lost("/orgs/1/workloads/a", "a"), lost("/orgs/1/workloads/b-old", "b"),
                                              lost("/orgs/1/workloads/c-old", "nobody-knows")]}])
    got = precursor_events(ctx, start=NOW - minutes(60), end=NOW)
    assert sorted(p.host_key for p in got.items) == ["/orgs/1/workloads/a", "/orgs/1/workloads/b-new"]
    assert got.unmatched == 1


def test_event_naming_no_host_is_counted_unmatched(tmp_path):
    # Security review of 23e68c98: an event without any host field must not vanish from the counts.
    from illumio_ops.services.eventsource import precursor_events, tamper_events
    ctx = configured_ctx(tmp_path)
    _inventory(ctx, ("/orgs/1/workloads/w-1", "a", "/v/1"))
    bare = _tamper("/orgs/1/events/e1", "/v/1", "a", NOW - minutes(10))
    bare["created_by"] = {}
    _store_events(ctx, [bare])
    assert precursor_events(ctx, start=NOW - minutes(60), end=NOW).unmatched == 1
    assert tamper_events(ctx, start=NOW - minutes(60), end=NOW).unmatched == 1


def test_events_after_skips_backfill(collected):
    from illumio_ops.domain.events import normalize_event
    from illumio_ops.domain.values import DataOrigin
    from illumio_ops.services.eventsource import events_after, max_event_id
    from illumio_ops.store.flowdb.events import upsert_events
    with collected.flows().connect() as conn:
        upsert_events(conn, [normalize_event({"href": "/orgs/1/events/old", "event_type": "user.sign_in",
                                              "timestamp": "2026-10-01T00:00:00Z"})],
                      origin=DataOrigin.BACKFILL, now=NOW)
    rows, more = events_after(collected, 0, limit=100)
    assert len(rows) == 5 and not more and all(r.origin == "ingest" for r in rows)
    assert [r.id for r in rows] == sorted(r.id for r in rows) and max_event_id(collected) == 6


def test_events_after_limit_and_more(collected):
    from illumio_ops.services.eventsource import events_after
    first, more = events_after(collected, 0, limit=2)
    assert len(first) == 2 and more
    rest, more = events_after(collected, first[-1].id, limit=10)
    assert len(rest) == 3 and not more


def test_events_in_window_exact_types(collected):
    from illumio_ops.services.eventsource import events_in_window
    rows = events_in_window(collected, start=NOW - minutes(60), end=NOW, exact_types=("user.sign_in",))
    assert [r.event_type for r in rows] == ["user.sign_in"]
    assert len(events_in_window(collected, start=NOW - minutes(60), end=NOW, exact_types=None)) == 5
    assert events_in_window(collected, start=NOW - minutes(6), end=NOW, exact_types=None)[0].event_type == "user.sign_in"


def test_new_event_host_through_ven(collected):
    from illumio_ops.services.eventsource import events_after
    ven = TAMPER[0]["created_by"]["ven"]["href"]
    with collected.flows().connect() as conn:
        workloads.replace_inventory(conn, [workloads.WorkloadRow(
            href="/orgs/1/workloads/w-9", hostname="h9", name=None, managed=1, enforcement_mode=None,
            visibility_level=None, os_id=None, ven_version=None, ven_href=ven, label_set=None, online=1,
            risk_exposure=None, risk_percent=None, risk_updated_at=None, fetched_at="x")])
    rows, _ = events_after(collected, 0, limit=100)
    mine = [r for r in rows if r.created_by_href == ven]
    assert mine and all(r.host_key == "/orgs/1/workloads/w-9" and r.hostname == "h9" for r in mine)
