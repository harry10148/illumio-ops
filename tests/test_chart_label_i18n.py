"""Regression: chart slice/bar labels in zh_TW PDFs.

Only mod04 risk levels (Critical/High/Medium/Low) are translated — those are
generic severity terminology. Illumio-specific product terminology — mod01/mod02
policy verdicts (Allowed/Blocked/Potentially Blocked/Unknown) and mod08
managed/unmanaged host distinction — stays English by design; the guard test
below pins down that contract so a future contributor can't silently
re-introduce translation.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.i18n import set_language, get_language


def _make_traffic_df() -> pd.DataFrame:
    """Minimal traffic DataFrame that exercises every chart_spec branch
    in mod01 / mod02 / mod04 / mod08 — all four policy decisions, at least
    one flow on critical/high/medium ransomware-risk ports, and at least one
    unmanaged source so mod08's managed-vs-unmanaged pie has both slices."""
    return pd.DataFrame({
        "src_ip":            ["10.0.0.1", "10.0.0.2", "10.0.0.3", "10.0.0.4"],
        "dst_ip":            ["10.0.1.1", "10.0.1.2", "10.0.1.3", "10.0.1.4"],
        "port":              [445, 3389, 22, 80],
        "proto":             ["TCP", "TCP", "TCP", "TCP"],
        "bytes_total":       [10_000, 5_000, 20_000, 3_000],
        "num_connections":   [5, 3, 10, 2],
        "policy_decision":   ["allowed", "blocked", "potentially_blocked", "unknown"],
        "src_managed":       [True, True, False, True],
        "dst_managed":       [True, False, True, True],
        "first_detected":    pd.to_datetime(["2024-01-01"] * 4),
        "last_detected":     pd.to_datetime(["2024-01-02"] * 4),
        "src_app":           ["web", "db", "admin", "web"],
        "dst_app":           ["db", "cache", "web", "api"],
        "dst_hostname":      ["db-1", "cache-1", "web-1", "api-1"],
    })


_RANSOMWARE_CONFIG = {
    "ransomware_risk_ports": {
        "critical": [{"ports": [445], "service": "SMB"}],
        "high":     [{"ports": [3389], "service": "RDP"}],
        "medium":   [{"ports": [22], "service": "SSH"}],
        "low":      [{"ports": [80], "service": "HTTP"}],
    }
}


@pytest.fixture
def zh_tw_lang():
    prev = get_language()
    set_language("zh_TW")
    try:
        yield
    finally:
        set_language(prev)


def test_mod04_ransomware_exposure_labels_translate_to_zh_tw(zh_tw_lang):
    from src.report.analysis.mod04_ransomware_exposure import ransomware_exposure

    out = ransomware_exposure(_make_traffic_df(), _RANSOMWARE_CONFIG)
    labels = out["chart_spec"]["data"]["labels"]

    # All four risk levels are present in the test config + DataFrame, so
    # all four Chinese labels must surface.
    assert "嚴重" in labels
    assert "高" in labels
    assert "中" in labels
    assert "低" in labels
    # English absent
    assert "Critical" not in labels
    assert "High" not in labels
    assert "Medium" not in labels
    assert "Low" not in labels


def test_illumio_terms_stay_english_in_zh_tw(zh_tw_lang):
    """Illumio product terminology — policy verdicts (Allowed/Blocked/
    Potentially Blocked/Unknown) and the managed-vs-unmanaged host distinction
    — MUST stay English in zh_TW PDFs. These are technical terms operators
    recognize from the Illumio console, not user-facing language.

    This test pins down the user's stated requirement so a future contributor
    can't silently re-introduce translation by wrapping the literals in t().
    """
    from src.report.analysis.mod01_traffic_overview import traffic_overview
    from src.report.analysis.mod02_policy_decisions import policy_decision_analysis
    from src.report.analysis.mod08_unmanaged_hosts import unmanaged_traffic

    df = _make_traffic_df()

    mod01_labels = traffic_overview(df)["chart_spec"]["data"]["labels"]
    for verdict in ("Allowed", "Blocked", "Potentially Blocked", "Unknown"):
        assert verdict in mod01_labels, (
            f"Illumio verdict {verdict!r} should remain English in zh_TW "
            f"(it is product terminology, not user-facing language). "
            f"mod01 labels were: {mod01_labels!r}"
        )

    mod02_labels = policy_decision_analysis(df)["chart_spec"]["data"]["labels"]
    for verdict in ("Allowed", "Blocked", "Potentially Blocked"):
        assert verdict in mod02_labels, (
            f"Illumio verdict {verdict!r} should remain English in zh_TW "
            f"(it is product terminology, not user-facing language). "
            f"mod02 labels were: {mod02_labels!r}"
        )

    mod08_labels = unmanaged_traffic(df)["chart_spec"]["data"]["labels"]
    for term in ("Managed", "Unmanaged"):
        assert term in mod08_labels, (
            f"Illumio host classification {term!r} should remain English in "
            f"zh_TW (it is product terminology, not user-facing language). "
            f"mod08 labels were: {mod08_labels!r}"
        )
