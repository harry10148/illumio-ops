"""Track D acceptance — verify §3.4.2 C.6 (8/8) + §3.4.3 C.7 (4/4) on a
fully-built alert email."""
from email.parser import Parser
from email import policy
from unittest.mock import MagicMock, patch

import pytest

from src.reporter import Reporter, SIGNAL_HEX


@pytest.fixture
def reporter_with_full_alerts():
    cm = MagicMock()
    cm.config = {
        "email": {"sender": "ops@x", "recipients": ["a@x"]},
        "smtp": {"host": "localhost", "port": 25},
        "alerts": {"active": ["mail"]},
        "web_gui": {"public_url": "https://gui.example"},
    }
    r = Reporter(cm)
    r.health_alerts = [{
        "summary": "disk 95%",
        "severity": "warning",
        "status": "alarm",
        "details": "disk full",
        "time": "2026-05-07",
        "runbook_url": "https://runbooks/disk",
    }]
    r.event_alerts = [{
        "summary": "VEN offline",
        "severity": "critical",
        "rule": "VEN heartbeat lost",
        "desc": "VEN offline > 30min",
        "source": "10.0.0.5",
        "time": "2026-05-07T10:00",
        "count": 1,
        "runbook_url": "https://runbooks/ven",
    }]
    r.traffic_alerts = [{
        "rule": "spike",
        "severity": "warning",
        "count": 100,
        "criteria": "5min window",
        "details": "10.0.0.1 -> 10.0.0.2",
    }]
    r.metric_alerts = [{
        "rule": "latency p95 high",
        "severity": "info",
        "count": 1,
        "criteria": "p95 > 200ms",
        "details": "service-x",
    }]
    return r


def _send_and_capture(reporter):
    """Send via SMTP, capturing the raw message string. Patches the SMTP class
    in src.alerts.plugins (where the plugin imports it)."""
    captured = {}
    class FakeSMTP:
        def __init__(self, *args, **kwargs): pass
        def ehlo(self): pass
        def starttls(self, context=None): pass
        def login(self, u, p): pass
        def sendmail(self, sender, recipients, raw):
            captured["raw"] = raw
        def quit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    with patch("src.alerts.plugins.smtplib.SMTP", FakeSMTP):
        reporter.send_alerts()
    return captured.get("raw", "")


def _extract_html(raw_msg: str) -> str:
    """Extract the text/html part body from a raw multipart message."""
    msg = Parser(policy=policy.default).parsestr(raw_msg)
    for part in msg.walk():
        if part.get_content_type() == 'text/html':
            return part.get_content()
    return ''


def _msg_types(raw_msg: str) -> list:
    msg = Parser(policy=policy.default).parsestr(raw_msg)
    return [p.get_content_type() for p in msg.walk()]


# §3.4.2 C.6 — Cross-client compatibility (8/8)

def test_c6_1_table_layout(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    assert '<table' in html
    assert 'display:flex' not in html
    assert 'display:grid' not in html


def test_c6_2_inline_css_only(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    # No <style> blocks (case-insensitive)
    assert '<style' not in html.lower()


def test_c6_3_no_image_or_alt_present(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    if '<img' in html.lower():
        assert ' alt=' in html.lower()


def test_c6_4_no_webfont_reference(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    # The mail_wrapper currently uses system fonts (no webfont).
    # The deeper template (Track A finalize) uses Montserrat as fallback inside
    # a font-family stack. Accept that as long as there's no @font-face nor
    # remote font reference.
    assert '@font-face' not in html
    assert 'fonts.googleapis' not in html


def test_c6_5_no_flex_grid_in_layout(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    assert 'display:flex' not in html
    assert 'display:grid' not in html


def test_c6_6_bulletproof_cta_with_vml(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    assert '<!--[if mso]>' in html
    assert 'v:roundrect' in html.lower()


def test_c6_7_color_scheme_meta(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    assert 'color-scheme' in html


def test_c6_8_multipart_alternative_with_plaintext(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    types = _msg_types(raw)
    assert 'text/plain' in types
    assert 'text/html' in types


# §3.4.3 C.7 — Actionability (4/4)

def test_c7_1_subject_has_severity_prefix(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    msg = Parser(policy=policy.default).parsestr(raw)
    subject = msg['Subject'] or ''
    sev_words = ('CRITICAL', 'CRIT', 'HIGH', 'WARNING', 'WARN', 'INFO')
    assert any(w in subject.upper() for w in sev_words), \
        f"Subject lacks severity word: {subject!r}"


def test_c7_2_preheader_present(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    import re
    m = re.search(r'<div[^>]*display\s*:\s*none[^>]*>([^<]*)</div>', html)
    assert m, "preheader hidden div not found"
    text = m.group(1).strip()
    assert text, "preheader empty"
    assert 5 <= len(text) <= 200, f"preheader length {len(text)} out of band"


def test_c7_3_cta_in_all_four_sections(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    for hint in ('tab=health', 'tab=events', '/traffic', 'tab=metrics'):
        assert hint in html, f"CTA hint {hint!r} missing"


def test_c7_4_severity_badge_and_runbook_link(reporter_with_full_alerts):
    raw = _send_and_capture(reporter_with_full_alerts)
    html = _extract_html(raw)
    # Severity badge color present (from Track D Task 3)
    assert (SIGNAL_HEX['danger'] in html
            or SIGNAL_HEX['warning'] in html
            or SIGNAL_HEX['info'] in html)
    # Runbook link for at least one issue carrying runbook_url
    assert 'runbooks/disk' in html or 'runbooks/ven' in html
