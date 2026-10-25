"""The one async traffic-query lifecycle: submit, poll, optional draft recompute, download, delete."""
import gzip
import json
import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
import responses

from illumio_ops.pce import async_query as aq
from illumio_ops.pce.async_query import (
    PceQueryError,
    run_traffic_query,
    traffic_payload,
)

from .conftest import BASE

SUBMIT = f"{BASE}/api/v2/orgs/1/traffic_flows/async_queries"
HREF = "/orgs/1/traffic_flows/async_queries/q-1"
Q = f"{BASE}/api/v2{HREF}"
T0 = datetime(2026, 10, 24, 0, 0, 0, 123456, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    waits = []
    monkeypatch.setattr(aq, "_sleep", waits.append)
    return waits


def _payload(max_results=100):
    return traffic_payload(T0, T0 + timedelta(minutes=10), max_results=max_results, query_name="t")


def _gz(rows):
    body = "[\n" + ",\n".join(json.dumps(r) for r in rows) + "\n]\n"
    return gzip.compress(body.encode())


def _submit_ok():
    responses.add(responses.POST, SUBMIT, status=202, json={"href": HREF, "status": "queued"})


def _deadline():
    return time.monotonic() + 600


def test_payload_timestamps_have_z_and_no_microseconds():
    p = traffic_payload(T0.astimezone(timezone(timedelta(hours=8))), T0 + timedelta(hours=1),
                        max_results=10, query_name="q")
    assert p["start_date"] == "2026-10-24T00:00:00Z" and p["end_date"] == "2026-10-24T01:00:00Z"
    assert p["sources"] == {"include": [[]], "exclude": []} and p["services"] == {"include": [], "exclude": []}
    assert p["sources_destinations_query_op"] == "and" and p["max_results"] == 10
    with pytest.raises(ValueError):
        traffic_payload(datetime(2026, 10, 24), T0, max_results=1, query_name="q")


@responses.activate
def test_query_polls_until_completed_with_backoff(client, _no_sleep):
    _submit_ok()
    for _ in range(4):
        responses.add(responses.GET, Q, json={"status": "working"})
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 2, "flows_count": 2})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}, {"a": 2}]))
    responses.add(responses.DELETE, Q, status=204)
    r = run_traffic_query(client, _payload(), deadline=_deadline())
    assert [x["a"] for x in r.rows] == [1, 2] and r.matches_count == 2 and r.capped is False
    assert _no_sleep[:4] == [2.0, 3.0, 4.5, 6.75] and max(_no_sleep) <= 10
    assert responses.calls[-1].request.method == "DELETE"


@pytest.mark.parametrize("state", ["failed", "killed", "cancel_requested", "cancelled", "canceled"])
@responses.activate
def test_query_cancel_states_are_terminal(client, state):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": state})
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=_deadline())
    assert e.value.stage == "failed"


@responses.activate
def test_query_not_found_while_polling_is_pending_until_deadline(client):
    _submit_ok()
    responses.add(responses.GET, Q, status=404)
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=time.monotonic() + 0.05)
    assert e.value.stage == "timeout"


@responses.activate
def test_submit_rejected_raises(client):
    responses.add(responses.POST, SUBMIT, status=406, json=[{"token": "invalid"}])
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=_deadline())
    assert (e.value.stage, e.value.status) == ("submit", 406)


@responses.activate
def test_partial_download_is_not_success(client, _no_sleep):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 5, "flows_count": 5})
    responses.add(responses.GET, f"{Q}/download", body=_gz([]))
    responses.add(responses.GET, f"{Q}/download", body=_gz([]))
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=_deadline())
    assert e.value.stage == "download" and 3.0 in _no_sleep


@responses.activate
def test_download_retry_succeeds_second_time(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 1, "flows_count": 1})
    responses.add(responses.GET, f"{Q}/download", body=_gz([]))
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}]))
    responses.add(responses.DELETE, Q, status=204)
    assert len(run_traffic_query(client, _payload(), deadline=_deadline()).rows) == 1


@responses.activate
def test_download_short_of_flows_count_is_retried_then_fails(client, _no_sleep):
    # Measured on lab: the result file always holds flows_count rows (matches_count can be larger).
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 5, "flows_count": 5})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}]))
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}]))
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=_deadline())
    assert e.value.stage == "download" and 3.0 in _no_sleep


@responses.activate
def test_download_short_once_then_whole_succeeds(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 9, "flows_count": 2})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}]))
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}, {"a": 2}]))
    responses.add(responses.DELETE, Q, status=204)
    assert len(run_traffic_query(client, _payload(), deadline=_deadline()).rows) == 2


@responses.activate
def test_truncated_gzip_download_is_a_download_failure(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 2, "flows_count": 2})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}, {"a": 2}])[:-8])
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=_deadline())
    assert e.value.stage == "download"


@responses.activate
def test_true_zero_matches_is_success(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 0, "flows_count": 0})
    responses.add(responses.GET, f"{Q}/download", body=_gz([]))
    responses.add(responses.DELETE, Q, status=204)
    assert run_traffic_query(client, _payload(), deadline=_deadline()).rows == []


@responses.activate
def test_plain_text_download_is_parsed(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 1})
    responses.add(responses.GET, f"{Q}/download", body=json.dumps([{"a": 7}]))
    responses.add(responses.DELETE, Q, status=204)
    assert run_traffic_query(client, _payload(), deadline=_deadline()).rows == [{"a": 7}]


@responses.activate
def test_compute_draft_runs_update_rules_and_waits(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 1, "rules": None})
    responses.add(responses.PUT, f"{Q}/update_rules", status=202)
    responses.add(responses.GET, Q, json={"status": "working", "rules": "working"})
    responses.add(responses.GET, Q, json={"status": "completed", "rules": "completed", "matches_count": 1})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"draft_policy_decision": "blocked_by_boundary"}]))
    responses.add(responses.DELETE, Q, status=204)
    r = run_traffic_query(client, _payload(), deadline=_deadline(), compute_draft=True)
    assert r.rows[0]["draft_policy_decision"] == "blocked_by_boundary"
    methods = [c.request.method for c in responses.calls]
    assert methods.index("PUT") < methods.index("GET", methods.index("PUT"))


@responses.activate
def test_update_rules_failure_raises(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 1})
    responses.add(responses.PUT, f"{Q}/update_rules", status=202)
    responses.add(responses.GET, Q, json={"status": "completed", "rules": "failed"})
    with pytest.raises(PceQueryError) as e:
        run_traffic_query(client, _payload(), deadline=_deadline(), compute_draft=True)
    assert e.value.stage == "update_rules"


@responses.activate
def test_delete_after_failure_does_not_fail_result(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 1})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": 1}]))
    responses.add(responses.DELETE, Q, status=500)
    assert len(run_traffic_query(client, _payload(), deadline=_deadline()).rows) == 1


@responses.activate
def test_capped_when_rows_reach_max_results(client):
    _submit_ok()
    responses.add(responses.GET, Q, json={"status": "completed", "matches_count": 9})
    responses.add(responses.GET, f"{Q}/download", body=_gz([{"a": i} for i in range(3)]))
    responses.add(responses.DELETE, Q, status=204)
    assert run_traffic_query(client, _payload(max_results=3), deadline=_deadline()).capped is True
