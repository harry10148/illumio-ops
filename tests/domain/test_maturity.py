"""The v6 segmentation maturity score (P5b-1 Task 4): five weighted parts, a part without data left out and the
rest rescaled, selective enforcement counted as half (5.x counted it as full through a fallback)."""
import pytest

from illumio_ops.domain.maturity import MaturityInputs, grade, maturity


def _inputs(**kw):
    base = {"hosts_managed": 10, "hosts_full": 10, "hosts_selective": 0, "connections": 100, "allowed_connections": 100,
                "admin_open_connections": 0, "unmanaged_source_connections": 0, "ransomware_services": 10,
                "ransomware_protected": 10}
    return MaturityInputs(**{**base, **kw})


def test_maturity_weights_and_rescale():
    assert maturity(_inputs()).score == pytest.approx(100)
    m = maturity(_inputs(hosts_full=5))  # enforcement 0.5 of its 40 points
    assert m.score == pytest.approx(80) and m.parts["enforcement"] == pytest.approx(0.5)
    m = maturity(_inputs(allowed_connections=0, admin_open_connections=30, unmanaged_source_connections=50))
    assert m.score == pytest.approx(50)  # policy 25, lateral 15 and managed 10 all at zero


def test_selective_counts_half():
    m = maturity(_inputs(hosts_full=0, hosts_selective=10))
    assert m.parts["enforcement"] == pytest.approx(0.5)


def test_lateral_and_managed_caps():
    assert maturity(_inputs(admin_open_connections=15)).parts["lateral"] == pytest.approx(0.5)
    assert maturity(_inputs(admin_open_connections=90)).parts["lateral"] == 0
    assert maturity(_inputs(unmanaged_source_connections=25)).parts["managed"] == pytest.approx(0.5)


def test_maturity_without_ransomware_rescales():
    m = maturity(_inputs(ransomware_services=None, ransomware_protected=None, hosts_full=5))
    assert m.parts["ransomware"] is None
    assert m.score == pytest.approx(100 * (40 * 0.5 + 25 + 15 + 10) / 90)


def test_no_data_no_score():
    m = maturity(_inputs(hosts_managed=0, hosts_full=0, connections=0, allowed_connections=0, ransomware_services=None,
                         ransomware_protected=None))
    assert m.score is None and m.grade is None


def test_grades():
    assert [grade(s) for s in (85, 84.9, 70, 55, 40, 39.9)] == ["A", "B", "B", "C", "D", "F"]


def test_policy_part_over_decided_connections():
    """A connection without a reported decision says nothing about policy (the readiness report's rule, P5b-2)."""
    m = maturity(_inputs(connections=100, allowed_connections=20, undecided_connections=80))
    assert m.parts["policy"] == pytest.approx(1.0)
    m = maturity(_inputs(connections=100, allowed_connections=0, undecided_connections=100))
    assert m.parts["policy"] is None
