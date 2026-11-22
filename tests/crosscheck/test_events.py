"""Events against the PCE (fake) and the event catalog, and against the flow database written by the product's own
writer (so the stored timestamp format is the real one)."""
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

import illumio_ops.crosscheck.__main__ as cli
from illumio_ops.crosscheck import events
from illumio_ops.crosscheck.model import Run
from illumio_ops.domain.events import EventRecord
from illumio_ops.domain.values import DataOrigin
from illumio_ops.paths import resolve_paths
from illumio_ops.pce.client import PceResponse, PceTransportError
from illumio_ops.settings.store import SettingsStore
from illumio_ops.store.flowdb import binding
from illumio_ops.store.flowdb.db import FlowDb
from illumio_ops.store.flowdb.events import upsert_events
from tests.web.conftest import cached_hash

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
URL = "https://pce.example.test:8443"
VALUE = "a-content-value-that-must-not-be-printed"


def _z(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def ev(i, ts, event_type="user.sign_in", **extra):
    return {"href": f"/orgs/3/events/{i:06d}", "event_type": event_type, "timestamp": _z(ts), "status": "success",
            "severity": "info", **extra}


class FakePce:
    """GET /events like the PCE: [gte, lte] by timestamp, newest first, at most max_results. `script` items are used
    first, one per request: an int is an HTTP status, an exception is raised."""

    def __init__(self, items, script=()):
        self.items = list(items)
        self.script = list(script)
        self.calls = []

    def request(self, method, path, **kw):
        assert method == "GET" and path.startswith("/events?")
        self.calls.append(path)
        if self.script:
            s = self.script.pop(0)
            if isinstance(s, Exception):
                raise s
            return PceResponse(s, b"")
        q = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
        gte, lte = (datetime.fromisoformat(q[k]) for k in ("timestamp[gte]", "timestamp[lte]"))
        sel = [e for e in self.items if gte <= datetime.fromisoformat(e["timestamp"]) <= lte]
        sel.sort(key=lambda e: e["timestamp"], reverse=True)
        return PceResponse(200, json.dumps(sel[: int(q["max_results"])]).encode())

    def close(self):
        pass


def _run(tmp_path, pce, *, days=7, margin=30, enabled=True, interval=300, event_days=90):
    paths = resolve_paths(tmp_path / "root")
    paths.ensure_dirs()
    store = SettingsStore(paths.settings_file)
    store.create_initial(password_hash=cached_hash("illumio"), secret_key="ab" * 32)

    def mutate(d):
        d["pce"].update(url=URL, org_id="3", api_key="k", api_secret="s")
        d["collection"].update(enabled=enabled, events_interval_seconds=interval)
        d["collection"]["retention"]["event_days"] = event_days

    s = store.update(store.current().revision, mutate)
    start, end = cli.period(NOW, days, margin)
    return Run(paths=paths, settings=s, pce=pce, start=start, end=end, now=NOW)


def _store(run, rows, bind=(URL, "3")):
    fdb = FlowDb(run.paths.flows_db)
    conn = fdb.connect()
    try:
        if bind:
            binding.bind(conn, bind[0], bind[1], NOW)
        recs = [EventRecord(r["href"], r["event_type"], None, None, datetime.fromisoformat(r["timestamp"]),
                            None, None, None, None, None, "{}") for r in rows]
        upsert_events(conn, recs, origin=DataOrigin.INGEST, now=NOW)
    finally:
        conn.close()


def _by(findings, status=None, item=None):
    return [f for f in findings if (status is None or f.status == status) and (item is None or item in f.item)]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(events, "_sleep", lambda s: None)


# --- fetching ---------------------------------------------------------------------------------------------------

T0 = datetime(2026, 11, 19, 0, 0, tzinfo=UTC)


def test_a_full_window_is_halved_until_not_full():
    items = [ev(i, T0 + timedelta(hours=i)) for i in range(6)]
    pce = FakePce(items)
    h = events.harvest(pce, T0, T0 + timedelta(days=1), timeout=30, cap=4)
    assert sorted(e["href"] for e in h.items) == sorted(e["href"] for e in items)
    assert h.unchecked == [] and len(pce.calls) > 1


def test_a_full_single_second_is_unchecked():
    items = [ev(i, T0 + timedelta(hours=5, milliseconds=i)) for i in range(5)]
    h = events.harvest(FakePce(items), T0, T0 + timedelta(days=1), timeout=30, cap=4)
    assert len(h.unchecked) == 1
    assert "second" in h.unchecked[0].reason and h.unchecked[0].end - h.unchecked[0].start <= timedelta(seconds=1)


def test_a_two_second_window_terminates():
    items = [ev(i, T0 + timedelta(milliseconds=i)) for i in range(5)]
    h = events.harvest(FakePce(items), T0, T0 + timedelta(seconds=2), timeout=30, cap=4)
    assert h.unchecked and all(s.end - s.start <= timedelta(seconds=1) for s in h.unchecked)


def test_split_windows_share_a_boundary_and_are_deduped():
    # events exactly on the midpoint second come back from both halves
    mid = T0 + timedelta(hours=12)
    items = [ev(i, mid) for i in range(2)] + [ev(10 + i, T0 + timedelta(hours=i)) for i in range(3)]
    h = events.harvest(FakePce(items), T0, T0 + timedelta(days=1), timeout=30, cap=4)
    hrefs = [e["href"] for e in h.items]
    assert len(hrefs) == len(set(hrefs)) == 5


def test_retries_three_times_then_succeeds():
    pce = FakePce([ev(1, T0)], script=[503, PceTransportError("/events", "timeout"), 429])
    h = events.harvest(pce, T0, T0 + timedelta(hours=1), timeout=30)
    assert len(h.items) == 1 and h.unchecked == [] and len(pce.calls) == 4


def test_four_failures_leave_the_slice_unchecked():
    pce = FakePce([ev(1, T0)], script=[503, 503, 503, 503])
    with pytest.raises(events.EventsUnavailable):  # nothing at all could be read: the area fails
        events.harvest(pce, T0, T0 + timedelta(hours=1), timeout=30)


def test_a_failed_slice_among_good_ones_is_unchecked():
    items = [ev(i, T0 + timedelta(hours=i)) for i in range(6)]
    # first call full -> split; the first half fails four times, the second half is read
    pce = FakePce(items, script=[])
    calls = {"n": 0}
    real = pce.request

    def flaky(method, path, **kw):
        calls["n"] += 1
        if 2 <= calls["n"] <= 5:
            pce.calls.append(path)
            return PceResponse(503, b"")
        return real(method, path, **kw)
    pce.request = flaky
    h = events.harvest(pce, T0, T0 + timedelta(days=1), timeout=30, cap=4)
    assert len(h.unchecked) == 1 and "503" in h.unchecked[0].reason and "3 retries" in h.unchecked[0].reason


def test_refused_connection_and_401_are_not_retried():
    with pytest.raises(PceTransportError):
        events.harvest(FakePce([], script=[PceTransportError("/events", "refused")]), T0, T0 + timedelta(hours=1),
                       timeout=30)
    with pytest.raises(events.EventsUnavailable, match="401"):
        events.harvest(FakePce([], script=[401]), T0, T0 + timedelta(hours=1), timeout=30)


# --- the check ----------------------------------------------------------------------------------------------------

def test_catalog_gap_is_inconsistent_with_field_names_only(tmp_path):
    t = NOW - timedelta(days=1)
    pce = FakePce([ev(1, t), ev(2, t, "brand_new.thing", action={"secret": VALUE}),
                   ev(3, t, "brand_new.thing", note=VALUE)])
    run = _run(tmp_path, pce)
    _store(run, pce.items)
    f = events.check(run)
    gap = _by(f, "inconsistent", "brand_new.thing")
    assert len(gap) == 1 and "2" in gap[0].detail
    assert set(gap[0].sample) == {"href", "event_type", "timestamp", "fields"}
    assert "action" in gap[0].sample["fields"] or "note" in gap[0].sample["fields"]
    assert VALUE not in json.dumps([f_.__dict__ for f_ in f], default=str)
    summary = _by(f, "consistent", "catalog")
    assert summary and "did not appear" in summary[0].detail


def test_events_missing_from_the_store_and_extra_ones(tmp_path):
    t = NOW - timedelta(days=2)
    pce = FakePce([ev(1, t), ev(2, t + timedelta(minutes=1)), ev(3, t + timedelta(minutes=2))])
    run = _run(tmp_path, pce)
    _store(run, [pce.items[0], pce.items[1], ev(99, t + timedelta(minutes=3))])
    f = events.check(run)
    missing = _by(f, "inconsistent", "not received")
    assert len(missing) == 1 and "1" in missing[0].detail
    assert missing[0].sample[0]["href"] == "/orgs/3/events/000003"
    extra = _by(f, "inconsistent", "not on the PCE")
    assert len(extra) == 1 and extra[0].sample[0]["href"] == "/orgs/3/events/000099"
    assert "deleted" in extra[0].detail
    matched = _by(f, "consistent", "received")
    assert matched and "2" in matched[0].detail


def test_all_received_is_consistent(tmp_path):
    t = NOW - timedelta(days=2)
    pce = FakePce([ev(i, t + timedelta(minutes=i)) for i in range(5)])
    run = _run(tmp_path, pce)
    _store(run, pce.items)
    f = events.check(run)
    assert _by(f, "inconsistent") == []
    assert _by(f, "consistent", "received")


def test_outside_retention_is_unchecked_not_missing(tmp_path):
    old = NOW - timedelta(days=3)
    pce = FakePce([ev(1, old), ev(2, NOW - timedelta(hours=5))])
    run = _run(tmp_path, pce, event_days=1)
    _store(run, [pce.items[1]])
    f = events.check(run)
    assert _by(f, "inconsistent") == []
    ret = _by(f, "unchecked", "retention")
    assert len(ret) == 1 and "1 PCE event" in ret[0].detail


def test_collection_off_leaves_the_store_unchecked_but_checks_the_catalog(tmp_path):
    pce = FakePce([ev(1, NOW - timedelta(days=1), "brand_new.thing")])
    run = _run(tmp_path, pce, enabled=False)
    f = events.check(run)
    assert _by(f, "unchecked", "received") and "switched off" in _by(f, "unchecked", "received")[0].detail
    assert _by(f, "inconsistent", "brand_new.thing")


def test_not_yet_collected_tail_is_unchecked(tmp_path):
    # collected every hour, the period ends 30 minutes ago: the last ~65 minutes may not be collected yet
    tail = NOW - timedelta(minutes=50)
    pce = FakePce([ev(1, NOW - timedelta(days=1)), ev(2, tail)])
    run = _run(tmp_path, pce, interval=3600)
    _store(run, [pce.items[0]])
    f = events.check(run)
    assert _by(f, "inconsistent") == []
    lag = _by(f, "unchecked", "not collected yet")
    assert len(lag) == 1 and "1 PCE event" in lag[0].detail


def test_store_of_another_pce_is_unchecked(tmp_path):
    pce = FakePce([ev(1, NOW - timedelta(days=1))])
    run = _run(tmp_path, pce)
    _store(run, [], bind=("https://other.example.test", "9"))
    f = events.check(run)
    assert _by(f, "inconsistent") == []
    assert "another PCE" in _by(f, "unchecked", "received")[0].detail


def test_missing_flow_database_is_unchecked(tmp_path):
    run = _run(tmp_path, FakePce([ev(1, NOW - timedelta(days=1))]))
    f = events.check(run)
    assert _by(f, "inconsistent") == [] and _by(f, "unchecked", "received")


def test_a_stored_event_inside_an_unread_slice_is_not_called_extra(tmp_path):
    # 5 events in one second at the cap: that second is unchecked; a stored event there must not be "extra"
    sec = NOW - timedelta(days=1)
    pce = FakePce([ev(i, sec + timedelta(milliseconds=i)) for i in range(5)])
    run = _run(tmp_path, pce)
    _store(run, [ev(99, sec + timedelta(milliseconds=500))])
    f = events.check(run, cap=4)
    assert _by(f, "inconsistent", "not on the PCE") == []
    assert any("one second" in w.detail for w in _by(f, "unchecked", "PCE window"))


def test_incomplete_pce_events_are_counted_with_field_names(tmp_path):
    t = NOW - timedelta(days=1)
    bad = {"event_type": "user.sign_in", "timestamp": _z(t), "info": VALUE}  # no href
    bad2 = {"href": "/orgs/3/events/x", "event_type": "user.sign_in", "timestamp": "yesterday", "info": VALUE}
    pce = FakePce([ev(1, t)])
    pce.items += [bad, bad2]
    real = pce.request

    def request(method, path, **kw):  # the fake's filter cannot parse "yesterday": serve all
        pce.calls.append(path)
        return PceResponse(200, json.dumps(pce.items).encode())
    pce.request = request
    run = _run(tmp_path, pce)
    _store(run, [pce.items[0]])
    f = events.check(run)
    inc = _by(f, "unchecked", "incomplete")
    assert len(inc) == 1 and "2" in inc[0].detail
    assert VALUE not in json.dumps([f_.__dict__ for f_ in f], default=str)
    assert real  # unused


def test_reads_the_store_read_only(tmp_path, monkeypatch):
    seen = []
    real = events.open_ro
    monkeypatch.setattr(events, "open_ro", lambda p: seen.append(p) or real(p))
    t = NOW - timedelta(days=1)
    pce = FakePce([ev(1, t)])
    run = _run(tmp_path, pce)
    _store(run, pce.items)
    events.check(run)
    assert seen == [run.paths.flows_db]


def test_full_is_judged_on_the_raw_response_and_non_objects_are_counted(tmp_path):
    t = NOW - timedelta(days=1)
    good = [ev(i, t + timedelta(hours=i % 5, minutes=i)) for i in range(3)]
    pce = FakePce(good)
    real = pce.request

    def request(method, path, **kw):  # every answer carries one non-object besides the events
        resp = real(method, path, **kw)
        return PceResponse(200, json.dumps(json.loads(resp.body) + ["not an event"]).encode())
    pce.request = request
    h = events.harvest(pce, t - timedelta(hours=1), t + timedelta(hours=6), timeout=30, cap=4)
    assert len(pce.calls) > 1  # 3 events + 1 non-object = 4 = the cap: the window was full and was split
    assert sorted(e["href"] for e in h.items) == sorted(e["href"] for e in good) and h.non_objects >= 1
    run = _run(tmp_path, pce)
    _store(run, good)
    inc = _by(events.check(run, cap=4), "unchecked", "incomplete")
    assert len(inc) == 1 and "not a JSON object" in inc[0].detail
