"""Guard: every HTML report exporter must render the shared print button.

rule_hit_count shipped without one (2026-07-04 print-layout plan missed it);
this scans exporter sources so a future report family can't repeat that.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORTER_DIR = ROOT / "src" / "report" / "exporters"


def test_every_html_exporter_has_print_button():
    exporters = sorted(EXPORTER_DIR.glob("*html_exporter.py"))
    assert len(exporters) >= 8  # audit/ven/pu/readiness/policy_diff/app_summary/rhc/traffic
    missing = [p.name for p in exporters if "print-btn" not in p.read_text()]
    assert not missing, f"exporters without print button: {missing}"
