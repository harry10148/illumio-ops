"""Phase 1: traffic-profile pipeline runs only lightweight modules."""
import pandas as pd
import pytest
from unittest.mock import MagicMock

from src.report.report_generator import ReportGenerator


def _flows_df(n=6):
    rows = []
    for i in range(n):
        rows.append({
            "src_ip": f"10.0.0.{i}", "src_hostname": f"h{i}", "src_managed": True,
            "src_app": "AppA", "src_env": "prod", "src_loc": "dc1", "src_role": "web",
            "dst_ip": f"10.0.1.{i}", "dst_hostname": f"d{i}", "dst_managed": (i % 2 == 0),
            "dst_app": "AppB", "dst_env": "prod", "dst_loc": "dc1", "dst_role": "db",
            "port": 443 + i, "proto": "TCP",
            "process_name": "", "user_name": "",
            "num_connections": 10 + i,
            "policy_decision": ["allowed", "blocked", "potentially_blocked"][i % 3],
            "bytes_total": 1000 * (i + 1), "bandwidth_mbps": 0.5,
            "data_source": "test",
            "first_detected": pd.Timestamp("2026-04-28", tz="UTC"),
            "last_detected": pd.Timestamp("2026-05-03", tz="UTC"),
        })
    return pd.DataFrame(rows)


def _gen():
    cm = MagicMock()
    cm.config = {"settings": {}}
    gen = ReportGenerator(cm, api_client=None)
    return gen


def test_traffic_profile_runs_only_lightweight_modules():
    result = _gen()._run_pipeline(_flows_df(), source="api",
                                  traffic_report_profile="traffic")
    mods = set(result.module_results.keys())
    assert {"mod01", "mod02", "mod08", "mod09", "mod11", "mod12"} <= mods
    for heavy in ("mod03", "mod04", "mod13", "mod14", "mod15",
                  "mod07", "mod10", "mod_ringfence", "mod_draft_summary"):
        assert heavy not in mods, heavy


def test_traffic_profile_skips_rules_engine():
    result = _gen()._run_pipeline(_flows_df(), source="api",
                                  traffic_report_profile="traffic")
    assert result.findings == []


def test_traffic_profile_accepted_by_generate_from_csv_validation():
    gen = _gen()
    with pytest.raises(ValueError):
        gen.generate_from_csv("/nonexistent.csv", traffic_report_profile="bogus")


def test_security_profile_still_runs_full_set():
    result = _gen()._run_pipeline(_flows_df(), source="api",
                                  traffic_report_profile="security_risk")
    assert "mod15" in result.module_results
    assert "mod13" in result.module_results
