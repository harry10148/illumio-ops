"""Anomalies in allowed traffic, second batch (spec §6.5.8 第二批): F reversed direction, G a new port on a known
pair, H a quiet host waking, I data staging, J off-hours activity."""
import json
from dataclasses import replace
from datetime import timedelta

from illumio_ops.domain.anomaly import (
    detect_data_staging,
    detect_direction_reversal,
    detect_new_pair_port,
    detect_off_hours,
    detect_quiet_host_wakes,
    drop_covered,
)
from illumio_ops.domain.detectors import Activity, AnomalyData, FanInFact
from illumio_ops.domain.values import DetectorKind, DetectorState, Severity
from tests.domain.test_anomaly import GROUPS, I18N, _det, new, run, traffic
from tests.domain.test_detectors import NOW, obs

HOUR = NOW.replace(minute=0, second=0, microsecond=0)
GIB, MIB = 2**30, 2**20


def _public_dst(o):
    return replace(o, dst_key="ip:8.8.8.8", dst_href=None, dst_ip="8.8.8.8", dst_hostname=None)


# ── F reversed direction ─────────────────────────────────────────────────────

def test_reversal_fires_when_the_usual_direction_existed_and_this_one_never_did():
    rows = [obs("/w/db", "/w/app", port=8080)]
    [d], status = run(rows, first_seen=new(rows), data=AnomalyData(pairs_before=frozenset({("/w/app", "/w/db")})),
                      detector=detect_direction_reversal)
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.DIRECTION_REVERSAL and d.fingerprint == "reverse|/w/db|/w/app"
    assert d.subject_key == "/w/db" and d.severity is Severity.MEDIUM
    assert d.summary["target"] == "/w/app" and d.summary["port"] == 8080
    assert ("t", "/w/app", "10.0.0.2") in d.ends and ("s", "/w/db", "10.0.0.1") in d.ends
    assert [p.port for p in d.segment.filter.ports] == [8080]


def test_reversal_not_when_the_reverse_pair_existed_before():
    # blocked attempts are in the baseline too: a reverse once tried is not new
    rows = [obs("/w/db", "/w/app", port=8080)]
    data = AnomalyData(pairs_before=frozenset({("/w/app", "/w/db"), ("/w/db", "/w/app")}))
    assert run(rows, first_seen=new(rows), data=data, detector=detect_direction_reversal)[0] == []


def test_reversal_needs_the_usual_direction():
    rows = [obs("/w/db", "/w/app", port=8080)]
    assert run(rows, first_seen=new(rows), data=AnomalyData(), detector=detect_direction_reversal)[0] == []


def test_reversal_skips_admin_dynamic_public_and_old_tuples():
    data = AnomalyData(pairs_before=frozenset({("/w/app", "/w/db"), ("ip:8.8.8.8", "/w/db")}))
    for rows in ([obs("/w/db", "/w/app", port=22)], [obs("/w/db", "/w/app", port=50000)],
                 [_public_dst(obs("/w/db", "/w/app", port=8080))]):
        assert run(rows, first_seen=new(rows), data=data, detector=detect_direction_reversal)[0] == []
    rows = [obs("/w/db", "/w/app", port=8080)]
    old = {k: NOW - timedelta(days=3) for k in new(rows)}
    assert run(rows, first_seen=old, data=data, detector=detect_direction_reversal)[0] == []


def test_reversal_accumulates_without_a_full_baseline():
    rows = [obs("/w/db", "/w/app", port=8080)]
    dets, status = run(rows, first_seen=new(rows), baseline_days=3.0,
                       data=AnomalyData(pairs_before=frozenset({("/w/app", "/w/db")})),
                       detector=detect_direction_reversal)
    assert dets == [] and status.state is DetectorState.ACCUMULATING


def test_reversal_to_a_critical_host_is_raised():
    rows = [obs("/w/db", "/w/fin", port=8080)]
    [d], _ = run(rows, first_seen=new(rows), data=AnomalyData(pairs_before=frozenset({("/w/fin", "/w/db")})),
                 detector=detect_direction_reversal)
    assert d.severity is Severity.HIGH and d.critical_asset


# ── G a new port on a known pair ─────────────────────────────────────────────

PAIR = frozenset({("/w/a", "/w/b")})


def test_new_port_to_a_new_listener_is_medium():
    rows = [obs("/w/a", "/w/b", port=4444)]
    [d], status = run(rows, first_seen=new(rows), data=AnomalyData(pairs_before=PAIR), detector=detect_new_pair_port)
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.NEW_PAIR_PORT and d.fingerprint == "pairport|/w/a|/w/b|4444|6"
    assert d.severity is Severity.MEDIUM and d.summary["new_listener"] is True and d.summary["port"] == 4444


def test_new_port_the_target_already_serves_is_low():
    rows = [obs("/w/a", "/w/b", port=8443)]
    data = AnomalyData(pairs_before=PAIR, ports_served=frozenset({("/w/b", 8443, 6)}))
    [d], _ = run(rows, first_seen=new(rows), data=data, detector=detect_new_pair_port)
    assert d.severity is Severity.LOW and d.summary["new_listener"] is False


def test_new_port_needs_a_known_pair():
    rows = [obs("/w/a", "/w/b", port=4444)]
    assert run(rows, first_seen=new(rows), data=AnomalyData(), detector=detect_new_pair_port)[0] == []


def test_new_port_peers_already_use_is_not_flagged():
    rows = [traffic("/w/p1", "/w/hr", port=8443)]
    data = AnomalyData(pairs_before=frozenset({("/w/p1", "/w/hr")}), group_sizes=GROUPS,
                       peer_seen={("Pay|Web", 8443, 6): frozenset({"g:HR|App"})})
    assert run(rows, first_seen=new(rows), data=data, detector=detect_new_pair_port)[0] == []


def test_new_port_skips_admin_dynamic_public():
    data = AnomalyData(pairs_before=frozenset({("/w/a", "/w/b"), ("/w/a", "ip:8.8.8.8")}))
    for rows in ([obs("/w/a", "/w/b", port=3389)], [obs("/w/a", "/w/b", port=60000)],
                 [_public_dst(obs("/w/a", "/w/b", port=4444))]):
        assert run(rows, first_seen=new(rows), data=data, detector=detect_new_pair_port)[0] == []


def test_new_port_to_a_critical_host_is_raised():
    rows = [obs("/w/a", "/w/fin", port=4444)]
    [d], _ = run(rows, first_seen=new(rows), data=AnomalyData(pairs_before=frozenset({("/w/a", "/w/fin")})),
                 detector=detect_new_pair_port)
    assert d.severity is Severity.HIGH


# ── H a quiet host waking ────────────────────────────────────────────────────

def quiet(recent, hours, *, known=("/w/a",), days=15.0, gaps=(), live=True):
    return AnomalyData(recent=recent, active_hours=hours, known_before_quiet=frozenset(known), activity_days=days,
                       hours_gaps=gaps, live=live)


def test_quiet_host_waking_fires():
    data = quiet({"/w/a": 150}, {"/w/a": [HOUR - timedelta(days=9)]})
    [d], status = run([obs("/w/a", "/w/b")], data=data, detector=detect_quiet_host_wakes)
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.QUIET_HOST_WAKES and d.fingerprint == "quiet|/w/a"
    assert d.severity is Severity.MEDIUM and d.summary["connections"] == 150 and d.summary["quiet_days"] == 7
    assert d.summary["last_active"] == (HOUR - timedelta(days=9)).isoformat()
    assert d.ends == (("s", "/w/a", "10.0.0.1"),)


def test_quiet_host_active_inside_the_quiet_period_is_not_flagged():
    data = quiet({"/w/a": 150}, {"/w/a": [HOUR - timedelta(days=9), HOUR - timedelta(days=2)]})
    assert run([], data=data, detector=detect_quiet_host_wakes)[0] == []


def test_quiet_needs_a_host_known_before_the_quiet_period():
    data = quiet({"/w/a": 150}, {}, known=())
    assert run([], data=data, detector=detect_quiet_host_wakes)[0] == []


def test_quiet_below_floor_or_unmanaged_is_not_flagged():
    assert run([], data=quiet({"/w/a": 99}, {}), detector=detect_quiet_host_wakes)[0] == []
    data = quiet({"ip:10.0.0.9": 500}, {}, known=("ip:10.0.0.9",))
    assert run([], data=data, detector=detect_quiet_host_wakes)[0] == []


def test_quiet_with_a_gap_in_the_quiet_period_is_incomplete_and_silent():
    # the collection stopped for days: every host would look quiet
    gap = (HOUR - timedelta(days=3), HOUR - timedelta(days=2), "ingest_failed")
    dets, status = run([], data=quiet({"/w/a": 500}, {}, gaps=(gap,)), detector=detect_quiet_host_wakes)
    assert dets == [] and status.state is DetectorState.INCOMPLETE


def test_quiet_accumulates_until_the_activity_covers_the_quiet_period():
    dets, status = run([], data=quiet({"/w/a": 500}, {}, days=6.0), detector=detect_quiet_host_wakes)
    assert dets == [] and status.state is DetectorState.ACCUMULATING and status.params["required"] == 7


def test_quiet_is_live_only():
    dets, status = run([], data=quiet({"/w/a": 500}, {}, live=False), detector=detect_quiet_host_wakes)
    assert dets == [] and status.reason_key == "detector_live_only"


# ── J off-hours ──────────────────────────────────────────────────────────────

def night_shift(days=6):
    """Active 01:00–09:00 on each of the last `days` days; NOW is 12:00."""
    return [HOUR.replace(hour=h) - timedelta(days=d) for d in range(1, days + 1) for h in range(1, 10)]


def off(recent, hours, *, days=15.0, gaps=(), live=True):
    return AnomalyData(recent=recent, active_hours=hours, activity_days=days, hours_gaps=gaps, live=live)


def test_off_hours_fires_low():
    [d], status = run([obs("/w/a", "/w/b")], data=off({"/w/a": 120}, {"/w/a": night_shift()}),
                      detector=detect_off_hours)
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.OFF_HOURS and d.fingerprint == "offhours|/w/a|12"
    assert d.severity is Severity.LOW and d.summary["active_days"] == 6 and d.summary["usual_hours"] == "01–09"


def test_off_hours_not_when_the_slot_was_used():
    hours = night_shift() + [HOUR.replace(hour=11) - timedelta(days=4)]
    assert run([], data=off({"/w/a": 120}, {"/w/a": hours}), detector=detect_off_hours)[0] == []


def test_off_hours_needs_a_routine():
    assert run([], data=off({"/w/a": 120}, {"/w/a": night_shift(days=4)}), detector=detect_off_hours)[0] == []


def test_off_hours_slot_with_a_gap_is_incomplete_and_silent():
    gap = (HOUR.replace(hour=11) - timedelta(days=2), HOUR.replace(hour=12) - timedelta(days=2), "truncated")
    dets, status = run([], data=off({"/w/a": 120}, {"/w/a": night_shift()}, gaps=(gap,)), detector=detect_off_hours)
    assert dets == [] and status.state is DetectorState.INCOMPLETE


def test_off_hours_gap_elsewhere_does_not_matter():
    gap = (HOUR.replace(hour=3) - timedelta(days=2), HOUR.replace(hour=4) - timedelta(days=2), "truncated")
    assert len(run([], data=off({"/w/a": 120}, {"/w/a": night_shift()}, gaps=(gap,)), detector=detect_off_hours)[0]) == 1


def test_off_hours_accumulates_for_seven_days():
    dets, status = run([], data=off({"/w/a": 120}, {"/w/a": night_shift()}, days=6.5), detector=detect_off_hours)
    assert dets == [] and status.state is DetectorState.ACCUMULATING


# ── I data staging ───────────────────────────────────────────────────────────

SOURCES = tuple(f"/w/s{i}" for i in range(6))


def staging(fan, *, coverage=(6, 6), days=8.0, gaps=(), live=True):
    return AnomalyData(fan_in=fan, fan_in_coverage=coverage, destination_days=days, fan_in_gaps=gaps, live=live)


def fact(*, bytes_=2 * GIB, sources=SOURCES, previous=300 * MIB):
    return FanInFact(connections=60, bytes=bytes_, sources=sources, previous_bytes=previous)


def test_staging_fires_on_many_sources_far_above_history():
    [d], status = run([], data=staging({"/w/sink": fact()}), detector=detect_data_staging)
    assert status.state is DetectorState.OK
    assert d.detector is DetectorKind.DATA_STAGING and d.fingerprint == "staging|/w/sink" and d.subject_key == "/w/sink"
    assert d.severity is Severity.MEDIUM and d.summary["sources"] == 6 and d.summary["mb"] == 2048
    assert d.summary["previous_max_mb"] == 300 and d.confidence.field == "bytes"
    assert sorted(k for r, k, _ in d.ends if r == "s") == list(SOURCES) and ("t", "/w/sink", "") in d.ends


def test_staging_not_within_its_own_history():
    assert run([], data=staging({"/w/sink": fact(previous=GIB)}), detector=detect_data_staging)[0] == []


def test_staging_needs_enough_internal_sources_and_bytes():
    assert run([], data=staging({"/w/sink": fact(sources=SOURCES[:4])}), detector=detect_data_staging)[0] == []
    public = SOURCES[:4] + ("ip:8.8.8.8", "ip:1.1.1.1")
    assert run([], data=staging({"/w/sink": fact(sources=public)}), detector=detect_data_staging)[0] == []
    assert run([], data=staging({"/w/sink": fact(bytes_=900 * MIB, previous=None)}),
               detector=detect_data_staging)[0] == []


def test_staging_without_history_takes_the_floor_alone():
    assert len(run([], data=staging({"/w/sink": fact(previous=None)}), detector=detect_data_staging)[0]) == 1


def test_staging_to_a_public_address_is_not_staging():
    assert run([], data=staging({"ip:8.8.8.8": fact()}), detector=detect_data_staging)[0] == []


def test_staging_says_when_no_growth_carried_bytes():
    dets, status = run([], data=staging({}, coverage=(0, 40)), detector=detect_data_staging)
    assert dets == [] and status.state is DetectorState.NO_DATA and status.reason_key == "detector_no_byte_data"


def test_staging_states_partial_byte_coverage():
    _, status = run([], data=staging({"/w/sink": fact()}, coverage=(6, 40)), detector=detect_data_staging)
    assert status.reason_key == "detector_partial_bytes" and status.params == {"covered": 6, "total": 40}


def test_staging_history_gap_is_incomplete_but_still_detects():
    gap = (NOW - timedelta(days=3, hours=1), NOW - timedelta(days=3), "truncated")
    [d], status = run([], data=staging({"/w/sink": fact()}, gaps=(gap,)), detector=detect_data_staging)
    assert status.state is DetectorState.INCOMPLETE and gap in d.confidence.incomplete_gaps


def test_staging_accumulates_for_seven_days_of_destination_history():
    dets, status = run([], data=staging({"/w/sink": fact()}, days=5.0), detector=detect_data_staging)
    assert dets == [] and status.state is DetectorState.ACCUMULATING


# ── one thing, one detection ─────────────────────────────────────────────────

def test_drop_covered_keeps_the_broader_detection():
    surge, wake, offh = (_det(k, "/w/a", 0, 10) for k in (DetectorKind.VOLUME_SURGE, DetectorKind.QUIET_HOST_WAKES,
                                                         DetectorKind.OFF_HOURS))
    assert [d.detector for d in drop_covered([surge, wake, offh])] == [DetectorKind.VOLUME_SURGE]
    assert [d.detector for d in drop_covered([wake, offh])] == [DetectorKind.QUIET_HOST_WAKES]
    other = replace(_det(DetectorKind.QUIET_HOST_WAKES, "/w/b", 0, 10), fingerprint="quiet|/w/b")
    assert len(drop_covered([surge, other])) == 2


def test_drop_covered_peer_deviation_covers_the_same_connection():
    peer = replace(_det(DetectorKind.PEER_DEVIATION, "/w/a", 0, 10), summary={"port": 8443},
                   ends=(("s", "/w/a", ""), ("t", "/w/b", "")))
    same = replace(_det(DetectorKind.NEW_PAIR_PORT, "/w/a", 0, 10), summary={"port": 8443},
                   ends=(("s", "/w/a", ""), ("t", "/w/b", "")))
    other = replace(same, summary={"port": 9000})
    assert [d.summary["port"] for d in drop_covered([peer, same, other]) if d.detector is DetectorKind.NEW_PAIR_PORT] \
        == [9000]


def test_surge_kinds_unchanged_by_activity_shape():
    # B keeps its own reading of the activity: the second batch adds fields, it does not move B's
    data = AnomalyData(activity={("/w/a", "all"): Activity(1200, None, 300, 0)}, activity_days=8.0)
    assert data.recent == {} and data.fan_in == {}


def test_batch2_titles_carry_their_summary():
    for lang in ("en", "zh_TW"):
        d = json.loads((I18N / f"{lang}.json").read_text())
        assert "{quiet_days}" in d["focus_title_quiet_host_wakes"] and "{sources}" in d["focus_title_data_staging"]
        assert "{usual_hours}" in d["focus_title_off_hours"] and "{port}" in d["focus_title_new_pair_port"]
        assert "{target}" in d["focus_title_direction_reversal"]


def test_off_hours_ignores_gaps_before_the_activity_began():
    """Scale run: the kept 14 days reach before an install's first live hour; a gap there is not missing activity."""
    gap = (HOUR.replace(hour=11) - timedelta(days=12), HOUR.replace(hour=12) - timedelta(days=12), "not_yet_collected")
    [_d], status = run([], data=off({"/w/a": 120}, {"/w/a": night_shift()}, days=8.0, gaps=(gap,)),
                      detector=detect_off_hours)
    assert status.state is DetectorState.OK
