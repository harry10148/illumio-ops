"""Shared fixtures for the v6 test suite."""
import pytest


@pytest.fixture(autouse=True)
def _short_flowdb_reset_wait(monkeypatch):
    """A reset waits for open flow-store connections (120 s in service); a test that resets with one
    still open on its own thread fails in seconds instead of hanging."""
    from illumio_ops.store.flowdb import db as flowdb
    monkeypatch.setattr(flowdb, "RESET_WAIT_SECONDS", 5.0)
