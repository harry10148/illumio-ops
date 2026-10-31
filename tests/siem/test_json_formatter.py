import json
import re

# ── NormalizedJSONFormatter ───────────────────────────────────────────────────





def test_normalized_json_event_flat():
    from illumio_ops.siem.formatters.normalized_json import NormalizedJSONFormatter
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








# ── SplunkHECTransport JSON object passthrough ────────────────────────────────

def test_hec_sends_json_as_object_not_string():
    """JSON payloads arrive at Splunk as an object (auto-indexable), not a string."""
    from unittest.mock import MagicMock, patch

    from illumio_ops.siem.transports.splunk_hec import SplunkHECTransport

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

    from illumio_ops.siem.transports.splunk_hec import SplunkHECTransport

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


# ── SyslogWrappedFormatter ────────────────────────────────────────────────────

def test_syslog_wrapped_cef_event_has_rfc5424_header():
    from illumio_ops.siem.formatters.cef import CEFFormatter
    from illumio_ops.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
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
    from illumio_ops.siem.formatters.normalized_json import NormalizedJSONFormatter
    from illumio_ops.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    ev = {"uuid": "u2", "timestamp": "2026-05-13T10:00:00Z",
          "event_type": "user.login", "severity": "info", "status": "success",
          "pce_fqdn": "pce.corp.com"}
    line = SyslogWrappedFormatter(NormalizedJSONFormatter()).format_event(ev)
    assert line.startswith("<")
    assert ">1 " in line
    assert "user.login" in line


def test_syslog_wrapped_severity_mapping():
    """warning→4, error→3, critical→2, info→6 in RFC5424 PRI."""
    from illumio_ops.siem.formatters.cef import CEFFormatter
    from illumio_ops.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    fmt = SyslogWrappedFormatter(CEFFormatter())
    for sev_str, expected_sev in [("warning", 4), ("error", 3), ("critical", 2), ("info", 6)]:
        line = fmt.format_event({
            "uuid": "x", "timestamp": "2026-05-13T10:00:00Z",
            "event_type": "e", "severity": sev_str, "status": "success",
        })
        pri = int(re.match(r"<(\d+)>", line).group(1))
        assert pri % 8 == expected_sev, f"{sev_str}: expected RFC5424 sev {expected_sev}, got {pri % 8}"




# ── _build_formatter routing ──────────────────────────────────────────────────







