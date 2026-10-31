"""SIEM formatter fixes (verified against live Graylog 2026-06-28):
- CEF must omit the `outcome` extension when the event has no status, rather
  than emitting `outcome=None` / `outcome=`.
- The syslog wrapper must use a meaningful RFC5424 hostname for flows (which
  carry no pce_fqdn) instead of the NILVALUE `-`.
"""
from illumio_ops.siem.formatters.cef import CEFFormatter
from illumio_ops.siem.formatters.syslog_wrapped import SyslogWrappedFormatter


def test_cef_event_omits_outcome_when_status_absent():
    line = CEFFormatter().format_event({
        "event_type": "user.pce_session_terminated", "severity": "info",
        "timestamp": "2026-04-19T10:00:00Z", "pce_event_id": "u1"})  # no status key
    assert "outcome=" not in line


def test_cef_event_omits_outcome_when_status_none():
    line = CEFFormatter().format_event({
        "event_type": "x", "severity": "info", "status": None, "pce_event_id": "u1"})
    assert "outcome=None" not in line
    assert "outcome=" not in line


def test_cef_event_keeps_outcome_when_status_present():
    line = CEFFormatter().format_event({
        "event_type": "x", "severity": "info", "status": "success", "pce_event_id": "u1"})
    assert "outcome=success" in line


def _rfc5424_hostname(line: str) -> str:
    # <pri>1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID STRUCTURED-DATA MSG
    return line.split(" ")[2]




def test_syslog_event_uses_pce_fqdn_when_present():
    ev = {"event_type": "user.login", "severity": "info", "status": "success",
          "pce_fqdn": "pce.corp.com", "timestamp": "2026-05-13T10:00:00Z", "uuid": "u1"}
    line = SyslogWrappedFormatter(CEFFormatter()).format_event(ev)
    assert _rfc5424_hostname(line) == "pce.corp.com"
