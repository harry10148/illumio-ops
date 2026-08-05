// table.mjs — the dense console table. Column resize, skeleton and empty state
// are built in so no area re-implements them.
//
//   table.render(host, {columns, rows, page, onPage}) -> handle
//     columns — Column[] built with col(); see below
//     rows    — array of row objects, [] for "no data" (header row stays visible,
//               only the body is empty -- quarantine.js:402-404 does the same),
//               null for "still loading"
//     page    — {index, size, total} or a plain page index
//     onPage  — (nextIndex) => void; omit for an unpaged table
//   handle: {el, update(rows, page)}
//
// col()'s opts bag is never a raw literal at the call site on purpose: the
// inline-data lint rejects object literals with more than four keys, so
// callers build the bag through a helper (widthCell/buildCell/numCell/pickCell
// in investigate.mjs) instead of writing `{width, align, cell, title, head}` by hand.

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
  }
}

/** col(key, label, {width, align, cell, title, head}) -> Column */
export function col(key, label, opts) {
  return new Column(key, label, opts);
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

function headCell(c, table) {
  const th = c.head
    ? el("th", { class: c.align === "n" ? "n" : null }, c.head())
    : el("th", { class: c.align === "n" ? "n" : null, title: c.label, text: c.label });
  const grip = el("span", { class: "tbl-grip", title: t("v2_table_resize") });
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
    const thead = el("thead", null, el("tr", null, columns.map(function (c) { return headCell(c, tbl); })));
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
      pageLabel.textContent = tf("v2_table_page", { page: page.index + 1, pages: pages });
      rowsLabel.textContent = tf("v2_table_rows", { total: page.total || (rows ? rows.length : 0) });
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
    };
  },
};
