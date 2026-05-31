"""Legacy snapshot panel — top actions anchor and findings table structure."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src" / "templates" / "index.html"


def test_index_has_top_actions_anchor():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="d-top-actions"' in html


def test_findings_body_wrapped_in_details():
    html = INDEX_HTML.read_text(encoding="utf-8")
    pattern = re.compile(r'<details[^>]*>[\s\S]*?id="snap-findings-body"', re.MULTILINE)
    assert pattern.search(html), "snap-findings-body must be wrapped in <details>"
