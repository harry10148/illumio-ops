"""Enforcement readiness of one app (P5b-2 Task 5): 5.x's five factors and weights over the app's inbound
connections and its hosts; a factor without data is left out and the rest rescaled."""
import pytest

from illumio_ops.domain.readiness import ReadinessInputs, readiness


def _i(**kw):
    base = {"connections": 100, "decided": 100, "allowed": 100, "same_app": 100, "potentially_blocked": 0, "remote": 10,
            "remote_allowed": 10, "hosts": 4, "full": 4, "selective": 0}
    return ReadinessInputs(**{**base, **kw})


def test_factor_weights_and_rescale():
    assert readiness(_i()).score == pytest.approx(100) and readiness(_i()).grade == "A"
    r = readiness(_i(allowed=0))  # policy 35 lost
    assert r.score == pytest.approx(65) and r.blocking == "policy"
    r = readiness(_i(remote=0, remote_allowed=0, full=0))  # no remote traffic: 90 points; enforcement 0 of 20
    assert r.parts["remote"] is None and r.score == pytest.approx(100 * 70 / 90)
    assert r.blocking == "enforcement"


def test_selective_counts_half_and_staged():
    r = readiness(_i(full=0, selective=4, potentially_blocked=50))
    assert r.parts["enforcement"] == pytest.approx(0.5) and r.parts["staged"] == pytest.approx(0.5)


def test_no_traffic_only_enforcement():
    r = readiness(_i(connections=0, decided=0, allowed=0, same_app=0, remote=0, remote_allowed=0, full=2))
    assert r.parts["policy"] is None and r.score == pytest.approx(50) and r.grade == "D"


def test_nothing_known_no_score():
    r = readiness(_i(connections=0, decided=0, allowed=0, same_app=0, remote=0, remote_allowed=0, hosts=0, full=0))
    assert r.score is None and r.grade is None and r.blocking is None
