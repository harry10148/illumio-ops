from __future__ import annotations

import pandas as pd


def test_export_report_pdf_produces_pdf_magic_bytes(tmp_path):
    from src.report.exporters.pdf_exporter import export_report_pdf

    out = tmp_path / "traffic.pdf"
    export_report_pdf(
        title="Traffic Flow Report",
        output_path=str(out),
        module_results={
            "mod01": {
                "title": "Traffic Overview",
                "summary": pd.DataFrame([{"Metric": "Flows", "Value": 12}]),
            }
        },
        metadata={"generated_at": "2026-04-26 12:00", "record_count": 12},
    )

    assert out.read_bytes().startswith(b"%PDF-")
    assert out.stat().st_size > 1000


def test_pdf_export_is_english_ui_even_when_values_are_non_latin(tmp_path):
    from src.report.exporters.pdf_exporter import _sanitize_pdf_value, export_report_pdf

    out = tmp_path / "english.pdf"
    assert _sanitize_pdf_value("中文主機") == "[non-Latin text]"
    export_report_pdf(
        title="Audit Report",
        output_path=str(out),
        module_results={
            "mod00": {
                "title": "Executive Summary",
                "summary": pd.DataFrame([{"Object": "中文主機", "Count": 1}]),
            }
        },
        metadata={"generated_at": "2026-04-26 12:00"},
    )
    assert out.read_bytes().startswith(b"%PDF-")


def test_export_pdf_compatibility_wrapper_accepts_html(tmp_path):
    from src.report.exporters.pdf_exporter import export_pdf

    out = tmp_path / "compat.pdf"
    export_pdf("<html><body><h1>Ignored HTML</h1><p>Body text</p></body></html>", str(out))
    assert out.read_bytes().startswith(b"%PDF-")
