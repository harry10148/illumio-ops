"""ReportLab PDF export with CJK font support and full layout control."""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Any

import pandas as pd
from loguru import logger
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

PDF_AVAILABLE = True
_ASCII_SAFE_RE = re.compile(r"^[\x09\x0a\x0d\x20-\x7e]*$")

# Landscape A4 usable width: 297mm - 24mm margins = 273mm
_PAGE_USABLE_W = 273 * mm

_CJK_FONT_NAME = "Helvetica"  # overwritten below by _try_register_cjk()
_CJK_FONT_BOLD = "Helvetica-Bold"

# Registration order:
#  1. ReportLab's built-in CID font for Traditional Chinese (no file needed,
#     ships with reportlab, renders both Latin and CJK glyphs).
#  2. TrueType-flavoured filesystem fallbacks. NOT used for Noto Sans CJK
#     OTF/TTC files — those are PostScript/CFF outlines, which reportlab's
#     TTFont cannot parse ("postscript outlines are not supported").
_CJK_TTF_FALLBACKS: list[str] = [
    # Add TTF fallbacks here if a deployment ships a TrueType-flavoured CJK
    # font. Note: bundled NotoSansCJKtc-Regular.otf is CFF-flavoured and
    # CANNOT be loaded by reportlab — leave it for matplotlib's use only.
]


def _try_register_cjk() -> str:
    """Register a CJK-capable font that also has Latin coverage. Return its name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    # Primary: ReportLab built-in CID font for Traditional Chinese.
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
        logger.info("PDF CJK font registered: MSung-Light (built-in CID)")
        return "MSung-Light"
    except Exception as exc:
        logger.warning("PDF MSung-Light registration failed: {}", exc)

    # Fallback: TrueType-flavoured files only.
    for path in _CJK_TTF_FALLBACKS:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont("CJKFont", path))
            logger.info("PDF CJK font registered from {}", path)
            return "CJKFont"
        except Exception as exc:
            logger.debug("PDF font {} failed: {}", path, exc)

    logger.warning(
        "No CJK font registered for PDF; Chinese AND ASCII text may render "
        "as blank glyphs with Helvetica fallback."
    )
    return "Helvetica"


_CJK_FONT_NAME = _try_register_cjk()


def _sanitize_pdf_value(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ").strip()
    return text[:180] if text else "-"


def _col_widths(n_cols: int) -> list[float]:
    """Equal-width columns fitting landscape A4."""
    w = _PAGE_USABLE_W / max(n_cols, 1)
    return [w] * n_cols


def _make_cell_style(font: str, size: int = 8) -> ParagraphStyle:
    return ParagraphStyle("pdfcell", fontName=font, fontSize=size, leading=size + 2, wordWrap="CJK")


def _dataframe_to_table(df: pd.DataFrame, *, max_cols: int = 10, lang: str = "en") -> Table:
    from src.report.exporters.report_i18n import STRINGS, COL_I18N
    trimmed = df.iloc[:, :max_cols].copy()
    font = _CJK_FONT_NAME
    font_size = 8 if trimmed.shape[1] <= 6 else 7
    cell_style = _make_cell_style(font, font_size)
    hdr_style = ParagraphStyle("pdfhdr", fontName=font, fontSize=font_size,
                               leading=font_size + 2, textColor=colors.white, wordWrap="CJK")

    def _translate_col(col_name: str) -> str:
        key = COL_I18N.get(str(col_name))
        if key:
            return STRINGS[key].get(lang) or str(col_name)
        return _sanitize_pdf_value(col_name)

    header = [Paragraph(_translate_col(c), hdr_style) for c in trimmed.columns]
    data: list[list] = [header]
    for _, row in trimmed.iterrows():
        data.append([Paragraph(_sanitize_pdf_value(v), cell_style) for v in row.tolist()])

    col_w = _col_widths(len(trimmed.columns))
    table = Table(data, colWidths=col_w, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _top_apps_to_df(top_apps: list[dict]) -> pd.DataFrame:
    rows = []
    for a in top_apps:
        rows.append({"App": a.get("app", a.get("index", "")), "Flows": a.get("flows", a.get(0, ""))})
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _deltas_to_df(deltas: dict) -> pd.DataFrame:
    rows = []
    for kpi, d in deltas.items():
        rows.append({
            "KPI": kpi,
            "Previous": d.get("previous", ""),
            "Current": d.get("current", ""),
            "Delta": d.get("delta", ""),
            "Direction": d.get("direction", ""),
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _append_module(story: list[Any], styles, name: str, module: dict[str, Any],
                   lang: str = "en", chart_paths: list[str] | None = None) -> None:
    # chart_paths: caller-owned list that collects temp PNG paths so the caller
    # can unlink them AFTER doc.build() reads the files. Unlinking here would
    # delete the file before reportlab's lazy ImageReader opens it.
    from src.report.exporters.report_i18n import STRINGS

    raw_title = module.get("title")
    if not raw_title:
        strings_key = f"rpt_mod_{name}_title"
        raw_title = STRINGS[strings_key].get(lang) or name
    title = _sanitize_pdf_value(raw_title)

    heading = Paragraph(title, styles["Heading2"])
    story.append(Spacer(1, 4 * mm))

    # Build content blocks for this module
    content_blocks: list[Any] = []

    # Try standard data keys in priority order
    df: pd.DataFrame | None = None
    for key in ("summary", "table", "data", "factor_table", "app_env_scores"):
        value = module.get(key)
        if isinstance(value, pd.DataFrame) and not value.empty:
            df = value
            break

    # R3 special payloads
    if df is None:
        top_apps = module.get("top_apps")
        if isinstance(top_apps, list) and top_apps:
            df = _top_apps_to_df(top_apps)

    if df is None:
        deltas = module.get("deltas")
        if isinstance(deltas, dict) and deltas:
            df = _deltas_to_df(deltas)

    if df is not None and not df.empty:
        content_blocks.append(_dataframe_to_table(df, lang=lang))
        content_blocks.append(Spacer(1, 8 * mm))

    # Chart
    chart_spec = module.get("chart_spec")
    if chart_spec:
        try:
            from src.report.exporters.chart_renderer import render_matplotlib_png
            import tempfile
            png = render_matplotlib_png(chart_spec)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fh:
                fh.write(png)
                chart_path = fh.name
            if chart_paths is not None:
                chart_paths.append(chart_path)
            content_blocks.append(Image(chart_path, width=160 * mm, height=90 * mm, kind="proportional"))
            content_blocks.append(Spacer(1, 8 * mm))
        except Exception as exc:
            logger.warning("PDF chart render failed for {}: {}", name, exc)

    if content_blocks:
        # Keep heading with first content block to avoid orphan titles
        story.append(KeepTogether([heading, Spacer(1, 2 * mm), content_blocks[0]]))
        story.extend(content_blocks[1:])
    else:
        story.append(heading)


def export_report_pdf(
    *,
    title: str,
    output_path: str,
    module_results: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    lang: str = "en",
) -> None:
    from src.report.exporters.report_i18n import STRINGS

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
    # Override fonts to CJK-capable font
    for s in styles.byName.values():
        s.fontName = _CJK_FONT_NAME

    pdf_note = STRINGS["rpt_pdf_static_note"].get(lang) or STRINGS["rpt_pdf_static_note"]["en"]

    story: list[Any] = [
        Paragraph(_sanitize_pdf_value(title), styles["Title"]),
        Paragraph(pdf_note, styles["Normal"]),
        Spacer(1, 8 * mm),
    ]
    for key, value in (metadata or {}).items():
        story.append(Paragraph(f"{_sanitize_pdf_value(key)}: {_sanitize_pdf_value(value)}", styles["Normal"]))
    story.append(Spacer(1, 8 * mm))
    chart_paths: list[str] = []
    for name, module in (module_results or {}).items():
        if isinstance(module, dict):
            _append_module(story, styles, name, module, lang=lang, chart_paths=chart_paths)
    try:
        doc.build(story)
    finally:
        for p in chart_paths:
            try:
                os.unlink(p)
            except OSError:
                pass  # best-effort cleanup; tempfile may already be gone
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
