"""A cover meta value must stay with its own label.

`.cover-meta` is a CSS grid. With a bare <dt><dd><dt><dd> the four elements are
four independent grid items, so at three columns the flow placed
資料範圍 / its value / 產生時間 on the first row and left 產生時間's value alone on
the second — directly beneath 資料範圍's label, where a reader would attribute it
to the wrong field.

Conservation cannot see this: every string is still in the document, only its
position moved. It was found by rendering a real 17-page audit PDF and looking at
page one.

The assertion is on the DOM pairing rather than on rendered geometry, because
geometry needs a browser and the property that matters — "this value belongs to
that label" — is structural. A pair that is one grid item cannot be split by any
column count.
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from src.report.exporters.report_shell import ShellCover, ShellSection, build_shell_document


def _cover(meta: dict[str, str]) -> BeautifulSoup:
    html = build_shell_document(
        lang="en",
        cover=ShellCover(title="T", doc_title="T", type_label="Audit", meta=meta),
        sections=[ShellSection(id="s", title="S", html="<p>x</p>")],
    )
    return BeautifulSoup(html, "html.parser")


def test_each_label_and_value_share_one_grid_item():
    """Three pairs is the shape that broke: 6 bare items across 3 columns."""
    doc = _cover({"Data range": "2026-08-23 - 2026-08-30",
                  "Generated": "2026-08-30 16:50:33",
                  "PCE": "pce.lab.local"})
    grid = doc.select_one(".cover-meta")
    assert grid is not None

    # Every dt and dd is inside a pair wrapper, and each wrapper holds exactly
    # one of each — so the grid can never place a value away from its label.
    pairs = grid.select(".cover-meta-pair")
    assert len(pairs) == 3, [p.get_text(" ", strip=True) for p in pairs]
    for pair in pairs:
        assert len(pair.find_all("dt", recursive=False)) == 1
        assert len(pair.find_all("dd", recursive=False)) == 1

    # Nothing escaped the wrappers.
    assert grid.find_all("dt", recursive=False) == []
    assert grid.find_all("dd", recursive=False) == []


def test_the_pairs_keep_their_own_values():
    doc = _cover({"Data range": "RANGE-VALUE", "Generated": "GENERATED-VALUE"})
    got = {p.dt.get_text(strip=True): p.dd.get_text(strip=True)
           for p in doc.select(".cover-meta-pair")}
    assert got == {"Data range": "RANGE-VALUE", "Generated": "GENERATED-VALUE"}


def test_the_appendix_dl_is_left_alone():
    """It has no grid, so it never had the defect — and wrapping it would only
    add markup a plain <dl> does not need."""
    doc = _cover({"Data range": "R", "Generated": "G"})
    appendix = doc.select_one("section.appendix")
    assert appendix is not None
    assert appendix.select(".cover-meta-pair") == []
    assert appendix.select("dl dt"), "the appendix still lists the same parameters"
