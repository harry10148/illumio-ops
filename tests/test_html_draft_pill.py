"""Test draft pill appears in HTML report header when compute_draft=True."""
import pytest
from src.report.exporters.html_exporter import HtmlExporter
from src.i18n import t


def _make_html(compute_draft: bool) -> str:
    """Build a minimal HTML report and return it as a string."""
    exporter = HtmlExporter(
        results={},
        compute_draft=compute_draft,
    )
    return exporter._build()


def test_draft_pill_present_when_compute_draft():
    html = _make_html(compute_draft=True)
    assert '<span class="report-draft-pill"' in html
    assert t("rpt_hdr_draft_enabled") in html


def test_draft_pill_absent_when_not_compute_draft():
    html = _make_html(compute_draft=False)
    # The CSS class will be in the <style> block, but no <span> element should appear
    assert '<span class="report-draft-pill"' not in html


def test_draft_pill_i18n_key_resolves():
    label = t("rpt_hdr_draft_enabled")
    assert "Draft Policy Decision" in label
    assert label  # non-empty
