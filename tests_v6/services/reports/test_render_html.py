import re
from datetime import UTC

import pytest

from illumio_ops.domain.report import BarBlock, Finding, Kpi, Section, TextBlock
from illumio_ops.domain.values import Language, Severity
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.services.reports.svg import bar_svg
from tests_v6.services.reports.conftest import make_doc, table


def test_html_caps_rows_and_says_so(doc_with_rows):
    out = render_html(doc_with_rows(450), tz=UTC)
    assert out.count("<tr data-row") == 200
    assert "450" in out and "XLSX" in out


def test_html_shows_every_row_under_the_cap(doc_with_rows):
    out = render_html(doc_with_rows(5), tz=UTC)
    assert out.count("<tr data-row") == 5 and "Showing the first" not in out


def test_html_escapes_cells(doc_with_rows):
    out = render_html(doc_with_rows(1, cell="<script>alert(1)</script>"), tz=UTC)
    assert "<script>alert(1)" not in out and "&lt;script&gt;alert(1)" in out


def test_html_long_cell_points_to_xlsx(doc_with_rows):
    out = render_html(doc_with_rows(1, cell="x" * 2500), tz=UTC)
    assert "x" * 2001 not in out and "x" * 2000 in out and "2500" in out


def test_kpi_without_value_is_not_zero():
    k = Kpi(key="k", label="Assets reachable", value=None, previous=None, note="no critical assets set")
    out = render_html(make_doc(kpis=(k,)), tz=UTC)
    kpi_html = re.search(r'<div class="kpi" data-kpi="k">.*?</div>\s*</div>', out, re.DOTALL).group(0)
    assert ">0<" not in kpi_html and "no critical assets set" in kpi_html


def test_kpi_previous_none_says_no_previous():
    k = Kpi(key="k", label="Pivots", value=4, previous=None)
    out = render_html(make_doc(kpis=(k,)), tz=UTC)
    assert "No previous period" in out


def test_kpi_previous_delta_shown():
    out = render_html(make_doc(), tz=UTC)  # 3 vs 1
    assert "▲ 2" in out


def test_html_is_self_contained():
    out = render_html(make_doc(), tz=UTC)
    assert "<link " not in out and 'src="http' not in out and "<style>" in out and "<script>" in out


def test_empty_table_says_why():
    doc = make_doc(sections=(Section(id="s", title="S", blocks=(table([]),)),))
    out = render_html(doc, tz=UTC)
    assert "Nothing here" in out and "<tr data-row" not in out


def test_builder_limit_note_is_shown():
    t = table([("a", 1)], total=5).model_copy(update={"limit_note": "Only the first 1 of 5 are listed"})
    out = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(t,)),)), tz=UTC)
    assert "Only the first 1 of 5 are listed" in out


def test_findings_and_quality_and_text_rendered():
    doc = make_doc(findings=(Finding(severity=Severity.HIGH, title="fin-db-01 newly reachable",
                                     why="It holds payroll", action="Cut bak-01 to fin-db-01 RDP"),),
                   sections=(Section(id="t", title="T", blocks=(TextBlock(paragraphs=("Para one",)),)),))
    out = render_html(doc, tz=UTC)
    for text in ("fin-db-01 newly reachable", "It holds payroll", "Cut bak-01", "Para one",
                 "Traffic covers the whole period."):
        assert text in out


def test_zh_tw_chrome():
    out = render_html(make_doc(lang=Language.ZH_TW), tz=UTC)
    assert 'lang="zh-TW"' in out and "上期" in out


def test_gui_link_only_when_set():
    assert "https://ops.example/reports?id=7" in render_html(
        make_doc(gui_link="https://ops.example/reports?id=7"), tz=UTC)


@pytest.mark.parametrize("n,shown", [(3, 3), (120, 90)])
def test_bars_capped_with_note(n, shown):
    pts = tuple((f"d{i}", i + 1) for i in range(n))
    out = render_html(make_doc(sections=(Section(id="b", title="B", blocks=(
        BarBlock(title="Trend", points=pts, empty_text="none"),)),)), tz=UTC)
    assert out.count("<rect") == shown
    assert ("90" in out.split("Trend", 1)[1]) == (n > 90)


def test_bars_none_is_gap_not_zero():
    svg = bar_svg((("d1", 3), ("d2", None), ("d3", 5)))
    assert svg.count("<rect") == 2


def test_bars_escape_labels():
    svg = bar_svg((("<b>", 1),))
    assert "<b>" not in svg


def test_long_tables_may_break_across_printed_pages():
    out = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(table([(f"h{i}", i) for i in range(40)]),)),)),
                      tz=UTC)
    assert 'report-table-panel--long' in out and "break-inside: auto" in out


def test_bar_width_capped():
    import re as _re
    svg = bar_svg((("d1", 3),))
    widths = [float(w) for w in _re.findall(r'<rect [^>]*width="([\d.]+)"', svg)]
    assert widths and max(widths) <= 40
