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


def test_cef_audit_event_full_fields():
    """Full PCE API audit event with created_by, action, resource_changes."""
    from src.siem.formatters.cef import CEFFormatter
    ev = {
        "href": "/orgs/1/events/evt-1",
        "uuid": "evt-uuid-1",
        "timestamp": "2026-04-08T12:00:00Z",
        "event_type": "sec_policy.create",
        "severity": "warning",
        "status": "success",
        "pce_fqdn": "pce.example.com",
        "created_by": {"user": {"username": "admin@example.com"}},
        "action": {
            "api_method": "POST",
            "api_endpoint": "/api/v2/orgs/1/sec_policy",
            "src_ip": "10.0.0.5",
            "http_status_code": 201,
        },
        "resource_changes": [{
            "change_type": "create",
            "resource": {"sec_policy": {"name": "policy-1", "href": "/orgs/1/sec_policy/1"}},
        }],
    }
    line = CEFFormatter().format_event(ev)

    assert "CEF:0|Illumio|PCE|" in line
    assert "|sec_policy.create|sec_policy.create|6|" in line   # warning → 6
    assert "externalId=evt-uuid-1" in line
    assert "outcome=success" in line
    assert "suser=admin@example.com" in line
    assert "src=10.0.0.5" in line
    assert "requestMethod=POST" in line
    assert r"request=/api/v2/orgs/1/sec_policy" in line
    assert "cn1=201" in line
    assert "cn1Label=httpStatusCode" in line
    assert "msg=create:sec_policy:policy-1" in line


def test_cef_audit_event_system_actor():
    from src.siem.formatters.cef import CEFFormatter
    ev = {
        "uuid": "sys-1",
        "timestamp": "2026-04-08T12:00:00Z",
        "event_type": "agent.heartbeat",
        "severity": "info",
        "status": "success",
        "created_by": {"system": True},
    }
    line = CEFFormatter().format_event(ev)
    assert "suser=system" in line


def test_cef_audit_event_service_account_actor():
    from src.siem.formatters.cef import CEFFormatter
    ev = {
        "uuid": "sa-1",
        "timestamp": "2026-04-08T12:00:00Z",
        "event_type": "policy.update",
        "severity": "info",
        "status": "success",
        "created_by": {"service_account": {"name": "ci-bot"}},
    }
    line = CEFFormatter().format_event(ev)
    assert "suser=ci-bot" in line


def test_cef_audit_event_uuid_fallback():
    """When pce_event_id absent, fall back to uuid then href."""
    from src.siem.formatters.cef import CEFFormatter
    ev = {
        "href": "/orgs/1/events/fallback",
        "uuid": "raw-uuid",
        "timestamp": "2026-04-08T12:00:00Z",
        "event_type": "user.login",
        "severity": "info",
        "status": "success",
    }
    line = CEFFormatter().format_event(ev)
    assert "externalId=raw-uuid" in line


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
