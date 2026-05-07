"""Test that reporter email builders produce multipart/alternative bodies
with both text/plain and text/html parts."""
from email.parser import Parser
from email import policy
import pytest
from unittest.mock import MagicMock, patch

from src.reporter import Reporter


def _parse_msg_string(msg_string: str):
    return Parser(policy=policy.default).parsestr(msg_string)


def test_alert_email_body_is_multipart_alternative_with_text_and_html():
    cm = MagicMock()
    cm.config = {
        "email": {"sender": "ops@x", "recipients": ["a@x"]},
        "smtp": {"host": "localhost", "port": 25},
        "alerts": {"active": ["mail"]},
    }
    r = Reporter(cm)
    r.health_alerts = [{"summary": "disk 95%", "severity": "warning"}]

    captured = {}
    class FakeSMTP:
        def __init__(self, host, port, *args, **kwargs): pass
        def ehlo(self): pass
        def starttls(self, context=None): pass
        def login(self, u, p): pass
        def sendmail(self, sender, recipients, raw):
            captured["raw"] = raw
        def quit(self): pass

    # MailAlertPlugin imports smtplib at module level; patch there
    with patch("src.alerts.plugins.smtplib.SMTP", FakeSMTP):
        r.send_alerts(force_test=False)

    assert "raw" in captured, "sendmail was not invoked"
    msg = _parse_msg_string(captured["raw"])
    types = [part.get_content_type() for part in msg.walk()]
    assert "text/plain" in types, f"text/plain part missing; got types={types}"
    assert "text/html" in types, f"text/html part missing; got types={types}"


def test_report_email_body_is_multipart_alternative():
    cm = MagicMock()
    cm.config = {
        "email": {"sender": "ops@x", "recipients": ["a@x"]},
        "smtp": {"host": "localhost", "port": 25},
    }
    r = Reporter(cm)
    captured = {}
    class FakeSMTP:
        def __init__(self, host, port, timeout): pass
        def ehlo(self): pass
        def starttls(self, context=None): pass
        def login(self, u, p): pass
        def sendmail(self, sender, recipients, raw):
            captured["raw"] = raw
        def quit(self): pass

    with patch("smtplib.SMTP", FakeSMTP):
        r.send_report_email("subject", "<html><body>hi there</body></html>")

    assert "raw" in captured
    msg = _parse_msg_string(captured["raw"])
    types = [p.get_content_type() for p in msg.walk()]
    assert "text/plain" in types
    assert "text/html" in types
