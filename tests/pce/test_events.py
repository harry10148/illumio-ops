"""Windowed /events reads: explicit [gte, lte] bounds, the 10,000-row cap flag, deployment timeouts."""
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import responses

from illumio_ops.pce import events as ev
from illumio_ops.pce.async_query import PceQueryError
from illumio_ops.pce.events import events_timeout, fetch_events

from .conftest import BASE, pce_settings

URL = f"{BASE}/api/v2/orgs/1/events"
T0 = datetime(2026, 10, 24, 1, 2, 3, 999, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ev, "_sleep", lambda s: None)


@responses.activate
def test_events_capped_flag_and_window_params(client):
    responses.add(responses.GET, URL, json=[{"href": f"/e/{i}"} for i in range(3)])
    page = fetch_events(client, start=T0, end=T0 + timedelta(minutes=5), timeout=30,
                        deadline=time.monotonic() + 60, max_results=3)
    assert page.capped is True and len(page.items) == 3
    q = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert q["timestamp[gte]"] == ["2026-10-24T01:02:03Z"] and q["timestamp[lte]"] == ["2026-10-24T01:07:03Z"]
    assert q["max_results"] == ["3"]


@responses.activate
def test_events_under_cap_not_capped(client):
    responses.add(responses.GET, URL, json=[{"href": "/e/1"}])
    page = fetch_events(client, start=T0, end=T0, timeout=30, deadline=time.monotonic() + 60)
    assert page.capped is False


@responses.activate
def test_events_5xx_retried_within_deadline(client):
    responses.add(responses.GET, URL, status=503)
    responses.add(responses.GET, URL, json=[])
    assert fetch_events(client, start=T0, end=T0, timeout=30, deadline=time.monotonic() + 60).items == []


@responses.activate
def test_events_4xx_raises(client):
    responses.add(responses.GET, URL, status=406, json=[{"token": "invalid_timestamp"}])
    with pytest.raises(PceQueryError) as e:
        fetch_events(client, start=T0, end=T0, timeout=30, deadline=time.monotonic() + 60)
    assert e.value.status == 406


@responses.activate
def test_events_retry_stops_at_deadline(client):
    responses.add(responses.GET, URL, status=503)
    with pytest.raises(PceQueryError):
        fetch_events(client, start=T0, end=T0, timeout=30, deadline=time.monotonic() + 0.01)


def test_events_timeout_defaults_by_deployment():
    assert events_timeout(pce_settings(deployment_type="saas")) == 180
    assert events_timeout(pce_settings(deployment_type="on_prem")) == 30
    assert events_timeout(pce_settings(events_timeout_seconds=90)) == 90
