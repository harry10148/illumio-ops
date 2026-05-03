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


def test_pdf_sanitize_passes_cjk_text(tmp_path):
    from src.report.exporters.pdf_exporter import _sanitize_pdf_value, export_report_pdf

    # CJK text must pass through unchanged (no [non-Latin text] replacement)
    assert _sanitize_pdf_value("中文主機") == "中文主機"
    out = tmp_path / "cjk.pdf"
    export_report_pdf(
        title="Audit Report",
        output_path=str(out),
        lang="zh_TW",
        module_results={
            "mod00": {
                "title": "執行摘要",
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


def test_export_pdf_with_chart_spec_does_not_lose_tempfile(tmp_path):
    # Regression: previously the chart PNG tempfile was os.unlink()'d before
    # doc.build() ran, so reportlab's lazy ImageReader failed with
    # "Cannot open resource '/tmp/...png'" and the whole PDF returned no file.
    from src.report.exporters.pdf_exporter import export_report_pdf

    out = tmp_path / "with_chart.pdf"
    export_report_pdf(
        title="Traffic Flow Report",
        output_path=str(out),
        module_results={
            "mod01": {
                "title": "Top Talkers",
                "summary": pd.DataFrame([{"Metric": "Flows", "Value": 12}]),
                "chart_spec": {
                    "type": "bar",
                    "title": "Top destinations",
                    "data": {"labels": ["a", "b", "c"], "values": [3, 7, 2]},
                },
            }
        },
        metadata={"generated_at": "2026-05-04 00:00", "record_count": 12},
    )
    assert out.read_bytes().startswith(b"%PDF-")
    # Sanity: image-bearing PDF should be appreciably larger than text-only.
    assert out.stat().st_size > 4000
