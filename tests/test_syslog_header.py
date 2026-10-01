import re


def test_rfc5424_header_format():
    from src.siem.formatters.syslog_header import wrap_rfc5424
    result = wrap_rfc5424("test payload", hostname="myhost", app_name="myapp")
    # Should match: <PRI>1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID SD MSG
    assert re.match(r"^<\d+>1 \d{4}-\d{2}-\d{2}T", result)
    assert "myhost" in result
    assert "myapp" in result
    assert "test payload" in result


def test_rfc5424_pri_calculation():
    from src.siem.formatters.syslog_header import wrap_rfc5424
    # facility=1 (user), severity=6 (info) → PRI = 1*8+6 = 14
    result = wrap_rfc5424("payload", facility=1, severity=6)
    assert result.startswith("<14>")


def test_rfc5424_sd_param_escape():
    from src.siem.formatters.syslog_header import _escape_sd_param
    assert _escape_sd_param('a"b') == r'a\"b'
    assert _escape_sd_param("a]b") == r"a\]b"
    assert _escape_sd_param("a\\b") == r"a\\b"


def test_rfc5424_uses_record_time_not_send_time():
    """積壓或 DLQ replay 時，header 必須是事件發生時間而非送出時間。"""
    from datetime import datetime, timezone
    from src.siem.formatters.syslog_header import wrap_rfc5424
    ts = datetime(2026, 9, 11, 3, 4, 5, 678000, tzinfo=timezone.utc)
    result = wrap_rfc5424("payload", timestamp=ts)
    assert " 2026-09-11T03:04:05.678Z " in result


def test_syslog_wrapped_event_and_flow_carry_record_time():
    from src.siem.formatters.syslog_wrapped import SyslogWrappedFormatter
    from src.siem.formatters.normalized_json import NormalizedJSONFormatter
    fmt = SyslogWrappedFormatter(NormalizedJSONFormatter())
    ev = fmt.format_event({"event_type": "user.sign_in", "severity": "info",
                           "timestamp": "2026-09-11T03:04:05.123Z"})
    assert " 2026-09-11T03:04:05.123Z " in ev
    fl = fmt.format_flow({"src": {"ip": "10.0.0.1"}, "dst": {"ip": "10.0.0.2"},
                          "timestamp_range": {"first_detected": "2026-09-10T00:00:00Z",
                                              "last_detected": "2026-09-11T01:02:03Z"}})
    assert " 2026-09-11T01:02:03.000Z " in fl


def test_record_time_parsing_edge_cases():
    from src.siem.formatters.syslog_header import parse_record_time
    assert parse_record_time(None) is None
    assert parse_record_time("not-a-date") is None
    naive = parse_record_time("2026-09-11T03:04:05")
    assert naive is not None and naive.utcoffset().total_seconds() == 0
    assert parse_record_time("2026-09-11T11:04:05+08:00").hour == 3
