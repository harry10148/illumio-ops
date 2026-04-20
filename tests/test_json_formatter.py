import json


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
