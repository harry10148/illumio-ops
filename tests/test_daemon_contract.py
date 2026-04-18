"""Freeze daemon loop behavior before migrating to APScheduler."""
import inspect
import pytest
from unittest.mock import MagicMock, patch


def test_run_daemon_loop_callable():
    from src.main import run_daemon_loop
    assert callable(run_daemon_loop)


def test_daemon_accepts_interval_minutes():
    """run_daemon_loop(interval_minutes: int) — signature stable."""
    from src.main import run_daemon_loop
    sig = inspect.signature(run_daemon_loop)
    assert "interval_minutes" in sig.parameters
