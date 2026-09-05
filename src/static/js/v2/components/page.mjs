// page.mjs — the page skeletons of the v3.1 workbench (spec
// docs/superpowers/specs/2026-09-04-ui-redesign-v3-1-workbench-design.md §5.1).
//
// 3B let every area draw its own head: six near-identical copies of an
// `areaHead(title, route)` helper, each appending its own `.subnav`. v3.1 moves
// sub-navigation into the left-hand shell and gives every page ONE head —
// breadcrumbs, a sentence title, one line of subtitle, and an action row with
// at most one primary button. That head is this module's `pageHead`, and it is
// the only one the product has.
//
// Two structural notes that are contracts, not style:
//
//   1. `data-route` rides on the head element. It is not rendered (density
//      spec R4 — the route is not chrome), but a dozen e2e files use
//      `[data-route="#/x"]` as "this page has mounted"; moving the head
//      without carrying the attribute would break every one of them.
//   2. The head is built synchronously and appended before an area's first
//      await, so `.phead h2` is the signal that a page exists even while its
//      data is still loading.

import { el } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { NAV } from "../shell.mjs";

/**
 * pageHead({route, crumbs, title, sub, actions, cov}) -> HTMLElement
 *
 *   route    the hash this page lives at; becomes data-route (see note 1)
 *   crumbs   [[text, href|null], ...] — the trail above the title
 *   title    the sentence title (spec §5.2: a sentence, not a noun)
 *   sub      one line saying what this page does or where it stands
 *   actions  [HTMLElement, ...] — at most one may carry .btn.primary
 *   cov      a data-cov anchor, when the head itself is the coverage surface
 */
export function pageHead(opts) {
  const o = opts || {};
  const head = el("header", {
    class: "phead",
    "data-route": o.route || null,
    "data-cov": o.cov || null,
  });

  const crumbs = Array.isArray(o.crumbs) ? o.crumbs.filter(Boolean) : [];
  if (crumbs.length) {
    const trail = el("nav", { class: "crumbs" });
    crumbs.forEach(function (pair, i) {
      const text = Array.isArray(pair) ? pair[0] : pair;
      const href = Array.isArray(pair) ? pair[1] : null;
      if (i) trail.appendChild(el("i", { "aria-hidden": "true", text: "/" }));
      trail.appendChild(href ? el("a", { href: href, text: text }) : el("span", { text: text }));
    });
    head.appendChild(trail);
  }

  const text = el("div", { class: "phead-text" }, el("h2", { text: o.title || "" }));
  if (o.sub) text.appendChild(el("p", { text: o.sub }));

  const row = el("div", { class: "phead-main" }, text);
  const actions = Array.isArray(o.actions) ? o.actions.filter(Boolean) : [];
  if (actions.length) row.appendChild(el("div", { class: "actions" }, actions));
  head.appendChild(row);

  return head;
}

/**
 * section(title, meta, ...children) -> <section class="sect">
 *
 * A narrative block of a detail page. The h3 is body type at reading weight,
 * not an uppercase eyebrow (spec §5.2: panel titles are not shouted).
 */
export function section(title, meta, ...children) {
  const h = el("h3", null, el("span", { text: title }));
  if (meta) h.appendChild(el("small", { text: meta }));
  return el("section", { class: "sect" }, h, children);
}

/**
 * sideCard(title, ...children) -> <div class="side-card">
 *
 * A right-column helper card. Its h4 IS an uppercase eyebrow — one of the
 * three places §5.2 still allows uppercase (eyebrows, table heads, chips).
 */
export function sideCard(title, ...children) {
  return el("div", { class: "side-card" },
    el("h4", { class: "eyebrow", text: title }),
    children);
}

/**
 * crumbsFor(route) -> [[text, href|null], ...]
 *
 * The trail above a page title, derived from shell.mjs's NAV so the nav and
 * the breadcrumbs can never disagree about what lives where. Home is the root
 * and has no trail of its own; an area landing route stops at the area; a
 * sub-route ends on its own (unlinked) name.
 */
export function crumbsFor(route) {
  const path = String(route || "").split("?")[0];
  if (!path || path === "#/home") return [];
  const trail = [[t("gui_nav_home"), "#/home"]];
  const seg = path.replace(/^#\//, "").split("/")[0];
  const area = NAV.filter(function (a) { return a.id === seg; })[0];
  if (!area) return trail;
  const child = area.children.filter(function (pair) { return pair[0] === path; })[0];
  trail.push([t(area.key), child ? area.route : null]);
  if (child) trail.push([t(child[1]), null]);
  return trail;
}

/**
 * labelForRoute(route) -> string
 *
 * The name the left-hand nav gives a route: the sub-item's label if the route
 * is one, otherwise the area's. Falls back to the area name and never to the
 * route itself — printing the address is the thing this exists to stop.
 */
export function labelForRoute(route) {
  const path = String(route || "").split("?")[0];
  const seg = path.replace(/^#\//, "").split("/")[0];
  const area = NAV.filter(function (a) { return a.id === seg; })[0];
  if (!area) return "";
  const child = area.children.filter(function (pair) { return pair[0] === path; })[0];
  return child ? t(child[1]) : t(area.key);
}

/**
 * goLabel(route) -> string — "Go to Notification Channels".
 *
 * Spec §5.2: a link's text is a verb or an object name. Every "Go to" control
 * in the app used to build its own label by gluing the go-to word onto the
 * route variable, which is how "Go to #/system/cache" reached operators from
 * six different modules. There is no concatenation here — the destination's
 * name goes into the catalogue string's own placeholder — so there is nothing
 * for a caller to glue a route onto.
 */
export function goLabel(route) {
  return tf("gui_health_goto_named", { name: labelForRoute(route) });
}

/**
 * chip(text, tone) -> <span class="chip {tone}">
 *
 * §5.2: a status is a chip AND its word, never a colour alone. `tone` is one
 * of the tone families tokens.css declares (ok / warn / crit / info /
 * neutral); the dot inherits the chip's own text colour, so a chip stays
 * readable for a reader who cannot separate the hues.
 */
export function chip(text, tone) {
  return el("span", { class: "chip", "data-tone": tone || "neutral" },
    el("i", { "aria-hidden": "true" }),
    el("span", { text: text }));
}

/**
 * listRow({href, tone, when, title, sub, who, status}) -> <a class="lrow">
 *
 * §5.1: a list page is rows, not a column wall. One row carries a severity
 * stripe, when it happened, one sentence about what happened, who it was
 * about, and a status chip — and the whole row is the link into the detail
 * page, so there is no "open" affordance to hunt for.
 *
 *   when    {main, sub} — the clock time, and the day or age under it
 *   who     [[label, valueNode], ...] — rendered only at full width (§5.4
 *           folds the row to two lines and drops this column)
 */
export function listRow(opts) {
  const o = opts || {};
  const when = o.when || {};
  const row = el("a", { class: "lrow", href: o.href || null, "data-tone": o.tone || "neutral" });
  row.appendChild(el("span", { class: "stripe", "aria-hidden": "true" }));
  row.appendChild(el("span", { class: "when" },
    el("b", { text: when.main || "" }),
    when.sub ? el("span", { text: when.sub }) : null));
  const what = el("span", { class: "what" }, el("b", { text: o.title || "" }));
  if (o.sub) what.appendChild(el("span", { text: o.sub }));
  row.appendChild(what);
  const who = el("span", { class: "who" });
  (o.who || []).forEach(function (pair) {
    who.appendChild(el("span", null, el("i", { text: pair[0] }), pair[1]));
  });
  row.appendChild(who);
  row.appendChild(el("span", { class: "st" }, o.status || null));
  return row;
}

/** listFoot(leftText, rightNode) -> the count-and-a-link line under a list. */
export function listFoot(leftText, rightNode) {
  return el("div", { class: "lfoot" },
    el("span", { text: leftText }),
    rightNode || null);
}
