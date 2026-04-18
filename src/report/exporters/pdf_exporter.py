"""HTML -> PDF export via weasyprint.

On the RHEL RPM target (pango + cairo present) this works natively. On
Windows dev machines lacking GTK3, this module imports cleanly but export
will raise OSError — tests skip accordingly.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def export_pdf(html: str, output_path: str, base_url: Optional[str] = None) -> None:
    """Render HTML to a PDF file. base_url is used to resolve relative assets."""
    # Deferred import so modules importing pdf_exporter don't fail on Windows dev
    from weasyprint import HTML, CSS

    # Basic CJK + print CSS overlay
    cjk_css = CSS(string="""
        @page { size: A4; margin: 20mm; }
        body {
            font-family: "Noto Sans CJK TC", "Microsoft JhengHei",
                         "PingFang TC", "Heiti TC", sans-serif;
            font-size: 11pt;
            line-height: 1.5;
        }
        /* plotly <div> renders only in HTML — hide and fall back to <img>
           which the HTML exporter is expected to emit for PDF. */
        .plotly-fallback-img { display: inline-block; max-width: 100%; }
        div.plotly-graph-div, script[type="application/json"] { display: none; }
    """)
    HTML(string=html, base_url=base_url).write_pdf(output_path, stylesheets=[cjk_css])
    logger.info("pdf report written to %s", output_path)
