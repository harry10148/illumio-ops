"""Phase 2: TLS default-enable and hardening tests."""
import ssl
import sys
import os

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def _fresh_config():
    """Return a ConfigManager loaded with only built-in defaults (no config.json)."""
    from unittest.mock import patch
    from src.config import ConfigManager
    # Prevent loading any real config.json from disk
    with patch.object(ConfigManager, "load", lambda self: None):
        cm = ConfigManager()
    return cm


def test_default_tls_config_enabled():
    """tls.enabled must default to True so new deployments use HTTPS out of the box."""
    from src.config import _DEFAULT_CONFIG
    tls = _DEFAULT_CONFIG["web_gui"]["tls"]
    assert tls["enabled"] is True


def test_default_validity_days_397():
    """tls.validity_days must default to 397 (browser-accepted maximum)."""
    from src.config import _DEFAULT_CONFIG
    tls = _DEFAULT_CONFIG["web_gui"]["tls"]
    assert tls["validity_days"] == 397


def test_default_key_algorithm_ecdsa():
    """tls.key_algorithm must default to 'ecdsa-p256'."""
    from src.config import _DEFAULT_CONFIG
    tls = _DEFAULT_CONFIG["web_gui"]["tls"]
    assert tls["key_algorithm"] == "ecdsa-p256"


def test_ssl_context_min_tls12():
    """_build_ssl_context() must produce a context with TLS 1.2 as the minimum version."""
    from src.gui import _build_ssl_context
    ctx = _build_ssl_context({"min_version": "TLSv1.2", "ciphers": None})
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
