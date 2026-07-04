"""spec F3（draftpolicy i18n）+ F4（port 欄不套千分位）。"""
import pandas as pd
from src.report.exporters.report_i18n import STRINGS


def test_draftpolicy_category_i18n_exists():
    assert STRINGS["rpt_cat_draftpolicy_name"]["en"]
    assert STRINGS["rpt_cat_draftpolicy_name"]["zh_TW"]
    assert STRINGS["rpt_cat_draftpolicy_desc"]["en"]


def test_port_column_no_thousands_separator():
    from src.report.exporters.html_exporter import _df_to_html
    df = pd.DataFrame([{"Port": 8080, "Connections": 12345}]).astype({"Port": "Int64", "Connections": "Int64"})
    html = _df_to_html(df, lang="en")
    assert "8080" in html and "8,080" not in html      # Port 不分組
    assert "12,345" in html                             # 計數欄仍分組


def test_unique_ports_count_still_grouped():
    from src.report.exporters.html_exporter import _df_to_html
    df = pd.DataFrame([{"Unique Ports": 1234}]).astype("Int64")
    html = _df_to_html(df, lang="en")
    assert "1,234" in html                              # 含 port 字樣的計數欄不受豁免誤傷
