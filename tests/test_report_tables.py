import pandas as pd

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
    assert 'data-i18n="rpt_no_data"' in html_none
    # Must NOT regress to the legacy bare <p class="note"> form
    assert '<p class="note"' not in html_none

    html_empty = render_df_table(pd.DataFrame(), col_i18n={})
    assert 'report-table-panel--empty' in html_empty


def test_empty_panel_honors_custom_no_data_key():
    html = render_df_table(None, col_i18n={}, no_data_key="rpt_no_records")
    assert 'data-i18n="rpt_no_records"' in html


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


def test_i18n_marker_lives_on_inner_span_not_on_th():
    """Regression guard: data-i18n must be on the inner .th-label span, not on
    the <th> itself. The report's applyI18n runs `el.textContent = translated`
    on every [data-i18n] element, which wipes all children. When data-i18n was
    on the <th>, every sort-indicator and col-resizer added by TABLE_JS was
    clobbered on page load, breaking column resize on every interactive table
    except the Metric/Value summary (which has no i18n keys)."""
    df = pd.DataFrame([{"Port": 53, "Connections": 1000}])
    out = render_df_table(df, col_i18n={"Port": "rpt_col_port",
                                         "Connections": "rpt_col_connections"})
    # data-i18n must NOT appear on the <th> tag (would let applyI18n wipe children)
    assert 'th data-i18n=' not in out
    # data-i18n MUST appear on the th-label span
    assert 'class="th-label" data-i18n="rpt_col_port"' in out
    assert 'class="th-label" data-i18n="rpt_col_connections"' in out
