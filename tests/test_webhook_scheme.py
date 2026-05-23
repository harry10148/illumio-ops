import pytest
from pydantic import ValidationError


def test_webhook_rejects_http():
    """http:// webhook URLs must be rejected in favor of https://"""
    from src.config_models import AlertsSettings
    with pytest.raises((ValidationError, ValueError), match="https"):
        AlertsSettings(webhook_url="http://example.com/hook")


def test_webhook_accepts_https():
    from src.config_models import AlertsSettings
    cfg = AlertsSettings(webhook_url="https://example.com/hook")
    assert cfg.webhook_url == "https://example.com/hook"


def test_webhook_accepts_empty():
    """Empty webhook (disabled) must be allowed."""
    from src.config_models import AlertsSettings
    cfg = AlertsSettings(webhook_url="")
    assert cfg.webhook_url == ""


def test_webhook_rejects_other_schemes():
    """ftp://, file://, etc. should be rejected."""
    from src.config_models import AlertsSettings
    for bad in ["ftp://x/y", "file:///etc/passwd", "://no-scheme"]:
        with pytest.raises((ValidationError, ValueError)):
            AlertsSettings(webhook_url=bad)
