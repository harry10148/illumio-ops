"""Dual-engine chart renderer for illumio_ops reports.

Single chart_spec dict feeds both engines:
  - render_plotly_html(spec) -> str (HTML div, fully self-contained for offline use)
  - render_matplotlib_png(spec) -> bytes (PNG for PDF/Excel embedding)

chart_spec shape:
  {
    "type": "bar" | "pie" | "line" | "heatmap" | "network",
    "title": str,
    "x_label": str (optional, for bar/line),
    "y_label": str (optional, for bar/line),
    "data": {
        "labels": [...],
        "values": [...] OR "x": [...], "y": [...],
        "matrix": [[...]] (for heatmap),
        "nodes": [...], "edges": [...] (for network),
    },
    "i18n": {"lang": "en" | "zh_TW"},
  }
"""
from __future__ import annotations

import io
from loguru import logger
import math
from pathlib import Path
from typing import Any

import matplotlib

# Only switch to headless backend if no interactive backend is already active.
# This avoids breaking callers running in Jupyter / IDE / GUI contexts.
if matplotlib.get_backend().lower() != "agg":
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
import plotly.graph_objects as go
import plotly.offline as plotly_offline

# Bundle a CJK-capable font so offline-isolated deployments don't depend on
# an OS-level font install. Loaded before rcParams so the family lookup
# below resolves to the bundled face.
_BUNDLED_CJK_FONT = (
    Path(__file__).resolve().parents[2] / "static" / "fonts" / "NotoSansCJKtc-Regular.otf"
)
if _BUNDLED_CJK_FONT.exists():
    font_manager.fontManager.addfont(str(_BUNDLED_CJK_FONT))

def _filter_existing_font_families(candidates: list[str]) -> list[str]:
    """Drop families matplotlib cannot resolve, always keep 'sans-serif' last.

    Without this filter, listing macOS/Windows-only families (PingFang TC,
    Microsoft JhengHei, Heiti TC) on Linux triggers a findfont warning per
    family per chart render — 30+ warning lines per report.
    """
    kept: list[str] = []
    for fam in candidates:
        if fam == "sans-serif":
            continue  # added at end
        try:
            font_manager.findfont(fam, fallback_to_default=False)
            kept.append(fam)
        except ValueError:
            logger.debug("font.family candidate {!r} not installed; dropping", fam)
    kept.append("sans-serif")
    return kept


# CJK font fallback for matplotlib — ensures zh_TW titles/labels render.
# Filtered to fonts actually installed so we don't spam warnings on Linux
# where Microsoft JhengHei / PingFang TC / Heiti TC are absent.
rcParams["font.family"] = _filter_existing_font_families([
    "Noto Sans CJK TC", "Microsoft JhengHei", "PingFang TC", "Heiti TC",
    "sans-serif",
])
rcParams["axes.unicode_minus"] = False  # minus sign glitch fix

# D.3 共享 signal palette — must match --color-signal-* in app.css and report_css.py
SIGNAL_COLORS = {
    'success':  '#2D9B5E',  # Allowed / Online / passing
    'warning':  '#C47A00',  # Potentially-Blocked / Warning
    'danger':   '#D93025',  # Blocked / Critical / Lost
    'info':     '#0077CC',  # Info / metadata
}

# Convenience aliases for verdict labels (Illumio terminology — 留英 per OQ-10)
VERDICT_COLORS = {
    'Allowed':              SIGNAL_COLORS['success'],
    'Blocked':              SIGNAL_COLORS['danger'],
    'Potentially-Blocked':  SIGNAL_COLORS['warning'],
    'Potentially_Blocked':  SIGNAL_COLORS['warning'],  # alt spelling
    'Unknown':              SIGNAL_COLORS['info'],
}

_PALETTE = [
    "#FF5500", "#FFA22F", "#299B65", "#375379", "#857ad6",
    "#38BDF8", "#F43F51", "#10B981", "#F59E0B", "#6366F1",
]


def _resolve_chart_text(spec: dict[str, Any], field: str, *, lang: str = "en") -> str:
    """Resolve a chart_spec text field, preferring `<field>_key` i18n lookup.

    Lookup order:
      1. spec[f"{field}_key"] -> STRINGS[key].get(lang) if both present
      2. spec[field] (literal fallback for backward compat)
      3. "" if neither present

    NOTE on silent failure: when the key IS set but the entry is missing
    from STRINGS (typo or stale key), we log a WARNING and fall back to
    the literal. This catches translation gaps in CI/dev logs that would
    otherwise pass unnoticed (a zh_TW PDF showing English for one chart
    is hard to spot in visual review).
    """
    key = spec.get(f"{field}_key")
    if key:
        from src.report.exporters.report_i18n import STRINGS
        if key not in STRINGS:
            logger.warning(
                "chart i18n key not found: {!r} (field={}, lang={}) — "
                "falling back to literal",
                key, field, lang,
            )
        else:
            translated = STRINGS[key].get(lang)
            if translated:
                return translated
    return str(spec.get(field, ""))


def _pie_autopct(pct: float, *, threshold: float = 0.0) -> str:
    """Suppress autopct labels for slices at or below `threshold` percent.

    Default threshold=0.0 with strict `>` hides only literally-zero slices,
    which were causing the '0.0%5.5%0.0%' label clusters in the sample
    report. Higher thresholds risk hiding operationally-significant slices
    (e.g. a 0.08% 'Critical' category is exactly the slice a security
    operator needs to see) — only raise the threshold when the chart's
    domain makes sub-N% noise meaningless.
    """
    return f"{pct:.1f}%" if pct > threshold else ""

_BASE_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Montserrat, -apple-system, sans-serif", size=13, color="#313638"),
    title_font=dict(size=15, color="#1A2C32", family="Montserrat, sans-serif"),
    margin=dict(l=48, r=24, t=52, b=48),
    legend=dict(
        bgcolor="rgba(247,244,238,0.88)",
        bordercolor="#D6D7D7",
        borderwidth=1,
        font=dict(size=12),
    ),
    hoverlabel=dict(
        bgcolor="#1A2C32",
        font=dict(color="#fff", size=12),
        bordercolor="#2D454C",
    ),
)


def _apply_base_layout(fig, title: str, x_label: str = "", y_label: str = "") -> None:
    updates = dict(**_BASE_LAYOUT, title=dict(text=title, x=0.04, xanchor="left"))
    if x_label or y_label:
        updates["xaxis"] = dict(
            title=x_label,
            gridcolor="rgba(50,81,88,0.10)",
            linecolor="rgba(50,81,88,0.18)",
            tickfont=dict(size=11),
        )
        updates["yaxis"] = dict(
            title=y_label,
            gridcolor="rgba(50,81,88,0.10)",
            linecolor="rgba(50,81,88,0.18)",
            tickfont=dict(size=11),
        )
    fig.update_layout(**updates)


class FirstChartTracker:
    """One instance per document. First call to consume() returns True; subsequent False."""

    def __init__(self):
        self._first = True

    def consume(self) -> bool:
        v = self._first
        self._first = False
        return v


def render_plotly_html(spec: dict[str, Any], *, include_js: bool = True) -> str:
    """Render chart spec as a styled plotly HTML div (offline, self-contained).

    Args:
        spec: Chart specification dict.
        include_js: If True (default), embeds the full Plotly JS bundle (~3 MB) inline.
            Set to False for subsequent charts in the same document to avoid repeating
            the bundle — Plotly reuses the already-loaded runtime from the first chart.
    """
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = spec.get("title", "")

    if chart_type == "bar":
        labels = data.get("labels", [])
        values = data.get("values", [])
        colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(labels))]
        fig = go.Figure(go.Bar(
            x=labels,
            y=values,
            marker=dict(color=colors, line=dict(color="rgba(0,0,0,0.08)", width=1)),
            hovertemplate="%{x}<br><b>%{y:,}</b><extra></extra>",
        ))
        _apply_base_layout(fig, title, spec.get("x_label", ""), spec.get("y_label", ""))
        fig.update_layout(bargap=0.28)
    elif chart_type == "pie":
        labels = data.get("labels", [])
        values = data.get("values", [])
        fig = go.Figure(go.Pie(
            labels=labels,
            values=values,
            hole=0.38,
            marker=dict(
                colors=_PALETTE[:len(labels)],
                line=dict(color="#ffffff", width=2),
            ),
            textfont=dict(size=12, family="Montserrat, sans-serif"),
            hovertemplate="<b>%{label}</b><br>%{value:,} (%{percent})<extra></extra>",
            pull=[0.04] + [0] * max(0, len(labels) - 1),
        ))
        _apply_base_layout(fig, title)
        fig.update_layout(
            legend=dict(**_BASE_LAYOUT["legend"], orientation="v", x=1.02, y=0.5),
            margin=dict(l=24, r=160, t=52, b=24),
        )
    elif chart_type == "line":
        fig = go.Figure(go.Scatter(
            x=data.get("x", []),
            y=data.get("y", []),
            mode="lines+markers",
            line=dict(color=_PALETTE[0], width=2.5),
            marker=dict(size=7, color=_PALETTE[0], line=dict(color="#fff", width=1.5)),
            hovertemplate="%{x}<br><b>%{y:,}</b><extra></extra>",
        ))
        _apply_base_layout(fig, title, spec.get("x_label", ""), spec.get("y_label", ""))
    elif chart_type == "heatmap":
        fig = go.Figure(go.Heatmap(
            z=data.get("matrix", []),
            x=data.get("labels", []),
            y=data.get("ylabels", data.get("labels", [])),
            colorscale=[[0, "#F7F4EE"], [0.5, "#FFA22F"], [1, "#1A2C32"]],
            hovertemplate="x: %{x}<br>y: %{y}<br><b>%{z:,}</b><extra></extra>",
        ))
        _apply_base_layout(fig, title)
        fig.update_layout(
            xaxis=dict(tickfont=dict(size=11), gridcolor="rgba(0,0,0,0)"),
            yaxis=dict(tickfont=dict(size=11), gridcolor="rgba(0,0,0,0)"),
        )
    elif chart_type == "network":
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        n = len(nodes) or 1
        node_x = [math.cos(2 * math.pi * i / n) for i in range(n)]
        node_y = [math.sin(2 * math.pi * i / n) for i in range(n)]
        edge_x, edge_y = [], []
        name_to_idx = {node.get("id") or node.get("name"): i for i, node in enumerate(nodes)}
        for src, dst in edges:
            i, j = name_to_idx.get(src), name_to_idx.get(dst)
            if i is None or j is None:
                continue
            edge_x += [node_x[i], node_x[j], None]
            edge_y += [node_y[i], node_y[j], None]
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="rgba(50,81,88,0.30)", width=1.5),
            hoverinfo="none",
        ))
        fig.add_trace(go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            text=[nd.get("label", nd.get("id", "")) for nd in nodes],
            marker=dict(
                size=24,
                color=_PALETTE[3],
                line=dict(color="#fff", width=2),
            ),
            textposition="bottom center",
            textfont=dict(size=11),
            hovertemplate="%{text}<extra></extra>",
        ))
        _apply_base_layout(fig, title)
        fig.update_layout(
            showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False, visible=False),
            yaxis=dict(showgrid=False, zeroline=False, visible=False),
        )
    else:
        raise ValueError(f"unsupported chart type: {chart_type!r}")

    return plotly_offline.plot(
        fig,
        output_type="div",
        include_plotlyjs="inline" if include_js else False,
        show_link=False,
    )

def render_matplotlib_png(spec: dict[str, Any], *, lang: str = "en") -> bytes:
    """Render chart spec as a PNG byte string (for PDF/Excel embedding).

    Title and axis labels are resolved through `_resolve_chart_text` so that
    chart_specs carrying `title_key` / `x_label_key` / `y_label_key` render in
    the requested language. Specs without those keys fall back to the literal
    `title` / `x_label` / `y_label` for backward compatibility.
    """
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = _resolve_chart_text(spec, "title", lang=lang)
    x_label = _resolve_chart_text(spec, "x_label", lang=lang)
    y_label = _resolve_chart_text(spec, "y_label", lang=lang)

    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)

    if chart_type == "bar":
        ax.bar(data.get("labels", []), data.get("values", []), color="#375379")
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
    elif chart_type == "pie":
        ax.pie(
            data.get("values", []),
            labels=data.get("labels", []),
            autopct=_pie_autopct,
            startangle=90,
            pctdistance=0.78,        # % labels at 78% of radius (default 0.6)
            labeldistance=1.08,      # slice labels at 108% of radius (default 1.1)
            textprops={"fontsize": 9},
        )
        ax.axis("equal")
    elif chart_type == "line":
        ax.plot(data.get("x", []), data.get("y", []), marker="o")
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
    elif chart_type == "heatmap":
        import numpy as np
        raw_matrix = data.get("matrix", [[0]])
        # Guard: empty lists produce np.array([]) which imshow rejects with TypeError
        if not raw_matrix or not raw_matrix[0]:
            raw_matrix = [[0]]
        matrix = np.array(raw_matrix)
        im = ax.imshow(matrix, cmap="viridis", aspect="auto")
        fig.colorbar(im, ax=ax)
        labels = data.get("labels", [])
        ylabels = data.get("ylabels", labels)
        if labels:
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=45, ha="right")
        if ylabels:
            ax.set_yticks(range(len(ylabels)))
            ax.set_yticklabels(ylabels)
    elif chart_type == "network":
        # Simple circular layout for static rendering
        nodes = data.get("nodes", [])
        n = len(nodes) or 1
        positions = {
            (node.get("id") or node.get("name")): (math.cos(2 * math.pi * i / n),
                                                    math.sin(2 * math.pi * i / n))
            for i, node in enumerate(nodes)
        }
        for src, dst in data.get("edges", []):
            if src in positions and dst in positions:
                x1, y1 = positions[src]
                x2, y2 = positions[dst]
                ax.plot([x1, x2], [y1, y2], "gray", alpha=0.5)
        for node in nodes:
            key = node.get("id") or node.get("name")
            x, y = positions[key]
            ax.plot(x, y, "o", markersize=20, color="#375379")
            ax.annotate(node.get("label", key), (x, y), xytext=(0, -15),
                        textcoords="offset points", ha="center")
        ax.set_xlim(-1.5, 1.5)
        ax.set_ylim(-1.5, 1.5)
        ax.axis("off")
    else:
        plt.close(fig)
        raise ValueError(f"unsupported chart type: {chart_type!r}")

    ax.set_title(title)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return buf.getvalue()
