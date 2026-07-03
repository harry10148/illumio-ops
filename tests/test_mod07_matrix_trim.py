"""跨 Label 矩陣 HTML 只留 ENV/APP（spec C2）。"""
import pandas as pd
from src.report.exporters.html_exporter import NetworkInventoryHtmlExporter


def _mod07():
    def _dim(n):
        return {"same_value_flows": n, "cross_value_flows": n + 1,
                "matrix": pd.DataFrame([{"a": 1}]),
                "top_cross_pairs": pd.DataFrame([{"Src X": "a", "Dst X": "b", "Connections": n}])}
    return {"matrices": {"env": _dim(1), "app": _dim(2), "role": _dim(3), "loc": _dim(4)}}


def _html():
    results = {"mod07": _mod07(), "mod12": {"kpis": [], "key_findings": []}, "findings": []}
    return NetworkInventoryHtmlExporter(results, lang="en").build()


def test_only_env_app_rendered():
    html = _html()
    assert "ENV" in html and "APP" in html
    # ROLE 三字母亦出現於下放註記文字（"ROLE and LOC dimension..."），LOC 亦可能出現於其他詞——
    # 故不用純子字串比對，改以維度標題的完整片段斷言。
    assert "Label Key: ROLE" not in html and "ROLE</h3>" not in html
    assert "Label Key: LOC" not in html and "LOC</h3>" not in html


def test_xlsx_demotion_note_present():
    html = _html()
    from src.report.exporters.report_i18n import STRINGS
    assert STRINGS["rpt_tr_matrix_xlsx_note"]["en"] in html
