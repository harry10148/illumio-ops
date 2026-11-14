import re
from datetime import UTC

import pytest

from illumio_ops.domain.report import (
    PRINT_ROW_CAP,
    BarBlock,
    Column,
    Finding,
    Kpi,
    Section,
    TableBlock,
    TextBlock,
)
from illumio_ops.domain.values import Language, ReportType, Severity
from illumio_ops.services.reports.finish import finish
from illumio_ops.services.reports.render_html import host_url, kpi_trend, render_html
from illumio_ops.services.reports.svg import bar_svg
from tests.services.reports.conftest import make_doc, table
from tests.services.reports.dom import dom as _dom


def test_html_caps_rows_and_says_so(doc_with_rows):
    out = render_html(doc_with_rows(450), tz=UTC)
    assert out.count("<tr data-row") == 200
    assert "450" in out and "XLSX" in out


def test_html_shows_every_row_under_the_cap(doc_with_rows):
    out = render_html(doc_with_rows(5), tz=UTC)
    assert out.count("<tr data-row") == 5 and "rows are listed here" not in out
    assert "rows are listed here" in render_html(doc_with_rows(201), tz=UTC)  # the words a cut table does say


def test_html_escapes_cells(doc_with_rows):
    out = render_html(doc_with_rows(1, cell="<script>alert(1)</script>"), tz=UTC)
    assert "<script>alert(1)" not in out and "&lt;script&gt;alert(1)" in out


def test_html_long_cell_points_to_xlsx(doc_with_rows):
    out = render_html(doc_with_rows(1, cell="x" * 2500), tz=UTC)
    assert "x" * 2001 not in out and "x" * 2000 in out and "2500" in out


def test_kpi_without_value_is_not_zero():
    k = Kpi(key="k", label="Assets reachable", value=None, previous=None, note="no critical assets set")
    out = render_html(make_doc(kpis=(k,)), tz=UTC)
    page = _dom(out)
    cell = page.one("data-kpi", "k")
    assert cell.text_of("data-role", "kpi-value") == "No data"
    assert "no critical assets set" not in cell.text()  # the reason is under the row, so the cells stay level
    assert page.one("data-role", "lead-notes").text() == "Assets reachable: no critical assets set"


def test_kpi_without_a_previous_period_prints_nothing_under_the_number():
    """6.6.0 Task 1: "No previous period" under every number was noise; the data notes say it once."""
    k = Kpi(key="k", label="Pivots", value=4, previous=None)
    out = render_html(make_doc(kpis=(k,)), tz=UTC)
    assert "No previous period" not in out


def test_kpi_previous_delta_shown():
    out = render_html(make_doc(), tz=UTC)  # 3 vs 1
    assert "Up 2 from the previous period" in out and "▲" not in out.split("</style>")[-1].split("<script>")[0]


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
    notes = _dom(out).one("id", "notes")  # the data notes are the report's closing chapter, not on its first page
    assert notes.find("h2")[0].text() == "Data notes" and [li.text() for li in notes.find("li")] == [
        "Traffic covers the whole period."]


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
    i_kpis = out.index('data-role="lead-kpis"')
    i_findings = out.index('data-role="findings"')
    assert i_conclusion < i_kpis < i_findings
    assert "Seven new connections, two into critical assets." in out


def test_top_rule_color_is_highest_severity():
    crit = _first_page(findings=(Finding(severity=Severity.LOW, title="a", why="b", action="c"),
                                 Finding(severity=Severity.CRITICAL, title="d", why="e", action="f")))
    assert re.search(r'<header class="cover"[^>]*data-top="crit"', crit)
    none = _first_page(findings=())
    assert re.search(r'<header class="cover"[^>]*data-top="none"', none)


def test_a_finding_is_a_card_with_its_three_parts():
    out = _first_page(findings=(Finding(severity=Severity.MEDIUM, title="Open RDP", why="5 sources", action="Block",
                                        what="RDP is open from 5 sources."),))
    card = _dom(out).one("data-role", "finding")
    assert card.attrs["data-severity"] == "medium" and card.attrs["id"] == "finding-1"
    assert card.find("h3")[0].text() == "Medium Open RDP"
    assert [(d.text(), v.text()) for d, v in zip(card.find("dt"), card.find("dd"), strict=True)] == [
        ("What happened", "RDP is open from 5 sources."), ("Why it matters", "5 sources"),
        ("What to do", "See number 1 above. Block")]


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
    out = render_html(make_doc(sections=(), data_quality=()), tz=UTC).split("</style>")[-1]
    assert "Contents" not in out and "<ol>" not in out and "print-btn" in out
    out = render_html(make_doc(sections=(Section(id="s", title="S", blocks=(TextBlock(paragraphs=("x",)),)),)), tz=UTC)
    assert "<ol>" in out.split("</style>")[-1]


def test_without_an_xlsx_beside_it_the_html_keeps_its_rows():
    """A table that leaves rows to the XLSX (html_rows) prints them when no XLSX is made, and a cut table does not
    point at a sheet that does not exist."""
    t = _tbl(_cols("a", "b"), [(f"row{i}", i) for i in range(3)]).model_copy(
        update={"html_rows": 0, "html_note": "Left to the sheet."})
    doc = make_doc(sections=(Section(id="s", title="S", blocks=(t,)),))
    with_xlsx = render_html(doc, tz=UTC).split("</style>")[-1]
    assert "row2" not in with_xlsx and "Left to the sheet." in with_xlsx and 'data-role="xlsx-only"' in with_xlsx
    alone = render_html(doc, tz=UTC, xlsx=False).split("</style>")[-1]
    assert "row2" in alone and "Left to the sheet." not in alone and "XLSX" not in alone
    long = make_doc(sections=(Section(id="s", title="S", blocks=(_tbl(_cols("a", "b"), [(f"r{i}", i) for i in range(260)]),)),))
    cut = render_html(long, tz=UTC, xlsx=False).split("</style>")[-1]
    assert "no XLSX was made" in cut and "XLSX sheet" not in cut


# ── stage 3a Task 6: the first page, cards, the closing part, paper, host links ──────────────────



def _body(out):
    return out.split("</style>")[-1].split("<script>")[0]


def _kpis(n):
    return tuple(Kpi(key=f"k{i}", label=f"Number {i}", value=10 * (i + 1), previous=None) for i in range(n))


def _f(title, code=None, severity=Severity.HIGH, **kw):
    kw.setdefault("why", f"why {title}")
    kw.setdefault("action", f"do {title}")
    if code is not None:
        kw.setdefault("action_short", f"Short {code}.")
    return Finding(severity=severity, title=title, action_code=code, **kw)


def _unevaluated(rows):
    """The closing rules section as findings.unevaluated_section builds it: a table of the rules not evaluated
    (empty: the rules did not run)."""
    cols = tuple(Column(key=k, label=k) for k in ("rule", "found"))
    return Section(id="findings", title="Rules not evaluated", blocks=(TableBlock(
        title="Rules", columns=cols, rows=tuple(rows), total_rows=len(rows), empty_text="The rules did not run."),))


def test_the_page_runs_from_the_conclusion_to_how_to_read_it():
    how = Section(id="how", title="How the score is made", blocks=(TextBlock(paragraphs=("x",)),))
    doc = make_doc(
        kpis=_kpis(5), findings=(_f("Open RDP", "enforce"),),
        sections=(how, _unevaluated([("L006", "no exposure analysis")]),
                  Section(id="hosts", title="Hosts", blocks=(table([("a", 1)]),)),
                  Section(id="nothing", title="Nothing to show this period", blocks=(TextBlock(paragraphs=("y",)),)),
                  Section(id="ports", title="Ports", blocks=(table([("b", 2)]),))),
    ).model_copy(update={"conclusion": "One thing to do.", "caveats": ("Two stretches were not collected.",)})
    out = _body(render_html(doc, tz=UTC))
    marks = ['data-role="conclusion"', 'data-role="caveats"', 'data-role="lead-kpis"', 'data-role="top-actions"',
             'data-role="findings"', 'data-role="other-kpis"', 'data-shell="toc"', 'id="hosts"', 'id="ports"',
             'id="findings"', 'data-role="how-part"', 'id="how"', 'id="notes"', 'id="nothing"']
    places = [out.index(m) for m in marks]
    assert places == sorted(places), list(zip(marks, places, strict=True))
    page = _dom(out)
    chapters = [(c.attrs["id"], c.text_of("class", "chapter-index")) for c in page.find_attr("data-shell", "detail")]
    assert chapters == [("hosts", "S01"), ("ports", "S02"), ("findings", "S03"), ("how", "S04"), ("notes", "S05"),
                        ("nothing", "S06")]
    toc = page.one("data-shell", "toc")
    assert [a.attrs["href"] for a in toc.find("a")] == ["#hosts", "#ports", "#findings", "#how", "#notes", "#nothing"]
    assert [li.text() for li in toc.find("li")][3:5] == ["How to read this report", "04How the score is made"]
    assert page.one("data-role", "how-part").text() == "How to read this report"


def test_a_report_without_a_closing_part_has_no_heading_for_it():
    out = _body(render_html(make_doc(data_quality=(), sections=(Section(id="hosts", title="Hosts"),)), tz=UTC))
    assert 'data-role="how-part"' not in out and 'id="notes"' not in out and "How to read this report" not in out


@pytest.mark.parametrize("n,lead,other", [(5, 3, 2), (3, 3, 0), (1, 1, 0), (0, 0, 0)])
def test_three_numbers_lead_and_the_others_follow(n, lead, other):
    page = _dom(render_html(make_doc(kpis=_kpis(n)), tz=UTC))
    blocks = page.find_attr("data-role", "lead-kpis")
    assert len(blocks) == (1 if lead else 0)
    if lead:
        assert [c.attrs["data-kpi"] for c in blocks[0].find_attr("data-role", "lead-kpi")] == [f"k{i}" for i in range(lead)]
        assert blocks[0].attrs["data-count"] == str(lead)
    rest = page.find_attr("data-role", "other-kpis")
    assert len(rest) == (1 if other else 0)
    if other:
        assert [c.attrs["data-kpi"] for c in rest[0].find_attr("class", "kpi")] == ["k3", "k4"]
        assert rest[0].find("h2")[0].text() == "Other numbers"


def test_a_lead_number_says_its_change_and_which_way_is_better():
    kpis = (Kpi(key="a", label="A", value=4, previous=None, better="higher"),
            Kpi(key="b", label="B", value=5, previous=5, better="lower"),
            Kpi(key="c", label="C", value=9948, previous=7125),
            Kpi(key="d", label="D", value=40.5, previous=43.0, unit="percent", better="higher"))
    page = _dom(render_html(make_doc(kpis=kpis), tz=UTC))

    def lines(key):
        cell = page.one("data-kpi", key)
        return [x.text() for x in cell.find_attr("data-role", "kpi-change")], [
            x.text() for x in cell.find_attr("data-role", "kpi-better")]
    assert lines("a") == ([], ["Higher is better"])  # no previous period: the line is not written at all
    assert lines("b") == (["Unchanged from the previous period"], ["Lower is better"])
    assert lines("c") == (["Up 2,823 from the previous period"], [])  # neutral: no direction
    assert page.one("data-kpi", "c").text_of("data-role", "kpi-value") == "9,948"
    # the fourth number is one of the others: the same sentence, a percentage in points
    assert page.one("data-kpi", "d").text_of("class", "kpi-trend") == "Down 2.5 percentage points from the previous period"
    zh = [kpi_trend(k, Language.ZH_TW) for k in kpis]
    assert zh == ["", "與上期持平", "比上期多 2,823", "比上期少 2.5 個百分點"]


def test_a_note_of_a_lead_number_is_under_the_row_with_its_name():
    kpis = (Kpi(key="a", label="Maturity", value=47, previous=None, note="Out of 100."),
            Kpi(key="b", label="Hosts", value=3, previous=None),
            Kpi(key="c", label="Flows", value=None, previous=None, note="<script>x</script>"))
    out = render_html(make_doc(kpis=kpis), tz=UTC)
    page = _dom(out)
    assert [p.text() for p in page.one("data-role", "lead-notes").find("p")] == [
        "Maturity: Out of 100.", "Flows: <script>x</script>"]
    assert "<script>x</script>" not in _body(out)
    assert page.find_attr("data-role", "lead-notes")[0].find_attr("class", "kpi-note") == []
    assert _dom(render_html(make_doc(kpis=kpis[1:2]), tz=UTC)).find_attr("data-role", "lead-notes") == []


SIX = (_f("Ransomware ports open", "enforce", Severity.CRITICAL, action_focus="Mostly dc (65)."),
       _f("Lateral ports open", "enforce", Severity.HIGH, action_focus="Mostly web (12)."),
       _f("One account, many hosts", "accounts", Severity.HIGH),
       _f("Unmanaged into databases", "unmanaged", Severity.MEDIUM),
       _f("Old protocols", "legacy_protocols", Severity.LOW),
       _f("Extra lateral finding", "enforce", Severity.MEDIUM, action_focus="A third sentence."))


def test_six_findings_in_four_things_to_do():
    out = render_html(make_doc(findings=SIX), tz=UTC)
    page = _dom(out)
    top = page.one("data-role", "top-actions")
    assert top.find("h2")[0].text() == "What to do first (3)"
    items = top.find_attr("data-role", "top-action")
    assert [i.text_of("data-role", "action-short") for i in items] == ["Short enforce.", "Short accounts.",
                                                                       "Short unmanaged."]
    assert [i.text_of("class", "badge") for i in items] == ["Critical", "High", "Medium"]
    assert items[0].text_of("data-role", "action-solves") == (
        "Findings this addresses (3): Ransomware ports open, Lateral ports open, Extra lateral finding")
    assert [p.text() for p in items[0].find_attr("data-role", "action-focus")] == ["Mostly dc (65).", "Mostly web (12)."]
    assert top.text_of("data-role", "actions-more") == "1 more to do; see the findings below."
    # every link in a thing to do opens the card whose title it shows
    cards = {c.attrs["id"]: c for c in page.find_attr("data-role", "finding")}
    assert len(cards) == 6
    links = [a for i in items for a in i.find("a")]
    assert len(links) == 5
    for a in links:
        assert cards[a.attrs["href"][1:]].find("h3")[0].text().endswith(a.text())
    # the cards: every finding, the most severe first, each saying which thing to do it belongs to
    order = [c.find("h3")[0].text() for c in page.find_attr("data-role", "finding")]
    assert order == ["Critical Ransomware ports open", "High Lateral ports open", "High One account, many hosts",
                     "Medium Unmanaged into databases", "Medium Extra lateral finding", "Low Old protocols"]

    def do(title):
        card = next(c for c in cards.values() if c.find("h3")[0].text().endswith(title))
        return card.find("dd")[-1].text()
    assert do("One account, many hosts") == "See number 2 above. do One account, many hosts"
    assert do("Extra lateral finding") == "See number 1 above. do Extra lateral finding"
    assert do("Old protocols") == "do Old protocols"  # the fourth thing is not on the first page
    assert page.one("data-role", "findings").find("h2")[0].text() == "Findings (6, most severe first)"


def test_one_thing_with_six_findings_lists_four_titles_and_counts_the_rest():
    doc = make_doc(findings=tuple(_f(f"Finding {i}", "enforce") for i in range(6)))
    top = _dom(render_html(doc, tz=UTC)).one("data-role", "top-actions")
    assert top.find("h2")[0].text() == "What to do first (1)"
    assert top.text_of("data-role", "action-solves") == (
        "Findings this addresses (6): Finding 0, Finding 1, Finding 2, Finding 3, and 2 more")
    assert top.find_attr("data-role", "actions-more") == []


def test_no_finding_is_one_sentence_without_a_list_or_cards():
    page = _dom(render_html(make_doc(), tz=UTC))
    top = page.one("data-role", "top-actions")
    assert top.text() == "Nothing in this report needs action this period."
    assert top.find("ol") == [] and page.find_attr("data-role", "findings") == []
    assert page.find_attr("data-role", "finding") == []


def test_a_rule_not_evaluated_is_never_said_as_nothing_to_do():
    """The four cases of (findings or none) x (rules not evaluated or rules not run)."""
    held = _unevaluated([("L006", "no exposure analysis")])
    not_run = _unevaluated([])

    def top(findings, section):
        page = _dom(render_html(make_doc(findings=findings, sections=(section,)), tz=UTC))
        return page.one("data-role", "top-actions")
    two = (_f("A", "enforce"), _f("B", "accounts"))
    t = top(two, held)
    assert len(t.find_attr("data-role", "top-action")) == 2
    said = t.one("data-role", "actions-unevaluated")
    assert said.text() == "Rules that could not be evaluated: 1; see “Rules not evaluated”."
    assert said.find("a")[0].attrs["href"] == "#findings"
    assert "Nothing in this report needs action" not in t.text()
    # no finding, a rule not evaluated (every flow report on a lightweight install): "nothing needs action" is for
    # a report whose rules were all evaluated, so only the rule left out is said
    t = top((), held)
    assert t.text() == "Rules that could not be evaluated: 1; see “Rules not evaluated”."
    assert t.find("a")[0].attrs["href"] == "#findings"
    # the rules did not run at all: only that
    t = top((), not_run)
    assert t.text() == "This period has no traffic to evaluate the rules on; see “Rules not evaluated”."
    assert t.find("a")[0].attrs["href"] == "#findings"
    # the rules did not run, another part of the report found something
    t = top(two, not_run)
    assert len(t.find_attr("data-role", "top-action")) == 2
    assert t.text_of("data-role", "actions-unevaluated") == (
        "This period has no traffic to evaluate the rules on; see “Rules not evaluated”.")
    zh = _dom(render_html(make_doc(lang=Language.ZH_TW, findings=(), sections=(not_run,)), tz=UTC))
    assert "本期沒有需要處理的項目" not in zh.text()
    assert zh.one("data-role", "top-actions").text() == "這段期間沒有流量可以評估規則，見〈Rules not evaluated〉。"


def test_a_custom_report_has_no_things_to_do_and_no_cards():
    doc = make_doc(report_type=ReportType.CUSTOM, kpis=(), findings=(),
                   sections=(Section(id="s1", title="Ranking", blocks=(table([("a", 1)]),)),)).model_copy(
        update={"conclusion": "3 sections."})
    out = _body(render_html(doc, tz=UTC))
    for role in ("top-actions", "findings", "lead-kpis", "other-kpis"):
        assert f'data-role="{role}"' not in out
    assert 'data-role="conclusion"' in out and 'href="#s1"' in out
    assert "Nothing in this report needs action" not in out


def test_a_card_has_no_empty_part():
    doc = make_doc(findings=(Finding(severity=Severity.LOW, title="Only a title", why="", action="Look at it."),))
    card = _dom(render_html(doc, tz=UTC)).one("data-role", "finding")
    assert [d.text() for d in card.find("dt")] == ["What to do"]
    assert all(d.text() for d in card.find("dd"))


def _host_table(n, **kw):
    cols = (Column(key="host", label="Host", kind="host"), Column(key="count", label="Count", kind="number"))
    return TableBlock(title="Hosts", columns=cols, rows=tuple((f"h{i}", i) for i in range(n)), total_rows=n,
                      empty_text="-", **kw)


def _printed(doc, **kw):
    page = _dom(render_html(doc, tz=UTC, **kw))
    return page.find("table"), [p.text() for p in page.find_attr("data-role", "print-capped")]


def test_paper_lists_ten_rows_and_says_where_the_rest_is():
    assert PRINT_ROW_CAP == 10

    def doc(t, section="hosts"):
        return make_doc(sections=(Section(id=section, title="S", blocks=(t,)),))
    tables, said = _printed(doc(_host_table(12)))
    assert tables[0].attrs["data-print-cap"] == "10"
    assert said == ["Print lists the first 10 rows of 12; every row is in the XLSX sheet “Hosts”."]
    assert len(tables[0].find("tbody")[0].find("tr")) == 12  # the screen keeps them all
    tables, said = _printed(doc(_host_table(10)))
    assert "data-print-cap" not in tables[0].attrs and said == []
    tables, said = _printed(doc(_host_table(12, html_rows=5, html_note="The rest is in the sheet.")))
    assert "data-print-cap" not in tables[0].attrs and said == []
    tables, said = _printed(doc(_host_table(12)), xlsx=False)
    assert said == ["Print lists the first 10 rows; this report on screen lists the first 12 of 12."]
    tables, said = _printed(doc(_host_table(260)), xlsx=False)
    assert said == ["Print lists the first 10 rows; this report on screen lists the first 200 of 260."]
    # the tables of "how to read this report" explain, they are not data: paper prints them whole
    tables, said = _printed(doc(_host_table(12), section="how"))
    assert "data-print-cap" not in tables[0].attrs and said == []
    css = render_html(doc(_host_table(12)), tz=UTC).split("<style>")[1].split("</style>")[0]
    assert re.search(r"table\[data-print-cap\] tbody tr:nth-child\(n\+11\)\s*\{\s*display:\s*none", css)


@pytest.mark.parametrize("key,section,expected", [
    ("/orgs/1/workloads/3f2a-b1", "status", "https://ops.example/hosts?key=%2Forgs%2F1%2Fworkloads%2F3f2a-b1#status"),
    ("ip:10.0.0.5", None, "https://ops.example/hosts?key=ip%3A10.0.0.5"),
    ("ip:fe80::1%eth0", "connections", "https://ops.example/hosts?key=ip%3Afe80%3A%3A1%25eth0#connections"),
    # the characters Python's urlencode and the browser's URLSearchParams write differently
    ("/orgs/12/workloads/a b~*+&=c", None,
     "https://ops.example/hosts?key=%2Forgs%2F12%2Fworkloads%2Fa+b%7E*%2B%26%3Dc"),
])
def test_host_url_is_the_one_the_console_makes(key, section, expected):
    """The expected strings are `new URLSearchParams({key}).toString()` run in node (web/src HostLink.tsx hostPath)."""
    assert host_url("https://ops.example", key, section) == expected


def test_host_url_only_for_what_the_host_page_opens():
    assert host_url(None, "ip:10.0.0.5", None) is None and host_url("", "ip:10.0.0.5", None) is None
    assert host_url("https://ops.example", "/orgs/1/container_workloads/x", "status") is None
    assert host_url("https://ops.example", "/orgs/1/kubernetes_workloads/x", None) is None
    assert host_url("https://ops.example", "x/orgs/1/workloads/a", None) is None


def _linked(gui_base, t):
    doc = make_doc(sections=(Section(id="s", title="S", blocks=(t,)),)).model_copy(update={"gui_base": gui_base})
    return _dom(render_html(doc, tz=UTC))


def test_a_host_in_a_table_leads_to_its_page():
    keys = ("/orgs/1/workloads/a", None, "/orgs/1/container_workloads/c", "ip:10.0.0.9")
    t = _host_table(4, host_keys={"host": keys}, host_section="status")
    rows = _linked("https://ops.example", t).find("tbody")[0].find("tr")
    links = [[(a.attrs["href"], a.text(), a.attrs["data-role"]) for a in r.find("a")] for r in rows]
    assert links == [[(host_url("https://ops.example", keys[0], "status"), "h0", "host-link")], [], [],
                     [("https://ops.example/hosts?key=ip%3A10.0.0.9#status", "h3", "host-link")]]
    assert [r.find("td")[0].text() for r in rows] == ["h0", "h1", "h2", "h3"]  # a cell without a link is its text
    assert _linked(None, t).find_attr("data-role", "host-link") == []


def test_links_follow_the_column_key_when_a_column_is_left_out():
    cols = (Column(key="action", label="Action"), Column(key="src", label="Source", kind="host"),
            Column(key="dst", label="Destination", kind="host"), Column(key="n", label="N", kind="number"))
    rows = tuple(("Check it.", f"s{i}", f"d{i}", i) for i in range(3))
    t = TableBlock(title="T", columns=cols, rows=rows, total_rows=3, empty_text="-",
                   host_keys={"dst": tuple(f"/orgs/1/workloads/d{i}" for i in range(3)),
                              "src": (None, "ip:10.0.0.1")},  # shorter than the rows: the third row has no key
                   host_section="connections")
    page = _linked("https://ops.example", t)
    assert page.find_attr("data-role", "said-once") != []  # the action column is said once and left out
    got = [[(a.text(), a.attrs["href"]) for a in r.find("a")] for r in page.find("tbody")[0].find("tr")]
    def url(key):
        return host_url("https://ops.example", key, "connections")
    assert got == [[("d0", url("/orgs/1/workloads/d0"))],
                   [("s1", url("ip:10.0.0.1")), ("d1", url("/orgs/1/workloads/d1"))],
                   [("d2", url("/orgs/1/workloads/d2"))]]


def test_everything_from_the_data_is_escaped():
    x = "<script>alert(1)</script>"
    t = _host_table(1, host_keys={"host": ("/orgs/1/workloads/a",)}).model_copy(update={"rows": ((x, 1),)})
    doc = make_doc(findings=(Finding(severity=Severity.HIGH, title=x, why=x, action=x, what=x, action_code="enforce",
                                     action_short=x, action_focus=x, techniques=((x, x),)),),
                   kpis=(Kpi(key="k", label=x, value=1, previous=None, note=x),), data_quality=(x,),
                   sections=(Section(id="s", title=x, intro=x, blocks=(t,)),)).model_copy(
        update={"caveats": (x,), "conclusion": x, "gui_base": "https://ops.example/\"><script>"})
    body = _body(render_html(doc, tz=UTC))
    assert "<script" not in body and body.count("&lt;script&gt;alert(1)") >= 12


def test_the_caveats_are_under_the_conclusion_one_line_each():
    doc = make_doc().model_copy(update={"caveats": ("First.", "Second.")})
    block = _dom(render_html(doc, tz=UTC)).one("data-role", "caveats")
    assert block.find("strong")[0].text() == "Know this before reading the numbers" and [
        p.text() for p in block.find("p")] == ["First.", "Second."]
    assert 'data-role="caveats"' not in _body(render_html(make_doc(), tz=UTC))


def test_notes_is_a_reserved_section_id():
    with pytest.raises(ValueError, match="reserved"):
        make_doc(sections=(Section(id="notes", title="N"),))


def test_no_host_links_is_said_once_in_the_data_notes():
    linked = _host_table(2, host_keys={"host": ("/orgs/1/workloads/a", None)})
    containers = _host_table(2, host_keys={"host": ("/orgs/1/container_workloads/a", None)})
    sentence = "The console's external address is not set, so the hosts named in this report are not links."

    def notes(t, base):
        doc = make_doc(sections=(Section(id="s", title="S", blocks=(t,)),)).model_copy(update={"gui_base": base})
        return finish(doc).data_quality
    assert notes(linked, None)[-1] == sentence and notes(linked, None).count(sentence) == 1
    assert sentence not in notes(linked, "https://ops.example")
    assert sentence not in notes(containers, None)  # nothing here would have been a link
    assert sentence not in notes(_host_table(2), None)


def test_print_does_not_force_a_page_per_part():
    css = render_html(make_doc(), tz=UTC).split("<style>")[1].split("</style>")[0]
    tail = css[css.rindex("/* stage 3a print */"):]
    for rule in (r"\.cover\s*\{[^}]*break-after:\s*auto", r"\.toc\s*\{[^}]*break-after:\s*auto",
                 r"\.chapter\s*\{[^}]*break-before:\s*auto", r"\.finding\s*\{[^}]*break-inside:\s*avoid"):
        assert re.search(rule, tail), rule


@pytest.mark.parametrize("lang", [Language.EN, Language.ZH_TW])
def test_rules_that_did_not_run_are_still_said_after_finish(lang):
    """finish() folds a section that holds nothing into the closing list. The rules section of a report whose
    rules did not run is such a section (an empty table) — folded, the first page lost the only thing that told it
    the rules were never evaluated, and said nothing needs action."""
    rules = _unevaluated([])
    doc = finish(make_doc(lang=lang, findings=(), sections=(Section(id="hosts", title="Hosts", blocks=(table([("a", 1)]),)),
                                                            rules)))
    assert [s.id for s in doc.sections] == ["hosts", "findings"]
    page = _dom(render_html(doc, tz=UTC))
    top = page.one("data-role", "top-actions")
    assert top.text() == {Language.EN: "This period has no traffic to evaluate the rules on; see “Rules not evaluated”.",
                          Language.ZH_TW: "這段期間沒有流量可以評估規則，見〈Rules not evaluated〉。"}[lang]
    assert "Nothing in this report needs action" not in page.text() and "本期沒有需要處理的項目" not in page.text()
    chapter = page.one("id", "findings")  # where the sentence's link lands: the section, saying why it is empty
    assert top.find("a")[0].attrs["href"] == "#findings" and "The rules did not run." in chapter.text()


# ── what a column sorts by on screen (report_table.js reads data-sort, never the printed text) ──────────────

def _sorts(columns, rows):
    block = TableBlock(title="T", columns=columns, rows=tuple(rows), total_rows=len(rows), empty_text="none")
    root = _dom(render_html(make_doc(sections=(Section(id="s", title="S", blocks=(block,)),)), tz=UTC))
    types = [th.attrs.get("data-sort-type") for th in root.find("th")]
    cells = [[td.attrs.get("data-sort") for td in row.find("td")] for row in root.find("tbody")[0].find("tr")]
    return types, [list(col) for col in zip(*cells, strict=True)]


def test_a_cell_carries_the_number_or_the_time_it_sorts_by():
    columns = (Column(key="n", label="N", kind="number"), Column(key="at", label="At", kind="time"),
               Column(key="share", label="Share"), Column(key="size", label="Size"), Column(key="rate", label="Rate"))
    types, by = _sorts(columns, [(1204, "2026-10-22T03:00:00+00:00", "12.5%", "900 KB", "1,204.5"),
                                 (0.5, "2026-10-22T03:00:01.000+00:00", "100.0%", "1.5 GB", "7"),
                                 (None, None, "—", "", "—")])
    assert types == ["number"] * 5
    assert by[0] == ["1204", "0.5", ""]  # the value itself, not "1,204"; nothing for no value
    assert float(by[1][1]) - float(by[1][0]) == 1 and by[1][2] == ""  # a second apart: every digit is written
    assert by[2] == ["12.5", "100.0", ""]
    assert by[3] == ["900000.0", "1500000000.0", ""]  # sizes in different units: in bytes
    assert by[4] == ["1204.5", "7.0", ""]


def test_a_column_that_is_not_all_numbers_sorts_by_its_text_and_marks_only_its_empty_cells():
    columns = (Column(key="host", label="Host", kind="host"), Column(key="when", label="When", kind="time"),
               Column(key="mixed", label="Mixed"), Column(key="units", label="Units"), Column(key="none", label="None"))
    types, by = _sorts(columns, [("web-1", "not a time", "12", "3 hosts", None), ("10.0.0.1", "2026-10-22T03:00:00+00:00", "n/a", "2 MB", ""),
                                 ("", None, "—", "5 hosts", "—")])
    assert types == ["text"] * 5  # an address, a time that cannot be read, a word among numbers, units that do not compare, nothing
    assert by == [[None, None, ""], [None, None, ""], [None, None, ""], [None, None, None], ["", "", ""]]


def test_a_time_sorts_by_the_instant_whatever_zone_it_is_printed_in():
    columns = (Column(key="host", label="Host"), Column(key="at", label="At", kind="time"))
    _, by = _sorts(columns, [("a", "2026-10-22T03:00:00+00:00"), ("b", "2026-10-22T04:00:00+02:00"), ("c", "2026-10-22T03:00:01Z")])
    assert float(by[1][0]) - float(by[1][1]) == 3600 and float(by[1][2]) - float(by[1][0]) == 1


def test_a_table_of_one_row_or_one_column_has_no_sort_button_and_no_sort_value():
    one_row = _dom(render_html(make_doc(sections=(Section(id="s", title="S", blocks=(table([("a", 1)]),)),)), tz=UTC))
    assert one_row.find("button") == [b for b in one_row.find("button") if "print-btn" in b.attrs.get("class", "")]
    assert all("data-sort" not in td.attrs for td in one_row.find("td"))
    assert all("aria-sort" not in th.attrs for th in one_row.find("th"))
    two = _dom(render_html(make_doc(sections=(Section(id="s", title="S", blocks=(table([("a", 1), ("b", 2)]),)),)), tz=UTC))
    headers = two.find("th")
    assert [th.attrs["aria-sort"] for th in headers] == ["none", "none"]
    assert [th.find("button")[0].text() for th in headers] == ["Col 0", "Col 1"]  # the button's name is the column's
