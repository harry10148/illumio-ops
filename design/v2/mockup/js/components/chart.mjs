// chart.mjs — ranked horizontal bars, the one chart form the console needs.
//
// dataviz rules applied here, deliberately:
//   · the data's job is MAGNITUDE for a ranked list, so: bars, sorted, one row
//     per entity. One series -> ONE hue (--accent). No categorical scale is
//     introduced anywhere in this mockup, so none needs validating.
//   · no second axis and no gridlines: the value sits at the bar tip, which
//     makes the labels the scale. Row hairlines are recessive.
//   · 4px rounded data-end anchored to a common baseline; the bar never floats.
//   · hover layer by default — a per-mark tooltip with a hit target taller than
//     the mark itself, plus a native <title> so the same text is reachable
//     without a pointer.
//   · text wears text tokens (--text-*), never the series colour.
//
// Colours come from components.css classes (c-bar / c-ink*) so both themes and
// both densities follow the tokens with no JS branch.

import { el, svg, clear } from "../core/dom.mjs";

const MIN_W = 320;
const BAR_H = 10;
const CAP_R = 4;
const GUTTER = 10;

let measureCtx = null;

function measure(text, font) {
  if (!measureCtx) measureCtx = document.createElement("canvas").getContext("2d");
  measureCtx.font = font;
  return measureCtx.measureText(String(text)).width;
}

/** Ellipsize to fit `maxW` px in `font`. Measured, not guessed — CJK is wide. */
function fit(text, maxW, font) {
  let s = String(text === null || text === undefined ? "" : text);
  if (!s || measure(s, font) <= maxW) return s;
  while (s.length > 1 && measure(s + "…", font) > maxW) s = s.slice(0, -1);
  return s + "…";
}

/** Bar path: flush at the baseline, rounded only at the data-end. */
function capPath(x, y, w, h, r) {
  const rr = Math.max(0, Math.min(r, w, h / 2));
  return "M" + x + "," + y + " H" + (x + w - rr)
    + " A" + rr + "," + rr + " 0 0 1 " + (x + w) + "," + (y + rr)
    + " V" + (y + h - rr)
    + " A" + rr + "," + rr + " 0 0 1 " + (x + w - rr) + "," + (y + h)
    + " H" + x + " Z";
}

// ── tooltip ─────────────────────────────────────────────────────────────────
let tipEl = null;

function tipHost() {
  if (!tipEl) {
    tipEl = el("div", { class: "charttip", role: "tooltip", hidden: true });
    document.body.appendChild(tipEl);
  }
  return tipEl;
}

function showTip(pairs, ev) {
  const host = tipHost();
  clear(host);
  pairs.forEach(function (pair) {
    host.appendChild(el("div", null,
      el("span", { text: pair[0] }),
      el("b", { class: "mono", text: pair[1] })
    ));
  });
  host.hidden = false;
  moveTip(ev);
}

function moveTip(ev) {
  const host = tipHost();
  const box = host.getBoundingClientRect();
  const x = Math.min(ev.clientX + 14, window.innerWidth - box.width - 8);
  const y = Math.min(ev.clientY + 16, window.innerHeight - box.height - 8);
  host.style.left = Math.max(8, x) + "px";
  host.style.top = Math.max(8, y) + "px";
}

function hideTip() {
  if (tipEl) tipEl.hidden = true;
}

// ── SVG element builders ────────────────────────────────────────────────────
// Written as assignments rather than literals: the inline-data lint caps object
// literals at four keys, and an <rect> needs five.
function rectNode(cls, x, y, w, h) {
  const a = {};
  a.class = cls;
  a.x = x;
  a.y = y;
  a.width = w;
  a.height = h;
  return svg("rect", a);
}

function lineNode(cls, x1, y1, x2, y2) {
  const a = {};
  a.class = cls;
  a.x1 = x1;
  a.y1 = y1;
  a.x2 = x2;
  a.y2 = y2;
  return svg("line", a);
}

function textNode(cls, x, y, size, text) {
  const a = {};
  a.class = cls;
  a.x = x;
  a.y = y;
  a["font-size"] = size;
  a.text = text;
  return svg("text", a);
}

// ── the chart ───────────────────────────────────────────────────────────────
function paint(host, rows, tip) {
  const cs = getComputedStyle(host);
  const mono = cs.getPropertyValue("--font-mono").trim() || "monospace";
  const fsBody = parseFloat(cs.getPropertyValue("--fs-body")) || 11.5;
  const fsMini = parseFloat(cs.getPropertyValue("--fs-mini")) || 10.5;
  const rowH = (parseFloat(cs.getPropertyValue("--row-h")) || 26) + 14;
  const fontBody = fsBody + "px " + mono;
  const fontMini = fsMini + "px " + mono;

  const W = Math.max(MIN_W, Math.round(host.clientWidth || MIN_W));
  const H = rows.length * rowH + 2;
  const labelW = Math.round(Math.max(150, Math.min(280, W * 0.34)));
  const valueW = Math.round(Math.max(64, rows.reduce(function (m, r) {
    return Math.max(m, measure(r[3], fontMini));
  }, 0) + GUTTER * 2));
  const span = Math.max(24, W - labelW - valueW);
  const max = rows.reduce(function (m, r) { return Math.max(m, Number(r[2]) || 0); }, 0) || 1;

  const frame = svg("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, role: "img" });

  rows.forEach(function (r, i) {
    const y = i * rowH;
    const bw = Math.max(2, Math.round(span * ((Number(r[2]) || 0) / max)));
    const barY = y + rowH - BAR_H - 8;
    const g = svg("g", { class: "ch-row", tabindex: "0" });

    g.appendChild(svg("title", { text: r[0] + " · " + r[3] }));
    g.appendChild(rectNode("c-hit", 0, y, W, rowH - 1));
    g.appendChild(lineNode("c-grid", 0, y + rowH - 0.5, W, y + rowH - 0.5));
    g.appendChild(textNode("c-ink", 0, y + fsBody + 4, fsBody, fit(r[0], labelW - GUTTER, fontBody)));
    if (r[1]) {
      g.appendChild(textNode("c-ink-3", 0, y + fsBody + fsMini + 7, fsMini, fit(r[1], labelW - GUTTER, fontMini)));
    }
    g.appendChild(svg("path", { class: "c-bar", d: capPath(labelW, barY, bw, BAR_H, CAP_R) }));
    g.appendChild(textNode("c-ink-2", labelW + bw + GUTTER, barY + BAR_H - 1, fsMini, r[3]));

    if (tip) {
      g.addEventListener("mouseenter", function (ev) { showTip(tip(r, i), ev); });
      g.addEventListener("mousemove", moveTip);
      g.addEventListener("mouseleave", hideTip);
      g.addEventListener("blur", hideTip);
    }
    frame.appendChild(g);
  });

  clear(host).appendChild(frame);
}

export const chart = {
  /**
   * rankedBars(host, rows, tip?) -> {el, destroy()}
   *   rows — [label, sublabel, value, valueText][] already in rank order
   *   tip  — (row, index) => [caption, value][] rendered into the hover tooltip
   * The host repaints itself on resize (density and theme changes flow through
   * the tokens, so they need no hook). destroy() stops that observer early; a
   * chart whose host has been detached stops on its own at the next resize.
   */
  rankedBars(host, rows, tip) {
    host.classList.add("chart");
    paint(host, rows, tip);

    let ro = null;
    if (typeof ResizeObserver === "function") {
      ro = new ResizeObserver(function () {
        if (!host.isConnected) { ro.disconnect(); return; }
        paint(host, rows, tip);
      });
      ro.observe(host);
    }

    return {
      el: host,
      destroy() { if (ro) ro.disconnect(); hideTip(); },
    };
  },
};
