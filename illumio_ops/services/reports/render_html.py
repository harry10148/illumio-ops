"""ReportDocument -> one self-contained HTML file in the report shell (5.x report_shell.css / report_table.js,
copied unchanged from src/report/exporters/assets at 9ad38389). Every value from the PCE or the store is
escaped here; truncation follows the rules in domain.report and is always stated."""
from __future__ import annotations

import html
from datetime import datetime, tzinfo
from functools import cache
from importlib import resources

from illumio_ops.domain.report import (
    BAR_POINT_CAP,
    CELL_SOFT_MAX,
    HTML_ROW_CAP,
    BarBlock,
    Cell,
    Column,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
    period_text,
)
from illumio_ops.domain.values import Language, Severity
from illumio_ops.i18n import translate
from illumio_ops.services.reports.sheets import sheet_names
from illumio_ops.services.reports.svg import bar_svg

SEVERITY_TONE = {Severity.CRITICAL: "crit", Severity.HIGH: "crit", Severity.MEDIUM: "warn", Severity.LOW: "info"}
WIDE_COLUMNS = 9  # report_shell.css: tables this wide get a landscape print page
EXTRA_CSS = """
.report-bars rect { fill: var(--tone-info-border); }
.report-bars text { fill: var(--ink); }
.kpi-trend { font-size: 0.8em; color: var(--tone-neutral-fg); }
.kpi-note { font-size: 0.8em; color: var(--tone-neutral-fg); }
"""


@cache
def asset(name: str) -> str:
    return resources.files("illumio_ops.services.reports").joinpath("assets", name).read_text(encoding="utf-8")


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def tr(lang: Language, msg: str, /, **params: object) -> str:
    return translate(lang, msg, {k: str(v) for k, v in params.items()})


def fmt_number(value: float) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


def fmt_time(value: str, tz: tzinfo | None) -> str:
    """A stored UTC ISO time in the display zone; anything unparsable is shown as given."""
    try:
        return datetime.fromisoformat(value).astimezone(tz).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def cell_text(col: Column, value: Cell, tz: tzinfo | None) -> str:
    if value is None:
        return ""
    if col.kind == "time" and isinstance(value, str):
        return fmt_time(value, tz)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return fmt_number(value)
    return str(value)


def kpi_trend(k: Kpi, lang: Language) -> str:
    """'▲ 2 vs previous period', 'unchanged', or 'No previous period' (never a percentage from nothing)."""
    if k.value is None:
        return ""
    if k.previous is None:
        return tr(lang, "rpt_kpi_no_previous")
    delta = k.value - k.previous
    if delta == 0:
        return tr(lang, "rpt_kpi_flat")
    arrow = "▲" if delta > 0 else "▼"
    amount = fmt_number(abs(delta)) + (" pt" if k.unit == "percent" else "")
    return tr(lang, "rpt_kpi_delta", arrow=arrow, amount=amount)


def _kpi(k: Kpi, lang: Language) -> str:
    if k.value is None:
        value = _esc(tr(lang, "rpt_kpi_no_value"))
    else:
        value = _esc(fmt_number(k.value) + ("%" if k.unit == "percent" else ""))
    note = f'<div class="kpi-note">{_esc(k.note)}</div>' if k.note else ""
    return (f'<div class="kpi" data-kpi="{_esc(k.key)}"><div class="kpi-label">{_esc(k.label)}</div>'
            f'<div class="kpi-value">{value}</div>{note}'
            f'<div class="kpi-trend">{_esc(kpi_trend(k, lang))}</div></div>')


def _cell(col: Column, value: Cell, tz: tzinfo | None, lang: Language) -> str:
    text = cell_text(col, value, tz)
    if len(text) > CELL_SOFT_MAX:
        cut = _esc(text[:CELL_SOFT_MAX])
        return f'{cut}<span class="note">{_esc(tr(lang, "rpt_cell_cut", n=len(text)))}</span>'
    return _esc(text)


def _table(t: TableBlock, sheet: str, tz: tzinfo | None, lang: Language) -> str:
    head = f'<h3 class="subtable-label">{_esc(t.title)}</h3>'
    limit = f'<p class="note note-warn">{_esc(t.limit_note)}</p>' if t.limit_note else ""
    if not t.rows:
        return (head + limit + '<div class="report-table-panel report-table-panel--empty" data-empty="true">'
                f'<span class="empty-text">{_esc(t.empty_text)}</span></div>')
    shown = t.rows[:HTML_ROW_CAP]
    wide = len(t.columns) >= WIDE_COLUMNS
    panel = "report-table-panel" + (" report-table-panel--wide report-table-panel--landscape" if wide else "")
    numeric = {i for i, c in enumerate(t.columns) if c.kind == "number"}
    cols = "".join("<col>" for _ in t.columns)
    ths = "".join(f'<th scope="col"{" class=\"num\"" if i in numeric else ""}>'
                  f'<span class="th-label">{_esc(c.label)}</span></th>' for i, c in enumerate(t.columns))
    body = "".join(
        f'<tr data-row="{n}">' + "".join(
            f'<td{" class=\"num\"" if i in numeric else ""}>{_cell(c, row[i], tz, lang)}</td>'
            for i, c in enumerate(t.columns)) + "</tr>"
        for n, row in enumerate(shown))
    cap = ""
    if len(t.rows) > len(shown):
        cap = f'<p class="note">{_esc(tr(lang, "rpt_rows_capped", shown=len(shown), total=len(t.rows), sheet=sheet))}</p>'
    table = (f'<div class="{panel}"><div class="report-table-wrap"><table class="report-table'
             f'{" report-table--interactive" if len(t.columns) >= 2 else ""}" data-column-count="{len(t.columns)}">'
             f"<colgroup>{cols}</colgroup><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div></div>")
    return head + limit + table + cap


def _bars(b: BarBlock, lang: Language) -> str:
    head = f'<h3 class="subtable-label">{_esc(b.title)}</h3>'
    if not b.points or all(v is None for _, v in b.points):
        return head + f'<p class="note">{_esc(b.empty_text)}</p>'
    points = b.points[-BAR_POINT_CAP:]
    note = (f'<p class="note">{_esc(tr(lang, "rpt_bars_capped", n=BAR_POINT_CAP))}</p>'
            if len(b.points) > BAR_POINT_CAP else "")
    return head + bar_svg(points) + note


def _section_body(s: Section, names: dict[int, str], tz: tzinfo | None, lang: Language) -> str:
    parts = [f'<p class="section-intro">{_esc(s.intro)}</p>'] if s.intro else []
    for block in s.blocks:
        if isinstance(block, TableBlock):
            parts.append(_table(block, names[id(block)], tz, lang))
        elif isinstance(block, BarBlock):
            parts.append(_bars(block, lang))
        elif isinstance(block, TextBlock):
            parts.extend(f"<p>{_esc(p)}</p>" for p in block.paragraphs)
    return "".join(parts)


def _summary(doc: ReportDocument) -> str:
    lang = doc.lang
    kpis = "".join(_kpi(k, lang) for k in doc.kpis)
    if doc.findings:
        cards = "".join(
            f'<div class="finding-card" data-tone="{SEVERITY_TONE.get(f.severity, "neutral")}">'
            f'<div class="finding-header"><span class="badge" data-tone="{SEVERITY_TONE.get(f.severity, "neutral")}">'
            f'{_esc(tr(lang, "severity_" + f.severity.value))}</span>'
            f'<span class="finding-title">{_esc(f.title)}</span></div>'
            f'<p class="finding-desc"><b>{_esc(tr(lang, "rpt_finding_why"))}</b> {_esc(f.why)}</p>'
            f'<p class="finding-rec"><b>{_esc(tr(lang, "rpt_finding_action"))}</b> {_esc(f.action)}</p></div>'
            for f in doc.findings)
    else:
        cards = f'<p class="note">{_esc(tr(lang, "rpt_findings_none"))}</p>'
    quality = "".join(f"<li>{_esc(q)}</li>" for q in doc.data_quality)
    return (f'<div class="kpi-strip">{kpis}</div>'
            f'<h3>{_esc(tr(lang, "rpt_findings_title"))}</h3>{cards}'
            f'<h3>{_esc(tr(lang, "rpt_data_quality_title"))}</h3><ul class="note">{quality}</ul>')


def render_html(doc: ReportDocument, *, tz: tzinfo | None) -> str:
    lang = doc.lang
    names = {id(t): n for (_, t), n in zip(doc.tables(), sheet_names([t.title for _, t in doc.tables()]),
                                            strict=True)}
    meta = [(tr(lang, "rpt_cover_pce"), doc.pce_label),
            (tr(lang, "rpt_cover_period"), period_text(doc.period_start, doc.period_end, tz)),
            (tr(lang, "rpt_cover_generated"), fmt_time(doc.generated_at.isoformat(), tz))]
    meta_html = "".join(f'<div class="cover-meta-pair"><dt>{_esc(k)}</dt><dd>{_esc(v)}</dd></div>' for k, v in meta)
    link = (f'<p class="cover-kicker"><a href="{_esc(doc.gui_link)}">{_esc(tr(lang, "rpt_open_in_gui"))}</a></p>'
            if doc.gui_link else "")
    cover = (f'<header class="cover" data-shell="cover" data-tone="neutral">'
             f'<p class="cover-eyebrow">illumio-ops</p><h1>{_esc(doc.title)}</h1>{link}'
             f'<dl class="cover-meta">{meta_html}</dl></header>')
    summary_title = tr(lang, "rpt_summary_title")
    summary = (f'<section class="exec" id="summary" data-shell="exec" data-tone="neutral">'
               f"<h2>{_esc(summary_title)}</h2>{_summary(doc)}</section>")
    toc_items = "".join(
        f'<li data-tone="neutral"><a href="#{_esc(s.id)}"><span class="toc-num">{i + 1:02d}</span>'
        f'<span class="toc-label">{_esc(s.title)}</span><span class="toc-dot"></span></a></li>'
        for i, s in enumerate(doc.sections))
    toc = (f'<nav class="toc" data-shell="toc"><button class="print-btn" onclick="window.print()">'
           f'{_esc(tr(lang, "rpt_print"))}</button><h2>{_esc(tr(lang, "rpt_toc_title"))}</h2><ol>{toc_items}</ol></nav>')
    chapters = "".join(
        f'<section class="chapter" id="{_esc(s.id)}" data-shell="detail" data-tone="neutral">'
        f'<div class="chapter-head"><span class="chapter-index">S{i + 1:02d}</span>'
        f'<h2 class="chapter-title">{_esc(s.title)}</h2></div>{_section_body(s, names, tz, lang)}</section>'
        for i, s in enumerate(doc.sections))
    lang_attr = "zh-TW" if lang is Language.ZH_TW else "en"
    return ("<!DOCTYPE html>\n"
            f'<html lang="{lang_attr}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{_esc(doc.title)}</title><style>\n{asset('report_shell.css')}\n{EXTRA_CSS}</style></head>"
            f'<body data-report-title="{_esc(doc.title)}"><div class="sheet"><div class="doc">'
            f'{cover}{summary}{toc}<div class="chapters">{chapters}</div></div></div>'
            f"<script>\n{asset('report_table.js')}</script></body></html>")
