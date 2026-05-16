"""AlertsSettings schema must accept Telegram bot/chat config."""
from src.config_models import AlertsSettings


def test_alerts_defaults_include_empty_telegram_fields():
    a = AlertsSettings()
    assert a.telegram_bot_token == ""
    assert a.telegram_chat_id == ""
    # Existing defaults unchanged
    assert a.active == ["mail"]
    assert a.line_target_id == ""


def test_alerts_accepts_telegram_values():
    a = AlertsSettings(
        active=["mail", "telegram"],
        telegram_bot_token="123:abc",
        telegram_chat_id="-1001234567890",
    )
    assert "telegram" in a.active
    assert a.telegram_bot_token == "123:abc"
    assert a.telegram_chat_id == "-1001234567890"
