"""Regression tests for cache_reader wiring across the 8 ReportGenerator /
AuditGenerator call sites.

The cache-aware fetch path inside ReportGenerator._fetch_traffic and
AuditGenerator._fetch_events is dead code unless callers pass
cache_reader=. This test guards each call site against silent regressions
that would put reports back on the API-only path.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# (file path, regex that must appear at least once in the file)
_REPORT_GEN_SITES = [
    ("src/main.py", r"ReportGenerator\([^)]*cache_reader\s*="),
    ("src/cli/report.py", r"ReportGenerator\([^)]*cache_reader\s*="),
    ("src/gui/routes/reports.py", r"ReportGenerator\([^)]*cache_reader\s*="),
    ("src/report_scheduler.py", r"ReportGenerator\([^)]*cache_reader\s*="),
]

_AUDIT_GEN_SITES = [
    ("src/main.py", r"AuditGenerator\([^)]*cache_reader\s*="),
    ("src/cli/report.py", r"AuditGenerator\([^)]*cache_reader\s*="),
    ("src/gui/routes/reports.py", r"AuditGenerator\([^)]*cache_reader\s*="),
    ("src/report_scheduler.py", r"AuditGenerator\([^)]*cache_reader\s*="),
]

# Analyzer call sites for query_flows / run_analysis paths (Top10, dashboard
# widgets, scheduled monitor cycle). Must pass cache_reader= so query_flows
# can short-circuit to the cache when fully covered.
_ANALYZER_SITES = [
    ("src/gui/routes/dashboard.py", r"Analyzer\(.*?cache_reader\s*="),
    ("src/gui/routes/actions.py", r"Analyzer\(.*?cache_reader\s*="),
    # Phase 2C moved the interactive "run analysis now" / "debug mode" paths out
    # of main.rule_management_menu into the alerting area. The guard follows the
    # call, otherwise it is watching a file that no longer builds an Analyzer.
    ("src/cli/menus/areas.py", r"Analyzer\(.*?cache_reader\s*="),
    ("src/scheduler/jobs.py", r"Analyzer\(.*?cache_reader\s*="),
]


@pytest.mark.parametrize("relpath,pattern", _REPORT_GEN_SITES + _AUDIT_GEN_SITES + _ANALYZER_SITES)
def test_cache_reader_passed_at_call_site(relpath, pattern):
    text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
    # Allow the pattern to span multiple lines (DOTALL) since some call
    # sites split arguments across lines.
    assert re.search(pattern, text, re.DOTALL), (
        f"{relpath}: missing cache_reader= argument. "
        f"Reports/audit must pass cache_reader (e.g. via "
        f"_make_cache_reader(cm)) or the cache-aware fetch path inside "
        f"the generator is dead code."
    )


def test_make_cache_reader_returns_none_when_cache_disabled():
    """_make_cache_reader should silently return None when pce_cache is
    not enabled; callers must not error out in that case."""
    from unittest.mock import MagicMock

    from src.main import _make_cache_reader

    cm = MagicMock()
    cm.models.pce_cache.enabled = False
    assert _make_cache_reader(cm) is None
