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


def _draft_badge() -> str:
    """The exact cover badge the draft flag must produce.

    The pill moved from the summary hero onto the v2 shell cover's badge row,
    so it is a ``.badge`` with a warn tone now, not ``.report-draft-pill``.
    Matching the whole element (not just the label) keeps this a markup guard:
    the label alone also lives in the CSS-free parts of other reports.
    """
    return f'<span class="badge" data-tone="warn">{t("rpt_hdr_draft_enabled")}</span>'


def test_draft_pill_present_when_compute_draft():
    html = _make_html(compute_draft=True)
    assert _draft_badge() in html
    assert t("rpt_hdr_draft_enabled") in html


def test_draft_pill_absent_when_not_compute_draft():
    html = _make_html(compute_draft=False)
    # The label must not appear at all — there is no stylesheet copy of it.
    assert _draft_badge() not in html
    assert t("rpt_hdr_draft_enabled") not in html


def test_draft_pill_i18n_key_resolves():
    label = t("rpt_hdr_draft_enabled")
    assert "Draft Policy Decision" in label
    assert label  # non-empty
