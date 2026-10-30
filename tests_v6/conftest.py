"""Shared fixtures for the v6 test suite."""
import pytest


@pytest.fixture(autouse=True)
def _short_flowdb_reset_wait(monkeypatch):
    """A reset waits for open flow-store connections (120 s in service); a test that resets with one
    still open on its own thread fails in seconds instead of hanging."""
    from illumio_ops.store.flowdb import db as flowdb
    monkeypatch.setattr(flowdb, "RESET_WAIT_SECONDS", 5.0)


def pytest_configure(config):
    config.addinivalue_line("markers", "real_rhc: use the real Rule Hit Count status check (no stub)")


@pytest.fixture(autouse=True)
def _rhc_status_stub(request, monkeypatch):
    """The report catalog asks the PCE whether Rule Hit Count is on; tests have no PCE, so it reads as on unless a
    test says otherwise (monkeypatching rhc.cached_status) or is marked real_rhc."""
    if request.node.get_closest_marker("real_rhc"):
        return
    from illumio_ops.domain.values import RhcState
    from illumio_ops.services import rhc
    monkeypatch.setattr(rhc, "cached_status", lambda ctx: rhc.RhcStatus(
        state=RhcState.ENABLED, pce_report=True, ven_scopes=True, reason_key=None, detail=None, write_key=True,
        saas=False))
