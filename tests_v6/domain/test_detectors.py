"""Lateral-movement detectors (spec §6.5.1 正在發生): pure functions over observed connections."""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illumio_ops.domain.detectors import (
    DetectorConfig,
    DetectorInput,
    Obs,
    detect_fanout,
    detect_new_admin,
    run_detectors,
)
from illumio_ops.domain.lateral import HostInfo, effective_admin_ports
from illumio_ops.domain.values import (
    LATERAL_PORTS_DEFAULT,
    DetectorKind,
    DetectorState,
    Severity,
)

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "lateral_obs.json"
PORTS = effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(), removed=(), include_pce=False)
CFG = DetectorConfig(
    fanout_targets=10, fanout_window=timedelta(minutes=60), account_fanout_targets=10,
    account_fanout_window=timedelta(minutes=60), chain_window=timedelta(minutes=30), blocked_targets=5,
    blocked_window=timedelta(minutes=60), blocked_surge_factor=3.0, exclude_system_accounts=True,
    precursor_window=timedelta(hours=24), expected={}, admin_ports=PORTS, environment_label_key="env",
    admin_groups_configured=False)
CRITICAL = {"/w/fin"}


def host(key, ip="", hostname=None, labels=None):
    return HostInfo(key=key, href=None if key.startswith("ip:") else key, hostname=hostname or key, managed=True,
                    labels=labels or {}, enforcement_mode=None, visibility_level=None, os_id=None, ven_href=None,
                    critical=key in CRITICAL, admin_group=False)


def obs(src, dst, *, minutes_ago=5, port=445, decision="potentially_blocked", origin="ingest", user=None, proc=None):
    last = NOW - timedelta(minutes=minutes_ago)
    return Obs(src_key=src, dst_key=dst, src_href=src, dst_href=dst, src_ip="10.0.0.1", dst_ip="10.0.0.2",
               src_hostname=src, dst_hostname=dst, port=port, proto=6, decision=decision, first=last - timedelta(minutes=1),
               last=last, num_connections=1, initiator_user=user, initiator_process=proc, src_labels={}, dst_labels={},
               src_managed=True, origin=origin)


def inp(observations, *, window=(NOW - timedelta(minutes=40), NOW), first_seen=None, baseline_days=30.0,
        backfilling=False, cfg=CFG):
    return DetectorInput(window=window, obs=observations, blocked_obs=[], hosts=lambda k, ip, name, labels: host(k),
                         baseline_first_seen=first_seen or {}, precursors=[], config=cfg, baseline_days=baseline_days,
                         baseline_required=30, baseline_full=baseline_days >= 30 and not backfilling, gaps=())


def fan(src, n, **kw):
    return [obs(src, f"/w/t{i:02d}", **kw) for i in range(n)]


def test_fanout_fires_at_threshold_within_window():
    assert detect_fanout(inp(fan("/w/a", 9))) == ([], detect_fanout(inp(fan("/w/a", 9)))[1])
    dets, status = detect_fanout(inp(fan("/w/a", 10)))
    [d] = dets
    assert (d.detector, d.fingerprint, d.subject_key) == (DetectorKind.FANOUT, "fanout|/w/a", "/w/a")
    assert d.summary["targets"] == 10 and len(d.summary["sample_targets"]) == 10 and d.summary["ports"] == [445]
    assert status.state is DetectorState.OK
    assert d.segment.filter.src.hrefs == ("/w/a",) and d.segment.view.value == "detail"


def test_fanout_ignores_targets_outside_window():
    early = [obs("/w/a", f"/w/old{i}", minutes_ago=120) for i in range(5)]
    assert detect_fanout(inp(fan("/w/a", 6) + early))[0] == []


def test_fanout_blocked_targets_not_counted():
    assert detect_fanout(inp(fan("/w/a", 9) + [obs("/w/a", "/w/x", decision="blocked")]))[0] == []


def test_fanout_counts_unknown_decision():
    assert len(detect_fanout(inp(fan("/w/a", 9) + [obs("/w/a", "/w/x", decision="unknown")]))[0]) == 1


def test_fanout_severity_high_with_allowed_medium_otherwise():
    assert detect_fanout(inp(fan("/w/a", 10)))[0][0].severity is Severity.MEDIUM
    assert detect_fanout(inp(fan("/w/a", 9) + [obs("/w/a", "/w/x", decision="allowed")]))[0][0].severity is Severity.HIGH


def test_fanout_critical_target_raises_severity():
    d = detect_fanout(inp(fan("/w/a", 9) + [obs("/w/a", "/w/fin")]))[0][0]
    assert d.severity is Severity.HIGH and d.critical_asset is True


def test_new_admin_tuple_first_seen_in_window():
    o = obs("/w/a", "/w/b", minutes_ago=10, port=3389)
    known = obs("/w/a", "/w/c", minutes_ago=10, port=3389)
    seen = {("/w/a", "/w/b", 3389, 6): o.first, ("/w/a", "/w/c", 3389, 6): NOW - timedelta(days=12)}
    dets, status = detect_new_admin(inp([o, known], first_seen=seen))
    [d] = dets
    assert d.fingerprint == "new|/w/a|/w/b|3389|6" and d.severity is Severity.MEDIUM and status.state is DetectorState.OK
    to_fin = obs("/w/a", "/w/fin", minutes_ago=10, port=22)
    dets, _ = detect_new_admin(inp([to_fin], first_seen={("/w/a", "/w/fin", 22, 6): to_fin.first}))
    assert dets[0].severity is Severity.HIGH and dets[0].critical_asset


def test_new_admin_accumulating_before_baseline_full():
    o = obs("/w/a", "/w/b", minutes_ago=10)
    seen = {("/w/a", "/w/b", 445, 6): o.first}
    dets, status = detect_new_admin(inp([o], first_seen=seen, baseline_days=12.34))
    assert dets == [] and status.state is DetectorState.ACCUMULATING and status.params == {"days": 12.3, "required": 30}
    assert detect_new_admin(inp([o], first_seen=seen, backfilling=True))[1].state is DetectorState.ACCUMULATING


def test_backfill_origin_not_evaluated():
    assert detect_fanout(inp(fan("/w/a", 10, origin="backfill")))[0] == []
    o = obs("/w/a", "/w/b", origin="backfill")
    assert detect_new_admin(inp([o], first_seen={("/w/a", "/w/b", 445, 6): o.first}))[0] == []


def test_run_detectors_reports_every_detector():
    dets, statuses = run_detectors(inp(fan("/w/a", 10)))
    assert {s.detector for s in statuses} == set(DetectorKind)
    assert [d.detector for d in dets] == [DetectorKind.FANOUT]


def _fixture_obs():
    rows = json.loads(FIXTURE.read_text())
    out = []
    for r in rows:
        r = dict(r, first=datetime.fromisoformat(r["first"]), last=datetime.fromisoformat(r["last"]), origin="ingest")
        out.append(Obs(**r))
    return out


def test_lab_fixture_fanout_is_rare():
    # 34 days of lab management-port traffic, evaluated every 10 minutes as the pipeline does.
    all_obs = _fixture_obs()
    start, end = min(o.last for o in all_obs), max(o.last for o in all_obs)
    found = []
    t = start
    while t < end:
        window = (t, t + timedelta(minutes=10))
        near = [o for o in all_obs if window[0] - timedelta(minutes=60) <= o.last <= window[1]]
        found += detect_fanout(inp(near, window=window))[0]
        t = window[1]
    subjects = {d.subject_key for d in found}
    assert len(found) <= 5 and len(subjects) == 1

