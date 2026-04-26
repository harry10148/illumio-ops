"""When first/last_detected are missing or unparseable, the report metadata
should fall back to query_context.start_date / end_date instead of N/A."""
import pandas as pd

from src.report.analysis import mod01_traffic_overview


def test_date_range_falls_back_to_query_context_when_missing():
    flows = pd.DataFrame([{"src": "a", "dst": "b", "port": 80,
                           "policy_decision": "allowed"}])
    query_context = {"start_date": "2026-04-18", "end_date": "2026-04-25"}
    out = mod01_traffic_overview.analyze(flows, query_context=query_context)
    assert out["date_range"]["start"] == "2026-04-18"
    assert out["date_range"]["end"] == "2026-04-25"


def test_date_range_uses_first_last_detected_when_present():
    flows = pd.DataFrame([
        {"src": "a", "dst": "b", "port": 80, "policy_decision": "allowed",
         "first_detected": "2026-04-19T01:00:00Z", "last_detected": "2026-04-24T22:00:00Z"},
    ])
    query_context = {"start_date": "2026-04-18", "end_date": "2026-04-25"}
    out = mod01_traffic_overview.analyze(flows, query_context=query_context)
    # Detected times override query_context when they are real
    assert out["date_range"]["start"].startswith("2026-04-19")
    assert out["date_range"]["end"].startswith("2026-04-24")


def test_date_range_returns_query_context_when_detected_unparseable():
    flows = pd.DataFrame([
        {"src": "a", "dst": "b", "port": 80, "policy_decision": "allowed",
         "first_detected": "garbage", "last_detected": None},
    ])
    query_context = {"start_date": "2026-04-18", "end_date": "2026-04-25"}
    out = mod01_traffic_overview.analyze(flows, query_context=query_context)
    assert out["date_range"]["start"] == "2026-04-18"
    assert out["date_range"]["end"] == "2026-04-25"
