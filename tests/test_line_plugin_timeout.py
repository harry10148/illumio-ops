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

    # 2026-07-24 審查 B2：冷卻是暫時不可用 → skipped（failed 會消耗 DLQ 額度）
    assert result["status"] == "skipped", "Cooldown should make send return skipped"
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


def test_line_cooldown_resets_counter_when_expired(monkeypatch):
    """After cooldown expires, a single failure should NOT immediately re-trigger cooldown.

    Without the fix: _consecutive_failures stays at 3 after expiry, so the very
    next failure sets _cooldown_until again (3 >= 3).  With the fix: the counter
    is reset to 0 on cooldown expiry, so one failure only brings it to 1.
    """
    plugin = _make_line_plugin()
    reporter = _make_reporter()

    # Simulate state after 3 failures + 300 s cooldown that has now expired
    plugin._consecutive_failures = 3
    plugin._cooldown_until = 1000.0  # past timestamp

    fake_now = [2000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    # Send one failing request after cooldown expiry
    with patch("urllib.request.urlopen", side_effect=socket.timeout("simulated")):
        plugin.send(reporter, "subject")

    # The counter should have been reset before the failure was counted,
    # so after one failure it should be 1 (not 3+1=4 clamped to 3).
    assert plugin._consecutive_failures == 1, (
        f"After cooldown expiry, one failure should give counter=1, got {plugin._consecutive_failures}"
    )
    # And cooldown must NOT be re-triggered by a single failure
    assert plugin._cooldown_until <= fake_now[0], (
        "A single failure after cooldown expiry must not immediately re-trigger cooldown"
    )


def test_line_plugin_instance_reused_across_dispatch_cycles():
    """The cooldown counters only work if the SAME plugin instance survives
    across dispatches. The daemon builds a fresh Reporter every monitor cycle
    (scheduler/jobs.run_monitor_cycle) but reuses one long-lived ConfigManager,
    so Reporter must cache the plugin on cm — otherwise the 3-strike cooldown
    resets every dispatch and never engages.
    """
    from src.reporter import Reporter

    cm = MagicMock(spec=ConfigManager)
    cm.config = {
        "alerts": {"line_channel_access_token": "T", "line_target_id": "U"},
        "settings": {"language": "en"},
    }
    # Two independent Reporters sharing one ConfigManager (== two dispatch cycles)
    p1 = Reporter(cm)._get_output_plugin("line")
    p2 = Reporter(cm)._get_output_plugin("line")
    assert p1 is not None
    assert p1 is p2, "Reporter must reuse the cached plugin instance across cycles"


def test_line_cooldown_log_throttled(monkeypatch, capsys):
    """During cooldown, log should be emitted at most once per 60 seconds."""
    plugin = _make_line_plugin()
    reporter = _make_reporter()

    fake_now = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: fake_now[0])

    # Force cooldown active: expires at 1300 (300s from now)
    plugin._cooldown_until = 1300.0
    plugin._consecutive_failures = 3
    plugin._last_cooldown_log_at = 0.0  # never logged

    # First call: should log
    plugin.send(reporter, "s")
    captured1 = capsys.readouterr().out

    # Second call 10s later: should NOT log again
    fake_now[0] = 1010.0
    plugin.send(reporter, "s")
    captured2 = capsys.readouterr().out

    # Third call 61s after first: SHOULD log again
    fake_now[0] = 1071.0
    plugin.send(reporter, "s")
    captured3 = capsys.readouterr().out

    assert "cooldown" in captured1.lower(), "first cooldown call should log"
    assert "cooldown" not in captured2.lower(), "second call within 60s should NOT log"
    assert "cooldown" in captured3.lower(), "third call after 60s should log again"
