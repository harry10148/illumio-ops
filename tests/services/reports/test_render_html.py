import re
from datetime import UTC

import pytest

from illumio_ops.domain.report import BarBlock, Finding, Kpi, Section, TextBlock
from illumio_ops.domain.values import Language, Severity
from illumio_ops.services.reports.render_html import render_html
from illumio_ops.services.reports.svg import bar_svg
from tests.services.reports.conftest import make_doc, table


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


def test_kpi_without_a_previous_period_prints_nothing_under_the_number():
    """6.6.0 Task 1: "No previous period" under every number was noise; the data notes say it once."""
    k = Kpi(key="k", label="Pivots", value=4, previous=None)
    out = render_html(make_doc(kpis=(k,)), tz=UTC)
    assert "No previous period" not in out


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


# ── the unified first page (UI redesign spec §8) ────────────────────────────

def _first_page(**kw):
    doc = make_doc(**kw).model_copy(update={"conclusion": "Seven new connections, two into critical assets."})
    return render_html(doc, tz=UTC)


def test_first_page_order():
    out = _first_page(findings=(Finding(severity=Severity.HIGH, title="Open RDP", why="5 sources", action="Block"),))
    i_conclusion = out.index('data-role="conclusion"')
    i_kpis = out.index('class="kpi-strip"')
    i_findings = out.index('data-role="findings-table"')
    assert i_conclusion < i_kpis < i_findings
    assert "Seven new connections, two into critical assets." in out


def test_top_rule_color_is_highest_severity():
    crit = _first_page(findings=(Finding(severity=Severity.LOW, title="a", why="b", action="c"),
                                 Finding(severity=Severity.CRITICAL, title="d", why="e", action="f")))
    assert re.search(r'<header class="cover"[^>]*data-top="crit"', crit)
    none = _first_page(findings=())
    assert re.search(r'<header class="cover"[^>]*data-top="none"', none)


def test_findings_table_rows():
    out = _first_page(findings=(Finding(severity=Severity.MEDIUM, title="Open RDP", why="5 sources", action="Block"),))
    table_html = out[out.index('data-role="findings-table"'):]
    table_html = table_html[:table_html.index("</table>")]
    assert "Open RDP" in table_html and "Block" in table_html and "5 sources" in table_html


def test_sections_numbered():
    doc = make_doc(sections=(Section(id="a", title="First"), Section(id="b", title="Second")))
    out = render_html(doc, tz=UTC)
    assert ">01<" in out and ">02<" in out and "First" in out


def test_print_css_repeats_header_and_keeps_rows():
    out = _first_page()
    css = out[out.index("<style>"):out.index("</style>")]
    assert re.search(r"thead\s*\{\s*display:\s*table-header-group", css)
    assert re.search(r"tr\s*\{\s*break-inside:\s*avoid", css)


def test_no_external_requests():
    out = _first_page()
    refs = re.findall(r'(?:src|href)="(https?://[^"]+)"', out) + re.findall(r"url\((https?://[^)]+)\)", out)
    assert refs == []


def test_findings_show_mitre_chips_without_external_links():
    out = _first_page(findings=(Finding(severity=Severity.HIGH, title="SMB", why="w", action="a",
                                        techniques=(("T1021.002", "SMB/Windows Admin Shares"),)),))
    assert re.search(r'<span class="mitre-chip" title="SMB/Windows Admin Shares">T1021\.002</span>', out)


# ── 6.6.0 Task 6: presentation ───────────────────────────────────────────────

def _cols(*keys):
    from illumio_ops.domain.report import Column
    return tuple(Column(key=k, label=k.title()) for k in keys)


def _tbl(columns, rows, title="T"):
    from illumio_ops.domain.report import TableBlock
    return TableBlock(title=title, columns=columns, rows=tuple(rows), total_rows=len(rows), empty_text="-")


def test_a_share_column_draws_a_bar_of_its_length():
    t = _tbl(_cols("app", "share", "note"), [("a", "12.5%", "x"), ("b", "100.0%", "5%"), ("c", "—", "y")])
    out = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(t,)),)), tz=UTC)
    bars = re.findall(r'<progress class="share-bar" max="100" value="([^"]+)"', out)
    assert bars == ["12.5", "100"]  # the share column only: "note" mixes words and a share, a dash draws no bar
    assert 'style="' not in out  # a report page carries no inline style


def test_a_number_over_100_percent_is_not_a_share():
    t = _tbl(_cols("app", "growth"), [("a", "250.0%"), ("b", "10.0%")])
    out = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(t,)),)), tz=UTC)
    assert "share-bar" not in out.split("</style>")[-1]


def test_two_narrow_tables_share_a_row_and_a_wide_one_does_not():
    narrow = _tbl(_cols("a", "b"), [("x", 1)])
    wide = _tbl(_cols("a", "b", "c", "d"), [("x", 1, 2, 3)])
    body = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(narrow, narrow, narrow, wide)),)),
                       tz=UTC).split("</style>")[-1]
    assert body.count('class="table-pair"') == 1  # the first two; the third stands alone beside a wide one
    empty = _tbl(_cols("a", "b"), [])
    body = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(narrow, empty)),)), tz=UTC)
    assert 'class="table-pair"' not in body.split("</style>")[-1]


def test_an_action_every_row_repeats_is_said_once_above_the_table():
    same = _tbl(_cols("rule", "found", "action"), [("r1", "a", "Check the change record."),
                                                   ("r2", "b", "Check the change record.")])
    body = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(same,)),)), tz=UTC).split("</style>")[-1]
    assert body.count("Check the change record.") == 1 and 'data-role="said-once"' in body
    assert 'data-column-count="2"' in body
    differs = _tbl(_cols("rule", "found", "action"), [("r1", "a", "Do this."), ("r2", "b", "Do that.")])
    body = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(differs,)),)), tz=UTC).split("</style>")[-1]
    assert 'data-role="said-once"' not in body and 'data-column-count="3"' in body


def test_a_report_without_sections_has_no_empty_table_of_contents():
    out = render_html(make_doc(sections=()), tz=UTC).split("</style>")[-1]
    assert "Contents" not in out and "<ol>" not in out and "print-btn" in out
    out = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(TextBlock(paragraphs=("x",)),)),)), tz=UTC)
    assert "<ol>" in out.split("</style>")[-1]
