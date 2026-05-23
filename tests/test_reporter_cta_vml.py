"""Test bulletproof CTA includes VML conditional wrap for Outlook."""
import pytest
from src.reporter import Reporter


def test_cta_has_mso_conditional_vml():
    html = Reporter._render_cta(label="Open dashboard", url="https://x/y", severity='info')
    assert '<!--[if mso]>' in html
    assert '<![endif]-->' in html
    assert 'v:roundrect' in html.lower()
    # Fallback for non-MSO clients still present
    assert '<table' in html
    assert '<a href=' in html


def test_cta_is_neutral_white_button():
    """R3: CTA buttons are white/neutral (no colored fill) with grey border."""
    html = Reporter._render_cta("Open", "https://x/y", severity='danger')
    # VML uses white fill + grey stroke
    assert 'fillcolor="#ffffff"' in html.lower()
    assert 'strokecolor="#e5e5e5"' in html.lower()
    # Non-MSO uses white background
    assert 'bgcolor="#ffffff"' in html.lower()
    # Link text is dark, not white
    assert 'color:#0a0a0a' in html


def test_cta_label_is_html_escaped_in_both_branches():
    """The label is escaped in both VML and HTML branches."""
    html = Reporter._render_cta("<script>x</script>", "https://x/y")
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
