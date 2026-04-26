from __future__ import annotations


def test_pdf_available_flag_is_true_with_reportlab():
    from src.report.exporters.pdf_exporter import PDF_AVAILABLE
    assert PDF_AVAILABLE is True


def test_requirements_offline_includes_reportlab_and_excludes_weasyprint():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    content = open(os.path.join(root, "requirements-offline.txt"), encoding="utf-8").read().lower()
    assert "reportlab" in content
    assert "weasyprint" not in content
    assert "cheroot" in content
    assert "waitress" not in content
