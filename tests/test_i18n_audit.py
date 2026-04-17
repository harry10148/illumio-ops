"""Runs the comprehensive i18n audit script as a CI regression gate.

The audit covers seven categories (A–G) enumerated in
``scripts/audit_i18n_usage.py``. A green CI means:

  - no placeholder leak in either locale (A/B/F/G)
  - no hardcoded CJK outside the translation tables (C)
  - no auto-translate residue in zh_TW strings (D)
  - no glossary drift — whitelist terms still in English in zh_TW (E)

Runs the audit via a subprocess so the script's standalone import context
(``from src.i18n import ...`` etc.) stays intact, and fails loudly on any
non-zero exit, printing the full report path for the operator.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts" / "audit_i18n_usage.py"
REPORT_PATH = ROOT / "scripts" / "audit_i18n_report.md"


def test_comprehensive_i18n_audit_is_clean():
    """Fails if any of the seven audit categories reports findings.

    Run ``python scripts/audit_i18n_usage.py`` locally to regenerate the
    Markdown report under ``scripts/audit_i18n_report.md`` with full
    per-finding details.
    """
    assert AUDIT_PATH.exists(), f"audit script missing: {AUDIT_PATH}"

    result = subprocess.run(
        [sys.executable, str(AUDIT_PATH)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        summary = result.stdout.strip() or result.stderr.strip()
        pytest.fail(
            "i18n audit reported findings.\n"
            f"See {REPORT_PATH.relative_to(ROOT)} for full detail.\n"
            f"{summary}"
        )
