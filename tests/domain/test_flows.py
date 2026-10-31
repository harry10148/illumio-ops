"""Flow normalization and the dual-report pairing rule, against anonymized LAB-PCE records."""
import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from illumio_ops.domain.flows import (
    FlowShapeError,
    normalize_flow,
    record_key,
    same_connection,
)
from illumio_ops.domain.values import FlowDirection

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "flows_sample.json"


@pytest.fixture(scope="module")
def raw():
    return json.loads(FIXTURE.read_text())


def test_normalize_flow_maps_lab_fields(raw):
    r = normalize_flow(raw[5])  # inbound mysqld, destination has labels and a deny-rule draft
    assert r.direction is FlowDirection.INBOUND
    assert (r.src_ip, r.dst_ip, r.port, r.proto) == ("10.0.0.7", "10.0.0.8", 3306, 6)
    assert r.own_process == "mysqld" and r.own_user == "user-02"
    assert r.dst_href and r.dst_href.startswith("/orgs/1/workloads/")
    assert ("app", "DemoApp") in r.dst_labels and r.dst_labels == tuple(sorted(r.dst_labels))
    assert r.policy_decision == "potentially_blocked"
    assert r.first_detected.tzinfo is not None and r.first_detected < r.last_detected
    assert r.num_connections >= 1


def test_unmanaged_source_without_workload(raw):
    r = normalize_flow(raw[12])  # ICMPv6 from a bare IP
    assert r.src_href is None and r.src_managed is False and r.src_labels == ()
    assert r.proto == 58


def test_missing_bytes_stay_none(raw):
    known = normalize_flow(raw[0])
    assert known.bytes_in == 104732056 and known.bytes_out == 0
    zero = normalize_flow(raw[1])  # outbound side of the same connection: PCE reports 0 / 0
    assert zero.bytes_in is None and zero.bytes_out is None
    absent = copy.deepcopy(raw[0])
    del absent["dst_bi"], absent["dst_bo"]
    assert normalize_flow(absent).bytes_in is None


@pytest.mark.parametrize("path", [("src", "ip"), ("dst", "ip"), ("timestamp_range",), ("flow_direction",),
                                  ("policy_decision",)])
def test_missing_required_field_raises_shape_error(raw, path):
    bad = copy.deepcopy(raw[0])
    node = bad
    for p in path[:-1]:
        node = node[p]
    del node[path[-1]]
    with pytest.raises(FlowShapeError):
        normalize_flow(bad)


def test_record_key_differs_by_direction(raw):
    a, b = normalize_flow(raw[0]), normalize_flow(raw[1])
    assert record_key(a) != record_key(b)
    assert record_key(a) == record_key(normalize_flow(copy.deepcopy(raw[0])))


def test_same_connection_overlap_and_600s_gap(raw):
    inbound, outbound = normalize_flow(raw[0]), normalize_flow(raw[1])
    assert same_connection(inbound, outbound) and same_connection(outbound, inbound)
    later = _shift(outbound, start=inbound.last_detected + timedelta(seconds=600))
    assert same_connection(inbound, later)


def test_pairing_rejects_ranges_more_than_600s_apart(raw):
    inbound, outbound = normalize_flow(raw[0]), normalize_flow(raw[1])
    later = _shift(outbound, start=inbound.last_detected + timedelta(seconds=601))
    assert not same_connection(inbound, later)


def test_same_connection_rejects_same_direction(raw):
    a = normalize_flow(raw[0])
    assert not same_connection(a, a)


def test_same_connection_rejects_other_tuple(raw):
    assert not same_connection(normalize_flow(raw[3]), normalize_flow(raw[4]))  # reversed endpoints


def _shift(r, *, start: datetime):
    from dataclasses import replace
    length = r.last_detected - r.first_detected
    return replace(r, first_detected=start.astimezone(UTC), last_detected=(start + length).astimezone(UTC))


def test_kubernetes_workload_named_by_its_name(raw):
    """Lab 2026-10-31: the PCE sends a Kubernetes Workload with hostname null and its name ("coredns"); the name is
    what the flow is shown by, not the href."""
    k8s = copy.deepcopy(raw[5])
    k8s["dst"]["workload"].update(href="/orgs/1/kubernetes_workloads/698dd122-7dbd", hostname=None, name="coredns")
    assert normalize_flow(k8s).dst_hostname == "coredns"
    named = copy.deepcopy(raw[5])
    named["dst"]["workload"].update(hostname="db01", name="DB 01")
    assert normalize_flow(named).dst_hostname == "db01"  # a hostname, when sent, stays what it is shown by
