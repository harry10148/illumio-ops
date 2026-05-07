"""Test runbook inline link rendering in alert email body."""
import pytest
from unittest.mock import MagicMock
from src.reporter import Reporter


def test_render_runbook_link_with_url():
    html = Reporter._render_runbook_link("https://wiki/runbooks/disk-full")
    assert "https://wiki/runbooks/disk-full" in html
    assert 'href="https://wiki/runbooks/disk-full"' in html
    assert 'Runbook' in html


def test_render_runbook_link_empty_when_no_url():
    assert Reporter._render_runbook_link(None) == ''
    assert Reporter._render_runbook_link('') == ''


def test_render_runbook_link_html_escaped():
    """Quotes/HTML in URL must be escaped in the href."""
    html = Reporter._render_runbook_link('https://x/r?"><script>')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html or '&quot;' in html


def test_alert_body_renders_runbook_link_when_present():
    """Integration: alert with runbook_url should produce inline anchor in body."""
    cm = MagicMock()
    cm.config = {
        "email": {"sender": "x@x", "recipients": ["a@x"]},
        "alerts": {"active": ["mail"]},
    }
    r = Reporter(cm)
    r.health_alerts = [{
        "summary": "disk 95%",
        "severity": "warning",
        "status": "alarm",
        "details": "disk full",
        "time": "2026-05-07",
        "runbook_url": "https://wiki/runbooks/disk-full",
    }]
    html = r._build_mail_html("subject")
    assert "https://wiki/runbooks/disk-full" in html
    assert 'href="https://wiki/runbooks/disk-full"' in html


def test_alert_body_omits_runbook_link_when_absent():
    """Issues without runbook_url should NOT produce a runbook URL anywhere."""
    cm = MagicMock()
    cm.config = {
        "email": {"sender": "x@x", "recipients": ["a@x"]},
        "alerts": {"active": ["mail"]},
    }
    r = Reporter(cm)
    r.health_alerts = [{
        "summary": "x",
        "severity": "warning",
        "status": "alarm",
        "details": "x",
        "time": "2026-05-07",
    }]
    html = r._build_mail_html("subject")
    assert "/runbooks/" not in html
    assert "runbook_url" not in html
