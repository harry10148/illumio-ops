"""Test severity badge inline component."""
import pytest
from src.reporter import Reporter, SIGNAL_HEX


def test_severity_badge_critical():
    html = Reporter._render_severity_badge('critical')
    assert SIGNAL_HEX['danger'] in html
    assert 'CRIT' in html.upper()
    assert 'bgcolor=' in html.lower()  # double-write for Outlook


def test_severity_badge_warning():
    html = Reporter._render_severity_badge('warning')
    assert SIGNAL_HEX['warning'] in html
    assert 'WARN' in html.upper()


def test_severity_badge_info():
    html = Reporter._render_severity_badge('info')
    assert SIGNAL_HEX['info'] in html
    assert 'INFO' in html.upper()


def test_severity_badge_unknown_falls_back_to_info():
    html = Reporter._render_severity_badge('mystery')
    assert SIGNAL_HEX['info'] in html


def test_severity_badge_html_escaped():
    """Defensive: a custom severity input should never produce raw HTML."""
    html = Reporter._render_severity_badge('<x>')
    assert '<x>' not in html


def test_health_section_emits_badge_when_alert_has_severity():
    """Integration: a Reporter._build_mail_html with a health_alert carrying
    a severity field should embed _render_severity_badge output in the body."""
    from unittest.mock import MagicMock
    cm = MagicMock()
    cm.config = {
        "email": {"sender": "x@x", "recipients": ["a@x"]},
        "alerts": {"active": ["mail"]},
    }
    r = Reporter(cm)
    r.health_alerts = [{"summary": "disk 95%", "severity": "warning", "time": "2026-05-07", "status": "alarm", "details": "disk full"}]
    html = r._build_mail_html("subject")
    # Badge color present
    assert SIGNAL_HEX['warning'] in html
    # WARN label present
    assert 'WARN' in html.upper()
