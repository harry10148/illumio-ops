"""Anomalies in allowed traffic (spec §6.5.8): pure detectors over the run's connections and the baselines the
service looked up for them."""
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from illumio_ops.domain.anomaly import (
    apply_directory_followup,
    detect_account_new_source,
    detect_auth_to_non_dc,
    detect_directory_surge,
    detect_new_dc_client,
    detect_new_process,
    detect_peer_deviation,
    detect_suspicious_tool,
    detect_volume_surge,
    group_of,
    target_signature,
)
from illumio_ops.domain.detectors import (
    DETECTORS,
    Activity,
    AnomalyData,
    Detection,
    DetectionConfidence,
    Precursor,
    dedup_windows,
    run_detectors,
)
from illumio_ops.domain.filter import FilterSpec
from illumio_ops.domain.focus import DETECTION_TITLE_KEYS
from illumio_ops.domain.segment import FlowSegment
from illumio_ops.domain.values import (
    DetectorKind,
    DetectorState,
    PrecursorKind,
    SegmentView,
    Severity,
)
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


# ── C an account from a new source ────────────────────────────────────────────

ALICE = "corp\\alice"
OLD = NOW - timedelta(days=10)
NEW_FIRST = NOW - timedelta(minutes=10)


def acct_data(src="/w/b", *, since=OLD, first=NEW_FIRST, sources=1, account=ALICE):
    return AnomalyData(account_first={(account, src): first}, account_since={account: since},
                       account_sources={account: sources})


def test_account_from_new_source():
    rows = [obs("/w/b", "/w/t1", port=8080, user="CORP\\Alice")]
    [d], status = run(rows, data=acct_data(), detector=detect_account_new_source)
    assert d.detector is DetectorKind.ACCOUNT_NEW_SOURCE and d.subject_key == ALICE
    assert d.fingerprint == f"acctsrc|{ALICE}|/w/b" and d.severity is Severity.MEDIUM
    assert d.summary["user"] == "CORP\\Alice" and d.summary["source"] == "/w/b" and d.summary["known_sources"] == 1
    assert d.segment.filter.initiator_user == "CORP\\Alice"
    assert d.confidence.field == "initiator_user" and (d.confidence.covered, d.confidence.total) == (1, 1)
    assert status.state is DetectorState.OK


def test_account_case_variants_match():
    rows = [obs("/w/b", "/w/t1", port=8080, user="corp\\ALICE")]
    assert len(run(rows, data=acct_data(), detector=detect_account_new_source)[0]) == 1


def test_new_account_is_not_judged():
    rows = [obs("/w/b", "/w/t1", port=8080, user="CORP\\Alice")]
    assert run(rows, data=acct_data(since=NOW - timedelta(days=3)), detector=detect_account_new_source)[0] == []


def test_known_source_is_not_new():
    rows = [obs("/w/b", "/w/t1", port=8080, user="CORP\\Alice")]
    assert run(rows, data=acct_data(first=OLD), detector=detect_account_new_source)[0] == []


def test_system_account_skipped():
    rows = [obs("/w/b", "/w/t1", port=8080, user="NT AUTHORITY\\SYSTEM")]
    data = acct_data(account="nt authority\\system")
    assert run(rows, data=data, detector=detect_account_new_source)[0] == []


def test_account_accumulating_and_no_user_data():
    rows = [obs("/w/b", "/w/t1", port=8080, user="CORP\\Alice")]
    _, status = run(rows, data=acct_data(), baseline_days=10.0, detector=detect_account_new_source)
    assert status.state is DetectorState.ACCUMULATING
    dets, status = run([obs("/w/b", "/w/t1", port=8080)], data=acct_data(), detector=detect_account_new_source)
    assert dets == [] and status.state is DetectorState.NO_DATA and status.reason_key == "detector_no_user_data"


def test_account_detection_skips_precursor_raise():
    rows = [obs("/w/b", "/w/t1", port=8080, user="CORP\\Alice")]
    i = replace(inp([], precursors=[Precursor(ALICE, PrecursorKind.TAMPER, NOW - timedelta(minutes=30), True)]),
                traffic_obs=rows, anomaly=acct_data())
    dets, _ = run_detectors(i)
    [d] = [d for d in dets if d.detector is DetectorKind.ACCOUNT_NEW_SOURCE]
    assert d.severity is Severity.MEDIUM and "precursors" not in d.summary


# ── D suspicious tools and new processes ─────────────────────────────────────

TOOLS = replace(CFG, suspicious_tools=frozenset({"psexec.exe", "powershell.exe", "nc"}))


def test_tool_to_internal_target():
    rows = [obs("/w/a", "/w/t1", port=8080, proc="psexec.exe"), obs("/w/a", "/w/t2", port=8080, proc="psexec.exe")]
    [d], status = run(rows, cfg=TOOLS, detector=detect_suspicious_tool)
    assert d.detector is DetectorKind.SUSPICIOUS_TOOL and d.fingerprint == "tool|/w/a|psexec.exe"
    assert d.summary["targets"] == 2 and d.summary["process"] == "psexec.exe" and d.severity is Severity.MEDIUM
    assert d.segment.filter.initiator_process == "psexec.exe"
    assert status.state is DetectorState.OK


def test_tool_to_public_target_skipped():
    rows = [replace(obs("/w/a", "ip:8.8.8.8", port=443, proc="nc"), dst_ip="8.8.8.8", dst_href=None)]
    assert run(rows, cfg=TOOLS, detector=detect_suspicious_tool)[0] == []


def test_tool_on_port_with_expected_list_skipped():
    rows = [obs("/w/a", "/w/t1", port=445, proc="powershell.exe")]  # 445 has a list: unexpected_initiator judges it
    assert run(rows, cfg=TOOLS, detector=detect_suspicious_tool)[0] == []


def test_empty_tool_list_disabled():
    dets, status = run([obs("/w/a", "/w/t1", port=8080, proc="psexec.exe")], detector=detect_suspicious_tool)
    assert dets == [] and status.state is DetectorState.DISABLED and status.reason_key == "detector_no_tools"


def test_no_process_data_status():
    dets, status = run([obs("/w/a", "/w/t1", port=8080)], cfg=TOOLS, detector=detect_suspicious_tool)
    assert dets == [] and status.state is DetectorState.NO_DATA and status.reason_key == "detector_no_process_field"


def proc_data(src="/w/a", process="curl", *, first=NEW_FIRST, since=OLD):
    return AnomalyData(process_first={(src, process): first}, process_since={src: since})


def test_first_process_on_established_host():
    rows = [obs("/w/a", "/w/t1", port=8080, proc="curl")]
    [d], _ = run(rows, cfg=TOOLS, data=proc_data(), detector=detect_new_process)
    assert d.detector is DetectorKind.NEW_PROCESS and d.fingerprint == "newproc|/w/a|curl"
    assert d.severity is Severity.LOW and d.summary["process"] == "curl"


def test_new_process_on_new_host_skipped():
    rows = [obs("/w/a", "/w/t1", port=8080, proc="curl")]
    assert run(rows, cfg=TOOLS, data=proc_data(since=NOW - timedelta(days=2)), detector=detect_new_process)[0] == []


def test_tool_is_not_also_new_process():
    rows = [obs("/w/a", "/w/t1", port=8080, proc="psexec.exe")]
    assert run(rows, cfg=TOOLS, data=proc_data(process="psexec.exe"), detector=detect_new_process)[0] == []


def test_new_process_accumulating():
    rows = [obs("/w/a", "/w/t1", port=8080, proc="curl")]
    _, status = run(rows, cfg=TOOLS, data=proc_data(), baseline_days=3.0, detector=detect_new_process)
    assert status.state is DetectorState.ACCUMULATING


# ── E directory and authentication ────────────────────────────────────────────

DC = "/w/dc1"


def dc_data(**kw):
    return AnomalyData(**{"directory_servers": frozenset({DC}), "directory_inferred": 1, **kw})


def test_ldap_to_non_directory_server():
    rows = [obs("/w/a", "/w/x", port=389), obs("/w/a", DC, port=389), obs("/w/a", "/w/x", port=8080)]
    [d], status = run(rows, data=dc_data(), detector=detect_auth_to_non_dc)
    assert d.detector is DetectorKind.AUTH_TO_NON_DC and d.fingerprint == "authdst|/w/a|/w/x|389"
    assert d.severity is Severity.MEDIUM and d.summary["port"] == 389 and status.state is DetectorState.OK


def test_kerberos_to_public_ip_is_high():
    rows = [replace(obs("ip:10.9.9.9", "ip:123.56.53.50", port=88), dst_ip="123.56.53.50", dst_href=None)]
    [d], _ = run(rows, data=dc_data(), detector=detect_auth_to_non_dc)
    assert d.severity is Severity.HIGH


def test_traffic_to_declared_ip_is_not_flagged():
    rows = [replace(obs("/w/a", "ip:10.0.7.7", port=88), dst_ip="10.0.7.7", dst_href=None)]
    assert run(rows, data=dc_data(directory_ips=frozenset({"10.0.7.7"})), detector=detect_auth_to_non_dc)[0] == []


def test_no_directory_servers_status():
    for detector in (detect_auth_to_non_dc, detect_new_dc_client):
        dets, status = run([obs("/w/a", "/w/x", port=389)], detector=detector)
        assert dets == [] and status.state is DetectorState.NO_DATA
        assert status.reason_key == "detector_no_directory_servers"


def test_declared_but_not_inferred_status():
    _, status = run([], data=dc_data(directory_declared_missing=2), detector=detect_auth_to_non_dc)
    assert status.state is DetectorState.OK and status.reason_key == "detector_directory_mismatch"
    assert status.params["missing"] == 2


def test_new_dc_client_unmanaged_medium_managed_low():
    rows = [replace(obs("ip:10.0.8.8", DC, port=88), src_managed=False, src_href=None),
            obs("/w/ws4", DC, port=389)]
    dets, _ = run(rows, first_seen=new(rows), data=dc_data(), detector=detect_new_dc_client)
    by_src = {d.subject_key: d for d in dets}
    assert by_src["ip:10.0.8.8"].severity is Severity.MEDIUM and by_src["/w/ws4"].severity is Severity.LOW
    assert by_src["ip:10.0.8.8"].fingerprint == "dcclient|ip:10.0.8.8"


def test_known_dc_client_not_flagged():
    rows = [obs("/w/ws4", DC, port=389)]
    data = dc_data(directory_clients_before=frozenset({"/w/ws4"}))
    assert run(rows, first_seen=new(rows), data=data, detector=detect_new_dc_client)[0] == []
    old = {k: NOW - timedelta(days=3) for k in new(rows)}
    assert run(rows, first_seen=old, data=dc_data(), detector=detect_new_dc_client)[0] == []


def test_new_dc_client_accumulating():
    rows = [obs("/w/ws4", DC, port=389)]
    _, status = run(rows, first_seen=new(rows), data=dc_data(), baseline_days=3.0, detector=detect_new_dc_client)
    assert status.state is DetectorState.ACCUMULATING


def test_directory_surge():
    data = AnomalyData(activity={("/w/a", "directory"): Activity(800, None, 100, 0)}, activity_days=8.0)
    [d], _ = run([], data=data, detector=detect_directory_surge)
    assert d.detector is DetectorKind.DIRECTORY_SURGE and d.fingerprint == "dirsurge|/w/a"
    assert {p.port for p in d.segment.filter.ports} >= {88, 389}


def test_directory_ports_removed_disables_e():
    from illumio_ops.domain.lateral import effective_admin_ports
    from illumio_ops.domain.values import LATERAL_PORTS_DEFAULT, PortClass
    ports = effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(), include_pce=False,
                                  removed=[(p, None) for p, _, c in LATERAL_PORTS_DEFAULT if c is PortClass.DIRECTORY])
    cfg = replace(CFG, admin_ports=ports)
    for detector in (detect_auth_to_non_dc, detect_new_dc_client, detect_directory_surge):
        dets, status = run([obs("/w/a", "/w/x", port=389)], data=dc_data(), cfg=cfg, detector=detector)
        assert dets == [] and status.state is DetectorState.DISABLED
        assert status.reason_key == "detector_no_directory_ports"


def _det(kind, subject, first_min, last_min, severity=Severity.MEDIUM):
    return Detection(detector=kind, fingerprint=f"{kind.value}|{subject}", subject_key=subject, severity=severity,
                     first_seen=NOW + timedelta(minutes=first_min), last_seen=NOW + timedelta(minutes=last_min),
                     critical_asset=False, summary={},
                     segment=FlowSegment(filter=FilterSpec(start=NOW, end=NOW + timedelta(hours=1)),
                                         view=SegmentView.DETAIL, limit=10),
                     confidence=DetectionConfidence())


def test_fanout_after_directory_is_raised():
    window = timedelta(minutes=30)
    recent = [("/w/a", "auth_to_non_dc", NOW, NOW + timedelta(minutes=5))]
    [d] = apply_directory_followup([_det(DetectorKind.FANOUT, "/w/a", 15, 20)], recent, window=window)
    assert d.severity is Severity.HIGH and d.summary["after_directory"]["detector"] == "auth_to_non_dc"
    [late] = apply_directory_followup([_det(DetectorKind.FANOUT, "/w/a", 40, 45)], recent, window=window)
    assert late.severity is Severity.MEDIUM and "after_directory" not in late.summary


def test_fanout_before_directory_not_raised():
    recent = [("/w/a", "new_dc_client", NOW + timedelta(minutes=30), NOW + timedelta(minutes=35))]
    [d] = apply_directory_followup([_det(DetectorKind.FANOUT, "/w/a", 0, 10)], recent, window=timedelta(minutes=30))
    assert d.severity is Severity.MEDIUM


def test_non_execution_detections_not_raised():
    recent = [("/w/a", "auth_to_non_dc", NOW, NOW + timedelta(minutes=5))]
    [d] = apply_directory_followup([_det(DetectorKind.VOLUME_SURGE, "/w/a", 10, 20)], recent,
                                   window=timedelta(minutes=30))
    assert d.severity is Severity.MEDIUM


def test_followup_reads_stored_and_this_runs_directory_detections():
    rows = [obs("/w/a", "/w/x", port=389, minutes_ago=20)] + [obs("/w/a", f"/w/t{i}", minutes_ago=5) for i in range(10)]
    i = replace(inp([o for o in rows if o.port == 445]), traffic_obs=rows, anomaly=dc_data())
    dets, _ = run_detectors(i)
    [fan_det] = [d for d in dets if d.detector is DetectorKind.FANOUT]
    assert "after_directory" in fan_det.summary
    stored = replace(i, traffic_obs=[o for o in rows if o.port == 445],
                     anomaly=dc_data(recent_directory=[("/w/a", "auth_to_non_dc", NOW - timedelta(minutes=25),
                                                        NOW - timedelta(minutes=20))]))
    [fan_det] = [d for d in run_detectors(stored)[0] if d.detector is DetectorKind.FANOUT]
    assert "after_directory" in fan_det.summary


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

