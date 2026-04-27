"""Appendix wrapper renders content inside collapsible <details> by default,
and expanded in 'full' mode."""
from src.report.exporters.html_exporter import render_appendix


def test_appendix_uses_details_in_standard():
    out = render_appendix("Test", "<p>body</p>", detail_level="standard")
    assert "<details" in out
    assert "<summary" in out
    assert "<p>body</p>" in out
    assert "<details open" not in out  # collapsed by default


def test_appendix_open_in_full():
    out = render_appendix("Test", "<p>body</p>", detail_level="full")
    assert "<details open" in out


def test_appendix_omitted_in_executive():
    """Executive mode hides appendix entirely."""
    out = render_appendix("Test", "<p>body</p>", detail_level="executive")
    assert out == ""
