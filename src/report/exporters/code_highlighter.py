"""pygments wrapper for syntax highlighting in HTML/PDF reports."""
from __future__ import annotations

from pygments import highlight
from pygments.lexers import JsonLexer, YamlLexer, BashLexer
from pygments.formatters import HtmlFormatter


_FORMATTER = HtmlFormatter(style="default", cssclass="highlight", nowrap=False)


def highlight_json(code: str) -> str:
    """Highlight a JSON string as HTML with pygments classes."""
    return highlight(code, JsonLexer(), _FORMATTER)


def highlight_yaml(code: str) -> str:
    return highlight(code, YamlLexer(), _FORMATTER)


def highlight_bash(code: str) -> str:
    return highlight(code, BashLexer(), _FORMATTER)


def get_highlight_css() -> str:
    """CSS styles for pygments highlight classes. Embed in <style> tag once per doc."""
    return _FORMATTER.get_style_defs(".highlight")
