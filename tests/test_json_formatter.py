import json
import re

# ── NormalizedJSONFormatter ───────────────────────────────────────────────────

def test_normalized_json_flow_flat_no_nested_keys():
    """format_flow produces flat JSON with no nested objects."""
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    fl = {
        "src": {"ip": "10.0.0.1", "workload": {
            "hostname": "web-01", "href": "/orgs/1/workloads/abc",
            "labels": [{"key": "app", "value": "web"}, {"key": "env", "value": "prod"}],
        }},
        "dst": {"ip": "52.178.17.235", "fqdn": "api.example.com"},
        "service": {"port": 443, "proto": 6, "process_name": "nginx", "user_name": "www"},
        "policy_decision": "potentially_blocked",
        "num_connections": 7,
        "dst_bi": 1024,
        "dst_bo": 512,
        "flow_direction": "outbound",
        "state": "active",
        "timestamp_range": {"first_detected": "2026-05-13T10:00:00Z"},
    }
    line = NormalizedJSONFormatter().format_flow(fl)
    parsed = json.loads(line)

    # no nested objects
    for v in parsed.values():
        assert not isinstance(v, dict), f"unexpected nested dict in value: {v}"
        assert not isinstance(v, list), f"unexpected list in value: {v}"

    assert parsed["src_ip"] == "10.0.0.1"
    assert parsed["dst_ip"] == "52.178.17.235"
    assert parsed["dst_port"] == 443
    assert parsed["proto"] == "tcp"
    assert parsed["pd"] == "potentially_blocked"
    assert parsed["src_hostname"] == "web-01"
    assert parsed["src_href"] == "/orgs/1/workloads/abc"
    assert parsed["src_labels"] == "app:web env:prod"
    assert parsed["fqdn"] == "api.example.com"
    assert parsed["pn"] == "nginx"
    assert parsed["un"] == "www"
    assert parsed["count"] == 7
    assert parsed["dst_dbi"] == 1024
    assert parsed["dst_dbo"] == 512
    assert parsed["dir"] == "O"
    assert parsed["state"] == "active"
    assert parsed["timestamp"] == "2026-05-13T10:00:00Z"


def test_normalized_json_flow_icmp():
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    fl = {
        "src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
        "service": {"proto": 1, "icmp_type": 8, "icmp_code": 0},
        "policy_decision": "allowed",
        "first_detected": "2026-05-13T10:00:00Z",
    }
    parsed = json.loads(NormalizedJSONFormatter().format_flow(fl))
    assert parsed["proto"] == "icmp"
    assert parsed["type"] == 8
    assert parsed["code"] == 0


def test_normalized_json_event_flat():
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    ev = {
        "uuid": "evt-1",
        "timestamp": "2026-05-13T10:00:00Z",
        "event_type": "sec_policy.create",
        "severity": "warning",
        "status": "success",
        "pce_fqdn": "pce.corp.com",
        "created_by": {"user": {"username": "admin@example.com"}},
        "action": {
            "api_method": "POST",
            "api_endpoint": "/api/v2/orgs/1/sec_policy",
            "src_ip": "10.0.0.5",
            "http_status_code": 201,
        },
        "resource_changes": [{
            "change_type": "create",
            "resource": {"sec_policy": {"name": "policy-1"}},
        }],
    }
    line = NormalizedJSONFormatter().format_event(ev)
    parsed = json.loads(line)

    for v in parsed.values():
        assert not isinstance(v, dict), f"unexpected nested dict: {v}"

    assert parsed["event_type"] == "sec_policy.create"
    assert parsed["pce_event_id"] == "evt-1"
    assert parsed["suser"] == "admin@example.com"
    assert parsed["src_ip"] == "10.0.0.5"
    assert parsed["request_method"] == "POST"
    assert parsed["request"] == "/api/v2/orgs/1/sec_policy"
    assert parsed["http_status_code"] == 201
    assert parsed["resource_changes"] == "create:sec_policy:policy-1"


def test_normalized_json_no_empty_fields():
    """Fields with empty string or None values are omitted."""
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    fl = {
        "src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
        "service": {"port": 80, "proto": 6},
        "policy_decision": "allowed",
        "first_detected": "2026-05-13T10:00:00Z",
    }
    parsed = json.loads(NormalizedJSONFormatter().format_flow(fl))
    # fields without values should not appear
    assert "src_hostname" not in parsed
    assert "src_href" not in parsed
    assert "pn" not in parsed
    assert "fqdn" not in parsed


def test_build_formatter_json_uses_normalized():
    from src.siem.tester import _build_formatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    assert isinstance(_build_formatter("json"), NormalizedJSONFormatter)


def test_build_formatter_syslog_json_uses_normalized():
    from src.siem.tester import _build_formatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    f = _build_formatter("syslog_json")
    assert isinstance(f, SyslogWrappedFormatter)
    assert isinstance(f._inner, NormalizedJSONFormatter)


# ── SplunkHECTransport JSON object passthrough ────────────────────────────────

def test_hec_sends_json_as_object_not_string():
    """JSON payloads arrive at Splunk as an object (auto-indexable), not a string."""
    from unittest.mock import MagicMock, patch
    from src.siem.transports.splunk_hec import SplunkHECTransport

    captured = {}
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.Session") as MockSession:
        session_inst = MagicMock()
        session_inst.post.return_value = mock_resp
        MockSession.return_value = session_inst
        t = SplunkHECTransport("https://splunk.corp:8088", token="tok")
        t._session = session_inst

        payload = '{"src_ip":"10.0.0.1","dst_ip":"10.0.0.2","pd":"allowed"}'
        t.send(payload)
        _, kwargs = session_inst.post.call_args
        event_val = kwargs["json"]["event"]
        assert isinstance(event_val, dict), "JSON payload should be sent as object"
        assert event_val["src_ip"] == "10.0.0.1"


def test_hec_sends_cef_as_string():
    """Non-JSON payloads (CEF) stay as strings in the HEC event field."""
    from unittest.mock import MagicMock, patch
    from src.siem.transports.splunk_hec import SplunkHECTransport

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.Session") as MockSession:
        session_inst = MagicMock()
        session_inst.post.return_value = mock_resp
        MockSession.return_value = session_inst
        t = SplunkHECTransport("https://splunk.corp:8088", token="tok")
        t._session = session_inst

        cef_payload = "CEF:0|Illumio|PCE|3.11|traffic.flow|traffic.flow|3|src=10.0.0.1"
        t.send(cef_payload)
        _, kwargs = session_inst.post.call_args
        event_val = kwargs["json"]["event"]
        assert isinstance(event_val, str), "CEF payload should remain a string"
        assert event_val.startswith("CEF:0")


def test_json_line_event_roundtrip():
    from src.siem.formatters.json_line import JSONLineFormatter
    ev = {"event_type": "policy.update", "severity": "info", "pce_fqdn": "pce.test"}
    line = JSONLineFormatter().format_event(ev)
    parsed = json.loads(line)
    assert parsed["event_type"] == "policy.update"


def test_json_line_flow_roundtrip():
    from src.siem.formatters.json_line import JSONLineFormatter
    fl = {"src_ip": "10.0.0.1", "dst_ip": "10.0.0.2", "port": 443, "action": "blocked"}
    line = JSONLineFormatter().format_flow(fl)
    parsed = json.loads(line)
    assert parsed["action"] == "blocked"


def test_json_line_handles_unicode():
    from src.siem.formatters.json_line import JSONLineFormatter
    ev = {"desc": "測試事件", "type": "audit"}
    line = JSONLineFormatter().format_event(ev)
    assert "測試事件" in line


def test_json_formatter_event_all_fields_preserved():
    """Full PCE API audit event — all nested fields pass through unchanged."""
    from src.siem.formatters.json_line import JSONLineFormatter
    ev = {
        "uuid": "abc-123",
        "timestamp": "2026-05-13T10:00:00Z",
        "event_type": "policy.update",
        "severity": "warning",
        "status": "success",
        "pce_fqdn": "pce.example.com",
        "created_by": {"user": {"username": "admin@example.com"}},
        "action": {"api_method": "POST", "api_endpoint": "/api/v2/orgs/1/sec_policy",
                   "src_ip": "10.0.0.5", "http_status_code": 201},
        "resource_changes": [{"change_type": "create",
                               "resource": {"sec_policy": {"name": "p1"}}}],
    }
    line = JSONLineFormatter().format_event(ev)
    assert "\n" not in line
    parsed = json.loads(line)
    assert parsed["uuid"] == "abc-123"
    assert parsed["created_by"]["user"]["username"] == "admin@example.com"
    assert parsed["action"]["src_ip"] == "10.0.0.5"
    assert parsed["resource_changes"][0]["change_type"] == "create"


def test_json_formatter_flow_all_fields_preserved():
    """Raw PCE API flow — all nested fields pass through unchanged."""
    from src.siem.formatters.json_line import JSONLineFormatter
    fl = {
        "src": {"ip": "10.0.0.1", "workload": {"hostname": "web-01",
                "labels": [{"key": "app", "value": "web"}]}},
        "dst": {"ip": "10.0.0.2", "fqdn": "api.example.com"},
        "service": {"port": 443, "proto": 6, "process_name": "nginx", "user_name": "www"},
        "policy_decision": "potentially_blocked",
        "num_connections": 5,
        "dst_bi": 1024,
        "dst_bo": 512,
        "pd_qualifier": 1,
        "timestamp_range": {"first_detected": "2026-05-13T10:00:00Z"},
    }
    line = JSONLineFormatter().format_flow(fl)
    parsed = json.loads(line)
    assert parsed["src"]["workload"]["hostname"] == "web-01"
    assert parsed["service"]["process_name"] == "nginx"
    assert parsed["policy_decision"] == "potentially_blocked"
    assert parsed["num_connections"] == 5
    assert parsed["pd_qualifier"] == 1


# ── SyslogWrappedFormatter ────────────────────────────────────────────────────

def test_syslog_wrapped_cef_event_has_rfc5424_header():
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    ev = {
        "uuid": "u1",
        "timestamp": "2026-05-13T10:00:00Z",
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.corp.com",
    }
    line = SyslogWrappedFormatter(CEFFormatter()).format_event(ev)
    assert line.startswith("<")
    assert ">1 " in line
    assert "pce.corp.com" in line
    assert "CEF:0|Illumio|PCE|" in line


def test_syslog_wrapped_json_event_has_rfc5424_header():
    from src.siem.formatters.json_line import JSONLineFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    ev = {"uuid": "u2", "timestamp": "2026-05-13T10:00:00Z",
          "event_type": "user.login", "severity": "info", "status": "success",
          "pce_fqdn": "pce.corp.com"}
    line = SyslogWrappedFormatter(JSONLineFormatter()).format_event(ev)
    assert line.startswith("<")
    assert ">1 " in line
    assert "user.login" in line


def test_syslog_wrapped_severity_mapping():
    """warning→4, error→3, critical→2, info→6 in RFC5424 PRI."""
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    fmt = SyslogWrappedFormatter(CEFFormatter())
    for sev_str, expected_sev in [("warning", 4), ("error", 3), ("critical", 2), ("info", 6)]:
        line = fmt.format_event({
            "uuid": "x", "timestamp": "2026-05-13T10:00:00Z",
            "event_type": "e", "severity": sev_str, "status": "success",
        })
        pri = int(re.match(r"<(\d+)>", line).group(1))
        assert pri % 8 == expected_sev, f"{sev_str}: expected RFC5424 sev {expected_sev}, got {pri % 8}"


def test_syslog_wrapped_flow_uses_pce_fqdn():
    from src.siem.formatters.cef import CEFFormatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    fl = {
        "src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "allowed",
        "first_detected": "2026-05-13T10:00:00Z",
        "pce_fqdn": "pce.corp.com",
    }
    line = SyslogWrappedFormatter(CEFFormatter()).format_flow(fl)
    assert ">1 " in line
    assert "pce.corp.com" in line
    assert "CEF:0" in line


# ── _build_formatter routing ──────────────────────────────────────────────────

def test_build_formatter_cef():
    from src.siem.tester import _build_formatter
    from src.siem.formatters.cef import CEFFormatter
    assert isinstance(_build_formatter("cef"), CEFFormatter)


def test_build_formatter_json():
    from src.siem.tester import _build_formatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    assert isinstance(_build_formatter("json"), NormalizedJSONFormatter)


def test_build_formatter_syslog_cef():
    from src.siem.tester import _build_formatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    from src.siem.formatters.cef import CEFFormatter
    f = _build_formatter("syslog_cef")
    assert isinstance(f, SyslogWrappedFormatter)
    assert isinstance(f._inner, CEFFormatter)


def test_build_formatter_syslog_json():
    from src.siem.tester import _build_formatter
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    f = _build_formatter("syslog_json")
    assert isinstance(f, SyslogWrappedFormatter)
    assert isinstance(f._inner, NormalizedJSONFormatter)
