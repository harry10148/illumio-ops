"""Tamper readings, interval patterns, timeline and host-side guidance (spec §6.5.4)."""
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from illumio_ops.domain.tamper import (
    GUIDANCE_KEYS,
    TAMPER_ACTION_KEYS,
    Annotation,
    TimelineEvent,
    classify,
    explained_by,
    guidance,
    interpret,
    timeline,
)
from illumio_ops.domain.values import TamperAction, TamperPattern

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "pce"
T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _signal(kernel, ts="2026-10-01T11:03:51Z"):
    return {"timestamp": ts, "event_type": "agent.tampering", "notifications": [{"info": {
        "event_classification": "signal", "events": [{"timestamp": ts, "tamper_type": "firewall", "process_id": 1022307,
                                                     "kernel_functions": kernel, "process_name": "nft"}]}}]}


def test_signal_reading_actions_from_comma_joined_kernel_functions():
    [r] = interpret(_signal(["nfnetlink_rcv_batch,nf_tables_deltable", "nf_tables_newrule"]))
    assert r.classification == "signal" and r.process == "nft" and r.pid == 1022307 and r.has_process_info
    assert r.actions == (TamperAction.DELETE_TABLE, TamperAction.ADD_RULE) and r.tamper_type == "firewall"


def test_confirmed_reading_has_no_process_info():
    confirmed = json.loads((FIX / "events_tamper.json").read_text())
    raw = next(e for e in confirmed if e["notifications"][0]["info"].get("event_classification") == "confirmed")
    [r] = interpret(raw)
    assert r.classification == "confirmed" and r.process is None and r.has_process_info is False
    assert r.actions == ()


def test_unknown_kernel_function_kept_raw():
    [r] = interpret(_signal(["nf_tables_something_new"]))
    assert r.actions == ("nf_tables_something_new",)


def _fixture_by_host():
    by = defaultdict(list)
    for e in json.loads((FIX / "tamper_60d.json").read_text()):
        by[e["host"]].append(datetime.fromisoformat(e["timestamp"]))
    return by


def test_classify_lab_fixture():
    got = {h: classify(ts).kind for h, ts in _fixture_by_host().items()}
    assert got == {"host-01": TamperPattern.REGULAR_CYCLE, "host-04": TamperPattern.REGULAR_CYCLE,
                   "host-05": TamperPattern.REGULAR_CYCLE, "host-07": TamperPattern.REGULAR_CYCLE,
                   "host-03": TamperPattern.BURST, "host-02": TamperPattern.SPORADIC, "host-06": TamperPattern.TOO_FEW}
    r = classify(_fixture_by_host()["host-01"])
    assert r.n == 201 and round(r.median_minutes, 1) == 10.1


def _every(minutes, n, jitter=()):
    out, t = [], T0
    for i in range(n):
        out.append(t)
        t += timedelta(minutes=minutes + (jitter[i % len(jitter)] if jitter else 0))
    return out


def test_classify_threshold_edges():
    assert classify(_every(10, 2)).kind is TamperPattern.TOO_FEW
    assert classify(_every(10, 6)).kind is TamperPattern.REGULAR_CYCLE      # n = 6, no spread
    assert classify(_every(10, 5)).kind is TamperPattern.SPORADIC           # too few for a cycle
    assert classify(_every(2, 4)).kind is TamperPattern.BURST               # median exactly 2 min
    assert classify(_every(10, 8, jitter=(0, 8))).kind is TamperPattern.SPORADIC  # quartiles 10/18: too wide
    assert classify([]).kind is TamperPattern.TOO_FEW and classify([]).median_minutes is None


def test_timeline_window_and_types():
    first = T0
    events = [TimelineEvent(at=first - timedelta(hours=2), event_type="workload.update", summary="mode"),
              TimelineEvent(at=first + timedelta(hours=30), event_type="sec_policy.create", summary="late"),
              TimelineEvent(at=first - timedelta(minutes=5), event_type="user.sign_in", summary="noise"),
              TimelineEvent(at=first + timedelta(hours=1), event_type="sec_policy.create", summary="provision")]
    assert [e.summary for e in timeline(events, first)] == ["mode", "provision"]


def test_guidance_by_os_family():
    linux = guidance("ubuntu-x86_64-jammy")
    assert {c.platform for c in linux} == {"linux_nftables", "linux_iptables_legacy"}
    assert "nft -s list ruleset" in [c.text for c in linux]
    assert any("tampered" in c.text for c in linux) and any(c.text.startswith("auditctl") for c in linux)
    win = guidance("win-x86_64-server")
    assert {c.platform for c in win} == {"windows"} and "C:\\ProgramData\\Illumio" in win[0].text
    assert {c.platform for c in guidance(None)} == {"linux_nftables", "linux_iptables_legacy"}
    assert all(c.purpose_key in GUIDANCE_KEYS.values() for c in linux + win)


def test_annotation_explains_matching_readings():
    [r] = interpret(_signal(["nf_tables_newrule"]))
    by_host = Annotation(id=1, host_href="/w/1", pattern=None, process=None, reason="NetBird, known")
    by_pattern = Annotation(id=2, host_href=None, pattern=TamperPattern.REGULAR_CYCLE, process="nft", reason="x")
    other = Annotation(id=3, host_href="/w/2", pattern=None, process=None, reason="y")
    assert explained_by(r, "/w/1", TamperPattern.BURST, [other, by_host]) == 1
    assert explained_by(r, "/w/9", TamperPattern.REGULAR_CYCLE, [by_pattern]) == 2
    assert explained_by(r, "/w/9", TamperPattern.BURST, [by_pattern, other]) is None
    assert set(TAMPER_ACTION_KEYS) == set(TamperAction)
