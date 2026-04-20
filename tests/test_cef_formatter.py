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


def test_cef_traffic_flow_contains_network_fields():
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
    assert "act=blocked" in line


def test_cef_escapes_special_characters():
    from src.siem.formatters.cef import _cef_escape
    assert _cef_escape("a=b") == r"a\=b"
    assert _cef_escape("a|b") == r"a\|b"
    assert _cef_escape("a\\b") == r"a\\b"
