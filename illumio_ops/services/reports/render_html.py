"""ReportDocument -> one self-contained HTML file in the report shell (5.x report_shell.css / report_table.js,
copied from src/report/exporters/assets at 9ad38389; the column fitting in report_table.js is v6's). Every value
from the PCE or the store is escaped here; truncation follows the rules in domain.report and is always stated.

The page, top to bottom (UI redesign spec §9.1; each part has a data-role): the cover with the one-sentence
conclusion; "know this before reading the numbers" (caveats); the three lead numbers (lead-kpis, their notes under
the row in lead-notes); the things to do first (top-actions); every finding as a card (findings); the other numbers
(other-kpis); the contents; the sections; and last the part "how to read this report" — the builder's `how` section,
the data notes (a section this renderer writes, id `notes`) and the sections that hold nothing."""
from __future__ import annotations

import html
import re
from contextvars import ContextVar
from datetime import datetime, tzinfo
from functools import cache
from importlib import resources

from illumio_ops.domain.actions import TopAction, action_number, top_actions
from illumio_ops.domain.report import (
    BAR_POINT_CAP,
    CELL_SOFT_MAX,
    HTML_ROW_CAP,
    PRINT_ROW_CAP,
    BarBlock,
    Cell,
    Column,
    Finding,
    Kpi,
    ReportDocument,
    Section,
    TableBlock,
    TextBlock,
    period_text,
)
from illumio_ops.domain.values import Language, ReportType, Severity
from illumio_ops.i18n import translate
from illumio_ops.services.reports.common import host_url
from illumio_ops.services.reports.finish import NOTHING, UNEVALUATED
from illumio_ops.services.reports.sheets import sheet_names
from illumio_ops.services.reports.svg import bar_svg

SEVERITY_TONE = {Severity.CRITICAL: "crit", Severity.HIGH: "crit", Severity.MEDIUM: "warn", Severity.LOW: "info"}
# The top rule of the first page shows the report's highest severity (spec §8); no finding: grey.
TOP_RULE = {Severity.CRITICAL: "crit", Severity.HIGH: "high", Severity.MEDIUM: "medium", Severity.LOW: "low"}
SEVERITY_RANK = (Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL)
WIDE_COLUMNS = 9  # report_shell.css: tables this wide get a landscape print page
LEAD_KPIS = 3  # the numbers the first page leads with (finish() puts the type's lead numbers first)
# Section ids with a fixed place: the rules that were not evaluated close the ordinary sections; `how`, the data
# notes and the sections that hold nothing are the closing part, in that order.
HOW, NOTES = "how", "notes"
BETTER_KEYS = {"higher": "rpt_kpi_better_higher", "lower": "rpt_kpi_better_lower"}  # neutral: nothing is said
_SLOT = "\ufffc"  # stands in a translated sentence for markup put in after escaping
_CSS = """
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

/* ── stage 3a: the first page, the cards, the closing part ─────────────────────────────────────────────── */
/* A label that may hold Chinese is not letter-spaced ("期 間"). */
html[lang="zh-TW"] .cover-eyebrow, html[lang="zh-TW"] .cover-meta dt, html[lang="zh-TW"] .kpi-label,
html[lang="zh-TW"] .th-label, html[lang="zh-TW"] .toc h2, html[lang="zh-TW"] .badge,
html[lang="zh-TW"] .print-btn { letter-spacing: 0; }
.first-page, .findings, .other-kpis { grid-column: 1 / -1; min-width: 0; margin: 0 0 var(--space-7); }
.first-page a, .findings a, a[data-role="host-link"] { color: var(--text-1); text-decoration: underline;
  text-decoration-color: #8A8F91; text-underline-offset: 3px; }
.caveats { border-left: 3px solid var(--accent-fg); background: var(--surface-2); padding: 10px 14px;
  margin: 0 0 var(--space-6); font-size: var(--fs-ui); overflow-wrap: anywhere; }
.caveats strong { display: block; }
.caveats p { margin: 2px 0 0; }
/* One row, as many equal cells as there are numbers (three at most); the cells of a row are as tall as the tallest.
   A narrow screen stacks them (each as tall as the tallest, by grid-auto-rows); paper keeps the row. */
.lead-kpis { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 12px; margin: 0 0 8px; }
.lead-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-width: 0;
  display: flex; flex-direction: column; gap: 4px; break-inside: avoid; }
.lead-label { font-size: var(--fs-body); color: var(--text-2); overflow-wrap: anywhere; }
.lead-value { font-size: 30px; font-weight: 600; line-height: 1.2; font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere; color: var(--text-1); }
.lead-change { font-size: var(--fs-body); color: var(--text-3); }
.lead-change[data-trend="better"] { color: var(--tone-ok-fg); }
.lead-change[data-trend="worse"] { color: var(--tone-crit-fg); }
.lead-better { font-size: var(--fs-mini); color: var(--text-3); }
.lead-notes { font-size: var(--fs-body); color: var(--text-3); margin: 0 0 var(--space-6); overflow-wrap: anywhere; }
.lead-notes p { margin: 2px 0; }
@media screen and (max-width: 820px) {
  .lead-kpis { grid-auto-flow: row; grid-auto-rows: 1fr; }
  .finding dl { grid-template-columns: minmax(0, 1fr); }
}
.top-actions { margin: var(--space-6) 0 0; }
.top-actions > h2, .findings > h2, .other-kpis > h2 { font-size: var(--fs-lead); margin: 0 0 10px; break-after: avoid; }
.top-actions ol { list-style: none; margin: 0 0 8px; padding: 0; display: grid; gap: 8px; }
.top-action { display: grid; grid-template-columns: 24px minmax(0, 1fr); gap: 10px; background: var(--surface-2);
  border-radius: 8px; padding: 12px 14px; break-inside: avoid; }
.action-num { width: 24px; height: 24px; border-radius: 50%; background: var(--text-1); color: #FFFFFF;
  font-weight: 600; font-size: 13px; display: grid; place-items: center; }
.action-body { min-width: 0; overflow-wrap: anywhere; }
.action-short { font-weight: 600; }
.action-solves, .action-focus { display: block; color: var(--text-3); font-size: var(--fs-body); margin: 2px 0 0; }
.top-actions p { margin: 4px 0 0; }
.finding { border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; margin: 0 0 10px;
  break-inside: avoid; }
.finding h3 { margin: 0 0 8px; font-size: var(--fs-ui); overflow-wrap: anywhere; }
.finding dl { display: grid; grid-template-columns: 8.5em minmax(0, 1fr); gap: 4px 12px; margin: 0;
  font-size: var(--fs-body); }
.finding dt { color: var(--text-3); }
.finding dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.part-title { margin: 0 0 var(--space-6); padding-top: var(--space-5); border-top: 1px solid var(--line);
  font-size: var(--fs-lead); break-after: avoid; }
.toc li.toc-part { padding: var(--space-4) 0 var(--space-2); font-size: var(--fs-mini); color: var(--text-3);
  font-weight: 600; }
.notes-list { margin: 0; padding-left: 1.2em; overflow-wrap: anywhere; }
/* report_table.js narrows a column to the longest word of its header and cells before it lets a table scroll;
   a table that only fits that way (it marks it) draws its share bars half as long. */
.report-table--tight .share-bar { width: 36px; }
.notes-list li { margin: 0 0 4px; }

/* stage 3a print */
@media print {
  /* The cover, the first page and the findings run on: nothing here starts a page of its own. A heading stays
     with what it heads; a card, a number and a thing to do are never split. */
  .cover { min-height: 0; padding-top: 0; margin-bottom: var(--space-6); break-after: auto; }
  .toc { break-after: auto; margin-bottom: var(--space-6); }
  .chapter { break-before: auto; }
  .finding { break-inside: avoid; }
  .lead-value { font-size: 20pt; }
  /* A4's printable width is 695px: four share columns at their screen width (135px each, the number and a 72px
     bar that do not wrap) pushed the readiness scores table 100px past the paper's edge. */
  .share-bar { width: 36px; }
  .report-table td.share .share-num { min-width: 3em; margin-right: 4px; }
  /* Paper lists a table's first rows, as the reader sorted them (by place, not by the row's own number). */
  table[data-print-cap] tbody tr:nth-child(n+__AFTER_CAP__) { display: none; }
}
"""
EXTRA_CSS = _CSS.replace("__AFTER_CAP__", str(PRINT_ROW_CAP + 1))
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


def _kpi_delta(k: Kpi) -> tuple[int, str] | None:
    """(-1, 0 or 1, the size of the change as it is printed), or None without both values. A change that prints as
    0 (two percentages 0.04 apart) is no change: the sentence never says "up 0.0"."""
    if k.value is None or k.previous is None:
        return None
    delta = k.value - k.previous
    amount = fmt_number(abs(delta))
    if delta == 0 or float(amount.replace(",", "")) == 0:
        return 0, amount
    return (1 if delta > 0 else -1), amount


def kpi_trend(k: Kpi, lang: Language) -> str:
    """'Up 2,823 from the previous period', 'Down 2.5 percentage points …' or 'Unchanged …'; nothing without a
    previous period (the data notes say once that the report has none to compare with — finish.py — never a change
    from nothing). The one sentence the HTML, the XLSX and the email all print."""
    change = _kpi_delta(k)
    if change is None:
        return ""
    sign, amount = change
    if sign == 0:
        return tr(lang, "rpt_kpi_flat")
    if k.unit == "percent":
        amount = tr(lang, "rpt_kpi_points", n=amount)
    return tr(lang, "rpt_kpi_more" if sign > 0 else "rpt_kpi_fewer", amount=amount)


def _kpi_value(k: Kpi, lang: Language) -> str:
    if k.value is None:
        return tr(lang, "rpt_kpi_no_value")
    return fmt_number(k.value) + ("%" if k.unit == "percent" else "")


def _kpi(k: Kpi, lang: Language) -> str:
    """One of the other numbers: a small cell with its note inside."""
    note = f'<div class="kpi-note">{_esc(k.note)}</div>' if k.note else ""
    trend = kpi_trend(k, lang)
    return (f'<div class="kpi" data-kpi="{_esc(k.key)}"><div class="kpi-label">{_esc(k.label)}</div>'
            f'<div class="kpi-value">{_esc(_kpi_value(k, lang))}</div>{note}'
            + (f'<div class="kpi-trend">{_esc(trend)}</div>' if trend else "") + "</div>")


def _lead_kpi(k: Kpi, lang: Language) -> str:
    """One of the lead numbers: name, value, the change from the previous period (not written without one), which
    way is better (not written for a neutral number). Its note is under the row, so the cells stay level."""
    change = _kpi_delta(k)
    lines = ""
    if change is not None:
        better = {"higher": 1, "lower": -1}.get(k.better, 0) * change[0]
        trend = "better" if better > 0 else "worse" if better < 0 else "same"
        lines += (f'<div class="lead-change" data-role="kpi-change" data-trend="{trend}">'
                  f"{_esc(kpi_trend(k, lang))}</div>")
    if k.better in BETTER_KEYS:
        lines += f'<div class="lead-better" data-role="kpi-better">{_esc(tr(lang, BETTER_KEYS[k.better]))}</div>'
    return (f'<div class="lead-kpi" data-role="lead-kpi" data-kpi="{_esc(k.key)}">'
            f'<div class="lead-label" data-role="kpi-label">{_esc(k.label)}</div>'
            f'<div class="lead-value" data-role="kpi-value">{_esc(_kpi_value(k, lang))}</div>{lines}</div>')


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


_XLSX_BESIDE: ContextVar[bool] = ContextVar("xlsx_beside", default=True)  # for the length of one render_html call
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


def _table(t: TableBlock, sheet: str, tz: tzinfo | None, lang: Language, *, base: str | None = None,
           print_cap: bool = True) -> str:
    """base: the console's address, for the host links (None: the names are text). print_cap: paper lists the
    first PRINT_ROW_CAP rows (False for the tables that explain the report: they are printed whole)."""
    head = f'<h3 class="subtable-label">{_esc(t.title)}</h3>'
    limit = f'<p class="note note-warn">{_esc(t.limit_note)}</p>' if t.limit_note else ""
    if not t.rows:
        return (head + limit + '<div class="report-table-panel report-table-panel--empty" data-empty="true">'
                f'<span class="empty-text">{_esc(t.empty_text)}</span></div>')
    beside = _XLSX_BESIDE.get()
    own = t.html_rows if beside else None
    shown = t.rows[:HTML_ROW_CAP if own is None else min(HTML_ROW_CAP, own)]
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

    def linked(c: Column, n: int, inner: str) -> str:
        # by the column's key and the row's place in `rows`: columns were dropped above, rows never reordered
        keys = t.host_keys.get(c.key, ())
        url = host_url(base, keys[n] if n < len(keys) else None, t.host_section)
        return inner if url is None else f'<a data-role="host-link" href="{_esc(url)}">{inner}</a>'

    body = "".join(
        f'<tr data-row="{n}">' + "".join(
            (_share_cell(c, row[i], tz) if i in shares else
             f'<td{" class=\"num\"" if i in numeric else ""}>{linked(c, n, _cell(c, row[i], tz, lang))}</td>')
            for i, c in enumerate(t.columns)) + "</tr>"
        for n, row in enumerate(shown))
    cap = ""
    if len(t.rows) > len(shown):
        said = f"{t.html_note} " if t.html_note and own is not None else ""
        words = (tr(lang, "rpt_rows_capped", shown=len(shown), total=len(t.rows), sheet=sheet) if beside
                 else tr(lang, "rpt_rows_capped_no_xlsx", shown=len(shown), total=len(t.rows)))
        cap = f'<p class="note">{_esc(said)}{_esc(words)}</p>'
    on_paper = ""
    if print_cap and len(shown) > PRINT_ROW_CAP:  # paper only: the first rows, how many there are and where
        words = (tr(lang, "rpt_print_capped", cap=PRINT_ROW_CAP, total=len(t.rows), sheet=sheet) if beside
                 else tr(lang, "rpt_print_capped_no_xlsx", cap=PRINT_ROW_CAP, shown=len(shown), total=len(t.rows)))
        on_paper = f'<p class="note print-only" data-role="print-capped">{_esc(words)}</p>'
    table = (f'<div class="{panel}"><div class="report-table-wrap"><table class="report-table'
             f'{" report-table--interactive" if len(t.columns) >= 2 else ""}" data-column-count="{len(t.columns)}"'
             f'{f" data-print-cap=\"{PRINT_ROW_CAP}\"" if on_paper else ""}>'
             f"<colgroup>{cols}</colgroup><thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div></div>")
    return head + limit + table + on_paper + cap


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


def _section_body(s: Section, names: dict[int, str], tz: tzinfo | None, lang: Language, *,
                  base: str | None = None, print_cap: bool = True) -> str:
    def one(t: TableBlock) -> str:
        return _table(t, names[id(t)], tz, lang, base=base, print_cap=print_cap)

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
                         f"<div>{one(block)}</div><div>{one(nxt)}</div></div>")
            i += 2
            continue
        i += 1
        if isinstance(block, TableBlock):
            parts.append(one(block))
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


def _badge(severity: Severity, lang: Language) -> str:
    return (f'<span class="badge" data-tone="{SEVERITY_TONE.get(severity, "neutral")}">'
            f'{_esc(tr(lang, "severity_" + severity.value))}</span>')


def _lead(doc: ReportDocument) -> str:
    """The lead numbers in one row, and under it the notes of those that have one, each led by its number's name.
    Nothing when the report has no key number."""
    lang, lead = doc.lang, doc.kpis[:LEAD_KPIS]
    if not lead:
        return ""
    notes = "".join(f"<p>{_esc(tr(lang, 'rpt_kpi_note_line', name=k.label, note=k.note))}</p>" for k in lead if k.note)
    return (f'<div class="lead-kpis" data-role="lead-kpis" data-count="{len(lead)}">'
            + "".join(_lead_kpi(k, lang) for k in lead) + "</div>"
            + (f'<div class="lead-notes" data-role="lead-notes">{notes}</div>' if notes else ""))


def _unevaluated(doc: ReportDocument) -> tuple[Section, int] | None:
    """The section of rules that were not evaluated (services/reports/findings.py unevaluated_section) and how many
    rules its table lists — 0: the rules did not run at all. None: every rule was evaluated, or the report has none."""
    for s in doc.sections:
        if s.id == UNEVALUATED:
            return s, sum(len(b.rows) for b in s.blocks if isinstance(b, TableBlock))
    return None


def _action(n: int, a: TopAction, lang: Language) -> str:
    sep = tr(lang, "rpt_list_sep")
    titles = [f'<a href="#finding-{i + 1}">{_esc(title)}</a>' for i, title in zip(a.findings, a.titles, strict=False)]
    if a.titles_more:
        titles.append(_esc(tr(lang, "rpt_actions_titles_more", n=a.titles_more)))
    # the sentence is escaped whole, then the titles (each escaped, each a link to its card) take their place
    solves = _esc(tr(lang, "rpt_actions_solves", n=len(a.findings), titles=_SLOT)).replace(_SLOT, _esc(sep).join(titles))
    focus = "".join(f'<span class="action-focus" data-role="action-focus">{_esc(x)}</span>' for x in a.focus)
    return (f'<li class="top-action" data-role="top-action" id="action-{n}"><span class="action-num">{n}</span>'
            f'<div class="action-body">{_badge(a.severity, lang)}'
            f'<span class="action-short" data-role="action-short">{_esc(a.short)}</span>'
            f'<span class="action-solves" data-role="action-solves">{solves}</span>'
            f"{focus}</div></li>")


def _top_actions(doc: ReportDocument) -> str:
    """The things to do first (domain/actions.py: the same ones the XLSX and the email name). A rule that was not
    evaluated is never said as "nothing to do": the block ends by saying so and pointing at that section."""
    lang = doc.lang
    top, more = top_actions(doc.findings)
    parts = []
    if top:
        parts.append(f'<h2>{_esc(tr(lang, "rpt_actions_title", n=len(top)))}</h2><ol>'
                     + "".join(_action(n, a, lang) for n, a in enumerate(top, start=1)) + "</ol>")
        if more:
            parts.append(f'<p data-role="actions-more">{_esc(tr(lang, "rpt_actions_more", n=more))}</p>')
    held = _unevaluated(doc)
    if not top and held is None:  # no finding and every rule evaluated (or a report without rules): only then
        parts.append(f'<p data-role="actions-none">{_esc(tr(lang, "rpt_findings_none"))}</p>')
    not_run = held is not None and held[1] == 0
    if held is not None:
        section, n = held
        words = (tr(lang, "rpt_actions_not_run", section=section.title) if not_run
                 else tr(lang, "rpt_actions_unevaluated", n=n, section=section.title))
        parts.append(f'<p data-role="actions-unevaluated"><a href="#{UNEVALUATED}">{_esc(words)}</a></p>')
    return f'<section class="top-actions" data-role="top-actions">{"".join(parts)}</section>'


def _card(i: int, f: Finding, number: int | None, lang: Language) -> str:
    """One finding: what happened (its title heads the card), why it matters, what to do. A part without words is
    left out, never an empty heading. i is the finding's place in doc.findings: the things to do link to it."""
    rows = []
    if f.what:
        rows.append((tr(lang, "rpt_card_what"), _esc(f.what)))
    if f.why:
        rows.append((tr(lang, "rpt_card_why"), _esc(f.why)))
    see = ("" if number is None else
           f'<a href="#action-{number}" data-role="see-action">{_esc(tr(lang, "rpt_card_see_action", n=number))}</a> ')
    if see or f.action:
        rows.append((tr(lang, "rpt_card_do"), see + _esc(f.action)))
    parts = "".join(f"<dt>{_esc(k)}</dt><dd>{v}</dd>" for k, v in rows)
    return (f'<article class="finding" data-role="finding" id="finding-{i + 1}" data-severity="{f.severity.value}">'
            f"<h3>{_badge(f.severity, lang)} {_esc(f.title)}</h3>"
            + (f"<dl>{parts}</dl>" if parts else "") + f"{_chips(f.techniques)}</article>")


def _cards(doc: ReportDocument) -> str:
    """Every finding as a card, the most severe first (findings of one severity keep the builder's order)."""
    if not doc.findings:
        return ""
    numbers = action_number(doc.findings)
    order = sorted(range(len(doc.findings)), key=lambda i: -SEVERITY_RANK.index(doc.findings[i].severity))
    return (f'<section class="findings" data-role="findings">'
            f'<h2>{_esc(tr(doc.lang, "rpt_findings_heading", n=len(order)))}</h2>'
            + "".join(_card(i, doc.findings[i], numbers.get(i), doc.lang) for i in order) + "</section>")


def _first_page(doc: ReportDocument) -> str:
    """Under the cover: caveats, the lead numbers, the things to do. A custom report has no rules and no key
    numbers: its first page is the conclusion and the contents."""
    lang = doc.lang
    caveats = ""
    if doc.caveats:
        caveats = (f'<div class="caveats" data-role="caveats"><strong>{_esc(tr(lang, "rpt_caveats_title"))}</strong>'
                   + "".join(f"<p>{_esc(c)}</p>" for c in doc.caveats) + "</div>")
    actions = "" if doc.report_type is ReportType.CUSTOM else _top_actions(doc)
    inner = caveats + _lead(doc) + actions
    return f'<section class="first-page" id="summary" data-shell="exec">{inner}</section>' if inner else ""


def _other_kpis(doc: ReportDocument) -> str:
    rest = doc.kpis[LEAD_KPIS:]
    if not rest:
        return ""
    return (f'<section class="other-kpis" data-role="other-kpis"><h2>{_esc(tr(doc.lang, "rpt_other_kpis_title"))}</h2>'
            f'<div class="kpi-strip">{"".join(_kpi(k, doc.lang) for k in rest)}</div></section>')


def _ordered(doc: ReportDocument) -> tuple[list[Section], list[Section]]:
    """(the ordinary sections, the closing part "how to read this report"). The rules that were not evaluated close
    the ordinary ones; the part is the builder's `how`, the data notes, then the sections that hold nothing."""
    by_id = {s.id: s for s in doc.sections}
    fixed = (HOW, UNEVALUATED, NOTHING)
    ordinary = [s for s in doc.sections if s.id not in fixed] + [by_id[i] for i in (UNEVALUATED,) if i in by_id]
    part = [by_id[HOW]] if HOW in by_id else []
    if doc.data_quality:
        part.append(Section(id=NOTES, title=tr(doc.lang, "rpt_data_quality_title")))
    if NOTHING in by_id:
        part.append(by_id[NOTHING])
    return ordinary, part


def _top(doc: ReportDocument) -> str:
    if not doc.findings:
        return "none"
    return TOP_RULE[max((f.severity for f in doc.findings), key=SEVERITY_RANK.index)]


def render_html(doc: ReportDocument, *, tz: tzinfo | None, xlsx: bool = True) -> str:
    """xlsx: an XLSX of the same report is made beside this page. Without one, a table's html_rows is not applied
    (its rows would be nowhere) and a cut table says only how many rows it shows."""
    token = _XLSX_BESIDE.set(xlsx)
    try:
        return _render(doc, tz)
    finally:
        _XLSX_BESIDE.reset(token)


def _render(doc: ReportDocument, tz: tzinfo | None) -> str:
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
    ordinary, part = _ordered(doc)
    part_title = tr(lang, "rpt_part_how")
    toc_items, chapters = [], []
    for i, sec in enumerate([*ordinary, *part]):
        in_part = i >= len(ordinary)
        if in_part and i == len(ordinary):  # the part's heading, once, in the contents and in the page
            toc_items.append(f'<li class="toc-part">{_esc(part_title)}</li>')
            chapters.append(f'<h2 class="part-title" data-role="how-part">{_esc(part_title)}</h2>')
        toc_items.append(
            f'<li data-tone="neutral"><a href="#{_esc(sec.id)}"><span class="toc-num">{i + 1:02d}</span>'
            f'<span class="toc-label">{_esc(sec.title)}</span><span class="toc-dot"></span></a></li>')
        if sec.id == NOTES:
            inner = '<ul class="notes-list">' + "".join(f"<li>{_esc(q)}</li>" for q in doc.data_quality) + "</ul>"
        else:  # the tables of the closing part explain the report: paper prints them whole
            inner = _section_body(sec, names, tz, lang, base=doc.gui_base, print_cap=not in_part)
        chapters.append(
            f'<section class="chapter" id="{_esc(sec.id)}" data-shell="detail" data-tone="neutral">'
            f'<div class="chapter-head"><span class="chapter-index">S{i + 1:02d}</span>'
            f'<h2 class="chapter-title">{_esc(sec.title)}</h2></div>{inner}</section>')
    toc = (f'<nav class="toc" data-shell="toc"><button class="print-btn" onclick="window.print()">'
           f'{_esc(tr(lang, "rpt_print"))}</button>'
           # a report without sections (nothing computed) has no table of contents to head
           + (f'<h2>{_esc(tr(lang, "rpt_toc_title"))}</h2><ol>{"".join(toc_items)}</ol>' if toc_items else "")
           + "</nav>")
    cards = "" if doc.report_type is ReportType.CUSTOM else _cards(doc)
    lang_attr = "zh-TW" if lang is Language.ZH_TW else "en"
    return ("<!DOCTYPE html>\n"
            f'<html lang="{lang_attr}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{_esc(doc.title)}</title><style>\n{asset('report_shell.css')}\n{EXTRA_CSS}</style></head>"
            f'<body data-report-title="{_esc(doc.title)}"><div class="sheet"><div class="doc">'
            f'{cover}{_first_page(doc)}{cards}{_other_kpis(doc)}{toc}'
            f'<div class="chapters">{"".join(chapters)}</div></div></div>'
            f"<script>\n{asset('report_table.js')}</script></body></html>")
