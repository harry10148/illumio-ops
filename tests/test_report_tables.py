import pandas as pd
from bs4 import BeautifulSoup

from src.report.exporters.table_renderer import WIDE_COL_THRESHOLD, render_df_table


def test_report_table_becomes_interactive_when_two_or_more_columns():
    df_one = pd.DataFrame([{"A": 1}])
    html_one = render_df_table(df_one, col_i18n={})
    assert 'data-interactive="false"' in html_one
    assert "report-table--interactive" not in html_one

    df_two = pd.DataFrame([{"A": 1, "B": 2}])
    html_two = render_df_table(df_two, col_i18n={})
    assert 'data-interactive="true"' in html_two
    assert "report-table--interactive" in html_two

    df_three = pd.DataFrame([{"A": 1, "B": 2, "C": 3}])
    html_three = render_df_table(df_three, col_i18n={})
    assert 'data-interactive="true"' in html_three
    assert "report-table--interactive" in html_three


def test_empty_dataframe_renders_styled_panel_not_bare_paragraph():
    """Empty data should be rendered inside the panel chrome so it visually
    matches surrounding tables instead of looking like a rendering bug."""
    html_none = render_df_table(None, col_i18n={})
    assert 'report-table-panel--empty' in html_none
    assert 'data-empty="true"' in html_none
    assert 'empty-text' in html_none
    # Must NOT regress to the legacy bare <p class="note"> form
    assert '<p class="note"' not in html_none

    html_empty = render_df_table(pd.DataFrame(), col_i18n={})
    assert 'report-table-panel--empty' in html_empty


def test_empty_panel_honors_custom_no_data_key():
    html = render_df_table(None, col_i18n={}, no_data_key="rpt_no_records")
    assert 'empty-text' in html


def test_wide_table_gets_sticky_first_column_panel_class():
    """Tables with >= WIDE_COL_THRESHOLD columns get the wide panel class
    (which the CSS uses for sticky first column + scroll affordance)."""
    cols = {f"C{i}": i for i in range(WIDE_COL_THRESHOLD)}
    df_wide = pd.DataFrame([cols])
    html_wide = render_df_table(df_wide, col_i18n={})
    assert 'report-table-panel--wide' in html_wide

    cols_narrow = {f"C{i}": i for i in range(WIDE_COL_THRESHOLD - 1)}
    df_narrow = pd.DataFrame([cols_narrow])
    html_narrow = render_df_table(df_narrow, col_i18n={})
    assert 'report-table-panel--wide' not in html_narrow


def test_compact_table_keeps_compact_class_and_skips_wide():
    df = pd.DataFrame([{"A": 1, "B": 2}])
    out = render_df_table(df, col_i18n={})
    assert 'report-table-panel--compact' in out
    assert 'report-table-panel--wide' not in out


def test_i18n_column_headers_rendered_at_build_time():
    """Column headers must render translated text directly (Python-side i18n),
    not emit data-i18n attributes for JS-side translation."""
    df = pd.DataFrame([{"Port": 53, "Connections": 1000}])
    out = render_df_table(df, col_i18n={"Port": "rpt_col_port",
                                         "Connections": "rpt_col_connections"},
                          lang="en")
    # No data-i18n attributes should appear anywhere (JS i18n removed)
    assert 'data-i18n=' not in out
    # Column header text must be inside a .th-label span
    assert 'class="th-label"' in out


def test_numeric_and_ts_columns_get_semantic_classes():
    df = pd.DataFrame({"Flows": [1, 2],
                       "Last Seen Timestamp": ["2026-01-01 10:00", "2026-01-02 11:00"]})
    html = render_df_table(df, col_i18n={}, lang="en")
    soup = BeautifulSoup(html, "html.parser")
    assert "num" in soup.select("thead th")[0].get("class", [])
    assert "col-ts" in soup.select("thead th")[1].get("class", [])
    assert "<wbr/>" in html or "<wbr>" in html


def test_ten_plus_columns_get_landscape_and_hint():
    df = pd.DataFrame({f"c{i}": [1] for i in range(11)})
    html = render_df_table(df, col_i18n={}, lang="zh_TW")
    assert "report-table-panel--landscape" in html and 'class="table-hint"' in html


def test_eight_column_wide_table_gets_a_hint_but_stays_portrait():
    """A7 ruling: the hint follows ``--wide``, matching the design prototype
    (``design/v2/tools/reskin_report.py:_wide_table_hint``), which emits a hint
    for every ``.report-table-panel--wide`` panel and adds ``--landscape`` only
    at >= 10 columns. An 8-column table scrolls horizontally on screen and must
    say so; it just prints portrait rather than landscape."""
    df = pd.DataFrame({f"c{i}": [1] for i in range(WIDE_COL_THRESHOLD)})
    html = render_df_table(df, col_i18n={}, lang="zh_TW")
    assert 'class="table-hint"' in html
    assert "report-table-panel--wide" in html
    assert "report-table-panel--landscape" not in html


def test_char_width_triggered_wide_table_also_gets_a_hint():
    """``--wide`` also fires on estimated row width, not only on column count —
    those panels scroll too, so they get the same affordance."""
    df = pd.DataFrame({c: [c * 90] for c in "ABCD"})   # 4 cols, far under 8
    html = render_df_table(df, col_i18n={}, lang="en")
    assert "report-table-panel--wide" in html
    assert 'class="table-hint"' in html
    assert "4" in html.split('class="table-hint"')[1].split("</p>")[0]


def test_narrow_table_gets_no_hint():
    df = pd.DataFrame([{"A": 1, "B": 2}])
    html = render_df_table(df, col_i18n={}, lang="en")
    assert "table-hint" not in html


def test_boolean_column_is_not_treated_as_numeric():
    """``is_numeric_dtype`` is True for bool, but a right-aligned monospace
    nowrap "True" is not a measurement — bools stay plain text cells."""
    df = pd.DataFrame({"enabled": [True, False], "hits": [3, 4]})
    soup = BeautifulSoup(render_df_table(df, col_i18n={}, lang="en"), "html.parser")
    heads = soup.select("thead th")
    assert "num" not in heads[0].get("class", [])
    assert "num" in heads[1].get("class", [])


def test_timestamp_cell_wbr_splits_date_from_time_without_losing_text():
    """CLAUDE.md report rule: the <wbr/> is a break opportunity, never a
    truncation — every character of the timestamp survives."""
    df = pd.DataFrame({"last_seen_at": ["2026-01-01T10:00:00Z"], "n": [1]})
    html = render_df_table(df, col_i18n={}, lang="en")
    soup = BeautifulSoup(html, "html.parser")
    cell = soup.select("tbody td")[0]
    assert cell.find("wbr") is not None
    assert cell.get_text("") == "2026-01-01T10:00:00Z"


def test_custom_render_cell_output_is_not_rewritten_by_the_ts_split():
    """Exporters that pass ``render_cell`` already emit HTML; the <wbr/> pass
    must not re-parse or re-escape it."""
    df = pd.DataFrame({"created_at": ["2026-01-01T10:00:00Z"], "n": [1]})
    html = render_df_table(
        df, col_i18n={}, lang="en",
        render_cell=lambda col, val, row: f"<code>{val}</code>")
    assert "<code>2026-01-01T10:00:00Z</code>" in html


def test_numeric_and_ts_classes_land_on_body_cells_too():
    df = pd.DataFrame({"hits": [1], "seen_at": ["2026-01-01T10:00:00Z"]})
    soup = BeautifulSoup(render_df_table(df, col_i18n={}, lang="en"), "html.parser")
    cells = soup.select("tbody td")
    assert "num" in cells[0].get("class", [])
    assert "col-ts" in cells[1].get("class", [])
