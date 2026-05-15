"""Verify the dashboard-scope i18n audit catches known-broken zh_TW values."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_dashboard_i18n.py"
PY = sys.executable


def _run_audit() -> dict:
    assert SCRIPT.exists(), f"audit script missing: {SCRIPT}"
    result = subprocess.run(
        [PY, str(SCRIPT), "--format=json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def test_audit_flags_mixed_language_titles() -> None:
    report = _run_audit()
    flagged_keys = {f["key"] for f in report["findings"]}
    # Must find at least one mixed-language case
    mixed = [f for f in report["findings"] if f["rule"] == "mixed_language"]
    assert mixed, (
        f"Expected at least one mixed_language finding; got: {sorted(flagged_keys)[:10]}"
    )


def test_audit_applies_five_rules() -> None:
    report = _run_audit()
    rules = report.get("rules_applied", [])
    expected = {"mixed_language", "low_han_ratio", "too_short_vs_english",
                "known_typo", "untranslated"}
    missing = expected - set(rules)
    assert not missing, f"missing rules: {missing}"


def test_audit_emits_markdown_report() -> None:
    """Running without --format=json must produce a markdown file path on stdout."""
    result = subprocess.run(
        [PY, str(SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert "dashboard_i18n_flagged.md" in result.stdout, result.stdout


def test_audit_dashboard_scope_excludes_login_keys() -> None:
    """Login/rule-scheduler keys must not appear in dashboard scope."""
    report = _run_audit()
    flagged_keys = {f["key"] for f in report["findings"]}
    assert not any(k.startswith("login_") for k in flagged_keys)
    assert not any(k.startswith("rs_") for k in flagged_keys)
