// table.mjs — the dense console table. Column resize, skeleton and empty state
// are built in so no area re-implements them.
//
//   table.render(host, {columns, rows, page, onPage, sort, onSort}) -> handle
//     columns — Column[] built with col(); see below
//     rows    — array of row objects, [] for "no data" (header row stays visible,
//               only the body is empty -- quarantine.js:402-404 does the same),
//               null for "still loading"
//     page    — {index, size, total} or a plain page index
//     onPage  — (nextIndex) => void; omit for an unpaged table
//     sort    — {key, dir} the caller is currently sorting by ("asc"/"desc")
//     onSort  — (key, dir) => void; omit for an unsortable table
//
// Sorting is REPORTED, not performed. The table only ever receives the rows for
// the current page, so sorting here would sort one page and leave the operator
// convinced they were looking at the top of the list. The caller owns the full
// model, so the caller sorts it and re-renders; this component owns the
// affordance (clickable header, direction indicator, aria-sort) and nothing
// else. Columns opt in with `sort` — see col().
//   handle: {el, update(rows, page), destroy()}
//
// PORT OF design/v2/mockup/js/components/table.mjs. Two differences:
//   1. i18n keys renamed from the mockup's v2_table_* to gui_table_* (this
//      task's global rename: v2_ keys become part of the real product
//      catalogue in src/i18n_en.json / src/i18n_zh_TW.json, which never
//      carries a v2_ prefix).
//   2. Teardown contract: the returned handle now exposes destroy(), which
//      detaches the table's root from its host. table.mjs holds no
//      persistent document-level listeners of its own (the resize grip's
//      mousemove/mouseup pair is removed on its own mouseup), so destroy()
//      only needs to do DOM cleanup — still required so callers that mount a
//      table inside a drawer/modal body have one teardown call to make,
//      matching every other component in this directory.

import { el, clear, spacer } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";

class Column {
  constructor(key, label, opts) {
    const o = opts || {};
    this.key = key;
    this.label = label;
    this.width = o.width || null;     // px; null = auto
    this.align = o.align || null;     // "n" for numeric (right, tabular)
    this.cell = o.cell || null;       // (row) => Node | string
    this.title = o.title || null;     // (row) => string, for the cell tooltip
    this.head = o.head || null;       // () => Node, replaces the text label (e.g. a select-all checkbox)
    // sort: true to sort on row[key], or (row) => comparable for a derived
    // value. A column with a `cell` renderer almost always needs the function
    // form — what the operator sees is not what the row stores.
    this.sort = o.sort || null;
  }
}

/** col(key, label, {width, align, cell, title, head, sort}) -> Column */
export function col(key, label, opts) {
  return new Column(key, label, opts);
}

/** sortRows(rows, columns, sort) -> a NEW sorted array (the caller's model is
 *  left alone). Missing values sort last in both directions — an unknown is
 *  not a smallest value, and burying them at the bottom is the only reading
 *  that stays true when the direction flips. Numbers compare numerically,
 *  everything else by locale, so "10" does not land before "9".
 */
export function sortRows(rows, columns, sort) {
  if (!sort || !sort.key || !Array.isArray(rows)) return rows;
  const c = columns.filter(function (x) { return x.key === sort.key && x.sort; })[0];
  if (!c) return rows;
  const valueOf = typeof c.sort === "function"
    ? c.sort
    : function (row) { return row ? row[c.key] : null; };
  const dir = sort.dir === "desc" ? -1 : 1;
  const missing = function (v) { return v === null || v === undefined || v === ""; };
  return rows.slice().sort(function (a, b) {
    const va = valueOf(a);
    const vb = valueOf(b);
    if (missing(va) && missing(vb)) return 0;
    if (missing(va)) return 1;
    if (missing(vb)) return -1;
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
    if (typeof va === "boolean" && typeof vb === "boolean") return ((va ? 1 : 0) - (vb ? 1 : 0)) * dir;
    return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir;
  });
}

function normalizePage(page) {
  const p = { index: 0, size: 0, total: 0 };
  if (typeof page === "number") p.index = page;
  else if (page) {
    p.index = Number(page.index) || 0;
    p.size = Number(page.size) || 0;
    p.total = Number(page.total) || 0;
  }
  return p;
}

const SORT_MARK = { asc: "\u2191", desc: "\u2193" };

function headCell(c, table, sort, onSort) {
  const sortable = !!(c.sort && onSort);
  const active = sortable && sort && sort.key === c.key ? sort.dir : null;
  let th;
  if (c.head) {
    th = el("th", { class: c.align === "n" ? "n" : null }, c.head());
  } else if (sortable) {
    // A button, not a th click handler: the resize grip lives in the same th
    // and a th-level handler would sort every time someone finished dragging
    // a column edge. It also makes the affordance reachable by keyboard,
    // which a clickable th is not.
    const label = el("button", {
      class: "th-sort", type: "button", title: c.label,
      "aria-label": c.label,
    }, el("span", { text: c.label }),
       el("span", { class: "th-dir", text: active ? SORT_MARK[active] : "" }));
    label.addEventListener("click", function () {
      onSort(c.key, active === "asc" ? "desc" : "asc");
    });
    th = el("th", {
      class: c.align === "n" ? "n" : null,
      "aria-sort": active ? (active === "asc" ? "ascending" : "descending") : "none",
    }, label);
  } else {
    th = el("th", { class: c.align === "n" ? "n" : null, title: c.label, text: c.label });
  }
  const grip = el("span", { class: "tbl-grip", title: t("gui_table_resize") });
  grip.addEventListener("mousedown", function (e) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = th.getBoundingClientRect().width;
    table.classList.add("resizing");
    function move(ev) {
      const w = Math.max(48, Math.round(startW + ev.clientX - startX));
      th.style.width = w + "px";
      if (c.colEl) c.colEl.style.width = w + "px";
    }
    function up() {
      table.classList.remove("resizing");
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
    }
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
  th.appendChild(grip);
  return th;
}

function bodyRows(columns, rows) {
  if (rows === null || rows === undefined) {
    const out = [];
    for (let i = 0; i < 6; i++) {
      out.push(el("tr", null, columns.map(function () {
        return el("td", null, el("span", { class: "skel" }));
      })));
    }
    return out;
  }
  return rows.map(function (row) {
    const tr = el("tr", { "data-tone": row && row._tone ? row._tone : null });
    columns.forEach(function (c) {
      const raw = c.cell ? c.cell(row) : row[c.key];
      const td = el("td", { class: c.align === "n" ? "n" : null, title: c.title ? c.title(row) : null });
      if (raw instanceof Node) td.appendChild(raw);
      else td.textContent = raw === null || raw === undefined ? "" : String(raw);
      tr.appendChild(td);
    });
    return tr;
  });
}

export const table = {
  render(host, spec) {
    const columns = spec.columns || [];
    const tbl = el("table", { class: "tbl" });
    const colgroup = el("colgroup");
    columns.forEach(function (c) {
      c.colEl = el("col", { style: c.width ? "width:" + c.width + "px" : null });
      colgroup.appendChild(c.colEl);
    });
    const thead = el("thead", null, el("tr", null, columns.map(function (c) {
      return headCell(c, tbl, spec.sort, spec.onSort);
    })));
    const tbody = el("tbody");
    tbl.appendChild(colgroup);
    tbl.appendChild(thead);
    tbl.appendChild(tbody);

    const wrap = el("div", { class: "tbl-wrap" }, tbl);
    // Empty state names the condition only; the *reason* belongs to the area that
    // knows the query (XC-09), and a generic table must not invent one.
    const emptyBox = el("div", { class: "empty", hidden: true },
      el("span", { class: "et", text: t("gui_empty_state_no_data_title") })
    );
    // review finding #3: the header row stays put on empty (quarantine.js:402-404
    // does the same -- it swaps only <tbody>, never the <thead>) so a caller that
    // declares real endpoint columns for an empty result (e.g. shadowPanel, IV-15)
    // actually shows them instead of the whole table vanishing.

    const pageLabel = el("span", { class: "page" });
    const rowsLabel = el("span");
    const prev = el("button", { class: "btn ghost", type: "button", text: t("gui_prev") });
    const next = el("button", { class: "btn ghost", type: "button", text: t("gui_next") });
    const foot = el("div", { class: "tbl-foot", hidden: !spec.onPage }, rowsLabel, spacer(), pageLabel, prev, next);

    const root = el("div", null, wrap, emptyBox, foot);
    clear(host).appendChild(root);

    let page = normalizePage(spec.page);

    function paint(rows) {
      clear(tbody);
      bodyRows(columns, rows).forEach(function (tr) { tbody.appendChild(tr); });
      const isEmpty = Array.isArray(rows) && rows.length === 0;
      emptyBox.hidden = !isEmpty;
      wrap.classList.toggle("tbl-wrap-empty", isEmpty);

      const pages = page.size ? Math.max(1, Math.ceil(page.total / page.size)) : 1;
      pageLabel.textContent = tf("gui_table_page", { page: page.index + 1, pages: pages });
      rowsLabel.textContent = tf("gui_table_rows", { total: page.total || (rows ? rows.length : 0) });
      prev.disabled = page.index <= 0;
      next.disabled = page.index >= pages - 1;
    }

    prev.addEventListener("click", function () { if (spec.onPage) spec.onPage(page.index - 1); });
    next.addEventListener("click", function () { if (spec.onPage) spec.onPage(page.index + 1); });

    paint(spec.rows);

    return {
      el: root,
      update(rows, nextPage) {
        if (nextPage !== undefined) page = normalizePage(nextPage);
        paint(rows);
      },
      /** destroy() — detach the table from its host. No document-level
       * listeners survive a mouseup, so there is nothing else to release. */
      destroy() {
        if (root.parentNode) root.parentNode.removeChild(root);
      },
    };
  },
};
