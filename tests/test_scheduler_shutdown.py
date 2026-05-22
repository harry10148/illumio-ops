import threading
import time
import pytest


def test_background_scheduler_responds_to_shutdown_event():
    """Background thread should exit within 2 seconds of shutdown_event being set."""
    from src.gui import _rs_background_scheduler, _shutdown_event

    # Ensure event is clear before test
    _shutdown_event.clear()

    # Use a mock cm — adapt to actual signature
    from unittest.mock import MagicMock
    cm = MagicMock()
    cm.config = {"web_gui": {"username": "illumio", "password": "$argon2id$dummy"}}

    t = threading.Thread(target=_rs_background_scheduler, args=(cm,), daemon=True)
    t.start()
    time.sleep(0.5)
    assert t.is_alive(), "scheduler thread should still be running"

    _shutdown_event.set()
    t.join(timeout=2.5)

    assert not t.is_alive(), "thread did not exit within 2.5s of shutdown_event being set"

    # Cleanup for subsequent tests
    _shutdown_event.clear()
