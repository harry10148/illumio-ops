"""Matplotlib chart renderer for illumio_ops reports.

Single chart_spec dict drives the renderer:
  - render_matplotlib_png(spec) -> bytes (PNG for Excel embedding)
  - render_matplotlib_svg(spec) -> str (inline SVG for HTML reports)

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

from .report_shell import SEVERITY_TONE, SHELL_TOKENS, TONE_HEX

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

# Every colour below is resolved from the report shell's :root tokens. Charts
# cannot use var() — matplotlib takes RGB values — so "same source" is the best
# available form of "same palette", and it is enforced by
# tests/test_chart_palette_tokens.py rather than by a comment.
#
# The names and shapes are unchanged from when these were hand-written hex
# tables, so any caller keeps working.

#: Default ink for marks that carry no severity of their own (plain bar fills,
#: network nodes). Deliberately --text-2 and not a tone: a bar with no semantic
#: meaning should read as ink, not as "info".
CHART_INK: str = SHELL_TOKENS["text-2"]

# D.3 shared signal palette, now the shell's tone LEDs.
SIGNAL_COLORS = {
    'success':  TONE_HEX['ok'],       # Allowed / Online / passing
    'warning':  TONE_HEX['warn'],     # Potentially-Blocked / Warning
    'danger':   TONE_HEX['crit'],     # Blocked / Critical / Lost
    'info':     TONE_HEX['info'],     # Info / metadata
}

# Convenience aliases for verdict labels (Illumio terminology — 留英 per OQ-10)
VERDICT_COLORS = {
    'Allowed':              SIGNAL_COLORS['success'],
    'Blocked':              SIGNAL_COLORS['danger'],
    'Potentially-Blocked':  SIGNAL_COLORS['warning'],
    'Potentially_Blocked':  SIGNAL_COLORS['warning'],  # alt spelling
    'Unknown':              TONE_HEX['neutral'],
}

def _resolve_chart_text(spec: dict[str, Any], field: str, *, lang: str = "en") -> str:
    """Resolve a chart_spec text field, preferring `<field>_key` i18n lookup.

    Lookup order:
      1. spec[f"{field}_key"] -> STRINGS[key].get(lang) if both present
      2. spec[field] (literal fallback for backward compat)
      3. "" if neither present

    NOTE on silent failure: when the key IS set but the entry is missing
    from STRINGS (typo or stale key), we log a WARNING and fall back to
    the literal. This catches translation gaps in CI/dev logs that would
    otherwise pass unnoticed (a zh_TW report showing English for one chart
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

    圓餅現在一律附完整圖例（名稱＋件數＋百分比），小切片的就地標籤只是
    重疊噪音（2026-07-23 視覺實檢：0.1%/0.0% 兩切片的名稱與百分比擠成一
    團）——pie 分支以 threshold=_PIE_LABEL_MIN_PCT 呼叫，資訊不會消失，
    只是移到圖例。
    """
    return f"{pct:.1f}%" if pct > threshold else ""


# 就地標籤（切片名＋百分比）的最小占比：低於此值只留圖例
_PIE_LABEL_MIN_PCT = 3.0

# 判定/嚴重度語意色：label 正規化（小寫、底線轉空白）後比對。
# 順序色曾把 98% Potentially Blocked 畫成安全綠（2026-07-23 視覺實檢）。
#
# 嚴重度那一半直接走 report_shell.SEVERITY_TONE——也就是 HTML 徽章用的同一份
# 對照表。在此之前兩邊是各寫各的：`low` 在圖上是綠色、在徽章上是 info 藍，
# 同一份報表裡對同一個嚴重度給兩種顏色，讀者無從得知哪個算數。
_SEMANTIC_TONE = {
    # 判定語彙
    "allowed": "ok",
    "blocked": "crit",
    "potentially blocked": "warn",
    "unknown": "neutral",
    # 嚴重度語彙（與徽章同源）
    "critical": SEVERITY_TONE["CRITICAL"],
    "high": SEVERITY_TONE["HIGH"],
    "medium": SEVERITY_TONE["MEDIUM"],
    "low": SEVERITY_TONE["LOW"],
    "info": SEVERITY_TONE["INFO"],
    # 別名
    "warning": SEVERITY_TONE["MEDIUM"],
    "error": SEVERITY_TONE["CRITICAL"],
}

_SEMANTIC_COLORS = {k: TONE_HEX[v] for k, v in _SEMANTIC_TONE.items()}

#: CRITICAL 與 HIGH 共用 crit tone；SHELL_CSS 靠「實心 vs 外框」把兩級分開
#: （`[data-tone="crit"][data-sev="CRITICAL"]` 是唯一一條做這件事的規則）。
#:
#: 圖上不能照抄那個裝置。徽章是小色片，外框＝淡底不會被讀成「比較不嚴重」；
#: 圓餅切片的顏色重量會直接被讀成量級，把 HIGH 畫成淡粉紅，它就比旁邊的琥珀色
#: MEDIUM 還輕——嚴重度排序在圖上被顛倒過來。這與 2026-07-23 抓到的
#: 「98% Potentially Blocked 被畫成安全綠」是同一類缺陷。
#:
#: 所以圖上共用 tone 的兩級用**同一個紅**保住色彩重量，靠白色斜線網底分開。
#: 網底在灰階列印下同樣看得出來，這是色相做不到的。
_HATCHED_LABELS = ("high",)
_HATCH = "//"


def _semantic_pie_colors(labels: list) -> "list[str] | None":
    """全部 label 都有語意色才回色列，否則 None（維持預設循環，不混用）。"""
    colors = [_SEMANTIC_COLORS.get(str(l).strip().lower().replace("_", " "))
              for l in labels]
    return colors if colors and all(colors) else None


def _semantic_pie_faces(labels: list) -> "list[tuple[str, str]] | None":
    """每個切片的 (facecolor, hatch)；沒有完整語意色時回 None。

    ``hatch`` 為 ``None`` 代表實心。只有 `_HATCHED_LABELS` 會拿到網底——目前
    只有 HIGH，它與 CRITICAL 共用 crit tone。
    """
    faces: list[tuple[str, str | None]] = []
    for label in labels:
        norm = str(label).strip().lower().replace("_", " ")
        tone = _SEMANTIC_TONE.get(norm)
        if tone is None:
            return None
        faces.append((TONE_HEX[tone],
                      _HATCH if norm in _HATCHED_LABELS else None))
    return faces or None


def _build_matplotlib_figure(spec: dict[str, Any], *, lang: str = "en"):
    """Build a matplotlib Figure from a chart spec (shared by PNG/SVG output).

    Title and axis labels are resolved through `_resolve_chart_text` so that
    chart_specs carrying `title_key` / `x_label_key` / `y_label_key` render in
    the requested language. Raises ValueError for unsupported chart types.
    Caller owns plt.close(fig).
    """
    chart_type = spec.get("type")
    data = spec.get("data", {})
    title = _resolve_chart_text(spec, "title", lang=lang)
    x_label = _resolve_chart_text(spec, "x_label", lang=lang)
    y_label = _resolve_chart_text(spec, "y_label", lang=lang)

    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    try:
        _draw_chart(fig, ax, chart_type, data, title, x_label, y_label)
    except BaseException:
        # pyplot 的 Gcf 對 Figure 持強參考，畫失敗若不 close 就永遠回收不掉；
        # 兩個呼叫端都會吞掉例外（壞圖不可弄死整份報表），在長駐的 GUI/排程
        # 行程裡會隨每次報表累積。
        plt.close(fig)
        raise
    return fig


def _draw_chart(fig, ax, chart_type, data, title, x_label, y_label) -> None:
    if chart_type == "bar":
        labels = data.get("labels", [])
        ax.bar(labels, data.get("values", []), color=CHART_INK)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        # Many categories collide when drawn horizontally (e.g. the audit
        # event-type ranking). Angle the tick labels so they stay legible;
        # tight_layout() below reflows the figure to fit them. Few-label charts
        # keep horizontal labels.
        if len(labels) > 6:
            ax.set_xticks(range(len(labels)))
            ax.set_xticklabels(labels, rotation=30, ha="right")
    elif chart_type == "pie":
        values = data.get("values", [])
        labels = data.get("labels", [])
        total = float(sum(values)) or 1.0
        pcts = [v * 100.0 / total for v in values]
        # 小切片就地標籤留白：完整名稱/件數/百分比一律在圖例
        draw_labels = [l if p >= _PIE_LABEL_MIN_PCT else ""
                       for l, p in zip(labels, pcts)]
        import functools as _ft
        wedges, *_rest = ax.pie(
            values,
            labels=draw_labels,
            colors=_semantic_pie_colors(labels),
            autopct=_ft.partial(_pie_autopct, threshold=_PIE_LABEL_MIN_PCT),
            startangle=90,
            pctdistance=0.78,        # % labels at 78% of radius (default 0.6)
            labeldistance=1.08,      # slice labels at 108% of radius (default 1.1)
            textprops={"fontsize": 9},
        )
        # CRITICAL and HIGH share the crit tone; without a second device they
        # are one red blob. The badge outlines HIGH, a pie hatches it — see the
        # note on _HATCHED_LABELS for why the badge's device does not transfer.
        faces = _semantic_pie_faces(labels)
        if faces:
            for wedge, (face, hatch) in zip(wedges, faces):
                wedge.set_facecolor(face)
                wedge.set_edgecolor(SHELL_TOKENS["paper"])
                wedge.set_linewidth(1.0)
                if hatch:
                    wedge.set_hatch(hatch)
        if labels:
            ax.legend(
                [f"{l} — {v:,} ({p:.1f}%)"
                 for l, v, p in zip(labels, values, pcts)],
                loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8,
                frameon=False,
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
            ax.plot(x, y, "o", markersize=20, color=CHART_INK)
            ax.annotate(node.get("label", key), (x, y), xytext=(0, -15),
                        textcoords="offset points", ha="center")
        ax.set_xlim(-1.5, 1.5)
        ax.set_ylim(-1.5, 1.5)
        ax.axis("off")
    else:
        raise ValueError(f"unsupported chart type: {chart_type!r}")

    ax.set_title(title)
    fig.tight_layout()


def render_matplotlib_png(spec: dict[str, Any], *, lang: str = "en") -> bytes:
    """Render chart spec as a PNG byte string (for Excel embedding)."""
    fig = _build_matplotlib_figure(spec, lang=lang)
    try:
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)
    finally:
        plt.close(fig)
    return buf.getvalue()


def render_matplotlib_svg(spec: dict[str, Any], *, lang: str = "en") -> str:
    """Render chart spec as inline-embeddable SVG markup (for HTML reports)."""
    fig = _build_matplotlib_figure(spec, lang=lang)
    try:
        buf = io.BytesIO()
        # Omit metadata fields (Date, Creator) to reduce SVG size for embedded reports.
        fig.savefig(buf, format="svg", metadata={"Date": None, "Creator": None})
    finally:
        plt.close(fig)
    svg = buf.getvalue().decode("utf-8")
    # Strip XML declaration / DOCTYPE so the markup embeds directly in HTML.
    idx = svg.find("<svg")
    svg = svg[idx:] if idx != -1 else svg
    # Remove the entire <metadata>...</metadata> block to further reduce size.
    # Matplotlib's SVG backend still emits the block even when Date/Creator are None.
    import re
    svg = re.sub(r'\s*<metadata>.*?</metadata>\s*', '', svg, flags=re.DOTALL)
    return svg
