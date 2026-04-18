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
import logging
import math
from typing import Any

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
from matplotlib import rcParams
import plotly.graph_objects as go
import plotly.offline as plotly_offline

logger = logging.getLogger(__name__)

# CJK font fallback for matplotlib — ensures zh_TW titles/labels render
rcParams["font.family"] = ["Noto Sans CJK TC", "Microsoft JhengHei",
                            "PingFang TC", "Heiti TC", "sans-serif"]
rcParams["axes.unicode_minus"] = False  # minus sign glitch fix


def render_plotly_html(spec: dict[str, Any]) -> str:
    """Render chart spec as a plotly HTML div (offline, self-contained)."""
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = spec.get("title", "")

    if chart_type == "bar":
        fig = go.Figure(go.Bar(
            x=data.get("labels", []),
            y=data.get("values", []),
            marker_color="rgb(55, 83, 109)",
        ))
        fig.update_layout(
            title=title,
            xaxis_title=spec.get("x_label", ""),
            yaxis_title=spec.get("y_label", ""),
        )
    elif chart_type == "pie":
        fig = go.Figure(go.Pie(
            labels=data.get("labels", []),
            values=data.get("values", []),
            hole=0.3,
        ))
        fig.update_layout(title=title)
    elif chart_type == "line":
        fig = go.Figure(go.Scatter(
            x=data.get("x", []),
            y=data.get("y", []),
            mode="lines+markers",
        ))
        fig.update_layout(
            title=title,
            xaxis_title=spec.get("x_label", ""),
            yaxis_title=spec.get("y_label", ""),
        )
    elif chart_type == "heatmap":
        fig = go.Figure(go.Heatmap(
            z=data.get("matrix", []),
            x=data.get("labels", []),
            y=data.get("ylabels", data.get("labels", [])),
            colorscale="Viridis",
        ))
        fig.update_layout(title=title)
    elif chart_type == "network":
        # Force-directed graph using circular layout
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
        fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                                 line=dict(color="gray"), hoverinfo="none"))
        fig.add_trace(go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            text=[nd.get("label", nd.get("id", "")) for nd in nodes],
            marker=dict(size=20), textposition="bottom center",
        ))
        fig.update_layout(title=title, showlegend=False,
                          xaxis=dict(showgrid=False, zeroline=False, visible=False),
                          yaxis=dict(showgrid=False, zeroline=False, visible=False))
    else:
        raise ValueError(f"unsupported chart type: {chart_type!r}")

    # include_plotlyjs='inline' — embeds plotly.min.js directly (offline-safe)
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
        matrix = np.array(data.get("matrix", [[0]]))
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
