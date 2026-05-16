"""TelegramAlertPlugin + digest template tests."""
import html as _html
from unittest.mock import MagicMock

from src.alerts import render_alert_template


def _make_reporter_with_alerts():
    """Build a minimal Reporter with one health alert + one event alert queued."""
    from src.config import ConfigManager
    from src.reporter import Reporter

    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"active": ["telegram"], "telegram_bot_token": "T", "telegram_chat_id": "C"},
        "settings": {"language": "en"},
        "gui_base_url": "",
    }
    r = Reporter(cm)
    r.add_health_alert({
        "rule": "API Health",
        "status": "503",
        "time": "2026-05-16 06:00",
        "details": "PCE unreachable",
    })
    r.event_alerts = []  # default
    r.traffic_alerts = []
    r.metric_alerts = []
    return r


def test_build_telegram_message_includes_subject_and_alert(monkeypatch):
    r = _make_reporter_with_alerts()
    body = r._build_telegram_message("Daily Digest")
    assert "Daily Digest" in body
    assert "API Health" in body
    assert "<b>" in body  # title is bold


def test_build_telegram_message_escapes_html_in_dynamic_fields(monkeypatch):
    r = _make_reporter_with_alerts()
    r.health_alerts[0]["details"] = "<script>alert(1)</script>"
    body = r._build_telegram_message("S")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_build_telegram_message_truncates_above_3500_chars(monkeypatch):
    r = _make_reporter_with_alerts()
    # Stuff in 50 fat health alerts
    for i in range(50):
        r.add_health_alert({
            "rule": f"r{i}",
            "status": "error",
            "time": "t",
            "details": "X" * 200,
        })
    body = r._build_telegram_message("Bulk")
    assert len(body) <= 3500
    # Footer marks truncation
    assert "more" in body.lower() or "…" in body


def test_telegram_digest_template_renders_sections():
    rendered = render_alert_template(
        "telegram_digest.html.tmpl",
        subject="Test Alert",
        generated_at="2026-05-16 14:23 (UTC+8)",
        total_issues=3,
        health_count=1,
        event_count=2,
        traffic_count=0,
        metric_count=0,
        health_section="<b>health item</b>",
        event_section="<b>event item</b>",
        traffic_section="",
        metric_section="",
    )
    # Title from auto-injected alert_tpl_telegram_title
    assert "Illumio" in rendered
    assert "Test Alert" in rendered
    assert "<b>health item</b>" in rendered
    assert "<b>event item</b>" in rendered
    # No literal $placeholder leakage
    assert "$" not in rendered
