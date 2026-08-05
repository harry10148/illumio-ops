// i18n.mjs — every visible string resolves through t().
//
// Two catalogues, in priority order:
//   1. snapshots/ui_translations.json — the shipping product catalogue (zh-Hant),
//      captured from the appliance. Authoritative: if a key exists here, it wins.
//   2. mockup/i18n-supplement.json — keys the product does NOT have yet (new area
//      names, columns Task 6 hardcoded). zh + en per key. This file doubles as the
//      Phase-2 i18n key backlog: everything in it must eventually land in the real
//      catalogue.
//
// Anything t() cannot resolve is recorded in i18n.missing() so a reviewer can see
// hardcoding creeping back in instead of having to grep for it.

import { store } from "./store.mjs";

const SUPPLEMENT_URL = "i18n-supplement.json";

let catalogue = null;    // snapshot: key -> zh string
let supplement = null;   // supplement: key -> {zh, en, _note}
let lang = "zh";
const missing = new Set();

export async function initI18n(preferred) {
  if (preferred) lang = preferred;
  const results = await Promise.allSettled([
    store.load("ui_translations"),
    fetch(SUPPLEMENT_URL, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(SUPPLEMENT_URL + " → HTTP " + r.status);
      return r.json();
    }),
  ]);
  catalogue = results[0].status === "fulfilled" ? results[0].value : null;
  const sup = results[1].status === "fulfilled" ? results[1].value : null;
  supplement = (sup && sup.keys) || null;
  return { catalogue: !!catalogue, supplement: !!supplement };
}

function fromSupplement(name) {
  const entry = supplement && supplement[name];
  if (!entry) return null;
  const v = entry[lang];
  return typeof v === "string" && v.length ? v : (typeof entry.zh === "string" ? entry.zh : null);
}

function fromCatalogue(name) {
  const v = catalogue && catalogue[name];
  return typeof v === "string" && v.length ? v : null;
}

/**
 * t(name, fallback?) -> string
 * Resolution: product catalogue -> supplement -> fallback -> the key itself.
 * For a non-zh language the supplement wins, because the captured catalogue only
 * carries the appliance's active language.
 */
export function t(name, fallback) {
  const hit = lang === "zh"
    ? (fromCatalogue(name) || fromSupplement(name))
    : (fromSupplement(name) || fromCatalogue(name));
  if (hit) return hit;
  missing.add(name);
  return fallback === undefined ? name : fallback;
}

/**
 * tf(name, values) -> string with {placeholders} substituted.
 * values: object ({source: "traffic"}) or array (positional, in appearance order).
 */
export function tf(name, values) {
  const raw = t(name);
  let i = 0;
  return String(raw).replace(/\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g, function (whole, token) {
    if (Array.isArray(values)) return values[i++] === undefined ? whole : String(values[i - 1]);
    if (values && Object.prototype.hasOwnProperty.call(values, token)) return String(values[token]);
    return whole;
  });
}

export const i18n = {
  t,
  tf,
  init(preferred) { return initI18n(preferred); },
  get lang() { return lang; },
  set lang(v) { lang = v; },
  /** Keys that fell through both catalogues — the live i18n backlog. */
  missing() { return Array.from(missing).sort(); },
};
