"""LINE plugin: timeout and channel cooldown tests (audit H-5)."""
import socket
import time
from unittest.mock import MagicMock, patch

import pytest

from src.config import ConfigManager


def _make_line_plugin():
    """Build a LineAlertPlugin with a minimal mock config_manager."""
    from src.alerts.plugins import LineAlertPlugin

    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {
            "line_channel_access_token": "test_token",
            "line_target_id": "test_user_id",
        },
        "settings": {"language": "en"},
    }
    return LineAlertPlugin(cm)


def _make_reporter():
    """Build a minimal mock reporter with _build_line_message."""
    reporter = MagicMock()
    reporter._build_line_message.return_value = "test message"
    return reporter


def test_line_urlopen_has_timeout():
    """LINE plugin must pass timeout= to urlopen to prevent indefinite blocking."""
    plugin = _make_line_plugin()
    reporter = _make_reporter()

    timeout_seen = {"value": None}

    def fake_urlopen(req, *args, **kwargs):
        timeout_seen["value"] = kwargs.get("timeout")
        raise socket.timeout("simulated network hang")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        start = time.monotonic()
        result = plugin.send(reporter, "subject")
        elapsed = time.monotonic() - start

    assert timeout_seen["value"] is not None, "LINE plugin urlopen() must pass timeout="
    assert 5 <= timeout_seen["value"] <= 30, (
        f"timeout should be 5-30 seconds, got {timeout_seen['value']}"
    )
    assert elapsed < 5, (
        f"LINE plugin should not block — returned in {elapsed:.2f}s but timeout was simulated"
    )
    assert result["status"] == "failed"


def test_line_plugin_cooldown_after_failures():
    """After 3 consecutive failures, channel should cool down (skip subsequent sends)."""
    plugin = _make_line_plugin()
    reporter = _make_reporter()

    def always_fail(*a, **kw):
        raise socket.timeout("simulated")

    with patch("urllib.request.urlopen", side_effect=always_fail):
        # First 3 attempts hit the network and fail
        for _ in range(3):
            plugin.send(reporter, "s")

    # 4th attempt: should skip without calling urlopen (cooldown active)
    call_count = {"value": 0}

    def counting_urlopen(*a, **kw):
        call_count["value"] += 1
        raise socket.timeout("should not reach here")

    with patch("urllib.request.urlopen", side_effect=counting_urlopen):
        result = plugin.send(reporter, "s2")

    assert result["status"] == "failed", "Cooldown should make send return failed"
    assert call_count["value"] == 0, (
        f"During cooldown urlopen() should not be called; was called {call_count['value']} times"
    )


def test_line_plugin_cooldown_resets_after_success():
    """Successful send should reset the consecutive failure counter."""
    plugin = _make_line_plugin()
    reporter = _make_reporter()

    def always_fail(*a, **kw):
        raise socket.timeout("simulated")

    # Fail twice (below threshold)
    with patch("urllib.request.urlopen", side_effect=always_fail):
        plugin.send(reporter, "s")
        plugin.send(reporter, "s")

    # Succeed — mock a 200 response
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.status = 200

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = plugin.send(reporter, "success")

    assert result["status"] == "success"
    assert plugin._consecutive_failures == 0, (
        "Success should reset _consecutive_failures to 0"
    )
