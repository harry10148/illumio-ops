"""pygments wrapper for report code highlighting."""
import pytest


def test_highlight_json_outputs_html_with_classes():
    from src.report.exporters.code_highlighter import highlight_json
    out = highlight_json('{"name": "test", "value": 42}')
    assert '<div class="highlight"' in out or '<pre' in out
    # pygments JSON lexer emits span tags with token classes; string keys
    # may be HTML-escaped (&quot;name&quot;) but the span wrapper must be present
    assert 'span' in out and ('name' in out or '&quot;name&quot;' in out)


def test_highlight_yaml_outputs_html():
    from src.report.exporters.code_highlighter import highlight_yaml
    out = highlight_yaml("name: test\nvalue: 42\n")
    assert '<pre' in out or '<div' in out


def test_highlight_css_generator_emits_style_tag():
    """Callers need the Pygments CSS once per HTML document."""
    from src.report.exporters.code_highlighter import get_highlight_css
    css = get_highlight_css()
    assert ".highlight" in css or ".k" in css  # pygments class


def test_highlight_handles_empty_string():
    from src.report.exporters.code_highlighter import highlight_json
    out = highlight_json("")
    assert isinstance(out, str)


def test_highlight_handles_invalid_json_gracefully():
    """If JSON is malformed, pygments still lexes it as text."""
    from src.report.exporters.code_highlighter import highlight_json
    out = highlight_json("{broken json")
    assert isinstance(out, str)
    assert len(out) > 0
