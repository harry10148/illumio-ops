import json
from pathlib import Path

import pytest

from illumio_ops.domain.events import EventShapeError, normalize_event
from illumio_ops.domain.values import TamperClassification

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "events_tamper.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(FIXTURE.read_text())


def test_tamper_classification_parsed(raw):
    kinds = [normalize_event(e).tamper_classification for e in raw]
    assert kinds == [TamperClassification.CONFIRMED, TamperClassification.CONFIRMED,
                     TamperClassification.SIGNAL, TamperClassification.SIGNAL]


def test_created_by_prefers_ven(raw):
    r = normalize_event(raw[0])
    assert r.created_by_kind == "ven"
    assert r.created_by_href and r.created_by_href.startswith("/orgs/1/vens/")
    assert r.created_by_name


def test_events_timestamps_are_aware_utc(raw):
    r = normalize_event(raw[0])
    assert r.timestamp.tzinfo is not None and r.timestamp.utcoffset().total_seconds() == 0


def test_unknown_classification_kept_as_text(raw):
    e = json.loads(json.dumps(raw[0]))
    e["notifications"][0]["info"]["event_classification"] = "suspected"
    assert normalize_event(e).tamper_classification == "suspected"


def test_non_tamper_event_has_no_classification(raw):
    e = json.loads(json.dumps(raw[0]))
    e["event_type"] = "user.sign_in"
    assert normalize_event(e).tamper_classification is None


def test_missing_href_or_timestamp_raises(raw):
    for key in ("href", "timestamp", "event_type"):
        e = json.loads(json.dumps(raw[0]))
        del e[key]
        with pytest.raises(EventShapeError):
            normalize_event(e)


def test_raw_json_is_kept(raw):
    assert json.loads(normalize_event(raw[2]).raw_json)["href"] == raw[2]["href"]


def test_event_hosts_three_shapes():
    from illumio_ops.domain.events import event_hosts
    agent = {"created_by": {"agent": {"href": "/orgs/1/agents/7", "hostname": "h1"},
                            "ven": {"href": "/orgs/1/vens/v-1", "hostname": "h1"}}}
    hosts = event_hosts(agent)
    assert hosts.ven_hrefs == frozenset({"/orgs/1/vens/v-1"}) and hosts.hostnames == frozenset({"h1"})
    offline = {"created_by": {"system": {}}, "resource_changes": [
        {"resource": {"workload": {"href": "/orgs/1/workloads/w-9", "hostname": "dev"}},
         "changes": {"online": {"before": True, "after": False}}}]}
    hosts = event_hosts(offline)
    assert hosts.workload_hrefs == frozenset({"/orgs/1/workloads/w-9"}) and hosts.hostnames == frozenset({"dev"})
    assert event_hosts({"created_by": {"user": {"username": "a"}}}) == event_hosts({})


def test_offline_precursor_only_on_online_to_offline():
    from illumio_ops.domain.events import precursor_of
    from illumio_ops.domain.values import PrecursorKind

    def offline(before, after):
        return {"event_type": "system_task.agent_offline_check", "created_by": {"system": {}}, "resource_changes": [
            {"resource": {"workload": {"href": "/orgs/1/workloads/w-9", "hostname": "dev"}},
             "changes": {"online": {"before": before, "after": after}}}]}
    kind, hosts, signal = precursor_of(offline(True, False))
    assert kind is PrecursorKind.OFFLINE and hosts.workload_hrefs == frozenset({"/orgs/1/workloads/w-9"}) and not signal
    assert precursor_of(offline(False, True)) is None
    tamper = {"event_type": "agent.tampering", "created_by": {"ven": {"href": "/orgs/1/vens/v-1", "hostname": "h"}},
              "notifications": [{"info": {"event_classification": "signal"}}]}
    assert precursor_of(tamper)[0] is PrecursorKind.TAMPER and precursor_of(tamper)[2] is True
    assert precursor_of({"event_type": "user.sign_in", "created_by": {"user": {}}}) is None
