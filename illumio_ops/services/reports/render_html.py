"""ReportDocument -> one self-contained HTML file in the report shell (5.x report_shell.css / report_table.js,
copied unchanged from src/report/exporters/assets at 9ad38389). Every value from the PCE or the store is
escaped here; truncation follows the rules in domain.report and is always stated."""
from __future__ import annotations

import html
import re
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
# The top rule of the first page shows the report's highest severity (spec §8); no finding: grey.
TOP_RULE = {Severity.CRITICAL: "crit", Severity.HIGH: "high", Severity.MEDIUM: "medium", Severity.LOW: "low"}
SEVERITY_RANK = (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
WIDE_COLUMNS = 9  # report_shell.css: tables this wide get a landscape print page
EXTRA_CSS = """
/* The console's light palette (UI redesign spec §7, §8): the same greys, ink and severity colours as the GUI. */
:root {
  --canvas: #F4F6F8; --surface-2: #F4F6F8; --text-1: #111827; --text-2: #374151; --text-3: #4B5563;
  --line: #E5E7EB; --line-soft: #F0F2F5; --track: #E5E7EB; --accent: #2563EB; --accent-fg: #1D4ED8;
  --tone-crit-border: #FCA5A5; --tone-crit-fg: #B91C1C; --tone-crit-bg: #FEF2F2;
  --tone-warn-border: #FDBA74; --tone-warn-fg: #C2410C; --tone-warn-bg: #FFF7ED;
  --tone-info-border: #CBD5E1; --tone-info-fg: #4B5563; --tone-info-bg: #F8FAFC;
  --tone-ok-border: #86EFAC; --tone-ok-fg: #15803D; --tone-ok-bg: #F0FDF4;
}
.cover { border-top: 6px solid #9CA3AF; }
.cover[data-top="crit"] { border-top-color: #B91C1C; }
.cover[data-top="high"] { border-top-color: #C2410C; }
.cover[data-top="medium"] { border-top-color: #A16207; }
.cover[data-top="low"] { border-top-color: #4B5563; }
.conclusion { font-size: 1.35em; line-height: 1.5; font-weight: 600; color: var(--text-1); margin: 0.6em 0 0.8em; }
.findings-table { width: 100%; border-collapse: collapse; font-size: var(--fs-body); }
.findings-table th, .findings-table td { text-align: left; vertical-align: top; padding: 6px 8px;
  border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
.findings-table th { color: var(--text-3); font-weight: 600; }
.mitre-chips { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px; }
@media print {
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  .print-btn { display: none; }
}
.report-bars rect { fill: var(--tone-info-border); }
.report-bars text { fill: var(--ink); }
.kpi-trend { font-size: 0.8em; color: var(--tone-neutral-fg); }
.kpi-note { font-size: 0.8em; color: var(--tone-neutral-fg); }
/* A long table may break across printed pages (rows still never split; the header repeats): the shell keeps a
   panel whole, which moved every long table to a fresh page and left the page before it blank. */
@media print { .report-table-panel--long { break-inside: auto; } }
"""
LONG_TABLE_ROWS = 15


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
    """'▲ 2 vs previous period' or 'unchanged'; nothing without a previous period (the data notes say once that
    the report has none to compare with — finish.py — never a percentage from nothing)."""
    if k.value is None or k.previous is None:
        return ""
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


def _share_cell(col: Column, value: Cell, tz: tzinfo | None) -> str:
    """A share as its number and a bar of that length (a <progress>, so no inline style)."""
    text = cell_text(col, value, tz)
    m = _SHARE.match(text)
    if not m:
        return f"<td>{_esc(text)}</td>"
    return (f'<td class="share"><span class="share-num">{_esc(text)}</span>'
            f'<progress class="share-bar" max="100" value="{float(m.group(1)):g}" aria-hidden="true"></progress></td>')


def _cell(col: Column, value: Cell, tz: tzinfo | None, lang: Language) -> str:
    text = cell_text(col, value, tz)
    if len(text) > CELL_SOFT_MAX:
        cut = _esc(text[:CELL_SOFT_MAX])
        return f'{cut}<span class="note">{_esc(tr(lang, "rpt_cell_cut", n=len(text)))}</span>'
    return _esc(text)


_SHARE = re.compile(r"^(\d{1,3}(?:\.\d+)?)%$")
SAME_ON_EVERY_ROW = frozenset({"action"})  # columns said once above the table when every row says the same


def _share_columns(t: TableBlock, tz: tzinfo | None) -> set[int]:
    """Columns whose every filled cell is a share between 0% and 100%: drawn with a bar beside the number."""
    out = set()
    for i, c in enumerate(t.columns):
        cells = [cell_text(c, r[i], tz) for r in t.rows]
        filled = [x for x in cells if x not in ("", "—")]
        if filled and all((m := _SHARE.match(x)) and float(m.group(1)) <= 100 for x in filled):
            out.add(i)
    return out


def _said_once(t: TableBlock, tz: tzinfo | None) -> dict[int, str]:
    """Column -> its text, for the SAME_ON_EVERY_ROW columns that repeat one sentence on every row (two rows or
    more): the HTML says it once above the table. The XLSX keeps the column."""
    if len(t.rows) < 2 or len(t.columns) < 3:
        return {}
    out = {}
    for i, c in enumerate(t.columns):
        if c.key in SAME_ON_EVERY_ROW:
            texts = {cell_text(c, r[i], tz) for r in t.rows}
            if len(texts) == 1 and next(iter(texts)).strip():
                out[i] = next(iter(texts))
    return out


def _table(t: TableBlock, sheet: str, tz: tzinfo | None, lang: Language) -> str:
    head = f'<h3 class="subtable-label">{_esc(t.title)}</h3>'
    limit = f'<p class="note note-warn">{_esc(t.limit_note)}</p>' if t.limit_note else ""
    if not t.rows:
        return (head + limit + '<div class="report-table-panel report-table-panel--empty" data-empty="true">'
                f'<span class="empty-text">{_esc(t.empty_text)}</span></div>')
    shown = t.rows[:HTML_ROW_CAP if t.html_rows is None else min(HTML_ROW_CAP, t.html_rows)]
    if not shown:  # every row is in the XLSX only: the builder's sentence and where to find them
        return (head + limit + f'<p class="note" data-role="xlsx-only">{_esc(t.html_note or "")} '
                f'{_esc(tr(lang, "rpt_rows_in_sheet", total=len(t.rows), sheet=sheet))}</p>')
    once = _said_once(t, tz)
    if once:  # the sentence every row repeats, said once; the column is left out of the HTML table
        head += "".join(f'<p class="note" data-role="said-once"><strong>{_esc(t.columns[i].label)}</strong> '
                        f"{_esc(text)}</p>" for i, text in once.items())
        keep = [i for i in range(len(t.columns)) if i not in once]
        t = t.model_copy(update={"columns": tuple(t.columns[i] for i in keep),
                                 "rows": tuple(tuple(r[i] for i in keep) for r in t.rows)})
        shown = t.rows[:len(shown)]
    shares = _share_columns(t, tz)
    wide = len(t.columns) >= WIDE_COLUMNS
    panel = ("report-table-panel" + (" report-table-panel--wide report-table-panel--landscape" if wide else "")
             + (" report-table-panel--long" if len(shown) > LONG_TABLE_ROWS else ""))
    numeric = {i for i, c in enumerate(t.columns) if c.kind == "number"}
    cols = "".join("<col>" for _ in t.columns)
    ths = "".join(f'<th scope="col"{" class=\"num\"" if i in numeric else ""}>'
                  f'<span class="th-label">{_esc(c.label)}</span></th>' for i, c in enumerate(t.columns))
    body = "".join(
        f'<tr data-row="{n}">' + "".join(
            (_share_cell(c, row[i], tz) if i in shares else
             f'<td{" class=\"num\"" if i in numeric else ""}>{_cell(c, row[i], tz, lang)}</td>')
            for i, c in enumerate(t.columns)) + "</tr>"
        for n, row in enumerate(shown))
    cap = ""
    if len(t.rows) > len(shown):
        said = f"{t.html_note} " if t.html_note and t.html_rows is not None else ""
        cap = (f'<p class="note">{_esc(said)}'
               f'{_esc(tr(lang, "rpt_rows_capped", shown=len(shown), total=len(t.rows), sheet=sheet))}</p>')
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


NARROW_COLUMNS = 3  # a table this narrow takes half the page at most


def _narrow(block: object) -> bool:
    return isinstance(block, TableBlock) and bool(block.rows) and len(block.columns) <= NARROW_COLUMNS


def _section_body(s: Section, names: dict[int, str], tz: tzinfo | None, lang: Language) -> str:
    parts = [f'<p class="section-intro">{_esc(s.intro)}</p>'] if s.intro else []
    if s.workbench_link:
        parts.append(f'<p class="section-link"><a href="{_esc(s.workbench_link)}">{_esc(tr(lang, "rpt_open_in_workbench"))}</a></p>')
    blocks = list(s.blocks)
    i = 0
    while i < len(blocks):
        block = blocks[i]
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if _narrow(block) and _narrow(nxt):  # two narrow tables share a row (one column when the page is narrow)
            assert isinstance(block, TableBlock) and isinstance(nxt, TableBlock)
            parts.append('<div class="table-pair">'
                         f"<div>{_table(block, names[id(block)], tz, lang)}</div>"
                         f"<div>{_table(nxt, names[id(nxt)], tz, lang)}</div></div>")
            i += 2
            continue
        i += 1
        if isinstance(block, TableBlock):
            parts.append(_table(block, names[id(block)], tz, lang))
        elif isinstance(block, BarBlock):
            parts.append(_bars(block, lang))
        elif isinstance(block, TextBlock):
            parts.extend(f"<p>{_esc(p)}</p>" for p in block.paragraphs)
    return "".join(parts)


def _chips(techniques: tuple[tuple[str, str], ...]) -> str:
    """MITRE ATT&CK technique ids under a finding's title, the official name on hover; not links (a report makes no
    external request, and its reader may be offline)."""
    if not techniques:
        return ""
    return '<div class="mitre-chips">' + " ".join(
        f'<span class="mitre-chip" title="{_esc(name)}">{_esc(tid)}</span>' for tid, name in techniques) + "</div>"


def _summary(doc: ReportDocument) -> str:
    """The key numbers, then S01 — findings and actions as a table (severity, finding, action, evidence) — then what
    the data covers."""
    lang = doc.lang
    kpis = "".join(_kpi(k, lang) for k in doc.kpis)
    if doc.findings:
        rows = "".join(
            f'<tr><td><span class="badge" data-tone="{SEVERITY_TONE.get(f.severity, "neutral")}">'
            f'{_esc(tr(lang, "severity_" + f.severity.value))}</span></td>'
            f'<td>{_esc(f.title)}{_chips(f.techniques)}</td><td>{_esc(f.action)}</td><td>{_esc(f.why)}</td></tr>'
            for f in doc.findings)
        head = "".join(f"<th>{_esc(tr(lang, k))}</th>" for k in (
            "rpt_findings_col_severity", "rpt_findings_col_finding", "rpt_findings_col_action", "rpt_findings_col_evidence"))
        cards = (f'<table class="findings-table" data-role="findings-table"><thead><tr>{head}</tr></thead>'
                 f"<tbody>{rows}</tbody></table>")
    else:
        cards = f'<p class="note" data-role="findings-table">{_esc(tr(lang, "rpt_findings_none"))}</p>'
    quality = "".join(f"<li>{_esc(q)}</li>" for q in doc.data_quality)
    return (f'<div class="kpi-strip">{kpis}</div>'
            f'<h3><span class="toc-num">S01</span> {_esc(tr(lang, "rpt_findings_title"))}</h3>{cards}'
            f'<h3>{_esc(tr(lang, "rpt_data_quality_title"))}</h3><ul class="note">{quality}</ul>')


def _top(doc: ReportDocument) -> str:
    if not doc.findings:
        return "none"
    return TOP_RULE[max((f.severity for f in doc.findings), key=SEVERITY_RANK.index)]


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
    sentence = (f'<p class="conclusion" data-role="conclusion">{_esc(doc.conclusion)}</p>' if doc.conclusion else "")
    cover = (f'<header class="cover" data-shell="cover" data-tone="neutral" data-top="{_top(doc)}">'
             f'<p class="cover-eyebrow">illumio-ops・{_esc(doc.title)}</p><h1>{_esc(doc.title)}</h1>{sentence}{link}'
             f'<dl class="cover-meta">{meta_html}</dl></header>')
    summary_title = tr(lang, "rpt_summary_title")
    summary = (f'<section class="exec" id="summary" data-shell="exec" data-tone="neutral">'
               f"<h2>{_esc(summary_title)}</h2>{_summary(doc)}</section>")
    toc_items = "".join(
        f'<li data-tone="neutral"><a href="#{_esc(s.id)}"><span class="toc-num">{i + 1:02d}</span>'
        f'<span class="toc-label">{_esc(s.title)}</span><span class="toc-dot"></span></a></li>'
        for i, s in enumerate(doc.sections))
    toc = (f'<nav class="toc" data-shell="toc"><button class="print-btn" onclick="window.print()">'
           f'{_esc(tr(lang, "rpt_print"))}</button>'
           # a report without sections (nothing computed) has no table of contents to head
           + (f'<h2>{_esc(tr(lang, "rpt_toc_title"))}</h2><ol>{toc_items}</ol>' if doc.sections else "") + "</nav>")
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
