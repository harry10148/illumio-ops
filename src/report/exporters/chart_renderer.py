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
from typing import Any

import matplotlib

# Only switch to headless backend if no interactive backend is already active.
# This avoids breaking callers running in Jupyter / IDE / GUI contexts.
if matplotlib.get_backend().lower() != "agg":
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams
import plotly.graph_objects as go
import plotly.offline as plotly_offline

# CJK font fallback for matplotlib — ensures zh_TW titles/labels render
rcParams["font.family"] = ["Noto Sans CJK TC", "Microsoft JhengHei",
                            "PingFang TC", "Heiti TC", "sans-serif"]
rcParams["axes.unicode_minus"] = False  # minus sign glitch fix

_PALETTE = [
    "#FF5500", "#FFA22F", "#299B65", "#375379", "#857ad6",
    "#38BDF8", "#F43F51", "#10B981", "#F59E0B", "#6366F1",
]

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


def render_plotly_html(spec: dict[str, Any]) -> str:
    """Render chart spec as a styled plotly HTML div (offline, self-contained)."""
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
        fig, output_type="div", include_plotlyjs="inline", show_link=False
    )

def render_matplotlib_png(spec: dict[str, Any]) -> bytes:
    """Render chart spec as a PNG byte string (for PDF/Excel embedding)."""
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = spec.get("title", "")

    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)

    if chart_type == "bar":
        ax.bar(data.get("labels", []), data.get("values", []), color="#375379")
        ax.set_xlabel(spec.get("x_label", ""))
        ax.set_ylabel(spec.get("y_label", ""))
    elif chart_type == "pie":
        ax.pie(data.get("values", []), labels=data.get("labels", []),
               autopct="%1.1f%%", startangle=90)
        ax.axis("equal")
    elif chart_type == "line":
        ax.plot(data.get("x", []), data.get("y", []), marker="o")
        ax.set_xlabel(spec.get("x_label", ""))
        ax.set_ylabel(spec.get("y_label", ""))
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
