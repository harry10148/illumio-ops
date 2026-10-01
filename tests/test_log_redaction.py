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


import pytest as _pytest


@_pytest.mark.parametrize("text,secret", [
    ("hec_token=abcd1234efgh", "abcd1234efgh"),
    ('"hec_token": "abcd-1234-efgh"', "abcd-1234-efgh"),
    ("teams_webhook_url=https://x.webhook.office.com/abc", "x.webhook.office.com"),
    ("telegram_bot_token=123456:ABCDEF", "123456:ABCDEF"),
    ("Authorization: Splunk abcd-1234-secret", "abcd-1234-secret"),
    ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
])
def test_prefixed_secret_fields_and_auth_schemes_are_redacted(text, secret):
    """舊版以 \\b 錨定欄位名稱，hec_token／teams_webhook_url 這類帶前綴的欄位
    不會被遮；Authorization 只認 Bearer，Splunk／Basic 的 token 本體照印。"""
    from src.loguru_config import _redact_secrets_in_text
    out = _redact_secrets_in_text(text)
    assert secret not in out
    assert "[REDACTED]" in out


@_pytest.mark.parametrize("text", ["token_count=5", "tokenizer=abc"])
def test_non_secret_lookalikes_untouched(text):
    from src.loguru_config import _redact_secrets_in_text
    assert _redact_secrets_in_text(text) == text


def test_traceback_does_not_print_local_variables(tmp_path):
    """diagnose=False：例外 traceback 不得印出區域變數的值（例如 hec_token）。"""
    from loguru import logger
    from src.loguru_config import setup_loguru
    log_file = tmp_path / "app.log"
    setup_loguru(str(log_file))
    # 機密值組在別處：traceback 本來就會印出呼叫那一行的原始碼，這裡要驗的是
    # 「區域變數的值」不被印出（loguru diagnose=True 會逐一標出變數值）。
    token = "".join(["SUPER", "SECRET", "VALUE"])
    try:
        def _send(dest_secret):
            raise RuntimeError("boom")
        _send(token)
    except RuntimeError:
        logger.exception("dispatch failed")
    logger.complete()
    content = log_file.read_text(encoding="utf-8")
    assert "dispatch failed" in content
    assert "SUPERSECRETVALUE" not in content
