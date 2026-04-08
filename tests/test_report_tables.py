import pandas as pd

from src.report.exporters.table_renderer import render_df_table


def test_report_table_becomes_interactive_only_when_three_or_more_columns():
    df_two = pd.DataFrame([{"A": 1, "B": 2}])
    html_two = render_df_table(df_two, col_i18n={})
    assert 'data-interactive="false"' in html_two
    assert "report-table-hint" not in html_two
    assert "report-table--interactive" not in html_two

    df_three = pd.DataFrame([{"A": 1, "B": 2, "C": 3}])
    html_three = render_df_table(df_three, col_i18n={})
    assert 'data-interactive="true"' in html_three
    assert "report-table--interactive" in html_three
    assert "report-table-hint" not in html_three
