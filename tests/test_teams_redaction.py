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


def test_redaction_strips_userinfo_credentials():
    # userinfo (user:password@) must NOT survive into the redacted output.
    red = redact_webhook_url(
        "https://user:PASSWORD@prod-12.westus.logic.azure.com:443/workflows/x?sig=S"
    )
    assert "PASSWORD" not in red
    assert "@" not in red
    assert red == "https://prod-12.westus.logic.azure.com:443/..."


def test_redaction_non_http_scheme_is_elided():
    # A parseable-but-unexpected scheme with no host -> bare marker, no leak.
    assert redact_webhook_url("javascript:alert(1)") == "..."


def test_redaction_protocol_relative_is_elided():
    # No scheme -> fail closed, secret must not leak.
    red = redact_webhook_url("//host/path?sig=SUPERSECRETSIG")
    assert "SUPERSECRETSIG" not in red
    assert red == "..."
