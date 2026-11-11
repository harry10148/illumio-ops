"""The shared presentation rules (purpose-led UI spec §5), measured on the rendered page — computed styles and boxes,
never class names alone, so a page that carries the right class and still looks wrong is caught.

violations(page) runs one script in the page and answers, per rule, what breaks it. Only what is visible inside
<main> is measured (the navigation is not a page)."""
from __future__ import annotations

RULES: tuple[str, ...] = ("one_primary", "styled_checkbox", "tag_not_button", "cards_apart", "no_overlap",
                          "header_one_line", "no_overflow_x", "button_font", "link_not_accent", "buttons_apart")

# every page the navigation reaches, and the rule editor
PATHS: tuple[str, ...] = (
    "/", "/detect", "/investigate", "/hosts", "/fleet", "/rule-schedules", "/rule-schedules/rulesets", "/reports",
    "/reports?tab=schedules", "/reports?tab=produced", "/siem", "/siem/dlq", "/alert-rules", "/alert-rules?tab=channels",
    "/alerts/rules/new", "/system/collection", "/system/pce", "/system/lateral", "/system/jobs", "/system/tls",
    "/system/security", "/system/logs", "/system/display")

PRIMARY_FILL = "rgb(194, 67, 0)"   # --accent-fg: a filled primary action
ACCENT_TEXT = "rgb(186, 64, 0)"    # --accent-text: what links used to be drawn in
CARD_GAP = 16                      # --space-6
MOST = 10                          # violations kept per rule

_JS = r"""
([PRIMARY_FILL, ACCENT_TEXT, CARD_GAP, MOST]) => {
  const root = document.querySelector('main') || document.body;
  const out = {};
  const add = (rule, el, what) => {
    const cls = typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).join('.') : '';
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 30);
    (out[rule] = out[rule] || []).push(`${el.tagName.toLowerCase()}${cls} "${text}": ${what}`);
  };
  const shown = (el) => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0 || cs.visibility === 'hidden' || cs.display === 'none' || cs.opacity === '0') return false;
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (p.tagName === 'DETAILS' && !p.open && !(el.tagName === 'SUMMARY' && el.parentElement === p) && !el.closest('summary')) return false;
    }
    return true;
  };
  const all = (sel) => [...root.querySelectorAll(sel)].filter(shown);
  const px = (v) => parseFloat(v) || 0;
  const lineHeight = (cs) => cs.lineHeight === 'normal' ? px(cs.fontSize) * 1.5 : px(cs.lineHeight);

  // one_primary: at most one filled primary action in a region
  const regions = new Map();
  for (const el of all('button, a')) {
    if (getComputedStyle(el).backgroundColor !== PRIMARY_FILL) continue;
    const region = el.closest('.page-head, .card, .panel, [role=dialog], dialog, aside') || root;
    regions.set(region, [...(regions.get(region) || []), el]);
  }
  for (const [, els] of regions) if (els.length > 1) add('one_primary', els[1], `${els.length} primary actions in one region`);

  // styled_checkbox: no checkbox in the browser's own look
  for (const el of all('input[type=checkbox]')) {
    const cs = getComputedStyle(el);
    if ((cs.appearance || cs.webkitAppearance) !== 'none') add('styled_checkbox', el, `appearance ${cs.appearance}`);
  }

  // tag_not_button: a state tag has no frame and stays on one line
  for (const el of all('.tag, .badge')) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    const border = Math.max(px(cs.borderTopWidth), px(cs.borderRightWidth), px(cs.borderBottomWidth), px(cs.borderLeftWidth));
    if (border > 0) add('tag_not_button', el, `border ${border}px`);
    else if (el.matches('.tag') && r.height > lineHeight(cs) * 1.5 + px(cs.paddingTop) + px(cs.paddingBottom)) add('tag_not_button', el, `wraps, ${Math.round(r.height)}px tall`);
    else if (el.matches('.tag') && r.right > el.parentElement.getBoundingClientRect().right + 1) add('tag_not_button', el, 'runs past what holds it');
  }

  // cards_apart: a card and the nearest card below it keep their distance
  const cards = all('.card, .panel').filter((c) => !c.parentElement.closest('.card, .panel'));
  for (const a of cards) {
    const ra = a.getBoundingClientRect();
    let nearest = null, gap = Infinity;
    for (const b of cards) {
      if (a === b) continue;
      const rb = b.getBoundingClientRect();
      if (rb.left >= ra.right - 1 || rb.right <= ra.left + 1) continue;   // not in the same column
      if (rb.top < ra.bottom - 1) continue;                               // not below
      if (rb.top - ra.bottom < gap) { gap = rb.top - ra.bottom; nearest = b; }
    }
    if (nearest && gap < CARD_GAP - 0.5) add('cards_apart', a, `${Math.round(gap * 10) / 10}px above the next card`);
  }

  // no_overlap: two things to press or read as a heading never share space
  const layer = (el) => el.closest('[role=dialog], dialog, .overlay');
  const things = all('button, a, input, select, textarea, th').map((el) => [el, el.getBoundingClientRect()]);
  for (let i = 0; i < things.length; i++) {
    const [a, ra] = things[i];
    for (let j = i + 1; j < things.length; j++) {
      const [b, rb] = things[j];
      const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
      const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
      if (w <= 2 || h <= 2 || a.contains(b) || b.contains(a) || layer(a) !== layer(b)) continue;
      add('no_overlap', a, `overlaps ${b.tagName.toLowerCase()} "${(b.innerText || '').trim().slice(0, 20)}" by ${Math.round(w)}x${Math.round(h)}px`);
    }
  }

  // header_one_line: a column heading is one line
  for (const el of all('th')) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!(el.innerText || '').trim()) continue;
    if (r.height > lineHeight(cs) * 1.5 + px(cs.paddingTop) + px(cs.paddingBottom) + 1) add('header_one_line', el, `${Math.round(r.height)}px tall`);
  }

  // no_overflow_x: the page never scrolls sideways
  // (the console scrolls inside <main>, not the document: both are looked at)
  for (const el of new Set([document.documentElement, root])) {
    if (el.scrollWidth > el.clientWidth + 1) add('no_overflow_x', el, `${el.scrollWidth} > ${el.clientWidth}`);
  }

  // button_font: buttons share one size (a segmented choice has its own)
  for (const el of all('button, a[class^="btn"], a[class*=" btn"]')) {
    if (el.hasAttribute('aria-pressed') || ['tab', 'switch'].includes(el.getAttribute('role')) || el.closest('[data-seg]')) continue;  // a switch has no words
    const size = getComputedStyle(el).fontSize;
    if (size !== '14px') add('button_font', el, size);
  }

  // link_not_accent: a link is ink with an underline; the accent is for the one main action
  for (const el of all('a')) {
    if (/(^|\s)btn/.test(typeof el.className === 'string' ? el.className : '')) continue;
    if (getComputedStyle(el).color === ACCENT_TEXT) add('link_not_accent', el, 'drawn in the accent colour');
  }

  // buttons_apart: two buttons side by side have air between them (the segments of one control are one control)
  const framed = (el) => { const cs = getComputedStyle(el); return px(cs.borderTopWidth) > 0 || !['rgba(0, 0, 0, 0)', 'transparent'].includes(cs.backgroundColor); };
  for (const a of all('button, a[class^="btn"], a[class*=" btn"]')) {
    const b = a.nextElementSibling;
    if (!b || !b.matches('button, a[class^="btn"], a[class*=" btn"]') || !shown(b)) continue;
    if (a.closest('[data-seg], .chips-row, .seg') || !framed(a) || !framed(b)) continue;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    if (Math.abs(ra.top - rb.top) > ra.height / 2) continue;   // on different lines
    const gap = rb.left - ra.right;
    if (gap < 4) add('buttons_apart', a, `${Math.round(gap * 10) / 10}px from "${(b.innerText || '').trim().slice(0, 20)}"`);
  }

  for (const k of Object.keys(out)) out[k] = [...new Set(out[k])].slice(0, MOST);
  return out;
}
"""


def violations(page) -> dict[str, list[str]]:
    """Per rule, what on the page breaks it (at most MOST each); a rule nothing breaks is absent."""
    found: dict[str, list[str]] = page.evaluate(_JS, [PRIMARY_FILL, ACCENT_TEXT, CARD_GAP, MOST])
    return found
