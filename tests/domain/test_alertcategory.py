"""Alert categories (UI redesign spec §4.1) and what an alert shows that the vendor's tools cannot."""
import pytest

from illumio_ops.domain.alertcategory import (
    ANOMALY_DETECTORS,
    category,
    category_filter,
)
from illumio_ops.domain.beyond_vendor import beyond_vendor
from illumio_ops.domain.values import AlertRuleType, DetectorKind

ANOMALIES = {"peer_deviation", "volume_surge", "account_new_source", "suspicious_tool", "new_process",
             "auth_to_non_dc", "new_dc_client", "directory_surge", "direction_reversal", "new_pair_port",
             "quiet_host_wakes", "data_staging", "off_hours"}


def test_anomaly_set_is_the_allowed_traffic_detectors():
    assert {d.value for d in ANOMALY_DETECTORS} == ANOMALIES


@pytest.mark.parametrize("detector", sorted(ANOMALIES))
def test_anomaly_detectors(detector):
    assert category(AlertRuleType.LATERAL, detector) == "anomaly"


@pytest.mark.parametrize("detector", sorted({d.value for d in DetectorKind} - ANOMALIES))
def test_lateral_detectors(detector):
    assert category(AlertRuleType.LATERAL, detector) == "lateral"


def test_lateral_without_detector():
    assert category(AlertRuleType.LATERAL, None) == "lateral"


@pytest.mark.parametrize("rule_type", [AlertRuleType.TRAFFIC, AlertRuleType.BANDWIDTH, AlertRuleType.VOLUME])
def test_traffic_kinds(rule_type):
    assert category(rule_type, None) == "traffic"


def test_event_and_system():
    assert category(AlertRuleType.EVENT, None) == "event"
    assert category(AlertRuleType.SYSTEM, None) == "system"


def test_filter_shapes():
    assert category_filter("traffic") == (("traffic", "bandwidth", "volume"), None, None)
    types, inside, outside = category_filter("anomaly")
    assert types == ("lateral",) and set(inside or ()) == ANOMALIES and outside is None
    types, inside, outside = category_filter("lateral")
    assert types == ("lateral",) and inside is None and set(outside or ()) == ANOMALIES


def test_beyond_vendor_only_from_fields_present():
    assert beyond_vendor({"port": 445, "target": "db-01"}) == []
    facts = beyond_vendor({"group": "app=pay", "group_size": 12, "starters": 1, "process": "psexesvc.exe",
                           "port": 445, "proto": 6})
    assert [f.text_key for f in facts] == ["beyond_peer_never", "beyond_process"]
    assert facts[0].params == {"group": "app=pay", "group_size": "12", "starters": "1"}


def test_beyond_vendor_volume_and_account():
    facts = beyond_vendor({"mb": 2400, "previous_max_mb": 310, "user": "CORP\\svc", "source": "ws-1",
                           "known_sources": 2})
    assert [f.text_key for f in facts] == ["beyond_volume", "beyond_account_sources"]


def test_beyond_vendor_new_listener_only_when_true():
    assert beyond_vendor({"new_listener": False, "target": "x"}) == []
    assert [f.text_key for f in beyond_vendor({"new_listener": True, "target": "x"})] == ["beyond_new_listener"]


def test_beyond_vendor_precursors_listed():
    f = beyond_vendor({"precursors": [{"kind": "tamper", "at": "2026-11-02T14:41:00+00:00", "signal": True},
                                      {"kind": "offline", "at": "2026-11-02T14:45:00+00:00", "signal": None}]})
    assert [(x.text_key, x.params) for x in f] == [
        ("beyond_precursor_tamper", {"at": "2026-11-02T14:41:00+00:00"}),
        ("beyond_precursor_offline", {"at": "2026-11-02T14:45:00+00:00"})]
