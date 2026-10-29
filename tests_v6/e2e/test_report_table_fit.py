"""Rendered report tables at screen width (2026-10-29, readiness on lab): a table whose long-text columns are
together wider than the page kept every column at its one-line width and scrolled, so the last column — the
rules to write — was past the right edge. Long text wraps instead; only a wide table (many columns) scrolls."""
from datetime import UTC

from illumio_ops.domain.report import Section
from illumio_ops.services.reports.render_html import render_html
from tests_v6.services.reports.conftest import make_doc, table

LONG = "38 points (F): the most is lost on “From the app itself” — 4.9% of the connections, 1 of its 20 points. " * 2
LINKS = "Endpoint → 5353/UDP (809 connections); Endpoint → 7000/TCP (279 connections); Web → 443/TCP (156) " * 2


def _overflow(context, html, width):
    page = context.new_page()
    page.set_viewport_size({"width": width, "height": 900})
    page.set_content(html)
    page.wait_for_timeout(300)
    return page.evaluate("""() => [...document.querySelectorAll('.report-table-wrap')]
        .map(w => w.scrollWidth - w.clientWidth)""")


def test_long_text_columns_wrap_to_the_page(context):
    rows = [("Endpoint (WIFI)", LONG, LINKS), ("DemoApp (Server)", LONG, LINKS)]
    doc = make_doc(sections=(Section(id="next", title="What to do first", intro="",
                                     blocks=(table(rows, cols=3),)),))
    for width in (1280, 768):
        assert _overflow(context, render_html(doc, tz=UTC), width) == [0], width
