"""Verify that the report-language <select> in the report dialog defaults
to the user's current UI language rather than a hard-coded value."""
from __future__ import annotations

import re
from pathlib import Path


TEMPLATE_PATH = Path(__file__).parent.parent / "src" / "templates" / "index.html"
JS_PATH = Path(__file__).parent.parent / "src" / "static" / "js" / "dashboard.js"


def test_index_html_does_not_hardcode_selected_on_report_lang():
    """index.html must not pre-select any language in the report-lang <select>;
    selection is set at runtime from UI language."""
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    # find the block around the m-gen-lang select element
    m = re.search(
        r'<select[^>]*id=["\']m-gen-lang["\'][^>]*>(.*?)</select>',
        html,
        flags=re.DOTALL,
    )
    assert m is not None, "m-gen-lang select not found"
    block = m.group(1)
    # No option should carry the hard-coded "selected" attribute
    assert " selected" not in block.lower(), (
        f"Expected no hard-coded 'selected' attribute in m-gen-lang options, got:\n{block}"
    )


def test_dashboard_js_syncs_report_lang_on_open():
    """dashboard.js must call a helper that sets m-gen-lang.value from UI lang
    when opening the report dialog."""
    js = JS_PATH.read_text(encoding="utf-8")
    # function we will add — name fixed for test stability
    assert "syncReportLangToUi" in js, (
        "Expected dashboard.js to define and invoke syncReportLangToUi()"
    )
