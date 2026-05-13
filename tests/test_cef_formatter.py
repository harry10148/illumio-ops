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
    """Flat/normalized form (pre-extracted fields) still works."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "first_detected": "2026-04-19T10:00:00Z",
        "src_ip": "10.0.0.1", "dst_ip": "10.0.0.2",
        "port": 443, "protocol": "tcp", "action": "blocked",
    }
    line = CEFFormatter().format_flow(fl)
    assert "src=10.0.0.1" in line
    assert "dst=10.0.0.2" in line
    assert "dpt=443" in line
    assert "proto=tcp" in line


def test_cef_traffic_flow_pce_api_format():
    """Raw PCE API format (nested src/dst/service) is correctly normalised."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "src": {"ip": "192.168.1.10", "workload": {"href": "/orgs/1/workloads/abc"}},
        "dst": {"ip": "10.0.0.5",     "workload": {"href": "/orgs/1/workloads/xyz"}},
        "service": {"port": 443, "proto": 6},
        "policy_decision": "potentially_blocked",
        "first_detected": "2026-05-13T10:00:00Z",
    }
    line = CEFFormatter().format_flow(fl)
    assert "src=192.168.1.10" in line
    assert "dst=10.0.0.5" in line
    assert "dpt=443" in line
    assert "proto=tcp" in line
    assert "pd=potentially_blocked" in line


def test_cef_traffic_flow_official_field_names():
    """CEF extension keys use the official Illumio log field names."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "src": {
            "ip": "172.16.15.150",
            "workload": {
                "hostname": "win10-jd",
                "href": "/orgs/1/workloads/abc",
                "labels": [
                    {"key": "app", "value": "Jumpdesk"},
                    {"key": "env", "value": "VMware"},
                ],
            },
        },
        "dst": {"ip": "52.178.17.235", "fqdn": "mobile.events.data.microsoft.com"},
        "network": {"name": "Corporate"},
        "service": {
            "port": 443, "proto": 6,
            "process_name": "onedrive.exe",
            "user_name": "LAB\\Administrator",
        },
        "num_connections": 7,
        "policy_decision": "potentially_blocked",
        "state": "active",
        "flow_direction": "outbound",
        "dst_bi": 10135,
        "dst_bo": 10501,
        "timestamp_range": {"first_detected": "2026-05-13T13:50:17Z"},
    }
    line = CEFFormatter().format_flow(fl)

    # CEF standard 5-tuple
    assert "src=172.16.15.150" in line
    assert "dst=52.178.17.235" in line
    assert "dpt=443" in line
    assert "proto=tcp" in line

    # Official Illumio field names
    assert "pd=potentially_blocked" in line
    assert "src_hostname=win10-jd" in line
    assert "src_href=" in line
    assert "src_labels=app:Jumpdesk env:VMware" in line
    assert "fqdn=mobile.events.data.microsoft.com" in line
    assert "pn=onedrive.exe" in line
    assert "un=LAB" in line          # backslash-escaped in CEF
    assert "count=7" in line
    assert "dst_dbi=10135" in line
    assert "dst_dbo=10501" in line
    assert "dir=O" in line
    assert "state=active" in line
    assert "network=Corporate" in line


def test_cef_traffic_flow_icmp_fields():
    """ICMP flows use official type/code field names."""
    from src.siem.formatters.cef import CEFFormatter
    fl = {
        "src": {"ip": "1.2.3.4"}, "dst": {"ip": "5.6.7.8"},
        "service": {"proto": 1, "icmp_type": 8, "icmp_code": 0},
        "policy_decision": "allowed",
        "first_detected": "2026-05-13T10:00:00Z",
    }
    line = CEFFormatter().format_flow(fl)
    assert "proto=icmp" in line
    assert "type=8" in line
    assert "code=0" in line


def test_cef_traffic_flow_proto_number_converted():
    """proto integer 17 → udp in CEF proto field."""
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


def test_cef_escapes_special_characters():
    from src.siem.formatters.cef import _cef_escape
    assert _cef_escape("a=b") == r"a\=b"
    assert _cef_escape("a|b") == r"a\|b"
    assert _cef_escape("a\\b") == r"a\\b"
