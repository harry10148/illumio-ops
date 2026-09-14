"""`cef` = ArcSight dialect of the PCE-native CEF shape (see cef_pce.py)."""
from __future__ import annotations

import json
import re

import pytest

from src.siem.formatters.cef import CEFFormatter, _cef_escape, _cef_header_escape


def _ext(line: str) -> dict[str, str]:
    ext = line.split("|", 7)[7]
    keys = re.findall(r"(?:^| )([A-Za-z0-9_]+)=", ext)
    out = {}
    for i, k in enumerate(keys):
        start = ext.index(f"{k}=") + len(k) + 1
        end = ext.index(f" {keys[i + 1]}=", start) if i + 1 < len(keys) else len(ext)
        out[k] = ext[start:end]
    return out


AUDIT = {
    "href": "/orgs/1/events/evt-1",
    "timestamp": "2026-04-08T12:00:00.250Z",
    "event_type": "sec_policy.create",
    "severity": "warning",
    "status": "success",
    "pce_fqdn": "pce.example.com",
    "created_by": {"user": {"href": "/users/11", "username": "admin@example.com"}},
    "action": {"api_method": "POST", "api_endpoint": "/api/v2/orgs/1/sec_policy",
               "src_ip": "10.0.0.5", "http_status_code": 201},
    "resource_changes": [{"uuid": "u1", "change_type": "create",
                          "resource": {"sec_policy": {"name": "policy-1", "href": "/orgs/1/sec_policy/1"}},
                          "changes": {"workloads_affected": {"before": None, "after": 69}}}],
    "notifications": [],
}


def test_cef_audit_event_is_pce_shaped_with_epoch_rt():
    line = CEFFormatter(pce_version="26.2.20").format_event(AUDIT)
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|sec_policy.create.success|Sec Policy Create Success|3|")
    e = _ext(line)
    assert list(e) == ["rt", "dvchost", "duid", "duser", "dst", "outcome", "cat", "request", "requestMethod",
                       "reason", "cs2", "cs2Label", "cn2", "cn2Label", "cs1Label", "cs1"]
    assert e["rt"] == "1775649600250"
    assert e["dvchost"] == "pce.example.com"
    assert e["duid"] == "11" and e["duser"] == "admin@example.com"
    assert e["dst"] == "10.0.0.5" and e["outcome"] == "success" and e["cat"] == "audit_events"
    assert e["request"] == "/api/v2/orgs/1/sec_policy" and e["requestMethod"] == "POST" and e["reason"] == "201"
    assert e["cs1"] == "/orgs/1/events/evt-1"
    # cs2 is the JSON, escaped per the CEF spec (ArcSight unescapes on parse)
    assert "\\=" not in e["cs2"] and json.loads(e["cs2"].replace("\\\\", "\\"))[0]["change_type"] == "create"


def test_cef_audit_omits_empty_values_unlike_graylog_dialect():
    ev = {"event_type": "user.pce_session_terminated", "status": None, "severity": "info",
          "timestamp": "2026-04-08T12:00:00Z", "created_by": {"system": {}}, "action": None,
          "resource_changes": [], "notifications": [], "href": "/e/1"}
    line = CEFFormatter().format_event(ev)
    assert "|user.pce_session_terminated|User Pce Session Terminated|1|" in line
    e = _ext(line)
    assert "outcome" not in e and "cs2" not in e and "cs4" not in e and "request" not in e
    assert e["duser"] == "system" and e["cs1"] == "/e/1"
    assert "cs2Label" not in e and "cs4Label" not in e


@pytest.mark.parametrize(("severity", "expected"), [("info", 1), ("warning", 3), ("err", 4), ("error", 4)])
def test_cef_audit_severity_follows_the_pce(severity, expected):
    line = CEFFormatter().format_event({"event_type": "a.b", "status": "success", "severity": severity,
                                        "timestamp": "2026-04-08T12:00:00Z", "created_by": {"system": {}}})
    assert line.split("|")[6] == str(expected)


def test_cef_audit_actor_variants():
    base = {"event_type": "a.b", "status": "success", "severity": "info",
            "timestamp": "2026-04-08T12:00:00Z", "action": None}
    assert " duser=system " in CEFFormatter().format_event({**base, "created_by": {"system": {}}})
    line = CEFFormatter().format_event({**base, "created_by": {"service_account": {"href": "/orgs/1/service_accounts/ci", "name": "ci-bot"}}})
    assert " duid=ci duser=ci-bot " in line
    line = CEFFormatter().format_event({**base, "created_by": {"agent": {"href": "/orgs/1/agents/5", "hostname": "h"},
                                                                 "ven": {"href": "/orgs/1/vens/abc", "hostname": "h"}}})
    assert " duid=abc duser=h " in line


def test_cef_values_are_escaped_per_spec_and_header_keeps_equals_literal():
    ev = {"event_type": "weird=type", "status": "success", "severity": "info",
          "timestamp": "2026-04-08T12:00:00Z",
          "created_by": {"user": {"href": "/users/1", "username": "DOM\\user=1"}},
          "action": {"api_endpoint": "/a?b=c", "api_method": "GET", "http_status_code": 200, "src_ip": "1.2.3.4"}}
    line = CEFFormatter().format_event(ev)
    assert "|weird=type.success|Weird=type Success|" in line    # '=' literal in header
    e = _ext(line)
    assert e["duser"] == "DOM\\\\user\\=1"
    assert e["request"] == "/a?b\\=c"


def test_cef_escape_helpers():
    assert _cef_escape("a=b") == r"a\=b"
    assert _cef_escape("a|b") == r"a\|b"
    assert _cef_escape("a\\b") == r"a\\b"
    assert _cef_header_escape("a=b") == "a=b"
    assert _cef_header_escape("a|b") == r"a\|b"


def test_cef_traffic_flow_pce_api_format():
    fl = {
        "src": {"ip": "172.16.15.150", "workload": {"hostname": "win10-jd", "href": "/orgs/1/workloads/abc",
                "labels": [{"key": "app", "value": "Jumpdesk"}, {"key": "env", "value": "VMware"}]}},
        "dst": {"ip": "52.178.17.235", "fqdn": "mobile.events.data.microsoft.com"},
        "network": {"name": "Corporate"},
        "service": {"port": 443, "proto": 6, "process_name": "onedrive.exe", "user_name": "LAB\\Administrator"},
        "num_connections": 7, "policy_decision": "potentially_blocked", "state": "active",
        "flow_direction": "outbound", "dst_bi": 10135, "dst_bo": 10501,
        "timestamp_range": {"first_detected": "2026-05-13T13:50:17Z", "last_detected": "2026-05-13T13:55:17Z"},
    }
    line = CEFFormatter(pce_fqdn="pce.example.com", pce_version="26.2.20").format_flow(fl)
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|flow_potentially_blocked|Flow Potentially Blocked|3|")
    e = _ext(line)
    assert list(e) == ["act", "cat", "deviceDirection", "dpt", "src", "dst", "proto", "cnt", "rt", "suser", "sproc",
                       "cn2", "cn2Label", "cn3", "cn3Label", "cs2", "cs2Label", "shost", "cs5", "cs5Label",
                       "cs3", "cs3Label", "dvchost", "msg"]
    assert e["act"] == "potentially_blocked" and e["cat"] == "flow_summary" and e["deviceDirection"] == "1"
    assert e["src"] == "172.16.15.150" and e["dst"] == "52.178.17.235" and e["dpt"] == "443" and e["proto"] == "tcp"
    assert e["cnt"] == "7" and e["rt"] == "1778680517000"
    assert e["suser"] == "LAB\\\\Administrator" and e["sproc"] == "onedrive.exe"
    assert e["cn2"] == "10135" and e["cn3"] == "10501" and e["cs2"] == "A"
    assert e["shost"] == "win10-jd" and e["cs5"] == "/orgs/1/workloads/abc"
    assert e["cs3"] == '{"app":"Jumpdesk","env":"VMware"}' and e["dvchost"] == "pce.example.com"
    assert e["msg"] == '{"trafclass_code":"U","network":"Corporate"}'


def test_cef_traffic_flow_flat_form_icmp_and_proto_number():
    line = CEFFormatter().format_flow({"first_detected": "2026-04-19T10:00:00Z", "src_ip": "10.0.0.1",
                                       "dst_ip": "10.0.0.2", "port": 443, "protocol": "tcp", "pd": "blocked"})
    assert "|flow_blocked|Flow Blocked|5|" in line
    e = _ext(line)
    assert e["src"] == "10.0.0.1" and e["dst"] == "10.0.0.2" and e["dpt"] == "443" and e["proto"] == "tcp"
    assert "cs2" not in e  # no state → omitted in the arcsight dialect
    line = CEFFormatter().format_flow({"src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
                                       "service": {"proto": 1, "icmp_type": 8, "icmp_code": 0},
                                       "policy_decision": "allowed", "first_detected": "2026-05-13T10:00:00Z"})
    e = _ext(line)
    assert e["proto"] == "icmp" and e["dpt"] == "0"
    assert e["msg"].replace("\\", "") == '{"icmp_type":8,"icmp_code":0,"trafclass_code":"U"}'
    line = CEFFormatter().format_flow({"src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
                                       "service": {"port": 53, "proto": 17}, "policy_decision": "allowed",
                                       "first_detected": "2026-05-13T10:00:00Z"})
    assert " proto=udp " in line and " dpt=53 " in line
