"""Large byte counts must render with auto-scaled human-readable units
(KB / MB / GB / TB), not raw MB."""
from __future__ import annotations

import pytest

from src.humanize_ext import fmt_bytes_auto, human_number
from src.report.analysis.mod12_executive_summary import executive_summary


def test_fmt_bytes_auto_picks_GB_at_billion_bytes():
    # 6062571061 bytes ≈ 5.65 GB
    assert fmt_bytes_auto(6062571061).endswith("GB"), fmt_bytes_auto(6062571061)


def test_fmt_bytes_auto_handles_mb_input():
    # 6062 MB → ~5.92 GB
    out = fmt_bytes_auto(6062, input_unit="MB")
    assert "GB" in out, out


def test_fmt_bytes_auto_handles_zero_and_negative():
    assert fmt_bytes_auto(0) == "0 B"
    assert fmt_bytes_auto(-1) == "—"


def test_mod12_total_data_volume_uses_human_readable():
    # Synthesize mod_results with a 6 GB total_mb in mod01
    mod_results = {
        "mod01": {"total_mb": 6062.0, "total_flows": 100},
        "mod02": {}, "mod03": {}, "mod04": {}, "mod05": {}, "mod06": {},
        "mod07": {}, "mod08": {}, "mod09": {}, "mod11": {"total_mb": 6062.0},
        "mod12": None, "mod13": {}, "mod14": {}, "mod15": {},
    }
    out = executive_summary(mod_results, profile="security_risk", lang="en")
    kpis = out["kpis"]
    vol = next((k for k in kpis if "data volume" in k["label"].lower()), None)
    assert vol, f"KPI dict had no data-volume entry; got labels {[k['label'] for k in kpis]}"
    # Should mention GB (auto-scaled), not raw MB
    assert "GB" in vol["value"], f"expected GB unit, got {vol['value']!r}"


def test_human_number_adds_thousands_separator():
    assert human_number(1234567) == "1,234,567"
