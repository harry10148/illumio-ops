"""Phase 3.1 Task 6 — graceful empty-state for hero / maturity / risk."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"


def test_js_has_renderHeroEmpty_and_call_site():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "function renderHeroEmpty" in js, "renderHeroEmpty must be defined"
    # at least one call site outside the definition
    assert re.search(r"renderHeroEmpty\(\)\s*;", js), "renderHeroEmpty must be called from snapshot load path"


def test_js_still_references_d_maturity():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "d-maturity" in js
