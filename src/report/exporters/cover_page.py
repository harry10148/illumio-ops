from __future__ import annotations
from datetime import datetime
from html import escape as _escape
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
    *,
    maturity_grade: str | None = None,
    maturity_score: int | None = None,
) -> str:
    date_str = " – ".join(d for d in date_range if d)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = _escape(title)
    report_type = _escape(report_type)
    pce_url = _escape(pce_url)
    org_name = _escape(org_name)
    date_str = _escape(date_str)

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
    grade_block = ""
    if maturity_grade and maturity_grade != "?":
        from src.report.exporters.grade_colors import grade_color
        color = grade_color(maturity_grade)
        score_part = (
            f' <span style="font-size:14pt;font-weight:400;opacity:0.7">'
            f'({maturity_score}/100)</span>'
            if maturity_score is not None else ""
        )
        grade_block = (
            f'<div class="cover-grade" style="margin-top:12px;color:{color};'
            f'font-size:28pt;font-weight:700;">'
            f'{_escape(str(maturity_grade))}{score_part}</div>'
        )
    org_html = (
        f'<div class="cover-org">{org_name}</div>'
        if org_name else '<div></div>'
    )

    meta_items = []
    meta_items.append(
        f'<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--slate-50);margin-bottom:2px">'
        f'{_s("rpt_cover_generated", lang)}</div>'
        f'<strong>{now_str}</strong></div>'
    )
    if date_str:
        meta_items.append(
            f'<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--slate-50);margin-bottom:2px">'
            f'{_s("rpt_cover_date_range", lang)}</div>'
            f'<strong>{date_str}</strong></div>'
        )
    if pce_url:
        meta_items.append(
            f'<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--slate-50);margin-bottom:2px">'
            f'PCE</div>'
            f'<strong>{pce_url}</strong></div>'
        )
    if org_name:
        meta_items.append(
            f'<div><div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--slate-50);margin-bottom:2px">'
            f'{_s("rpt_cover_org", lang) if _s("rpt_cover_org", lang) != "rpt_cover_org" else "Organization"}</div>'
            f'<strong>{org_name}</strong></div>'
        )
    meta_html = '<div class="meta">' + ''.join(meta_items) + '</div>' if meta_items else ''

    return (
        # Screen cover block (inside report-main, shown as first content element)
        '<div class="report-cover-block screen-only">'
        '<p class="eyebrow">Illumio PCE Ops</p>'
        f'<h1>{title}</h1>'
        + (f'<p class="sub">{report_type}</p>' if report_type and report_type != title else '')
        + grade_block
        + meta_html
        + '</div>'
        # Print-only full-page cover (always present but display:none on screen)
        + '<section class="report-cover card print-only" id="cover">'
        '<div>'
        '<div class="cover-eyebrow">Illumio Operations</div>'
        f'<div class="cover-title">{title}</div>'
        '<div class="cover-rule"></div>'
        f'{type_badge}'
        f'{grade_block}'
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
