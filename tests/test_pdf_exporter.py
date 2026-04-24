"""weasyprint PDF export — critical: runs on Linux (pango/cairo), skip on Windows."""
from __future__ import annotations

import pytest

# weasyprint raises OSError at import on Windows (no GTK3/GObject libs).
# Catch that here so pytest can collect the file and then skip all tests.
try:
    import weasyprint as _wp  # noqa: F401
    _WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    _WEASYPRINT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _WEASYPRINT_AVAILABLE,
    reason="weasyprint needs GTK3/GObject libs; available on Linux RPM target"
)


def test_export_pdf_produces_pdf_magic_bytes(tmp_path):
    from src.report.exporters.pdf_exporter import export_pdf
    html = "<html><head><meta charset='utf-8'></head><body><h1>Test</h1><p>body</p></body></html>"
    out = tmp_path / "report.pdf"
    export_pdf(html, str(out))
    assert out.exists()
    header = out.read_bytes()[:8]
    assert header.startswith(b"%PDF-")


def test_export_pdf_handles_cjk(tmp_path):
    from src.report.exporters.pdf_exporter import export_pdf
    html = "<html><body><h1>中文標題</h1><p>包含中文的段落內容</p></body></html>"
    out = tmp_path / "cjk.pdf"
    export_pdf(html, str(out))
    data = out.read_bytes()
    # PDF must be non-trivial size (CJK embedding failure often produces a tiny PDF)
    assert len(data) > 1500


def test_pdf_available_is_bool():
    from src.report.exporters.pdf_exporter import PDF_AVAILABLE
    assert isinstance(PDF_AVAILABLE, bool)
