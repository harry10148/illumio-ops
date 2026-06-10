"""AlertsSettings must accept a Teams Power Automate workflow webhook URL (https-only)."""
import pytest
from pydantic import ValidationError

from src.config_models import AlertsSettings


def test_teams_default_empty():
    a = AlertsSettings()
    assert a.teams_webhook_url == ""
    # Existing defaults unchanged
    assert a.active == ["mail"]


def test_teams_accepts_https():
    url = "https://prod-12.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?sig=SECRET"
    a = AlertsSettings(teams_webhook_url=url)
    assert a.teams_webhook_url == url


def test_teams_rejects_http():
    with pytest.raises((ValidationError, ValueError), match="teams_webhook_url"):
        AlertsSettings(teams_webhook_url="http://example.com/hook")


def test_teams_accepts_empty():
    assert AlertsSettings(teams_webhook_url="").teams_webhook_url == ""


def test_teams_rejects_non_https_scheme():
    with pytest.raises((ValidationError, ValueError), match="teams_webhook_url"):
        AlertsSettings(teams_webhook_url="ftp://example.com/hook")
