"""Appendix wrapper always renders full detail."""
from src.report.exporters.html_exporter import render_appendix


def test_appendix_uses_open_details_for_legacy_standard():
    out = render_appendix("Test", "<p>body</p>", detail_level="standard")
    assert "<details" in out
    assert "<summary" in out
    assert "<p>body</p>" in out
    assert "<details open" in out


def test_appendix_open_in_full():
    out = render_appendix("Test", "<p>body</p>", detail_level="full")
    assert "<details open" in out


def test_appendix_open_for_legacy_executive():
    out = render_appendix("Test", "<p>body</p>", detail_level="executive")
    assert "<details open" in out
    assert "<p>body</p>" in out
