from datetime import UTC
from io import BytesIO

from openpyxl import load_workbook

from illumio_ops.domain.report import Section
from illumio_ops.services.reports.render_xlsx import render_xlsx
from tests.services.reports.conftest import make_doc, table


def _wb(doc):
    return load_workbook(BytesIO(render_xlsx(doc, tz=UTC)))


def test_xlsx_one_sheet_per_table_all_rows(doc_with_rows):
    wb = _wb(doc_with_rows(450))
    data = [ws for ws in wb.worksheets if ws.title != "Summary"]
    assert len(data) == 1 and data[0].max_row == 451  # header + every row


def test_xlsx_summary_sheet_has_kpis_and_quality():
    ws = _wb(make_doc())["Summary"]
    values = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert "Pivot hosts" in values and 3 in values and "Traffic covers the whole period." in values


def test_xlsx_neutralises_formulas(doc_with_rows):
    wb = _wb(doc_with_rows(1, cell="=cmd|' /C calc'!A0"))
    ws = next(w for w in wb.worksheets if w.title != "Summary")
    assert ws["A2"].value.startswith("'=")


def test_xlsx_sheet_names_unique_and_short():
    long = "A very long table title that exceeds thirty-one characters: [x]"
    doc = make_doc(sections=(Section(id="a", title="A", blocks=(table([("a", 1)], title=long),
                                                                table([("b", 2)], title=long))),))
    names = _wb(doc).sheetnames
    assert len(set(names)) == len(names) and all(len(n) <= 31 for n in names)
    assert not any(ch in n for n in names for ch in "[]:*?/\\")


def test_xlsx_builder_limit_note_written():
    t = table([("a", 1)], total=5).model_copy(update={"limit_note": "Only the first 1 of 5"})
    ws = next(w for w in _wb(make_doc(sections=(Section(id="s", title="S", blocks=(t,)),))).worksheets
          if w.title != "Summary")
    assert ws["A1"].value == "Only the first 1 of 5" and ws["A2"].value == "Col 0"


def test_xlsx_long_cell_kept_whole(doc_with_rows):
    ws = next(w for w in _wb(doc_with_rows(1, cell="y" * 2500)).worksheets if w.title != "Summary")
    assert ws["A2"].value == "y" * 2500 and ws["A2"].alignment.wrap_text


def test_xlsx_shortened_sheet_name_keeps_full_title():
    """A sheet name is at most 31 characters (Excel): the table's whole title is then the first row."""
    long = "Outbound connections by destination app and service"
    doc = make_doc(sections=(Section(id="a", title="A", blocks=(table([("a", 1)], title=long),
                                                                table([("b", 2)], title="Short"))),))
    wb = _wb(doc)
    first, second = (ws for ws in wb.worksheets if ws.title != "Summary")
    assert first.title != long and first["A1"].value == long and first["A2"].value == "Col 0"
    assert second.title == "Short" and second["A1"].value == "Col 0"


def test_xlsx_findings_list_mitre_techniques():
    from illumio_ops.domain.report import Finding
    from illumio_ops.domain.values import Severity
    doc = make_doc(findings=(Finding(severity=Severity.HIGH, title="SMB", why="w", action="a",
                                     techniques=(("T1486", "Data Encrypted for Impact"),)),))
    values = [c.value for row in _wb(doc)["Summary"].iter_rows() for c in row if c.value is not None]
    assert "T1486 Data Encrypted for Impact" in values


# ── stage 3a (UI redesign spec §9.1): caveats, the findings' header and six columns ──

def _summary(doc):
    ws = _wb(doc)["Summary"]
    return ws, [[c.value for c in row] for row in ws.iter_rows()]


def _row(rows, first):
    return next(i for i, r in enumerate(rows) if r and r[0] == first)


def test_xlsx_findings_have_a_header_and_six_columns():
    from illumio_ops.domain.report import Finding
    from illumio_ops.domain.values import Severity
    doc = make_doc(findings=(
        Finding(severity=Severity.HIGH, title="SMB", what="12 hosts", why="w", action="a",
                techniques=(("T1486", "Data Encrypted for Impact"),)),
        Finding(severity=Severity.LOW, title="No fact", why="w2", action="a2")))
    ws, rows = _summary(doc)
    head = _row(rows, "Severity")
    assert rows[head][:6] == ["Severity", "Finding", "What happened", "Why it matters", "What to do", "MITRE ATT&CK"]
    assert rows[head - 1][0] == "Findings"
    assert rows[head + 1][:6] == ["High", "SMB", "12 hosts", "w", "a", "T1486 Data Encrypted for Impact"]
    assert rows[head + 2][:6] == ["Low", "No fact", None, "w2", "a2", None]  # no fact: the cell is left empty
    assert ws.cell(row=head + 1, column=1).font.bold and not ws.cell(row=head + 2, column=1).font.bold


def test_xlsx_caveats_before_the_numbers_and_the_headers_stay_bold():
    plain_ws, plain = _summary(make_doc())
    assert not any(r and r[0] == "Know this before reading the numbers" for r in plain)
    doc = make_doc().model_copy(update={"caveats": ("Two stretches were not collected.", "Three days unread.")})
    ws, rows = _summary(doc)
    at = _row(rows, "Know this before reading the numbers")
    assert [rows[at + 1][0], rows[at + 2][0]] == ["Two stretches were not collected.", "Three days unread."]
    metric = _row(rows, "Metric")
    assert _row(rows, "Generated") < at < metric and rows[metric + 1][0] == "Pivot hosts"
    assert ws.cell(row=metric + 1, column=1).font.bold and ws.cell(row=at + 1, column=1).font.bold
    assert not ws.cell(row=at + 2, column=1).font.bold
    assert plain_ws.cell(row=_row(plain, "Metric") + 1, column=1).font.bold


def test_xlsx_rules_not_evaluated_are_never_nothing_to_do():
    from tests.services.reports.test_render_html import _unevaluated
    values = [r[0] for r in _summary(make_doc(sections=(_unevaluated([]),)))[1] if r]
    assert "This period has no traffic to evaluate the rules on; see “Rules not evaluated”." in values
    assert "Nothing in this report needs action this period." not in values
    assert "Nothing in this report needs action this period." in [r[0] for r in _summary(make_doc())[1] if r]


def test_xlsx_a_custom_report_has_no_findings_block():
    from illumio_ops.domain.values import ReportType
    values = [r[0] for r in _summary(make_doc(report_type=ReportType.CUSTOM, kpis=()))[1] if r]
    assert "Findings" not in values and "Nothing in this report needs action this period." not in values
