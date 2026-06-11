# tests/test_format_evidence_lang.py
"""Evidence pill labels must follow the report lang, not the process language."""
from src.i18n import set_language
from src.report.exporters.html_exporter import _format_evidence


def test_evidence_labels_use_explicit_lang_not_global(monkeypatch):
    set_language("zh_TW")  # 模擬 GUI 行程全域語言為中文
    try:
        html = _format_evidence({"total_flows": 11}, lang="en")
    finally:
        set_language("en")
    assert "Flow 總數" not in html
    assert "Total Flows" in html
