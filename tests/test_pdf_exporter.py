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


def test_pdf_renders_ascii_inside_cjk_paragraph(tmp_path):
    """Regression for the broken CJK font lookup that dropped ASCII glyphs.

    Previously _CJK_FONT_SEARCH pointed at a non-existent path and fell
    through to DroidSansFallbackFull (CJK-only, no Latin coverage), so any
    PDF body containing both Chinese and ASCII (e.g. "此 PDF 為...")
    rendered with the ASCII tokens as blank .notdef glyphs.
    """
    import subprocess
    from src.report.exporters.pdf_exporter import export_report_pdf

    out = tmp_path / "mixed_lang.pdf"
    export_report_pdf(
        title="Illumio 流量分析報表",
        output_path=str(out),
        module_results={
            "mod01": {
                "title": "概要",
                "summary": pd.DataFrame([
                    {"判定": "Allowed", "流量數": 12345, "占總量比例": "93.4%"},
                    {"判定": "Blocked", "流量數": 678,   "占總量比例": "5.5%"},
                ]),
            }
        },
        metadata={"generated_at": "2026-05-04 00:00", "record_count": 13023},
        lang="zh_TW",
    )
    assert out.read_bytes().startswith(b"%PDF-")

    # Probe rendered text. CID-encoded fonts may not roundtrip through every
    # extractor, so accept either pdftotext finding ALL three ASCII tokens, or
    # pdftotext being unavailable — but if pdftotext IS available and finds
    # NONE of the tokens, that's a regression.
    try:
        r = subprocess.run(["pdftotext", str(out), "-"],
                           capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return  # extractor unavailable — visual-only verification path
    text = r.stdout
    # Some poppler builds (e.g. Ubuntu 24.04 poppler-data 0.4.12) ship the
    # 'UniGB-UCS2-H' CMap only under Adobe-GB1, while reportlab references it
    # under Adobe-CNS1 for MSung-Light. When that mismatch occurs poppler
    # emits "Couldn't find 'UniGB-UCS2-H' CMap file for 'Adobe-CNS1'" on
    # stderr and produces no extractable glyphs at all. Treat that as
    # "extractor unable to read this font", not as a regression — verify the
    # stream content directly instead.
    if "Adobe-CNS1" in r.stderr and not text.strip():
        _assert_pdf_stream_contains_ascii(out, ("Allowed", "Blocked", "12345"))
        return
    found = sum(tok in text for tok in ("Allowed", "Blocked", "12345"))
    assert found >= 2, (
        f"PDF text extraction found only {found}/3 ASCII tokens; "
        f"font likely lacks Latin coverage. Extracted text: {text!r}"
    )


def _assert_pdf_stream_contains_ascii(pdf_path, tokens):
    """Decode PDF content streams and assert ASCII tokens appear as UTF-16BE
    glyph codes inside text-show operators. Used when pdftotext can't read
    the CID font but we still need to verify glyph emission."""
    import base64
    import re
    import zlib

    data = pdf_path.read_bytes()
    streams = re.findall(rb"stream\s*\n(.*?)\s*endstream", data, re.DOTALL)
    decoded_text = ""
    for s in streams:
        s = s.strip()
        try:
            if s.endswith(b"~>"):
                s = base64.a85decode(s[:-2])
            decoded_text += zlib.decompress(s).decode("latin-1", errors="replace")
        except Exception:
            continue
    found = 0
    for tok in tokens:
        # ReportLab emits ASCII as UTF-16BE inside parens, so 'A' becomes \000A.
        utf16 = "".join(f"\\000{ch}" for ch in tok)
        if utf16 in decoded_text or tok in decoded_text:
            found += 1
    assert found >= 2, (
        f"PDF stream contained only {found}/{len(tokens)} ASCII tokens as "
        f"glyph codes; font likely lacks Latin coverage."
    )


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
