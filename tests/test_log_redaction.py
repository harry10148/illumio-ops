"""Tests for M-14 log redaction: Telegram bot tokens and PCE href identifiers."""
import pytest

from src.loguru_config import _redact_secrets_in_text


def test_telegram_bot_token_redacted():
    """Telegram bot token in URL should be redacted regardless of key:value form."""
    leaky = "Calling https://api.telegram.org/bot1234567890:ABCDEFghijklmnopqrstuvwxyz_-1234567/sendMessage"
    result = _redact_secrets_in_text(leaky)
    assert "ABCDEFghijklmnop" not in result, f"token not redacted: {result}"
    assert "1234567890" not in result, f"chat-id-part not redacted: {result}"


def test_pce_href_redacted():
    leaky = "GET /orgs/1/workloads/abcd-1234-5678-cafe completed"
    result = _redact_secrets_in_text(leaky)
    assert "abcd-1234-5678-cafe" not in result, f"href ID not masked: {result}"
    assert "<HREF>" in result or "/orgs/1/workloads/<" in result or "REDACTED" in result


def test_existing_keyvalue_secret_still_redacted():
    """Regression: existing api_key= redaction still works after changes."""
    leaky = 'api_key=sk-1234567890abcdef'
    result = _redact_secrets_in_text(leaky)
    assert "1234567890abcdef" not in result, f"api_key not redacted: {result}"


def test_non_secret_text_passthrough():
    """Ordinary text without secrets should pass through unchanged."""
    text = "Analysis cycle completed for tenant 'lab-01'"
    assert _redact_secrets_in_text(text) == text
