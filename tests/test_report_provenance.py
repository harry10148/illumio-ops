"""報表封面的資料來源資訊。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from src.report.provenance import build_provenance, filters_summary, pce_identity


def _cm():
    return SimpleNamespace(config={"api": {"url": "https://pce.example:8443", "org_id": 7},
                                   "settings": {"timezone": "Asia/Taipei"}})


def test_window_is_rendered_in_report_timezone():
    p = build_provenance(_cm(), source="api", start="2026-09-23T16:00:00Z", end="2026-09-30T15:59:59Z")
    assert p["window_start"] == "2026-09-24 00:00 (UTC+8)"
    assert p["window_end"] == "2026-09-30 23:59 (UTC+8)"
    assert p["pce_url"] == "https://pce.example:8443" and p["org"] == "org 7"
    assert p["tool_version"]


def test_csv_import_has_no_pce_identity():
    p = build_provenance(_cm(), source="csv")
    assert p["source"] == "csv" and p["pce_url"] == "" and p["window_start"] == ""


def test_filters_summary_skips_defaults():
    assert filters_summary({"policy_decisions": ["allowed"]},
                           ["allowed", "blocked", "potentially_blocked", "unknown"]) == ""
    assert filters_summary({"src_labels": ["app:web"]}, ["blocked"]) == \
        "policy_decision=blocked; src_labels=app:web"


def test_mock_config_does_not_leak_into_cover():
    assert pce_identity(MagicMock()) == ("", "")


def test_csv_report_is_not_labelled_mixed():
    from src.report.exporters.html_exporter import TrafficFlowsHtmlExporter
    html = TrafficFlowsHtmlExporter({"mod12": {}, "_provenance": build_provenance(_cm(), source="csv")},
                                    data_source="csv", profile="traffic")._build()
    assert "CSV" in html
    assert "mixed (cache + API)" not in html
