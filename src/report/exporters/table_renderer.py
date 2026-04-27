from __future__ import annotations

import html
from typing import Callable

from .report_i18n import STRINGS as _STRINGS

# Tables with this many columns or more get the wide-panel treatment
# (sticky first column + right-edge scroll-affordance gradient).
WIDE_COL_THRESHOLD = 10

def _is_empty(value) -> bool:
    if value is None:
        return True
    text = str(value)
    return text in ("None", "nan", "NaT")

def _default_cell(value) -> str:
    if _is_empty(value):
        return ""
    return html.escape(str(value))

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
    row_attrs: Callable | None = None,
    lang: str = "en",
) -> str:
    if df is None or (hasattr(df, "empty") and df.empty):
        return _empty_panel(no_data_key, lang)

    columns = list(df.columns)
    n_cols = len(columns)
    interactive = n_cols >= 2
    compact = n_cols <= 3
    wide = n_cols >= WIDE_COL_THRESHOLD

    table_cls_parts = ["report-table"]
    if interactive:
        table_cls_parts.append("report-table--interactive")
    table_class = " ".join(table_cls_parts)

    panel_cls_parts = ["report-table-panel"]
    if compact:
        panel_cls_parts.append("report-table-panel--compact")
    if wide:
        panel_cls_parts.append("report-table-panel--wide")
    panel_class = " ".join(panel_cls_parts)

    html_parts = [
        f'<div class="{panel_class}">',
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
        html_parts.append(f'<th title="{title}">{label_html}</th>')
    html_parts.append("</tr></thead><tbody>")

    for _, row in df.iterrows():
        attr_str = ""
        if row_attrs:
            attr_str = row_attrs(row) or ""
        html_parts.append(f"<tr{attr_str}>")
        for col in columns:
            cell_html = render_cell(col, row[col], row) if render_cell else _default_cell(row[col])
            html_parts.append(f"<td>{cell_html}</td>")
        html_parts.append("</tr>")

    html_parts.extend(["</tbody></table>", "</div>", "</div>"])
    return "".join(html_parts)
