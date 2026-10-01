function normalizeCellValue(text) {
  return (text || '').replace(/[\s\u00A0]+/g, ' ').trim();
}

function parseSortableValue(text) {
  const normalized = normalizeCellValue(text);
  const numeric = normalized.replace(/,/g, '').match(/^-?\d+(\.\d+)?$/);
  if (numeric) return { type: 'number', value: parseFloat(numeric[0]) };
  return { type: 'text', value: normalized.toLowerCase() };
}

function sortTable(table, col) {
  const body = table.tBodies[0];
  if (!body) return;
  const rows = Array.from(body.rows);
  const asc = !(table.dataset.sortCol === String(col) && table.dataset.sortDir === 'asc');
  rows.sort((a, b) => {
    const av = parseSortableValue(a.cells[col] ? a.cells[col].innerText : '');
    const bv = parseSortableValue(b.cells[col] ? b.cells[col].innerText : '');
    if (av.type === 'number' && bv.type === 'number') {
      return asc ? av.value - bv.value : bv.value - av.value;
    }
    return asc ? av.value.localeCompare(bv.value) : bv.value.localeCompare(av.value);
  });
  rows.forEach(row => body.appendChild(row));
  table.dataset.sortCol = String(col);
  table.dataset.sortDir = asc ? 'asc' : 'desc';
  table.querySelectorAll('th').forEach((th, index) => {
    th.classList.toggle('is-sorted-asc', index === col && asc);
    th.classList.toggle('is-sorted-desc', index === col && !asc);
    const indicator = th.querySelector('.sort-indicator');
    if (indicator) indicator.textContent = index === col ? (asc ? '\u25B2' : '\u25BC') : '\u2195';
  });
}

/* Auto-fit: measure natural content widths and distribute slack space.
 * Columns are categorised so narrow-value columns (Proto, Yes/No, short enums)
 * don't absorb slack that belongs to long-text columns. */
function measureColumnWidths(table) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  const body = table.tBodies[0];
  const rows = body ? Array.from(body.rows) : [];
  const nCols = headers.length;
  const MIN_COL = 56;
  /* The th's asymmetric padding (12px left / 28px right) already includes the
     space the absolutely-positioned .sort-indicator occupies, so there's no
     additional reserve to add here — adding one causes the label to
     double-count and ellipsis-truncate short CJK headers like 連接埠. */
  const NARROW_MAX_CHARS = 10;       /* content wider than this = "text" not "narrow" */
  const NARROW_DISTINCT_CAP = 6;     /* column with ≤ this many distinct values = enum-like */

  const probe = document.createElement('span');
  probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;font:inherit;padding:0;left:-9999px;top:0';
  document.body.appendChild(probe);

  const naturalWidths = new Array(nCols).fill(MIN_COL);
  const headerWidths = new Array(nCols).fill(MIN_COL);
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
      naturalWidths[i] = Math.max(naturalWidths[i], probe.offsetWidth + padCell);
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

  return { widths: naturalWidths, headerWidths, category };
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

  const { widths, category } = measureColumnWidths(table);
  const containerWidth = wrap ? wrap.clientWidth : table.parentElement.clientWidth;
  const naturalTotal = widths.reduce((a, b) => a + b, 0);

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

function autoFitSingleColumn(table, colIndex) {
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  const th = headers[colIndex];
  const col = cols[colIndex];
  if (!th) return;

  const { widths } = measureColumnWidths(table);
  const w = widths[colIndex];
  if (col) { col.style.width = w + 'px'; col.style.minWidth = ''; }
  th.style.width = w + 'px'; th.style.minWidth = '';

  const total = headers.reduce((sum, h) => sum + h.getBoundingClientRect().width, 0);
  table.style.minWidth = total + 'px';

  const panel = table.closest('.report-table-panel--wide');
  if (panel) updateWideScrollState(panel);
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

/* Wrap header content in <span class="th-label"> using DOM cloning (no innerHTML). */
function wrapHeaderLabel(th) {
  if (th.querySelector('.th-label')) return;
  const label = document.createElement('span');
  label.className = 'th-label';
  while (th.firstChild) label.appendChild(th.firstChild);
  th.appendChild(label);
}

function initReportTable(table) {
  if (!table) return;
  const headers = Array.from(table.querySelectorAll('thead th'));
  const cols = Array.from(table.querySelectorAll('colgroup col'));
  if (headers.length < 1) return;

  if (table.dataset.interactive !== 'true') {
    requestAnimationFrame(() => autoFitColumns(table));
    return;
  }

  headers.forEach(th => {
    wrapHeaderLabel(th);

    const indicator = document.createElement('span');
    indicator.className = 'sort-indicator';
    indicator.textContent = '\u2195';
    th.appendChild(indicator);

    const resizer = document.createElement('div');
    resizer.className = 'col-resizer';
    th.appendChild(resizer);

    th.addEventListener('click', event => {
      if (event.target === resizer) return;
      sortTable(table, Array.from(th.parentNode.children).indexOf(th));
    });

    let startX = 0;
    let startWidth = 0;
    const colIndex = Array.from(th.parentNode.children).indexOf(th);
    const targetCol = cols[colIndex] || null;

    const onMouseMove = event => {
      const width = Math.max(48, startWidth + event.clientX - startX);
      if (targetCol) { targetCol.style.width = width + 'px'; targetCol.style.minWidth = width + 'px'; }
      th.style.width = width + 'px'; th.style.minWidth = width + 'px';
      const total = headers.reduce((s, h) => s + h.getBoundingClientRect().width, 0);
      const wrapWidth = table.closest('.report-table-wrap')?.clientWidth || 0;
      table.style.minWidth = Math.max(total, wrapWidth) + 'px';
      const panel = table.closest('.report-table-panel--wide');
      if (panel) updateWideScrollState(panel);
    };
    const onMouseUp = () => {
      resizer.classList.remove('is-active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    resizer.addEventListener('mousedown', event => {
      event.preventDefault();
      event.stopPropagation();
      startX = event.clientX;
      startWidth = (targetCol || th).getBoundingClientRect().width;
      resizer.classList.add('is-active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      document.addEventListener('mousemove', onMouseMove);
      document.addEventListener('mouseup', onMouseUp);
    });

    resizer.addEventListener('dblclick', event => {
      event.preventDefault();
      event.stopPropagation();
      autoFitSingleColumn(table, colIndex);
    });
  });

  requestAnimationFrame(() => autoFitColumns(table));

  const widePanel = table.closest('.report-table-panel--wide');
  if (widePanel) {
    const wrap = widePanel.querySelector('.report-table-wrap');
    if (wrap) {
      wrap.addEventListener('scroll', () => updateWideScrollState(widePanel), { passive: true });
    }
  }
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
