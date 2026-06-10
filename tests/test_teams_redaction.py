"""Teams webhook URL is a secret (contains sig= token); it must be redacted (README L-12)."""
from src.alerts.plugins import redact_webhook_url


_URL = ("https://prod-12.westus.logic.azure.com:443/workflows/abc123/"
        "triggers/manual/paths/invoke?api-version=2016-06-01&sig=SUPERSECRETSIG")


def test_redaction_drops_secret_and_path():
    red = redact_webhook_url(_URL)
    assert "SUPERSECRETSIG" not in red
    assert "sig=" not in red
    assert "/workflows/" not in red
    assert "paths/invoke" not in red


def test_redaction_keeps_scheme_and_host():
    red = redact_webhook_url(_URL)
    assert red.startswith("https://")
    assert "prod-12.westus.logic.azure.com" in red


def test_redaction_empty_returns_empty():
    assert redact_webhook_url("") == ""


def test_redaction_handles_garbage():
    # Non-URL input must not raise; just return something secret-free.
    assert "SUPERSECRETSIG" not in redact_webhook_url("not a url SUPERSECRETSIG")
