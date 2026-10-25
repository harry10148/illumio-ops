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
