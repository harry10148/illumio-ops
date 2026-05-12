from __future__ import annotations
from datetime import datetime
from src.report.exporters.report_i18n import STRINGS


def _s(key: str, lang: str) -> str:
    entry = STRINGS.get(key, {})
    return entry.get(lang) or entry.get("en", key)


def build_cover_page(
    title: str,
    report_type: str,
    date_range: tuple[str, str] = ("", ""),
    pce_url: str = "",
    org_name: str = "",
    lang: str = "en",
) -> str:
    date_str = " – ".join(d for d in date_range if d)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    date_line = (
        f'<div>📅 {_s("rpt_cover_date_range", lang)}: {date_str}</div>'
        if date_str else ""
    )
    pce_line = (
        f'<div>🖥 {_s("rpt_cover_pce", lang)}: {pce_url}</div>'
        if pce_url else ""
    )
    type_badge = (
        f'<div class="cover-type">{report_type}</div>'
        if report_type else ""
    )
    org_html = (
        f'<div class="cover-org">{org_name}</div>'
        if org_name else '<div></div>'
    )

    return (
        '<section class="report-cover card" id="cover">'
        '<div>'
        '<div class="cover-eyebrow">Illumio Operations</div>'
        f'<div class="cover-title">{title}</div>'
        '<div class="cover-rule"></div>'
        f'{type_badge}'
        f'<div class="cover-meta">{date_line}{pce_line}</div>'
        '</div>'
        '<div class="cover-footer">'
        f'{org_html}'
        '<div class="cover-generated">'
        f'<div style="font-size:9pt;opacity:0.5;margin-bottom:2px">'
        f'{_s("rpt_cover_generated", lang)}</div>'
        f'<div>{now_str}</div>'
        '</div>'
        '</div>'
        '</section>'
    )
