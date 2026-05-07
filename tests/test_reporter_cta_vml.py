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


def test_cta_signal_color_used_in_vml():
    """VML fillcolor should match SIGNAL_HEX for the chosen severity."""
    from src.reporter import SIGNAL_HEX
    html = Reporter._render_cta("Open", "https://x/y", severity='danger')
    expected = SIGNAL_HEX['danger']
    assert expected in html
    # Appears at least twice: once in VML fillcolor, once in HTML inline style
    assert html.count(expected) >= 2


def test_cta_label_is_html_escaped_in_both_branches():
    """The label is escaped in both VML and HTML branches."""
    html = Reporter._render_cta("<script>x</script>", "https://x/y")
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
