"""TelegramAlertPlugin + digest template tests."""
from src.alerts import render_alert_template


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
