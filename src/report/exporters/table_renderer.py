from __future__ import annotations

import html
from typing import Callable


def _is_empty(value) -> bool:
    if value is None:
        return True
    text = str(value)
    return text in ("None", "nan", "NaT")


def _default_cell(value) -> str:
    if _is_empty(value):
        return ""
    return html.escape(str(value))


def render_df_table(
    df,
    *,
    col_i18n: dict[str, str],
    no_data_key: str = "rpt_no_data",
    render_cell: Callable | None = None,
    row_attrs: Callable | None = None,
) -> str:
    if df is None or (hasattr(df, "empty") and df.empty):
        return f'<p class="note" data-i18n="{no_data_key}">No data</p>'

    html_parts = [
        '<div class="report-table-panel">',
        '<div class="report-table-hint" data-i18n="rpt_table_hint">Sort • Resize</div>',
        '<div class="report-table-wrap">',
        '<table class="report-table">',
        '<colgroup>',
    ]

    columns = list(df.columns)
    for _ in columns:
        html_parts.append('<col style="width: 160px; min-width: 96px;">')

    html_parts.extend([
        '</colgroup>',
        '<thead><tr>',
    ])
    for col in columns:
        i18n_key = col_i18n.get(col)
        title = html.escape(str(col), quote=True)
        if i18n_key:
            html_parts.append(
                f'<th data-i18n="{i18n_key}" title="{title}">{html.escape(str(col))}</th>'
            )
        else:
            html_parts.append(f'<th title="{title}">{html.escape(str(col))}</th>')
    html_parts.append("</tr></thead><tbody>")

    for _, row in df.iterrows():
        attr_str = ""
        if row_attrs:
            attr_str = row_attrs(row) or ""
        html_parts.append(f"<tr{attr_str}>")
        for col in columns:
            if render_cell:
                cell_html = render_cell(col, row[col], row)
            else:
                cell_html = _default_cell(row[col])
            html_parts.append(f"<td>{cell_html}</td>")
        html_parts.append("</tr>")

    html_parts.extend(["</tbody></table>", "</div>", "</div>"])
    return "".join(html_parts)
