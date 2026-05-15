"""Phase 3.1 Task 4 — Top 3 action cards and collapsed findings table."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"
DASHBOARD_JS = ROOT / "src" / "static" / "js" / "dashboard.js"


def test_index_has_top_actions_anchor():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="d-top-actions"' in html


def test_js_has_renderTopActions_with_slice_3():
    js = DASHBOARD_JS.read_text(encoding="utf-8")
    assert "function renderTopActions" in js
    assert "slice(0, 3)" in js or "slice(0,3)" in js


def test_findings_body_wrapped_in_details():
    html = INDEX_HTML.read_text(encoding="utf-8")
    pattern = re.compile(r'<details[^>]*>[\s\S]*?id="snap-findings-body"', re.MULTILINE)
    assert pattern.search(html), "snap-findings-body must be wrapped in <details>"
