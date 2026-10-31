import pytest

from illumio_ops.pce.client import PceClient
from illumio_ops.settings.schema import PceSettings

BASE = "https://pce.example.com:8443"


def pce_settings(**kw):
    base = {"url": BASE, "org_id": "1", "api_key": "test-key", "api_secret": "test-secret",
            "deployment_type": "on_prem", "console_url": None, "verify_tls": True,
            "events_timeout_seconds": None}
    return PceSettings(**(base | kw))


@pytest.fixture
def client():
    c = PceClient(pce_settings())
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch):
    """Connection errors are retried with backoff 0/2/4 s (5.x behaviour); tests skip the waiting."""
    from urllib3.util.retry import Retry

    monkeypatch.setattr(Retry, "get_backoff_time", lambda self: 0.0)
