"""Anomalies in allowed traffic (spec §6.5.8): pure detectors over the run's connections and the baselines the
service looked up for them."""
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from illumio_ops.domain.anomaly import (
    detect_peer_deviation,
    detect_volume_surge,
    group_of,
    target_signature,
)
from illumio_ops.domain.detectors import DETECTORS, Activity, AnomalyData, dedup_windows
from illumio_ops.domain.focus import DETECTION_TITLE_KEYS
from illumio_ops.domain.values import DetectorKind, DetectorState, Severity
from tests_v6.domain.test_detectors import CFG, NOW, host, inp, obs

I18N = Path(__file__).resolve().parents[2] / "illumio_ops" / "i18n"
LO = NOW - timedelta(minutes=40)
PAY_WEB = {"app": "Pay", "role": "Web"}
HR_APP = {"app": "HR", "role": "App"}


def traffic(src, dst, *, port=8443, src_labels=PAY_WEB, dst_labels=HR_APP, **kw):
    return obs(src, dst, port=port, src_labels=src_labels, dst_labels=dst_labels, **kw)


def run(rows, *, data=None, first_seen=None, baseline_days=30.0, cfg=CFG, detector=detect_peer_deviation, **kw):
    i = replace(inp([], first_seen=first_seen, baseline_days=baseline_days, cfg=cfg, **kw), traffic_obs=rows,
                anomaly=data or AnomalyData())
    return detector(i)


def new(rows):
    """Every row's tuple first seen in this run's window."""
    return {(o.src_key, o.dst_key, o.port, o.proto): NOW - timedelta(minutes=10) for o in rows}


GROUPS = {"Pay|Web": 6}


# ── A peer-group deviation ───────────────────────────────────────────────────

def test_group_and_signature():
    assert group_of({"app": "Pay", "role": "Web", "env": "Prod"}, ("app", "role")) == "Pay|Web"
    assert group_of({"app": "Pay"}, ("app", "role")) is None
    managed = host("/w/hr", labels=HR_APP)
    assert target_signature("/w/hr", "10.0.0.2", managed, ("app", "role")) == "g:HR|App"
    assert target_signature("/w/x", "10.0.0.2", host("/w/x"), ("app", "role")) == "/w/x"
    assert target_signature("ip:10.1.1.1", "10.1.1.1", host("ip:10.1.1.1"), ("app", "role")) == "ip:10.1.1.1"
    assert target_signature("ip:8.8.8.8", "8.8.8.8", host("ip:8.8.8.8"), ("app", "role")) is None


def test_peer_deviation_fires_for_a_lone_starter():
    rows = [traffic("/w/p1", "/w/hr")]
    [d], status = run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.PEER_DEVIATION and d.subject_key == "/w/p1"
    assert d.fingerprint == "peer|/w/p1|g:HR|App|8443|6" and d.severity is Severity.MEDIUM
    assert d.summary["group_size"] == 6 and d.summary["starters"] == 1 and d.summary["target_group"] == "HR / App"
    assert d.summary["group"] == "Pay / Web" and d.summary["port"] == 8443
    assert [p.port for p in d.segment.filter.ports] == [8443]


def test_peer_deviation_critical_target_is_high():
    rows = [traffic("/w/p1", "/w/fin")]
    [d], _ = run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))
    assert d.severity is Severity.HIGH and d.critical_asset


def test_peer_seen_suppresses():
    rows = [traffic("/w/p1", "/w/hr")]
    data = AnomalyData(group_sizes=GROUPS, peer_seen={("Pay|Web", 8443, 6): frozenset({"g:HR|App"})})
    assert run(rows, first_seen=new(rows), data=data)[0] == []


def test_tuple_not_new_is_not_a_candidate():
    rows = [traffic("/w/p1", "/w/hr")]
    old = {k: NOW - timedelta(days=3) for k in new(rows)}
    assert run(rows, first_seen=old, data=AnomalyData(group_sizes=GROUPS))[0] == []


def test_whole_group_rollout_is_not_a_deviation():
    rows = [traffic(f"/w/p{i}", "/w/hr") for i in range(3)]
    assert run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))[0] == []
    two = rows[:2]
    assert len(run(two, first_seen=new(two), data=AnomalyData(group_sizes=GROUPS))[0]) == 2


def test_group_below_minimum_is_not_evaluated():
    rows = [traffic("/w/p1", "/w/hr")]
    dets, status = run(rows, first_seen=new(rows), data=AnomalyData(group_sizes={"Pay|Web": 4}))
    assert dets == [] and status.state is DetectorState.NO_DATA and status.reason_key == "detector_no_peer_groups"
    assert status.params == {"keys": "app, role", "min": 5}


def test_group_at_minimum_is_evaluated():
    rows = [traffic("/w/p1", "/w/hr")]
    assert len(run(rows, first_seen=new(rows), data=AnomalyData(group_sizes={"Pay|Web": 5}))[0]) == 1


def test_host_missing_a_group_label_is_skipped():
    rows = [traffic("/w/p1", "/w/hr", src_labels={"app": "Pay"})]
    assert run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))[0] == []


def test_management_and_dynamic_ports_skipped():
    rows = [traffic("/w/p1", "/w/hr", port=p) for p in (445, 389, 1433, 50000)]
    assert run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))[0] == []


def test_public_destination_skipped():
    rows = [replace(traffic("/w/p1", "ip:8.8.8.8", dst_labels={}), dst_ip="8.8.8.8", dst_href=None)]
    assert run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))[0] == []


def test_blocked_and_backfill_not_evaluated():
    rows = [traffic("/w/p1", "/w/hr", decision="blocked"), traffic("/w/p2", "/w/hr2", origin="backfill")]
    assert run(rows, first_seen=new(rows), data=AnomalyData(group_sizes=GROUPS))[0] == []


def test_peer_accumulating_until_baseline_full():
    rows = [traffic("/w/p1", "/w/hr")]
    dets, status = run(rows, first_seen=new(rows), baseline_days=12.0, data=AnomalyData(group_sizes=GROUPS))
    assert dets == [] and status.state is DetectorState.ACCUMULATING


# ── B volume surge ───────────────────────────────────────────────────────────

def surge(activity, *, days=8.0, live=True, **kw):
    return run([], data=AnomalyData(activity=activity, activity_days=days, live=live), detector=detect_volume_surge,
               **kw)


def test_volume_surge_on_connections():
    [d], status = surge({("/w/a", "all"): Activity(1200, None, 300, 0)})
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.VOLUME_SURGE and d.fingerprint == "volume|/w/a"
    assert d.summary == {"connections": 1200, "bytes": None, "previous_max": 300, "previous_max_bytes": 0,
                         "window_minutes": 60}
    assert d.last_seen == NOW and d.first_seen == NOW - timedelta(minutes=60)


def test_volume_below_factor_or_floor():
    assert surge({("/w/a", "all"): Activity(800, None, 300, 0)})[0] == []      # under 3 x 300
    assert surge({("/w/a", "all"): Activity(900, None, 0, 0)})[0] == []        # under the 1,000 floor
    assert len(surge({("/w/a", "all"): Activity(1000, None, 0, 0)})[0]) == 1   # no history: the floor alone


def test_volume_surge_on_bytes_only():
    gib = 2**30
    [d], _ = surge({("/w/a", "all"): Activity(50, 4 * gib, 40, gib)})
    assert d.summary["bytes"] == 4 * gib


def test_volume_ignores_directory_class():
    assert surge({("/w/a", "directory"): Activity(5000, None, 0, 0)})[0] == []


def test_volume_accumulating_before_seven_days():
    dets, status = surge({("/w/a", "all"): Activity(5000, None, 0, 0)}, days=3.25)
    assert dets == [] and status.state is DetectorState.ACCUMULATING
    assert status.reason_key == "detector_activity_accumulating" and status.params == {"days": 3.2, "required": 7}


def test_volume_not_evaluated_in_late_pass():
    dets, status = surge({("/w/a", "all"): Activity(5000, None, 0, 0)}, live=False)
    assert dets == [] and status.state is DetectorState.OK and status.reason_key == "detector_live_only"


def test_volume_critical_source_is_high():
    [d], _ = surge({("/w/fin", "all"): Activity(5000, None, 0, 0)})
    assert d.severity is Severity.HIGH


# ── registration ─────────────────────────────────────────────────────────────

def test_every_detector_kind_is_registered():
    assert set(DETECTORS) == set(DetectorKind)
    assert set(dedup_windows(CFG)) == set(DetectorKind)
    assert set(DETECTION_TITLE_KEYS) == set(DetectorKind)
    for lang in ("en", "zh_TW"):
        d = json.loads((I18N / f"{lang}.json").read_text())
        missing = [k for kind in DetectorKind for k in (f"detector_name_{kind.value}", DETECTION_TITLE_KEYS[kind])
                   if k not in d]
        assert missing == [], (lang, missing)

