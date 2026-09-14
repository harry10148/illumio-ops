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
    # 刻意差異：rt 去掉 ` +0000`（Graylog CEF codec 會把帶時區尾碼的整行丟掉）。
    cef = cef.replace(" +0000 dvchost=", " dvchost=", 1)
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



_KEY_RE = re.compile(r"(?:^| )([A-Za-z0-9_]+)=")


def _keys(ext: str) -> list[str]:
    return _KEY_RE.findall(ext)


@pytest.mark.parametrize("pair", PAIRS["flows"], ids=[f"{p['flow']['src']['ip']}>{p['flow']['dst']['ip']}" for p in PAIRS["flows"]])
def test_flow_key_order_matches_pce_reference(pair):
    """同 5-tuple 但非同一筆實例：只比鍵順序（去掉 ops 沒有的 in/out/cn1）。"""
    line = _formatter().format_flow(pair["flow"])
    ours = _keys(line.split("|", 7)[7])
    ref = [k for k in _keys(pair["pce_cef_reference"].split("|", 7)[7]) if k not in ("in", "out", "cn1", "cn1Label")]
    # PCE 只在有 process 資訊時帶 user/proc；我們的實例可能沒有，比對時以雙方交集的鍵順序驗證
    common = [k for k in ref if k in ours]
    assert [k for k in ours if k in common] == common
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|flow_")


def test_flow_full_line_raw_api_shape():
    flow = {
        "src": {"ip": "172.16.15.130", "workload": {"hostname": "pce.lab.local", "href": "/orgs/1/workloads/da7a",
                "labels": [{"key": "env", "value": "Server"}, {"key": "app", "value": "Illumio"}]}},
        "dst": {"ip": "172.16.15.100", "workload": {"hostname": "dc", "href": "/orgs/1/workloads/743a",
                "labels": [{"key": "role", "value": "DomainController"}]}},
        "network": {"name": "Corporate"},
        "service": {"port": 53, "proto": 17, "process_name": "dns.exe", "user_name": "NT AUTHORITY\\SYSTEM"},
        "num_connections": 1502, "policy_decision": "potentially_blocked", "state": "active",
        "flow_direction": "inbound", "dst_bi": 211039, "dst_bo": 222295,
        "timestamp_range": {"last_detected": "2026-09-11T09:11:55Z", "first_detected": "2026-09-11T00:00:48Z"},
        "transmission": "unicast",
    }
    line = _formatter().format_flow(flow)
    assert line == (
        "CEF:0|Illumio|PCE|26.2.20|flow_potentially_blocked|Flow Potentially Blocked|3|"
        "act=potentially_blocked cat=flow_summary deviceDirection=0 dpt=53 src=172.16.15.130 dst=172.16.15.100 "
        "proto=udp cnt=1502 rt=Sep 11 2026 09:11:55 duser=NT AUTHORITY\\SYSTEM dproc=dns.exe "
        "cn2=211039 cn2Label=dbi cn3=222295 cn3Label=dbo cs2=A cs2Label=state "
        "shost=pce.lab.local cs5=/orgs/1/workloads/da7a cs5Label=src_href "
        'cs3={"env":"Server","app":"Illumio"} cs3Label=src_labels '
        "dhost=dc cs6=/orgs/1/workloads/743a cs6Label=dst_href "
        'cs4={"role":"DomainController"} cs4Label=dst_labels dvchost=pce.lab.local '
        'msg={"trafclass_code":"U","network":"Corporate"}'
    )


def test_flow_outbound_puts_process_on_source_side_and_emits_icmp_and_counters():
    flow = {
        "src": {"ip": "10.0.0.1", "workload": {"hostname": "", "href": "/orgs/1/workloads/aaa", "labels": []}},
        "dst": {"ip": "10.0.0.2"},
        "service": {"port": 0, "proto": 1, "process_name": "ping", "user_name": "root"},
        "num_connections": 1, "policy_decision": "unknown", "state": "snapshot", "flow_direction": "outbound",
        "icmp_type": 8, "icmp_code": 0, "interval_sec": 600, "dst_tbi": 10, "dst_tbo": 20,
        "dst_dbi": 1, "dst_dbo": 2, "ddms": 5, "tdms": 7, "pd_qualifier": 0,
        "network": {"name": "Corporate"}, "timestamp": "2026-09-11T09:01:23Z",
    }
    line = _formatter().format_flow(flow)
    assert line == (
        "CEF:0|Illumio|PCE|26.2.20|flow_unknown|Flow Unknown|1|"
        "act=unknown cat=flow_summary deviceDirection=1 dpt=0 src=10.0.0.1 dst=10.0.0.2 proto=icmp cnt=1 "
        "in=10 out=20 rt=Sep 11 2026 09:01:23 suser=root sproc=ping cn1=600 cn1Label=interval_sec "
        "cn2=1 cn2Label=dbi cn3=2 cn3Label=dbo cs2=S cs2Label=state "
        "shost= cs5=/orgs/1/workloads/aaa cs5Label=src_href dvchost=pce.lab.local "
        'msg={"icmp_type":8,"icmp_code":0,"trafclass_code":"U","ddms":5,"tdms":7,"network":"Corporate","pd_qualifier":0}'
    )


def test_flow_flat_shape_numeric_pd_and_service_name():
    flow = {"src_ip": "1.1.1.1", "dst_ip": "2.2.2.2", "dst_port": 445, "proto": "tcp", "pd": 2,
            "count": 3, "dir": "I", "state": "C", "un": "System", "pn": "System", "service_name": "SMB",
            "class": "U", "network": "Corporate", "timestamp": "2026-09-11T09:11:54Z"}
    line = _formatter().format_flow(flow)
    assert line.startswith("CEF:0|Illumio|PCE|26.2.20|flow_blocked|Flow Blocked|5|")
    assert " duser=System destinationServiceName=SMB dproc=System " in line
    assert " cs2=C cs2Label=state dvchost=pce.lab.local msg=" in line


def test_flow_masked_user_is_forwarded_redacted():
    from src.siem.mask import mask_flow
    flow = {"src": {"ip": "1.1.1.1"}, "dst": {"ip": "2.2.2.2"},
            "service": {"port": 22, "proto": 6, "user_name": "alice", "process_name": "ssh"},
            "policy_decision": "allowed", "flow_direction": "outbound", "num_connections": 1,
            "timestamp_range": {"last_detected": "2026-09-11T09:11:54Z"}}
    line = _formatter().format_flow(mask_flow(flow, mask_pii=True))
    assert " suser=[REDACTED] sproc=[REDACTED] " in line
