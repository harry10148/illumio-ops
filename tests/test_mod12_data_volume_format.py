# tests/test_mod12_data_volume_format.py
"""Key Findings data-volume must be human-formatted, not raw MB."""
from src.report.analysis.mod12_executive_summary import executive_summary


def _base_results(total_mb):
    return {
        "mod01": {"total_flows": 10, "total_connections": 10, "unique_src_ips": 1,
                  "unique_dst_ips": 1, "blocked_flows": 0, "src_managed_pct": 100,
                  "total_mb": total_mb, "date_range": "x"},
        "mod03": {"enforced_coverage_pct": 90, "staged_coverage_pct": 5, "true_gap_pct": 5},
        "mod11": {"bytes_data_available": True, "total_mb": total_mb},
        "findings": [],
    }


def test_data_volume_key_finding_is_humanized():
    res = executive_summary(_base_results(438821219), lang="en")
    vol_findings = [k for k in res["key_findings"] if "data volume" in k["finding"].lower()]
    assert vol_findings, "data-volume key finding should fire above 1000 MB"
    text = vol_findings[0]["finding"]
    assert "438821219" not in text          # raw MB 不得出現
    assert "TB" in text                     # fmt_bytes_auto 換算後的單位
