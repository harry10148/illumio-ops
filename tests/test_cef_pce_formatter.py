from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PAIRS = json.loads((Path(__file__).parent / "fixtures" / "pce_native_cef_pairs.json").read_text("utf-8"))
PCE_VERSION = "26.2.20"
PCE_FQDN = "pce.lab.local"


def _formatter():
    from src.siem.formatters.cef_pce import PceNativeCEFFormatter
    return PceNativeCEFFormatter(pce_fqdn=PCE_FQDN, pce_version=PCE_VERSION)


def _expected_audit(pair: dict) -> str:
    """PCE 的 CEF 行，把 ops 無法知道的 dst 換成 spec §4.1 的規則值。"""
    event, cef = pair["event"], pair["cef"]
    src_ip = (event.get("action") or {}).get("src_ip")
    if not src_ip or src_ip == "FILTERED":
        cef = re.sub(r" dst=\S+ ", f" dst={PCE_FQDN} ", cef, count=1)
    return cef


def test_resource_changes_chunk_into_cs3_and_drop_changes_past_two_chunks():
    def ev(rc):
        return {"event_type": "a.b", "status": "success", "severity": "info", "href": "/e/1",
                "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}, "resource_changes": rc}
    mid = [{"uuid": "u", "resource": {"workload": {"href": "/w/1"}}, "changes": {"x": {"before": "a" * 5000, "after": ""}}, "change_type": "update"}]
    line = _formatter().format_event(ev(mid))
    cs2 = re.search(r" cs2=(.*?) cs2Label=", line).group(1)
    cs3 = re.search(r" cs1=/e/1 cs3=(.*) cs3Label=resource_changes_2$", line).group(1)
    assert len(cs2) == 3995 and json.loads(cs2 + cs3) == mid
    huge = [{"uuid": "u", "resource": {"workload": {"href": "/w/1"}}, "changes": {"x": {"before": "a" * 9000, "after": ""}}, "change_type": "update"}]
    line = _formatter().format_event(ev(huge))
    cs2 = re.search(r" cs2=(.*?) cs2Label=", line).group(1)
    assert json.loads(cs2) == [{"uuid": "u", "resource": {"workload": {"href": "/w/1"}}, "change_type": "update"}]
    assert " cs3=" not in line


@pytest.mark.parametrize("pair", PAIRS["audit"], ids=[p["cef"].split("|")[4] for p in PAIRS["audit"]])
def test_audit_event_matches_pce_native_line(pair):
    assert _formatter().format_event(pair["event"]) == _expected_audit(pair)


def test_audit_signature_omits_status_when_null():
    line = _formatter().format_event({
        "event_type": "user.pce_session_terminated", "status": None, "severity": "info",
        "timestamp": "2026-09-11T09:04:15.498Z", "pce_fqdn": PCE_FQDN,
        "created_by": {"system": {}}, "action": None, "resource_changes": [], "notifications": [],
        "href": "/orgs/1/events/x",
    })
    head, ext = line.split("|", 7)[:7], line.split("|", 7)[7]
    assert head[4] == "user.pce_session_terminated"
    assert head[5] == "User Pce Session Terminated"
    assert head[6] == "1"
    assert " outcome= cat=audit_events cs2= cs2Label=resource_changes cs4= cs4Label=notifications cn2=2 cn2Label=schema-version cs1Label=event_href cs1=/orgs/1/events/x" in ext
    assert "request=" not in ext


@pytest.mark.parametrize(("severity", "expected"), [
    ("info", 1), ("notice", 2), ("warning", 3), ("warn", 3), ("err", 4), ("error", 4),
    ("critical", 5), ("crit", 5), ("alert", 6), ("emerg", 7), ("emergency", 7), ("debug", 0), ("weird", 1),
])
def test_audit_severity_map(severity, expected):
    line = _formatter().format_event({"event_type": "x.y", "status": "success", "severity": severity,
                                      "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}})
    assert line.split("|")[6] == str(expected)


def test_audit_actor_variants():
    fmt = _formatter()
    base = {"event_type": "x.y", "status": "success", "severity": "info",
            "timestamp": "2026-01-01T00:00:00Z", "action": None}
    sa = fmt.format_event({**base, "created_by": {"service_account": {"href": "/orgs/1/service_accounts/abc", "name": "svc-ops"}}})
    assert " duid=abc duser=svc-ops " in sa
    agent_only = fmt.format_event({**base, "created_by": {"agent": {"href": "/orgs/1/agents/77", "hostname": "h1"}}})
    assert " duid=77 duser=h1 " in agent_only
    empty = fmt.format_event({**base, "created_by": {}})
    assert " duser=system " in empty and "duid=" not in empty


def test_audit_values_are_not_cef_escaped_but_newlines_are_flattened():
    line = _formatter().format_event({
        "event_type": "x.y", "status": "success", "severity": "info", "timestamp": "2026-01-01T00:00:00Z",
        "created_by": {"user": {"href": "/users/1", "username": "DOM\\user=1"}},
        "action": {"api_endpoint": "/a?b=c", "api_method": "GET", "http_status_code": 200, "src_ip": "1.2.3.4"},
        "resource_changes": [{"changes": {"desc": {"before": "a\nb", "after": "\"q\""}}}],
    })
    assert " duser=DOM\\user=1 " in line
    assert " request=/a?b=c " in line
    assert "\n" not in line
    assert '"after":"\\"q\\""' in line   # orjson 的 JSON 跳脫，不是 CEF 跳脫


def test_audit_header_pipe_is_escaped_and_version_injected():
    line = _formatter().format_event({"event_type": "a|b", "status": "success", "severity": "info",
                                      "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}})
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|a\\|b.success|A\\|b Success|1|")


def test_audit_dvchost_falls_back_to_injected_fqdn():
    line = _formatter().format_event({"event_type": "a.b", "status": "success", "severity": "info",
                                      "timestamp": "2026-01-01T00:00:00Z", "created_by": {"system": {}}})
    assert " dvchost=pce.lab.local duser=system dst=pce.lab.local " in line
