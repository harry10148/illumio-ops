"""Phase 1: per-profile trend/drift snapshot keying in export()."""
import pandas as pd
from unittest.mock import MagicMock, patch

from src.report.report_generator import ReportGenerator, ReportResult


def _result():
    df = pd.DataFrame([{
        "src_ip": "10.0.0.1", "dst_ip": "10.0.1.1", "src_app": "A", "dst_app": "B",
        "port": 443, "proto": "TCP", "num_connections": 3,
        "policy_decision": "allowed",
    }])
    return ReportResult(data_source="api", record_count=1,
                        module_results={"mod12": {"kpis": []}}, dataframe=df)


def _gen():
    cm = MagicMock()
    cm.config = {"settings": {}}
    return ReportGenerator(cm, api_client=None)


def _export(profile, tmp_path):
    gen = _gen()
    with patch("src.report.trend_store.load_previous", return_value=None) as lp, \
         patch("src.report.trend_store.save_snapshot") as ss, \
         patch("src.report.flow_history.load_previous_signatures",
               return_value=(None, None)) as ls, \
         patch("src.report.flow_history.save_signatures") as sv, \
         patch.object(gen, "_build_report_metadata", return_value={"kpis": [], "generated_at": ""}):
        gen.export(_result(), fmt="csv", output_dir=str(tmp_path),
                   traffic_report_profile=profile)
    return lp, ss, ls, sv


def test_security_risk_uses_profile_keyed_snapshots(tmp_path):
    lp, ss, ls, sv = _export("security_risk", tmp_path)
    assert lp.call_args.args[1] == "traffic_security_risk"
    assert ss.call_args.args[1] == "traffic_security_risk"
    assert ls.called and sv.called  # drift runs for security_risk


def test_traffic_profile_skips_drift(tmp_path):
    lp, ss, ls, sv = _export("traffic", tmp_path)
    assert lp.call_args.args[1] == "traffic_traffic"
    assert not ls.called and not sv.called  # no drift for traffic profile
