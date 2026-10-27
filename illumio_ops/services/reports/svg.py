"""Inline SVG bar charts for reports (no plotting library: the bundle stays small and the HTML self-contained)."""
from __future__ import annotations

import html
from collections.abc import Sequence

# Bars are coloured by the shell stylesheet (render_html.EXTRA_CSS), not here: no colour literals in markup.
MAX_BAR = 40.0  # one day of data must not fill the chart


def bar_svg(points: Sequence[tuple[str, int | float | None]], *, width: int = 640, height: int = 160) -> str:
    """One bar per point; a None point is a gap with its label kept (no data is not 0)."""
    n = max(len(points), 1)
    top = max((v for _, v in points if v is not None), default=0) or 1
    pad_bottom, pad_top = 22, 14
    slot = width / n
    bar_w = min(max(slot * 0.7, 1.0), MAX_BAR)
    usable = height - pad_bottom - pad_top
    parts = [(f'<svg class="report-bars" role="img" viewBox="0 0 {width} {height}" width="100%" '
             f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">')]
    label_every = max(1, n // 12)
    for i, (label, value) in enumerate(points):
        x = i * slot + (slot - bar_w) / 2
        if value is not None:
            h = usable * (value / top)
            parts.append(f'<rect x="{x:.1f}" y="{height - pad_bottom - h:.1f}" width="{bar_w:.1f}" '
                         f'height="{h:.1f}"><title>{html.escape(label)}: {value}</title></rect>')
        if i % label_every == 0:
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 6}" font-size="10" text-anchor="middle">'
                         f'{html.escape(label)}</text>')
    peak = max((v for _, v in points if v is not None), default=None)
    if peak is not None:
        parts.append(f'<text x="2" y="10" font-size="10">{html.escape(str(peak))}</text>')
    parts.append("</svg>")
    return "".join(parts)
