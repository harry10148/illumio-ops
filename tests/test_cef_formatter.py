def test_cef_audit_event_has_required_header():
    from src.siem.formatters.cef import CEFFormatter
    ev = {
        "pce_event_id": "uuid-abc",
        "timestamp": "2026-04-19T10:00:00Z",
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "pce_fqdn": "pce.example.com",
    }
    line = CEFFormatter().format_event(ev)
    assert line.startswith("CEF:0|Illumio|PCE|")
    assert "externalId=uuid-abc" in line
    assert "dvchost=pce.example.com" in line
    assert "outcome=success" in line


def test_cef_traffic_flow_normalized_form():
    """format_flow accepts pre-normalized fields (flat, no nesting)."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "first_detected": "2026-04-19T10:00:00Z",
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
        "port": 443, "protocol": "tcp", "action": "blocked",
        "pce_fqdn": "pce.example.com",
    }
    line = CEFFormatter().format_flow(fl)
    assert "src=10.0.0.1" in line
    assert "dst=10.0.0.2" in line
    assert "dpt=443" in line
    assert "proto=tcp" in line
    assert "act=blocked" in line


def test_cef_traffic_flow_pce_api_format():
    """format_flow accepts raw PCE API format with nested src/dst/service."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "src": {"ip": "192.168.1.10", "workload": {"href": "/orgs/1/workloads/abc"}},
        "dst": {"ip": "10.0.0.5",     "workload": {"href": "/orgs/1/workloads/xyz"}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "potentially_blocked",
        "first_detected": "2026-05-13T10:00:00Z",
        "last_detected":  "2026-05-13T10:05:00Z",
        "flow_count": 3,
    }
    line = CEFFormatter().format_flow(fl)
    assert "src=192.168.1.10" in line
    assert "dst=10.0.0.5" in line
    assert "dpt=443" in line
    assert "proto=tcp" in line
    assert "act=potentially_blocked" in line


def test_cef_traffic_flow_pce_api_proto_number():
    """Proto integer (17=UDP) is converted to string in CEF output."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
        "service": {"port": 53, "proto": 17},
        "policy_decision": "allowed",
        "first_detected": "2026-05-13T10:00:00Z",
    }
    line = CEFFormatter().format_flow(fl)
    assert "proto=udp" in line
    assert "dpt=53" in line


def test_cef_traffic_flow_missing_port_defaults_zero():
    """Flows with no port (e.g. ICMP) correctly emit dpt=0."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
        "service": {"proto": 1},
        "policy_decision": "allowed",
        "first_detected": "2026-05-13T10:00:00Z",
    }
    line = CEFFormatter().format_flow(fl)
    assert "dpt=0" in line
    assert "proto=icmp" in line


def test_cef_escapes_special_characters():
    from src.siem.formatters.cef import _cef_escape
    assert _cef_escape("a=b") == r"a\=b"
    assert _cef_escape("a|b") == r"a\|b"
    assert _cef_escape("a\\b") == r"a\\b"
