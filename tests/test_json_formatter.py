import json
import re


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
    from src.siem.formatters.json_line import JSONLineFormatter
    assert isinstance(_build_formatter("json"), JSONLineFormatter)


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
    from src.siem.formatters.json_line import JSONLineFormatter
    f = _build_formatter("syslog_json")
    assert isinstance(f, SyslogWrappedFormatter)
    assert isinstance(f._inner, JSONLineFormatter)
