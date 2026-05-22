"""T2.9 / M-9: SMTP timeout + context-manager + exception triage."""
import smtplib
import socket
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_plugin():
    """Return a MailAlertPlugin wired to a minimal config_manager mock."""
    from src.alerts.plugins import MailAlertPlugin

    cm = MagicMock()
    cm.config = {
        "smtp": {"host": "smtp.example.com", "port": 587, "user": "u", "password": "p",
                 "enable_tls": False, "enable_auth": True},
        "email": {"sender": "from@x.com", "recipients": ["to@y.com"]},
        "alerts": {},
    }
    return MailAlertPlugin(cm)


def _make_reporter_mock():
    """Return a minimal reporter mock whose methods MailAlertPlugin.send() needs."""
    reporter = MagicMock()
    reporter._build_mail_html.return_value = "<p>body</p>"
    reporter._build_mail_plain.return_value = "body"
    return reporter


# ---------------------------------------------------------------------------
# Test 1 — timeout= is passed to smtplib.SMTP
# ---------------------------------------------------------------------------

def test_smtp_call_uses_timeout():
    """smtplib.SMTP() in MailAlertPlugin.send() must pass timeout=."""
    captured = {}

    class MockSMTP:
        def __init__(self, host, port, timeout=None, **kw):
            captured["host"] = host
            captured["port"] = port
            captured["timeout"] = timeout

        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **kw): pass
        def login(self, *a): pass
        def sendmail(self, *a, **kw): pass
        def quit(self): pass

    plugin = _make_plugin()
    reporter = _make_reporter_mock()

    with patch("smtplib.SMTP", MockSMTP):
        plugin.send(reporter, "test subject")

    assert captured.get("timeout") is not None, "smtplib.SMTP must pass timeout="
    assert captured["timeout"] >= 10, f"timeout should be >=10s, got {captured['timeout']}"


# ---------------------------------------------------------------------------
# Test 2 — SMTPAuthenticationError is caught distinctly (config bug)
# ---------------------------------------------------------------------------

def test_smtp_auth_error_returns_failed_not_raises():
    """SMTPAuthenticationError must be caught distinctly and not bubble up."""

    class MockSMTPAuthFail:
        def __init__(self, host, port, timeout=None, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def ehlo(self): pass
        def starttls(self, **kw): pass
        def login(self, *a):
            raise smtplib.SMTPAuthenticationError(535, b"Authentication failed")
        def sendmail(self, *a, **kw): pass
        def quit(self): pass

    plugin = _make_plugin()
    reporter = _make_reporter_mock()

    with patch("smtplib.SMTP", MockSMTPAuthFail):
        result = plugin.send(reporter, "subject")

    # Must not raise; must signal failure
    assert isinstance(result, dict), "send() must return a dict"
    assert result.get("status") != "success", "auth failure must not report success"


# ---------------------------------------------------------------------------
# Test 3 — socket.timeout returns quickly, does not hang
# ---------------------------------------------------------------------------

def test_smtp_timeout_returns_fast_not_hang():
    """socket.timeout during SMTP connection must return promptly, not hang."""

    class MockSMTPTimeout:
        def __init__(self, host, port, timeout=None, **kw):
            raise socket.timeout("simulated connect timeout")
        def __enter__(self): return self
        def __exit__(self, *a): return False

    plugin = _make_plugin()
    reporter = _make_reporter_mock()

    with patch("smtplib.SMTP", MockSMTPTimeout):
        start = time.monotonic()
        result = plugin.send(reporter, "subject")
        elapsed = time.monotonic() - start

    assert elapsed < 5, f"plugin should return fast on timeout, took {elapsed:.2f}s"
    assert isinstance(result, dict)
    assert result.get("status") != "success"
