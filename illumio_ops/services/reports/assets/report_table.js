function normalizeCellValue(text) {
  return (text || '').replace(/[\s\u00A0]+/g, ' ').trim();
}

/* Sorting by a column header (render_html.py writes the header as a button, and on each cell what it sorts by).
   A header's state is its th's aria-sort: none -> ascending -> descending -> none (the report's own order).
   The rows as the report lists them stay where they are — paper prints them, in that order — and the screen shows
   a sorted copy beside them (the style sheet shows one tbody or the other by medium), so nothing has to be put
   back before printing and the third click only takes the copy away.
   A column of numbers (th data-sort-type="number") sorts by each cell's data-sort, never by the printed text; any
   other column by its text as a reader of the page's language orders it, digits by their value. A cell without a
   value (data-sort="", or no text) is last, whichever way the column is sorted. Rows that compare equal keep the
   report's order. */
const SORT_NEXT = { none: 'ascending', ascending: 'descending', descending: 'none' };

function sortValue(cell, numeric) {
  if (!cell || cell.dataset.sort === '') return null;
  if (numeric) {
    const n = parseFloat(cell.dataset.sort);
    return Number.isNaN(n) ? null : n;
  }
  return normalizeCellValue(cell.textContent) || null;
}

function sortTable(table, col, dir) {
  const listed = table.tBodies[0];
  if (!listed || !table.tHead) return;
  const headers = Array.from(table.tHead.rows[0].cells);
  headers.forEach((th, i) => {
    if (th.hasAttribute('aria-sort')) th.setAttribute('aria-sort', i === col ? dir : 'none');
  });
  const was = table.querySelector('tbody[data-role="sorted"]');
  if (dir === 'none') {
    if (was) was.remove();
    delete table.dataset.sorted;
    return;
  }
  const numeric = headers[col].dataset.sortType === 'number';
  const collator = new Intl.Collator(document.documentElement.lang || undefined, { numeric: true, sensitivity: 'base' });
  const sign = dir === 'descending' ? -1 : 1;
  const rows = Array.from(listed.rows).map(row => ({ row, key: sortValue(row.cells[col], numeric) }));
  rows.sort((a, b) => {
    if (a.key === null || b.key === null) return (a.key === null) - (b.key === null);
    return sign * (numeric ? a.key - b.key : collator.compare(a.key, b.key));
  });
  const sorted = document.createElement('tbody');
  sorted.dataset.role = 'sorted';
  rows.forEach(r => sorted.appendChild(r.row.cloneNode(true)));
  if (was) was.replaceWith(sorted); else table.appendChild(sorted);
  table.dataset.sorted = 'true';
}

/* Auto-fit: measure natural content widths and distribute slack space.
 * Columns are categorised so narrow-value columns (Proto, Yes/No, short enums)
 * don't absorb slack that belongs to long-text columns. */
/* The width a header needs when it may wrap: its longest unbreakable run. Latin words do not break; a run of CJK
   breaks anywhere, so it asks for a few characters, not for all of it. */
function wrappedHeaderWidth(probe, text) {
  const runs = (text || '').match(/[\x21-\x7e]+|[^\s\x21-\x7e]+/g) || [];
  let max = 0;
  runs.forEach(run => {
    probe.textContent = /^[\x21-\x7e]+$/.test(run) ? run : run.slice(0, 5);
    max = Math.max(max, probe.offsetWidth);
  });
  return max;
}

function measureColumnWidths(table) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  /* the rows that are drawn: a sorted table hides the rows as listed and shows their sorted copy (a share's bar
     is measured, and a row that is not drawn has none) */
  const body = Array.from(table.tBodies).find(b => b.rows[0] && b.rows[0].getClientRects().length) || table.tBodies[0];
  const rows = body ? Array.from(body.rows) : [];
  const nCols = headers.length;
  const MIN_COL = 56;
  /* The th's right padding (report_shell.css, tables with more than one column) already includes the space the
     absolutely-positioned .sort-indicator occupies, so there's no additional reserve to add here. */
  const NARROW_MAX_CHARS = 10;       /* content wider than this = "text" not "narrow" */
  const NARROW_DISTINCT_CAP = 6;     /* column with ≤ this many distinct values = enum-like */

  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font:inherit;padding:0;left:-9999px;top:0';
  document.body.appendChild(probe);

  const naturalWidths = new Array(nCols).fill(MIN_COL);
  const headerWidths = new Array(nCols).fill(MIN_COL);
  const headerMinWidths = new Array(nCols).fill(MIN_COL);  /* the header wrapped as far as it goes */
  const cellWidths = new Array(nCols).fill(MIN_COL);       /* the widest cell on one line, without the header */
  const cellMinWidths = new Array(nCols).fill(MIN_COL);    /* the widest cell wrapped as far as it goes */
  const SHARE_BAR_SPARE = 36;  /* report_shell: a share's 72px bar is 36px in a table marked report-table--tight */
  const isNumeric = new Array(nCols).fill(true);
  const maxCellChars = new Array(nCols).fill(0);
  const distinctVals = Array.from({ length: nCols }, () => new Set());

  headers.forEach((th, i) => {
    const label = th.querySelector('.th-label');
    const thStyle = getComputedStyle(th);
    /* Read padding live so we don't drift if CSS changes. Add a small
       safety buffer so sub-pixel font rendering doesn't ellipsis-truncate
       on exact-fit widths (observed 2-3px short on some CJK labels). */
    const padHead = (parseFloat(thStyle.paddingLeft) || 0)
                  + (parseFloat(thStyle.paddingRight) || 0)
                  + 6;
    probe.style.font = thStyle.font;
    probe.textContent = (label || th).textContent;
    const hw = probe.offsetWidth + padHead;
    headerWidths[i] = hw;
    naturalWidths[i] = Math.max(naturalWidths[i], hw);
    headerMinWidths[i] = Math.max(MIN_COL, wrappedHeaderWidth(probe, (label || th).textContent) + padHead);
  });

  const sampleRows = rows.slice(0, 30);
  sampleRows.forEach(row => {
    Array.from(row.cells).forEach((td, i) => {
      if (i >= nCols) return;
      const tdStyle = getComputedStyle(td);
      const padCell = (parseFloat(tdStyle.paddingLeft) || 0)
                    + (parseFloat(tdStyle.paddingRight) || 0);
      probe.style.font = tdStyle.font;
      probe.textContent = td.textContent;
      let cw = probe.offsetWidth + padCell;
      if (td.classList.contains('share') && td.firstElementChild) {
        /* a share is its number and a bar that never wrap: the text alone is half of what the cell needs */
        const bar = td.lastElementChild.getBoundingClientRect().width;
        cw = td.lastElementChild.getBoundingClientRect().right - td.firstElementChild.getBoundingClientRect().left
           + padCell + 2;
        cellMinWidths[i] = Math.max(cellMinWidths[i], cw - (bar > SHARE_BAR_SPARE ? SHARE_BAR_SPARE : 0));
      } else if (td.classList.contains('num')) {
        cellMinWidths[i] = Math.max(cellMinWidths[i], cw);  /* a number never wraps */
      } else {
        cellMinWidths[i] = Math.max(cellMinWidths[i], wrappedHeaderWidth(probe, td.textContent) + padCell);
      }
      naturalWidths[i] = Math.max(naturalWidths[i], cw);
      cellWidths[i] = Math.max(cellWidths[i], cw);
      const v = normalizeCellValue(td.textContent);
      if (v.length > maxCellChars[i]) maxCellChars[i] = v.length;
      if (v) distinctVals[i].add(v);
      if (isNumeric[i]) {
        if (v && !(/^-?[\d,]+(\.\d+)?%?$/.test(v))) isNumeric[i] = false;
      }
    });
  });
  probe.remove();

  /* Column categories:
   *   numeric       — pure numbers/percentages, stay tight, no slack
   *   narrow-value  — short text, few distinct values (Proto, Yes/No, enums), no slack
   *   text          — long or varied text content, absorbs slack proportionally
   */
  const category = naturalWidths.map((_, i) => {
    if (isNumeric[i]) return 'numeric';
    const short = maxCellChars[i] <= NARROW_MAX_CHARS;
    const fewDistinct = distinctVals[i].size > 0 && distinctVals[i].size <= NARROW_DISTINCT_CAP;
    if (short && fewDistinct) return 'narrow';
    return 'text';
  });

  return { widths: naturalWidths, headerWidths, headerMinWidths, cellWidths, cellMinWidths, category };
}

function autoFitColumns(table) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  const nCols = headers.length;
  if (nCols < 1) return;

  const wrap = table.closest('.report-table-wrap');
  const panel = table.closest('.report-table-panel');
  const isWide = panel && panel.classList.contains('report-table-panel--wide');

  if (table.dataset.autoFitted === 'true') {
    table.style.minWidth = '';
    headers.forEach((th, i) => { th.style.width = ''; if (cols[i]) cols[i].style.width = ''; });
  }

  const measured = measureColumnWidths(table);
  const category = measured.category;
  /* A text column's one-line width can be thousands of pixels (an explanation, a list of connections): it is
     capped, so its text wraps, never wider than TEXT_MAX unless its header is (2026-10-29, readiness on lab:
     the last column of "what to do first" sat past the right edge). */
  const TEXT_MAX = 420;
  const TEXT_MIN = 160;
  const widths = measured.widths.map((w, i) =>
    category[i] === 'text' ? Math.min(w, Math.max(TEXT_MAX, measured.headerWidths[i])) : w);
  const containerWidth = wrap ? wrap.clientWidth : table.parentElement.clientWidth;
  let naturalTotal = widths.reduce((a, b) => a + b, 0);
  /* Still wider than the page: the text columns give up width (down to TEXT_MIN, or their header) and wrap,
     so a table of a few columns fits; only when that is not enough does it scroll. */
  if (!isWide && naturalTotal > containerWidth) {
    const textIdx = widths.map((_, i) => i).filter(i => category[i] === 'text');
    const fixed = widths.reduce((s, w, i) => s + (category[i] === 'text' ? 0 : w), 0);
    const floor = i => Math.max(TEXT_MIN, measured.headerWidths[i]);
    const avail = containerWidth - fixed;
    if (textIdx.length && avail >= textIdx.reduce((s, i) => s + floor(i), 0)) {
      /* Proportional shares; a column whose share is under its floor keeps the floor and the rest share
         what is left, until every share holds. */
      let open = textIdx.slice();
      let room = avail;
      for (let changed = true; changed;) {
        changed = false;
        const openTotal = open.reduce((s, i) => s + widths[i], 0) || 1;
        for (const i of open) {
          if (room * widths[i] / openTotal < floor(i)) {
            widths[i] = floor(i);
            room -= widths[i];
            open = open.filter(j => j !== i);
            changed = true;
            break;
          }
        }
      }
      const openTotal = open.reduce((s, i) => s + widths[i], 0) || 1;
      open.forEach(i => { widths[i] = Math.floor(room * widths[i] / openTotal); });
      naturalTotal = widths.reduce((a, b) => a + b, 0);
    }
  }
  /* Still wider (stage 3a: a column named "Recording only (Visibility Only)" was as wide as its name on one line,
     and four of them pushed the last columns past the edge): the headers wrap too, then the cells. Every column
     gives up width in proportion to what it can spare, down to a floor, in two steps:
       1. a text column TEXT_MIN (or its own width when narrower), any other column its widest cell on one line;
       2. every column the longest word of its cells (a number never wraps; a share keeps its number and a
          shorter bar: the table is marked report-table--tight);
     and none less than its header's longest word. Only a table that does not fit at the last floors scrolls. */
  table.classList.remove('report-table--tight');
  if (!isWide && naturalTotal > containerWidth) {
    const shrinkTo = floors => {
      const spare = widths.map((w, i) => Math.max(0, w - floors[i]));
      const spareTotal = spare.reduce((a, b) => a + b, 0);
      const over = naturalTotal - containerWidth;
      for (let i = 0; i < widths.length; i++) {
        widths[i] = spareTotal <= over ? Math.min(widths[i], floors[i])
                                       : Math.floor(widths[i] - over * spare[i] / spareTotal);
      }
      naturalTotal = widths.reduce((a, b) => a + b, 0);
    };
    shrinkTo(widths.map((w, i) => Math.max(measured.headerMinWidths[i],
      category[i] === 'text' ? Math.min(w, TEXT_MIN) : measured.cellWidths[i])));
    if (naturalTotal > containerWidth) {
      table.classList.add('report-table--tight');
      shrinkTo(widths.map((w, i) => Math.max(measured.headerMinWidths[i], Math.min(w, measured.cellMinWidths[i]))));
    }
  }

  let finalWidths;
  let tableMinWidth;
  if (!isWide && naturalTotal <= containerWidth) {
    const slack = containerWidth - naturalTotal;
    /* Distribute slack:
       - If there are 'text' columns (long/varied content): split slack among
         them proportionally. Narrow and numeric cols stay at natural width.
       - If there are no text columns: keep all columns at natural width. The
         panel itself is `width: max-content`, so the narrow table gets a
         tight panel and the empty space lives OUTSIDE the panel (in the card
         background), not inside as bloated column padding. */
    const textIdx = widths.map((_, i) => i).filter(i => category[i] === 'text');
    if (textIdx.length > 0) {
      const textTotal = textIdx.reduce((s, i) => s + widths[i], 0) || 1;
      finalWidths = widths.map((w, i) =>
        category[i] === 'text' ? w + slack * (w / textTotal) : w
      );
      const allocated = finalWidths.reduce((a, b) => a + b, 0);
      if (allocated < containerWidth) {
        finalWidths[textIdx[textIdx.length - 1]] += containerWidth - allocated;
      }
      tableMinWidth = containerWidth;
    } else {
      /* No text columns — keep natural widths; the panel itself is
         width: max-content, so the surrounding card shows the empty space
         rather than the table's narrow columns being bloated. */
      finalWidths = widths.slice();
      tableMinWidth = Math.round(naturalTotal);
    }
  } else {
    /* Wide panel OR content overflows — keep natural widths, allow horizontal scroll */
    finalWidths = widths;
    tableMinWidth = Math.max(containerWidth, Math.round(naturalTotal));
  }

  headers.forEach((th, i) => {
    const w = Math.round(finalWidths[i]);
    if (cols[i]) cols[i].style.width = w + 'px';
    th.style.width = w + 'px';
  });
  table.style.minWidth = tableMinWidth + 'px';
  table.style.width = tableMinWidth + 'px';
  table.dataset.autoFitted = 'true';

  if (isWide) updateWideScrollState(panel);
}

function updateWideScrollState(panel) {
  const wrap = panel.querySelector('.report-table-wrap');
  if (!wrap) return;
  const max = wrap.scrollWidth - wrap.clientWidth;
  let state = 'fit';
  if (max > 1) {
    const left = wrap.scrollLeft;
    if (left <= 1) state = 'start';
    else if (left >= max - 1) state = 'end';
    else state = 'scrollable';
  }
  panel.setAttribute('data-scroll-state', state);
}

function initReportTable(table) {
  if (!table || !table.querySelector('thead th')) return;
  table.querySelectorAll('thead th > button.th-sort').forEach(button => {
    button.addEventListener('click', () => {
      const th = button.parentElement;
      sortTable(table, th.cellIndex, SORT_NEXT[th.getAttribute('aria-sort')] || 'ascending');
    });
  });
  requestAnimationFrame(() => autoFitColumns(table));
}

function debounce(fn, ms) {
  let t;
  return function () { clearTimeout(t); t = setTimeout(() => fn.apply(this, arguments), ms); };
}

const refitAllTables = debounce(() => {
  document.querySelectorAll('.report-table').forEach(t => autoFitColumns(t));
}, 120);

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.report-table').forEach(initReportTable);
  window.addEventListener('resize', refitAllTables);
});
