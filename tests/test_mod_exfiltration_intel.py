"""mod_exfiltration_intel: managed→unmanaged exfiltration + threat intel join."""
import pandas as pd

from src.report.analysis import mod_exfiltration_intel


def _flows_with_exfil():
    return pd.DataFrame([
        {"src": "internal-1", "dst": "203.0.113.50", "port": 443, "bytes": 5_000_000_000,
         "policy_decision": "allowed",
         "src_managed": True, "dst_managed": False},
        {"src": "internal-2", "dst": "203.0.113.51", "port": 443, "bytes": 100_000,
         "policy_decision": "allowed",
         "src_managed": True, "dst_managed": False},
    ])


def test_skipped_when_no_managed_columns():
    out = mod_exfiltration_intel.analyze(pd.DataFrame([{"src": "a", "dst": "b", "port": 80}]))
    assert out.get("skipped") is True


def test_high_volume_exfil_flagged():
    out = mod_exfiltration_intel.analyze(_flows_with_exfil())
    high = out["high_volume_exfil"]
    assert any(r["dst"] == "203.0.113.50" and r["bytes"] >= 1_000_000_000 for r in high)


def test_threat_intel_match(tmp_path):
    intel = tmp_path / "bad_ips.csv"
    intel.write_text("ip,reason\n203.0.113.50,known_c2\n")
    out = mod_exfiltration_intel.analyze(_flows_with_exfil(), threat_intel_csv=str(intel))
    matches = out["threat_intel_matches"]
    assert any(m["dst"] == "203.0.113.50" and m["reason"] == "known_c2" for m in matches)


def test_threat_intel_returns_empty_when_no_csv():
    out = mod_exfiltration_intel.analyze(_flows_with_exfil(), threat_intel_csv=None)
    assert out["threat_intel_matches"] == []
