"""Tests for production-profile TLS-verify guards (H-6 + M-6).

Audit reference: docs/security-audit-2026-05-22.md §3.2 H-6 + §3.3 M-6
"""
import pytest
from pydantic import ValidationError

from src.config_models import ApiSettings, SiemDestinationSettings


# ---------------------------------------------------------------------------
# ApiSettings.verify_ssl guard
# ---------------------------------------------------------------------------

class TestApiSettingsVerifySslGuard:
    def test_default_profile_is_production(self):
        """Default profile should be 'production' (fail-safe default)."""
        cfg = ApiSettings(url="https://pce.example.com:8443")
        assert cfg.profile == "production"

    def test_production_profile_rejects_verify_ssl_false(self):
        """production profile + verify_ssl=False → ValidationError."""
        with pytest.raises(ValidationError, match="verify_ssl|production"):
            ApiSettings(url="https://pce.example.com:8443", verify_ssl=False)

    def test_explicit_dev_profile_allows_verify_ssl_false(self):
        """dev profile permits verify_ssl=False (intentional lab config)."""
        cfg = ApiSettings(url="https://pce.lab.local:8443", verify_ssl=False, profile="dev")
        assert cfg.verify_ssl is False
        assert cfg.profile == "dev"

    def test_production_profile_allows_verify_ssl_true(self):
        """production profile + verify_ssl=True is always valid."""
        cfg = ApiSettings(url="https://pce.example.com:8443", verify_ssl=True, profile="production")
        assert cfg.verify_ssl is True

    def test_dev_profile_allows_verify_ssl_true(self):
        """dev profile + verify_ssl=True is also valid."""
        cfg = ApiSettings(url="https://pce.example.com:8443", verify_ssl=True, profile="dev")
        assert cfg.verify_ssl is True

    def test_invalid_profile_rejected(self):
        """Only 'production' and 'dev' are valid profile values."""
        with pytest.raises(ValidationError):
            ApiSettings(url="https://pce.example.com:8443", profile="staging")


# ---------------------------------------------------------------------------
# SiemDestinationSettings.tls_verify guard
# ---------------------------------------------------------------------------

SIEM_REQUIRED = {"name": "siem-test", "host": "siem.example.com"}


class TestSiemDestinationSettingsTlsVerifyGuard:
    def test_default_profile_is_production(self):
        cfg = SiemDestinationSettings(**SIEM_REQUIRED)
        assert cfg.profile == "production"

    def test_production_profile_rejects_tls_verify_false(self):
        with pytest.raises(ValidationError, match="tls_verify|production"):
            SiemDestinationSettings(**SIEM_REQUIRED, tls_verify=False)

    def test_explicit_dev_profile_allows_tls_verify_false(self):
        cfg = SiemDestinationSettings(**SIEM_REQUIRED, tls_verify=False, profile="dev")
        assert cfg.tls_verify is False
        assert cfg.profile == "dev"

    def test_production_profile_allows_tls_verify_true(self):
        cfg = SiemDestinationSettings(**SIEM_REQUIRED, tls_verify=True, profile="production")
        assert cfg.tls_verify is True

    def test_invalid_profile_rejected(self):
        with pytest.raises(ValidationError):
            SiemDestinationSettings(**SIEM_REQUIRED, profile="staging")
