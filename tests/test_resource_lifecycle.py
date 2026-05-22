"""Tests for close() + context manager protocol on ApiClient and SplunkHECTransport.

Audit reference: docs/security-audit-2026-05-22.md H-2.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


def _make_cm():
    """Build a minimal ConfigManager-like mock for ApiClient construction."""
    cm = MagicMock()
    cm.config = {
        "api": {
            "url": "https://localhost",
            "org_id": "1",
            "key": "k",
            "secret": "s",
            "verify_ssl": False,
            "profile": "dev",
        }
    }
    return cm


def test_api_client_has_close():
    from src.api_client import ApiClient
    client = ApiClient(_make_cm())
    assert hasattr(client, "close"), "ApiClient must have close()"
    assert hasattr(client, "__enter__") and hasattr(client, "__exit__"), (
        "ApiClient must be a context manager"
    )


def test_api_client_close_releases_session():
    from src.api_client import ApiClient
    client = ApiClient(_make_cm())
    sess = client._session
    assert sess is not None
    client.close()
    # After close, session should be None OR have empty adapters (closed)
    assert client._session is None or len(client._session.adapters) == 0


def test_api_client_close_is_idempotent():
    from src.api_client import ApiClient
    client = ApiClient(_make_cm())
    client.close()
    client.close()  # must not raise


def test_api_client_as_context_manager():
    from src.api_client import ApiClient
    with ApiClient(_make_cm()) as client:
        assert client._session is not None
    # exited; verify session closed
    assert client._session is None or len(client._session.adapters) == 0


def test_api_client_exit_returns_false():
    """__exit__ must not suppress exceptions."""
    from src.api_client import ApiClient
    client = ApiClient(_make_cm())
    result = client.__exit__(None, None, None)
    assert result is False


def test_splunk_hec_transport_close():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    transport = SplunkHECTransport(
        endpoint="https://localhost:8088",
        token="x",
        verify_tls=False,
    )
    assert hasattr(transport, "close"), "SplunkHECTransport must have close()"
    transport.close()  # must not raise


def test_splunk_hec_transport_close_is_idempotent():
    from src.siem.transports.splunk_hec import SplunkHECTransport
    transport = SplunkHECTransport(
        endpoint="https://localhost:8088",
        token="x",
        verify_tls=False,
    )
    transport.close()
    transport.close()  # must not raise


def test_api_client_use_after_close_raises():
    """Methods on a closed ApiClient must raise RuntimeError clearly, not return fake responses."""
    from src.api_client import ApiClient
    client = ApiClient(_make_cm())
    client.close()
    with pytest.raises(RuntimeError, match="closed"):
        client._request("https://localhost/api/v2/orgs/1/labels", "GET")
