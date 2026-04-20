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
