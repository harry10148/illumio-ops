"""Collection GETs: the 500-row page limit, and the async (Prefer: respond-async) path above it."""
import time

import pytest
import responses

from illumio_ops.pce import collections as coll
from illumio_ops.pce.collections import PceCollectionIncomplete, get_all

from .conftest import BASE

URL = f"{BASE}/api/v2/orgs/1/workloads"
JOB = "/orgs/1/jobs/0000-job"
RESULT = "/orgs/1/datafiles/0000-data"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(coll, "_sleep", lambda s: None)


def _deadline():
    return time.monotonic() + 60


def _rows(n):
    return [{"href": f"/orgs/1/workloads/{i}"} for i in range(n)]


@responses.activate
def test_collection_under_500_is_complete(client):
    responses.add(responses.GET, URL, json=_rows(20))
    assert len(get_all(client, "/workloads", params={"managed": "true"}, deadline=_deadline())) == 20
    sent = responses.calls[0].request.url
    assert "managed=true" in sent and "max_results=500" in sent
    assert "Prefer" not in responses.calls[0].request.headers


@responses.activate
def test_collection_ignores_x_total_count(client):
    # With a filter the PCE's X-Total-Count is the unfiltered total (5.x, measured on a real PCE).
    responses.add(responses.GET, URL, json=_rows(20), headers={"X-Total-Count": "30"})
    assert len(get_all(client, "/workloads", params={"managed": "true"}, deadline=_deadline())) == 20
    assert len(responses.calls) == 1


@responses.activate
def test_collection_at_500_uses_async_and_returns_all(client):
    responses.add(responses.GET, URL, json=_rows(500))
    responses.add(responses.GET, URL, status=202, headers={"Location": JOB},
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    responses.add(responses.GET, f"{BASE}/api/v2{JOB}", json={"status": "running"}, headers={"Retry-After": "1"})
    responses.add(responses.GET, f"{BASE}/api/v2{JOB}", json={"status": "done", "result": {"href": RESULT}})
    responses.add(responses.GET, f"{BASE}/api/v2{RESULT}", json=_rows(1234))
    assert len(get_all(client, "/workloads", params={"managed": "true"}, deadline=_deadline())) == 1234


@responses.activate
def test_collection_at_500_without_async_raises_incomplete(client):
    responses.add(responses.GET, URL, json=_rows(500))
    responses.add(responses.GET, URL, status=406, json=[{"token": "not_supported"}],
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    with pytest.raises(PceCollectionIncomplete) as e:
        get_all(client, "/workloads", params={"managed": "true"}, deadline=_deadline())
    assert e.value.partial_count == 500 and e.value.path == "/workloads"


@responses.activate
def test_async_job_failed_state_raises(client):
    responses.add(responses.GET, URL, json=_rows(500))
    responses.add(responses.GET, URL, status=202, headers={"Location": JOB},
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    responses.add(responses.GET, f"{BASE}/api/v2{JOB}", json={"status": "failed"})
    with pytest.raises(PceCollectionIncomplete) as e:
        get_all(client, "/workloads", params={}, deadline=_deadline())
    assert "failed" in e.value.reason


@responses.activate
def test_async_job_past_deadline_raises(client):
    responses.add(responses.GET, URL, json=_rows(500))
    responses.add(responses.GET, URL, status=202, headers={"Location": JOB},
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    responses.add(responses.GET, f"{BASE}/api/v2{JOB}", json={"status": "running"})
    with pytest.raises(PceCollectionIncomplete):
        get_all(client, "/workloads", params={}, deadline=time.monotonic() + 0.2)


def test_retry_after_is_clamped():
    assert coll._job_wait("1") == 2 and coll._job_wait("99") == 10 and coll._job_wait(None) == 2
    assert coll._job_wait("nan") == 2


@responses.activate
def test_async_request_does_not_carry_the_page_limit(client):
    # Measured on LAB-PCE: an async collection GET that keeps max_results=500 yields a 500-row
    # result file even when 124,255 rows match. The async request must drop the page limit.
    responses.add(responses.GET, URL, json=_rows(500))
    responses.add(responses.GET, URL, status=202, headers={"Location": JOB},
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    responses.add(responses.GET, f"{BASE}/api/v2{JOB}", json={"status": "done", "result": {"href": RESULT}})
    responses.add(responses.GET, f"{BASE}/api/v2{RESULT}", json=_rows(900))
    get_all(client, "/workloads", params={"managed": "true"}, deadline=_deadline())
    async_url = responses.calls[1].request.url
    assert "managed=true" in async_url and "max_results" not in async_url


@responses.activate
def test_collection_follows_recorded_lab_job_shape(client):
    import json
    from pathlib import Path
    rec = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pce" / "async_collection_job.json").read_text())
    job = rec["accept"]["location"]
    responses.add(responses.GET, URL, json=_rows(500))
    responses.add(responses.GET, URL, status=202, headers={"Location": job, "Retry-After": rec["accept"]["retry_after"]},
                  match=[responses.matchers.header_matcher({"Prefer": "respond-async"})])
    responses.add(responses.GET, f"{BASE}/api/v2{job}", json=rec["job_pending"]["body"],
                  headers=rec["job_pending"]["headers"])
    responses.add(responses.GET, f"{BASE}/api/v2{job}", json=rec["job_done"]["body"])
    responses.add(responses.GET, f"{BASE}/api/v2{rec['job_done']['body']['result']['href']}", json=_rows(777),
                  headers={"X-Total-Count": rec["result"]["x_total_count"]})
    assert len(get_all(client, "/workloads", params={}, deadline=_deadline())) == 777
