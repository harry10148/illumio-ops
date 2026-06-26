"""Reporter._build_teams_card builds a Power-Automate Adaptive Card POST body."""
from unittest.mock import MagicMock

from src.config import ConfigManager
from src.reporter import Reporter


def _reporter(gui_base_url=""):
    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"active": ["teams"], "teams_webhook_url": "https://x.logic.azure.com/…"},
        "settings": {"language": "en"},
        # The Teams deep-link base resolves via web_gui.public_url (same as the
        # mail CTAs), NOT the orphan flat 'gui_base_url' key that is set nowhere
        # in production.
        "web_gui": {"public_url": gui_base_url},
    }
    r = Reporter(cm)
    r.add_health_alert({
        "rule": "API Health",
        "status": "503",
        "time": "2026-06-08 06:00",
        "details": "PCE unreachable",
    })
    r.event_alerts = []
    r.traffic_alerts = []
    r.metric_alerts = []
    return r


def test_card_outer_envelope_is_power_automate_shape():
    card = _reporter()._build_teams_card("Daily Digest")
    assert card["type"] == "message"
    att = card["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert att["content"]["type"] == "AdaptiveCard"
    assert att["content"]["version"] == "1.4"


def test_card_contains_subject_and_alert():
    card = _reporter()._build_teams_card("Daily Digest")
    blob = str(card)
    assert "Daily Digest" in blob
    assert "API Health" in blob


def test_card_has_open_in_pce_action_when_base_url_set():
    card = _reporter(gui_base_url="https://pce.example.com:8443")._build_teams_card("S")
    actions = card["attachments"][0]["content"].get("actions", [])
    assert any(a.get("type") == "Action.OpenUrl" for a in actions)


def test_card_omits_actions_without_base_url():
    card = _reporter(gui_base_url="")._build_teams_card("S")
    assert not card["attachments"][0]["content"].get("actions")
