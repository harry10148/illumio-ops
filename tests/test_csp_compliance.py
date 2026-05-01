"""CSP-compliance regression tests (Task 3.1 / M1).

These tests guard against re-introducing inline onclick handlers, which break
under a strict ``script-src 'self' + nonce`` Content-Security-Policy.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_index_html_has_no_inline_onclick():
    """M1: inline onclick attributes break CSP nonce mode."""
    tpl = REPO_ROOT / "src" / "templates" / "index.html"
    text = tpl.read_text(encoding="utf-8")
    onclicks = re.findall(r"onclick\s*=", text)
    assert not onclicks, f"Found {len(onclicks)} inline onclick(s) in index.html"


def test_rule_scheduler_js_has_no_string_built_onclick():
    """M1: rule-scheduler.js builds buttons via string-HTML; switch to DOM."""
    js = REPO_ROOT / "src" / "static" / "js" / "rule-scheduler.js"
    text = js.read_text(encoding="utf-8")
    assert "onclick=" not in text, (
        "rule-scheduler.js still concatenates onclick into HTML strings"
    )
