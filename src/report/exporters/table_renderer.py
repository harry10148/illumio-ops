from __future__ import annotations

import html
import re
from typing import Callable

from src.i18n import t as _t

from .report_i18n import STRINGS as _STRINGS
from .report_shell import wide_table_attrs

# Tables qualify as "wide" (smaller print font + sticky first col + right-edge
# scroll gradient) when EITHER column count crosses the threshold OR the
# estimated row width exceeds the character budget.
WIDE_COL_THRESHOLD = 8
WIDE_CHARS_THRESHOLD = 120

# Column names whose cells hold a timestamp. Name-based, not value-based: the
# rendered value has often already been formatted (relative time, date-only) by
# the time it reaches here, so sniffing the value would miss those columns.
# Consequence to be aware of: columns named for what they record rather than
# that they are times — ``last_changed``, ``last_heartbeat``, ``paired_at``
# matches only via ``_at$`` — do not pick up ``.col-ts``. Widening this pattern
# is a deliberate change, not a bug fix.
_TS_COL_RE = re.compile(r"(timestamp|_at$|_time$|^time$)", re.I)

# Split point inside a timestamp cell: the single break opportunity between the
# date and the time half. Accepts both ``T`` and space separators — exporters
# emit both. A timestamp is one long whitespace-free token, so without this the
# print layout breaks it character by character and the time becomes unreadable.
_TS_CELL_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})([T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)$")

def _is_empty(value) -> bool:
    if value is None:
        return True
    text = str(value)
    return text in ("None", "nan", "NaT")


def _estimate_row_max_chars(df, columns) -> int:
    """Sum of per-column max-cell-length, capped — proxies A4 print width."""
    if df is None or (hasattr(df, "empty") and df.empty):
        return 0
    total = 0
    for col in columns:
        try:
            series = df[col].astype(str)
            col_max = max(len(str(col)), int(series.str.len().max() or 0))
        except Exception:
            col_max = len(str(col))
        total += min(col_max, 60)  # cap a single mega-col so total stays meaningful
    return total

def _default_cell(value) -> str:
    if _is_empty(value):
        return ""
    return html.escape(str(value))


def _numeric_columns(df, columns) -> set:
    """Columns rendered as measurements: right-aligned, monospace, never wrapped.

    ``is_numeric_dtype`` is True for bool as well, but a right-aligned tabular
    "True" is a state, not a magnitude — booleans are excluded so they keep
    reading as words. (The design prototype reached the same result from the
    other side: its value regex only matched digit-shaped text.)
    """
    try:
        from pandas.api.types import is_bool_dtype, is_numeric_dtype
    except Exception:      # pragma: no cover - pandas is a hard dependency
        return set()
    numeric = set()
    for col in columns:
        try:
            series = df[col]
            if is_numeric_dtype(series) and not is_bool_dtype(series):
                numeric.add(col)
        except Exception:
            continue
    return numeric


def _split_timestamp_cell(cell_html: str) -> str:
    """Insert one ``<wbr/>`` between the date and time halves of a timestamp.

    ``<wbr/>`` contributes no text: the cell still contains every character it
    did before, it just gains one legal place to wrap. Anything that is not a
    bare timestamp (already-formatted values, markup from a custom
    ``render_cell``) is returned untouched.
    """
    match = _TS_CELL_RE.match(cell_html)
    if match is None:
        return cell_html
    return f"{match.group(1)}<wbr/>{match.group(2)}"


def _cell_class(col, numeric_cols: set, ts_cols: set) -> str:
    if col in numeric_cols:
        return ' class="num"'
    if col in ts_cols:
        return ' class="col-ts"'
    return ""


def _wide_hint(n_cols: int, lang: str) -> tuple[str, str]:
    """Panel class suffix + hint paragraph for a wide table.

    A7 ruling — the hint follows ``--wide``, not ``--landscape``. The design
    prototype (``design/v2/tools/reskin_report.py::_wide_table_hint``) emits a
    hint for **every** ``.report-table-panel--wide`` panel and adds
    ``--landscape`` only from ten columns up, with the print half of the
    sentence changing between the two. A ``--wide`` table scrolls horizontally
    on screen whether it has eight columns or twenty, and a reader who cannot
    tell that columns are off-screen reads a scrolled table as a complete one —
    the silent-truncation failure this project's report rule exists to prevent.
    ``.table-hint`` is ``display: none`` in the print block, so this is purely a
    screen affordance and costs the printed page nothing.

    ``wide_table_attrs()`` owns the >=10 case (class and hint together); its
    signature is a contract shared with five tasks and is not touched here.
    """
    landscape_cls, landscape_hint = wide_table_attrs(n_cols, lang)
    if landscape_cls:
        return landscape_cls, landscape_hint
    hint = html.escape(_t("rpt_shell_table_hint_wide_portrait", lang=lang, cols=n_cols))
    return "", f'<p class="table-hint">{hint}</p>'

def _panel_attrs(df, columns, lang: str) -> tuple[str, str]:
    """``(panel class, hint paragraph)`` for a table of ``columns`` over ``df``.

    Extracted verbatim from ``render_df_table`` so the hand-written tables in
    policy_diff / rule_hit_count / readiness get exactly the same wide-table
    verdict. Those three build their own ``<tr>``/``<td>`` markup (row colouring
    by change type, per-cell truncation with the full value in ``title``,
    timestamps that must stay one unbroken token) which ``render_df_table``
    cannot express, but the panel is where every print-survival rule in
    SHELL_CSS hangs off — ``--wide`` alone carries the reduced font, the tighter
    padding and the four column-width floors. Duplicating the predicate in each
    exporter would let the three drift away from the other seven the first time
    the threshold moves.
    """
    n_cols = len(columns)
    wide = (
        n_cols >= WIDE_COL_THRESHOLD
        or _estimate_row_max_chars(df, columns) > WIDE_CHARS_THRESHOLD
    )
    parts = ["report-table-panel"]
    if n_cols <= 3:
        parts.append("report-table-panel--compact")
    hint_html = ""
    if wide:
        parts.append("report-table-panel--wide")
        landscape_cls, hint_html = _wide_hint(n_cols, lang)
        if landscape_cls:
            parts.append(landscape_cls.strip())
    return " ".join(parts), hint_html


def wrap_table_panel(table_html: str, df, columns, lang: str = "en") -> str:
    """Put a hand-written ``.report-table-wrap`` block inside a shell panel.

    ``table_html`` must already be the ``<div class="report-table-wrap">…</div>``
    the exporter renders; this only adds the panel and the screen-only wide-table
    hint around it, so the caller's cell markup is untouched.
    """
    panel_class, hint_html = _panel_attrs(df, columns, lang)
    return f'<div class="{panel_class}">{hint_html}{table_html}</div>'


def _empty_panel(no_data_key: str, lang: str = "en") -> str:
    """Render the empty-state tombstone panel."""
    msg = html.escape(_STRINGS[no_data_key].get(lang) or _STRINGS[no_data_key]["en"])
    return (
        '<div class="report-table-panel report-table-panel--empty" data-empty="true">'
        '<span class="empty-marker" aria-hidden="true"></span>'
        f'<span class="empty-text">{msg}</span>'
        '</div>'
    )

def render_df_table(
    df,
    *,
    col_i18n: dict[str, str],
    no_data_key: str = "rpt_no_data",
    render_cell: Callable | None = None,
    value_i18n_maps: dict[str, dict[str, str]] | None = None,
    row_attrs: Callable | None = None,
    lang: str = "en",
) -> str:
    if df is None or (hasattr(df, "empty") and df.empty):
        return _empty_panel(no_data_key, lang)

    columns = list(df.columns)
    n_cols = len(columns)
    interactive = n_cols >= 2

    table_cls_parts = ["report-table"]
    if interactive:
        table_cls_parts.append("report-table--interactive")
    table_class = " ".join(table_cls_parts)

    numeric_cols = _numeric_columns(df, columns)
    ts_cols = {col for col in columns
               if col not in numeric_cols and _TS_COL_RE.search(str(col))}

    panel_class, hint_html = _panel_attrs(df, columns, lang)

    html_parts = [
        f'<div class="{panel_class}">',
        hint_html,
        '<div class="report-table-wrap">',
        (
            f'<table class="{table_class}" '
            f'data-interactive="{str(interactive).lower()}" '
            f'data-column-count="{n_cols}">'
        ),
        "<colgroup>",
    ]

    for _ in columns:
        html_parts.append('<col>')

    html_parts.extend([
        "</colgroup>",
        "<thead><tr>",
    ])
    for col in columns:
        i18n_key = col_i18n.get(col)
        title = html.escape(str(col), quote=True)
        label_text = html.escape(str(col))
        if i18n_key:
            translated = html.escape(_STRINGS[i18n_key].get(lang) or _STRINGS[i18n_key]["en"])
            label_html = f'<span class="th-label">{translated}</span>'
        else:
            label_html = f'<span class="th-label">{label_text}</span>'
        cls = _cell_class(col, numeric_cols, ts_cols)
        html_parts.append(f'<th title="{title}"{cls}>{label_html}</th>')
    html_parts.append("</tr></thead><tbody>")

    for _, row in df.iterrows():
        attr_str = ""
        if row_attrs:
            attr_str = row_attrs(row) or ""
        html_parts.append(f"<tr{attr_str}>")
        for col in columns:
            raw_value = row[col]
            # Render-layer i18n: translate stable English value via map (if provided)
            # before custom render_cell or default rendering. Pass-through on miss.
            if value_i18n_maps and col in value_i18n_maps:
                key = value_i18n_maps[col].get(str(raw_value))
                if key:
                    entry = _STRINGS.get(key)
                    if entry:
                        translated = entry.get(lang) or entry.get("en")
                        if translated:
                            raw_value = translated
            if render_cell:
                cell_html = render_cell(col, raw_value, row)
            else:
                cell_html = _default_cell(raw_value)
                if col in ts_cols:
                    # Escaped first, then split: the <wbr/> is markup we add, so
                    # it must not itself go through html.escape().
                    cell_html = _split_timestamp_cell(cell_html)
            html_parts.append(f"<td{_cell_class(col, numeric_cols, ts_cols)}>{cell_html}</td>")
        html_parts.append("</tr>")

    html_parts.extend(["</tbody></table>", "</div>", "</div>"])
    return "".join(html_parts)
