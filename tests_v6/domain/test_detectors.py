"""Lateral-movement detectors (spec §6.5.1 正在發生): pure functions over observed connections."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illumio_ops.domain.detectors import (
    DetectorConfig,
    DetectorInput,
    Obs,
    Precursor,
    apply_precursors,
    detect_account_fanout,
    detect_blocked_surge,
    detect_cross_env,
    detect_fanout,
    detect_new_admin,
    detect_non_admin_group,
    detect_pivot_chain,
    detect_unexpected_initiator,
    run_detectors,
)
from illumio_ops.domain.lateral import HostInfo, effective_admin_ports
from illumio_ops.domain.values import (
    LATERAL_PORTS_DEFAULT,
    DetectorKind,
    DetectorState,
    PrecursorKind,
    Severity,
)

NOW = datetime(2026, 10, 25, 12, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "lateral_obs.json"
PORTS = effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(), removed=(), include_pce=False)
CFG = DetectorConfig(
    fanout_targets=10, fanout_window=timedelta(minutes=60), account_fanout_targets=10,
    account_fanout_window=timedelta(minutes=60), chain_window=timedelta(minutes=30), blocked_targets=5,
    blocked_window=timedelta(minutes=60), blocked_surge_factor=3.0, exclude_system_accounts=True,
    precursor_window=timedelta(hours=24),
    expected={(445, 6): frozenset({"system", "svchost.exe", "lsass.exe"}), (3389, 6): frozenset({"mstsc.exe"}),
              (135, 6): frozenset({"lsass.exe", "svchost.exe", "backgroundtaskhost.exe"})},
    admin_ports=PORTS, environment_label_key="env", admin_groups_configured=False, environment_labels_present=True)
ADMINS = {"/w/jump"}
CRITICAL = {"/w/fin"}


def host(key, ip="", hostname=None, labels=None):
    return HostInfo(key=key, href=None if key.startswith("ip:") else key, hostname=hostname or key,
                    managed=not key.startswith("ip:"), labels=labels or {}, enforcement_mode=None, visibility_level=None,
                    os_id=None, ven_href=None, critical=key in CRITICAL, admin_group=key in ADMINS)


def obs(src, dst, *, minutes_ago=5, port=445, decision="potentially_blocked", origin="ingest", user=None, proc=None,
        src_labels=None, dst_labels=None, first_ago=None):
    last = NOW - timedelta(minutes=minutes_ago)
    first = NOW - timedelta(minutes=first_ago) if first_ago is not None else last - timedelta(minutes=1)
    return Obs(src_key=src, dst_key=dst, src_href=src, dst_href=dst, src_ip="10.0.0.1", dst_ip="10.0.0.2",
               src_hostname=src, dst_hostname=dst, port=port, proto=6, decision=decision, first=first,
               last=last, num_connections=1, initiator_user=user, initiator_process=proc, src_labels=src_labels or {},
               dst_labels=dst_labels or {}, src_managed=True, origin=origin)


def inp(observations, *, window=(NOW - timedelta(minutes=40), NOW), first_seen=None, baseline_days=30.0,
        backfilling=False, cfg=CFG, blocked=(), history=None, precursors=()):
    return DetectorInput(window=window, obs=observations, blocked_obs=list(blocked),
                         hosts=lambda k, ip, name, labels: host(k, labels=labels),
                         baseline_first_seen=first_seen or {}, precursors=list(precursors), config=cfg,
                         baseline_days=baseline_days, baseline_required=30,
                         baseline_full=baseline_days >= 30 and not backfilling, gaps=(), blocked_history=history or {})


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




# ── pivot chain ──────────────────────────────────────────────────────────────

def test_chain_same_bucket_counts():
    ab = obs("/w/a", "/w/b", minutes_ago=10, first_ago=20)
    bc = obs("/w/b", "/w/c", minutes_ago=10, first_ago=20, port=3389)  # same reporting bucket as a → b
    [d] = detect_pivot_chain(inp([ab, bc]))[0]
    assert d.fingerprint == "chain|/w/a|/w/b|/w/c" and d.subject_key == "/w/a" and d.severity is Severity.MEDIUM
    assert d.summary["via"] == "/w/b" and d.summary["target"] == "/w/c" and d.summary["ports"] == [445, 3389]


def test_chain_second_leg_before_first_rejected():
    bc = obs("/w/b", "/w/c", minutes_ago=30, first_ago=35)
    ab = obs("/w/a", "/w/b", minutes_ago=5, first_ago=10)  # a reached b only after b had already moved on
    assert detect_pivot_chain(inp([ab, bc]))[0] == []
    late = obs("/w/b", "/w/c", minutes_ago=1, first_ago=1)  # b → c starts 9 min after a → b ended: within 30
    assert len(detect_pivot_chain(inp([ab, late]))[0]) == 1
    too_late = obs("/w/b", "/w/c", minutes_ago=1, first_ago=1)
    short = replace(CFG, chain_window=timedelta(minutes=3))  # b → c starts 4 min after a → b: too late
    assert detect_pivot_chain(inp([ab, too_late], cfg=short))[0] == []


def test_chain_excludes_return_to_origin():
    assert detect_pivot_chain(inp([obs("/w/a", "/w/b"), obs("/w/b", "/w/a")]))[0] == []


def test_chain_needs_a_leg_in_window():
    ab = obs("/w/a", "/w/b", minutes_ago=41, first_ago=45)
    bc = obs("/w/b", "/w/c", minutes_ago=42, first_ago=44)
    assert detect_pivot_chain(inp([ab, bc]))[0] == []  # both legs before the window: evaluated earlier
    to_fin = obs("/w/b", "/w/fin", minutes_ago=5, first_ago=12)  # in the window, started within 30 min of a → b
    assert detect_pivot_chain(inp([ab, to_fin]))[0][0].severity is Severity.HIGH


# ── blocked surge ────────────────────────────────────────────────────────────

def _blocked(src, n):
    return [obs(src, f"/w/b{i}", decision="blocked", port=1000 + i) for i in range(n)]


def test_blocked_surge_needs_factor_over_history():
    assert detect_blocked_surge(inp([], blocked=_blocked("/w/a", 6), history={"/w/a": 3}))[0] == []
    [d] = detect_blocked_surge(inp([], blocked=_blocked("/w/a", 6), history={"/w/a": 1}))[0]
    assert d.fingerprint == "blocked|/w/a" and d.summary["targets"] == 6 and d.summary["previous_max"] == 1


def test_blocked_surge_threshold_without_history():
    assert detect_blocked_surge(inp([], blocked=_blocked("/w/a", 4)))[0] == []
    assert len(detect_blocked_surge(inp([], blocked=_blocked("/w/a", 5)))[0]) == 1


# ── admin groups ─────────────────────────────────────────────────────────────

def test_non_admin_group_disabled_without_groups():
    dets, status = detect_non_admin_group(inp([obs("/w/a", "/w/b")]))
    assert dets == [] and status.state is DetectorState.DISABLED and status.reason_key == "detector_admin_groups_unset"


def test_non_admin_group_flags_unmanaged_source():
    cfg = replace(CFG, admin_groups_configured=True)
    found, status = detect_non_admin_group(inp([obs("ip:10.9.9.9", "/w/b"), obs("/w/jump", "/w/b"),
                                                obs("/w/a", "/w/fin", decision="blocked")], cfg=cfg))
    assert [d.subject_key for d in found] == ["ip:10.9.9.9"] and status.state is DetectorState.OK


# ── cross environment ───────────────────────────────────────────────────────

def test_cross_env_needs_both_env_labels():
    found = detect_cross_env(inp([obs("/w/a", "/w/b", src_labels={"env": "Dev"}, dst_labels={"env": "Prod"}),
                                  obs("/w/a", "/w/c", src_labels={"env": "Dev"}),
                                  obs("/w/a", "/w/d", src_labels={"env": "Dev"}, dst_labels={"env": "Dev"})]))[0]
    assert [(d.summary["src_env"], d.summary["dst_env"]) for d in found] == [("Dev", "Prod")]


def test_cross_env_allowed_is_high():
    allowed = obs("/w/a", "/w/b", decision="allowed", src_labels={"env": "Dev"}, dst_labels={"env": "Prod"})
    assert detect_cross_env(inp([allowed]))[0][0].severity is Severity.HIGH
    pb = replace(allowed, decision="potentially_blocked")
    assert detect_cross_env(inp([pb]))[0][0].severity is Severity.MEDIUM
    assert detect_cross_env(inp([replace(allowed, decision="blocked")]))[0] == []


def test_cross_env_no_data_without_env_labels():
    dets, status = detect_cross_env(inp([obs("/w/a", "/w/b")], cfg=replace(CFG, environment_labels_present=False)))
    assert dets == [] and status.state is DetectorState.NO_DATA


def test_cross_env_uses_configured_label_key():
    o = obs("/w/a", "/w/b", src_labels={"Environment": "Dev"}, dst_labels={"Environment": "Prod"})
    assert detect_cross_env(inp([o]))[0] == []
    assert len(detect_cross_env(inp([o], cfg=replace(CFG, environment_label_key="Environment")))[0]) == 1


# ── accounts ─────────────────────────────────────────────────────────────────

def test_account_fanout_excludes_system_accounts():
    rows = [obs("/w/a", f"/w/t{i}", user="NT AUTHORITY\\SYSTEM") for i in range(10)]
    assert detect_account_fanout(inp(rows))[0] == []
    cfg = replace(CFG, exclude_system_accounts=False)
    assert len(detect_account_fanout(inp(rows, cfg=cfg))[0]) == 1


def test_account_fanout_no_data_when_no_users():
    dets, status = detect_account_fanout(inp(fan("/w/a", 12)))
    assert dets == [] and status.state is DetectorState.NO_DATA and status.params == {"covered": 0, "total": 12}


def test_account_fanout_confidence_has_coverage():
    rows = [obs(f"/w/s{i % 3}", f"/w/t{i}", user="LAB\\Alice" if i % 2 else "lab\\alice") for i in range(10)]
    rows += [obs("/w/x", "/w/y")]
    [d] = detect_account_fanout(inp(rows))[0]
    assert d.fingerprint == "acct|lab\\alice" and d.severity is Severity.HIGH and d.summary["targets"] == 10
    assert (d.confidence.field, d.confidence.covered, d.confidence.total) == ("initiator_user", 10, 11)


# ── initiating processes ─────────────────────────────────────────────────────

def test_unexpected_initiator_flags_powershell_smb():
    [d] = detect_unexpected_initiator(inp([obs("/w/a", "/w/b", proc="powershell.exe"),
                                           obs("/w/a", "/w/c", proc="system")]))[0]
    assert d.fingerprint == "proc|/w/a|powershell.exe|445|6" and d.severity is Severity.MEDIUM


def test_unexpected_initiator_unknown_process_not_evaluable():
    dets, status = detect_unexpected_initiator(inp([obs("/w/a", "/w/b"), obs("/w/a", "/w/c")]))
    assert dets == [] and status.state is DetectorState.NO_DATA and status.params["not_evaluable"] == 2


def test_unexpected_initiator_unlisted_port_not_evaluated():
    dets, status = detect_unexpected_initiator(inp([obs("/w/a", "/w/b", port=389, proc="weird.exe")]))
    assert dets == [] and status.state is DetectorState.OK


def test_lab_fixture_unexpected_initiators():
    found = detect_unexpected_initiator(inp(_fixture_obs(), window=(NOW - timedelta(days=60), NOW)))[0]
    flagged = {(d.summary["process"], d.summary["port"]) for d in found}
    assert ("powershell.exe", 445) in flagged and ("powershell.exe", 3389) in flagged
    assert not any(proc in ("lsass.exe", "system") for proc, _ in flagged)


# ── precursors ───────────────────────────────────────────────────────────────

def test_precursor_raises_one_level_and_lists_reason():
    dets = detect_fanout(inp(fan("/w/a", 10)))[0]
    tamper = Precursor(host_key="/w/a", kind=PrecursorKind.TAMPER, at=NOW - timedelta(hours=3), signal=True)
    stale = Precursor(host_key="/w/a", kind=PrecursorKind.OFFLINE, at=NOW - timedelta(days=3), signal=False)
    other = Precursor(host_key="/w/z", kind=PrecursorKind.SUSPEND, at=NOW, signal=False)
    [d] = apply_precursors(dets, [tamper, stale, other], window=timedelta(hours=24))
    assert d.severity is Severity.HIGH and [p["kind"] for p in d.summary["precursors"]] == ["tamper"]
    assert d.summary["precursors"][0]["signal"] is True
    acct = detect_account_fanout(inp([obs("/w/a", f"/w/t{i}", user="bob") for i in range(10)]))[0]
    assert apply_precursors(acct, [Precursor("bob", PrecursorKind.TAMPER, NOW, True)],
                            window=timedelta(hours=24))[0].severity is Severity.HIGH  # accounts are not raised


def test_run_detectors_applies_precursors():
    tamper = Precursor(host_key="/w/a", kind=PrecursorKind.TAMPER, at=NOW - timedelta(hours=1), signal=False)
    dets, _ = run_detectors(inp(fan("/w/a", 10), precursors=[tamper]))
    assert dets[0].severity is Severity.HIGH


def test_backfill_rows_never_count_toward_thresholds():
    # Final review #10 (spec §7): history from a backfill must not complete a live detection.
    assert not [d for d in run_detectors(inp(fan("/w/a", 9, origin="backfill") + [obs("/w/a", "/w/x")]))[0]
                if d.detector is DetectorKind.FANOUT]
    legs = [obs("/w/a", "/w/b", minutes_ago=20, origin="backfill"), obs("/w/b", "/w/c", minutes_ago=10)]
    assert not [d for d in run_detectors(inp(legs))[0] if d.detector is DetectorKind.PIVOT_CHAIN]


def test_empty_admin_port_set_disables_management_detectors():
    # Final review #8: no management ports must not mean "every port".
    cfg = replace(CFG, admin_ports=effective_admin_ports(LATERAL_PORTS_DEFAULT, (), extra=(),
                                                         removed=[(p, None) for p, _ in LATERAL_PORTS_DEFAULT],
                                                         include_pce=False))
    dets, statuses = run_detectors(inp(fan("/w/a", 12, port=443), cfg=cfg))
    assert dets == []
    by_kind = {s.detector: s for s in statuses}
    assert by_kind[DetectorKind.FANOUT].state is DetectorState.DISABLED
    assert by_kind[DetectorKind.FANOUT].reason_key == "detector_no_admin_ports"
    assert by_kind[DetectorKind.BLOCKED_SURGE].state is not DetectorState.DISABLED


def _with_os(i):
    return replace(i, hosts=lambda k, ip, name, labels: replace(host(k), os_id="win-x86_64" if "win" in k else "ubuntu"))


def test_partial_user_coverage_names_the_host_kinds_without_any():
    # Final review #18: a few covered hosts must not hide that a whole kind of host carries no user.
    rows = [obs("/w/lin1", f"/w/t{i}") for i in range(12)] + [obs("/w/win1", "/w/t0", user="CORP\\alice")]
    _, status = detect_account_fanout(_with_os(inp(rows)))
    assert status.state is DetectorState.OK and status.reason_key == "detector_partial_users_none_from"
    assert status.params == {"covered": 1, "total": 13, "kinds": "Linux"}


def test_partial_process_coverage_names_the_host_kinds_without_any():
    rows = [obs("/w/lin1", f"/w/t{i}") for i in range(12)] + [obs("/w/win1", "/w/t0", proc="svchost.exe")]
    _, status = detect_unexpected_initiator(_with_os(inp(rows)))
    assert status.reason_key == "detector_partial_process_none_from"
    assert status.params == {"not_evaluable": 12, "total": 13, "kinds": "Linux"}


# ── window detectors: first_seen stays inside the window ─────────────────────
# .106: a PCE record spanning ~24 h (batch → Imperva:22, first 10-25 00:01, last 10-26 00:21) sat in a fan-out's
# window and dragged first_seen back a day, so the 60-minute dedup merged it with any fan-out of the day before.

DAY_LONG = 24 * 60


def test_fanout_first_seen_is_bounded_by_its_window():
    [d] = detect_fanout(inp(fan("/w/a", 9) + [obs("/w/a", "/w/long", first_ago=DAY_LONG)]))[0]
    assert d.first_seen >= d.last_seen - CFG.fanout_window


def test_account_fanout_first_seen_is_bounded_by_its_window():
    users = [obs("/w/a", f"/w/t{i}", user="LAB\\alice") for i in range(9)]
    users.append(obs("/w/a", "/w/long", user="LAB\\alice", first_ago=DAY_LONG))
    [d] = detect_account_fanout(inp(users))[0]
    assert d.first_seen >= d.last_seen - CFG.account_fanout_window


def test_blocked_surge_first_seen_is_bounded_by_its_window():
    # last seen a minute before the others, so it is the source's first row
    long = obs("/w/a", "/w/long", decision="blocked", minutes_ago=6, first_ago=DAY_LONG)
    [d] = detect_blocked_surge(inp([], blocked=[long] + _blocked("/w/a", 4)))[0]
    assert d.first_seen >= d.last_seen - CFG.blocked_window
