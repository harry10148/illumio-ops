"""English static PDF export via ReportLab.

PDF v1 intentionally does not render HTML/CSS and does not support CJK UI text.
Use HTML/XLSX for full i18n fidelity.
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Any

import pandas as pd
from loguru import logger
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PDF_AVAILABLE = True
_ASCII_SAFE_RE = re.compile(r"^[\x09\x0a\x0d\x20-\x7e]*$")


def _sanitize_pdf_value(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return "-"
    if not _ASCII_SAFE_RE.match(text):
        return "[non-Latin text]"
    return text[:180]


def _dataframe_to_table(df: pd.DataFrame, *, max_rows: int = 25, max_cols: int = 6) -> Table:
    trimmed = df.head(max_rows).iloc[:, :max_cols].copy()
    data = [[_sanitize_pdf_value(col) for col in trimmed.columns]]
    for _, row in trimmed.iterrows():
        data.append([_sanitize_pdf_value(v) for v in row.tolist()])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _append_module(story: list[Any], styles, name: str, module: dict[str, Any]) -> None:
    title = _sanitize_pdf_value(module.get("title") or name)
    story.append(Paragraph(title, styles["Heading2"]))
    story.append(Spacer(1, 4 * mm))
    for key in ("summary", "table", "data"):
        value = module.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            story.append(_dataframe_to_table(value))
            story.append(Spacer(1, 8 * mm))
            break
    chart_spec = module.get("chart_spec")
    if chart_spec:
        try:
            from src.report.exporters.chart_renderer import render_matplotlib_png
            import tempfile
            png = render_matplotlib_png(chart_spec)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fh:
                fh.write(png)
                chart_path = fh.name
            story.append(Image(chart_path, width=160 * mm, height=90 * mm, kind="proportional"))
            story.append(Spacer(1, 8 * mm))
            os.unlink(chart_path)
        except Exception as exc:
            logger.warning("PDF chart render failed for {}: {}", name, exc)


def export_report_pdf(
    *,
    title: str,
    output_path: str,
    module_results: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> None:
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    story: list[Any] = [
        Paragraph(_sanitize_pdf_value(title), styles["Title"]),
        Paragraph("Static English PDF summary. Use HTML or XLSX for full localized detail.", styles["Normal"]),
        Spacer(1, 8 * mm),
    ]
    for key, value in (metadata or {}).items():
        story.append(Paragraph(f"{_sanitize_pdf_value(key)}: {_sanitize_pdf_value(value)}", styles["Normal"]))
    story.append(Spacer(1, 8 * mm))
    for name, module in (module_results or {}).items():
        if isinstance(module, dict):
            _append_module(story, styles, name, module)
    doc.build(story)
    logger.info("pdf report written to {}", output_path)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def export_pdf(html: str, output_path: str, base_url: str | None = None) -> None:
    parser = _TextExtractor()
    parser.feed(html or "")
    text = " ".join(parser.parts[:20]) or "PDF export"
    export_report_pdf(
        title="Illumio Report",
        output_path=output_path,
        module_results={"html_summary": {"title": "Summary", "summary": pd.DataFrame([{"Content": text}])}},
        metadata={"source": "compatibility_wrapper"},
    )
