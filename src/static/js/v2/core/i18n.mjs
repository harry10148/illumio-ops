// i18n.mjs — every visible string in v2 resolves through t().
//
// Adapted from the mockup's core/i18n.mjs for a live backend:
//   - the single catalogue is the real product translation table, fetched
//     via api.load("ui_translations") (GET /api/ui_translations, whitelisted
//     to gui_/sched_/status_/error_/pd_ keys server-side by
//     src/gui/_helpers.py:_ui_translation_dict — see store-map.mjs's
//     ui_translations entry) instead of a captured snapshot;
//   - the mockup's second catalogue (mockup/i18n-supplement.json — keys the
//     product does not have yet) is dropped entirely. That file only backed
//     hardcoded mockup strings; in v2 an unresolved key falls straight
//     through to t()'s `fallback` argument (or the key itself), and is
//     recorded in missing() instead. Tasks 4-9 land each area's real keys in
//     src/i18n_en.json / src/i18n_zh_TW.json (gui_ prefix, zh_TW+en pair —
//     see those tasks' reports for the per-area key lists) as they port each
//     area, so missing() is expected to be non-empty until then;
//   - no client-settable `lang`: the server already resolves ui_translations
//     to the operator's configured language (src/gui/routes/dashboard.py
//     api_ui_translations reads settings.language), so switching language is
//     a server-side settings write (System area, Task 9) followed by
//     `api.invalidate("ui_translations")` + `init()` + a remount — not a
//     client-side toggle. There is nothing today for it to control, so it is
//     left out rather than shipped unused.

import { api } from "./api.mjs";

let catalogue = null; // ui_translations response: key -> string
const missing = new Set();

export async function initI18n() {
  try {
    catalogue = await api.load("ui_translations");
  } catch (e) {
    catalogue = null;
  }
  return { catalogue: !!catalogue };
}

function fromCatalogue(name) {
  const v = catalogue && catalogue[name];
  return typeof v === "string" && v.length ? v : null;
}

/**
 * t(name, fallback?) -> string
 * Resolution: product catalogue -> fallback -> the key itself. Anything that
 * falls through is recorded in i18n.missing() so a reviewer can see
 * hardcoding creeping back in instead of having to grep for it.
 */
export function t(name, fallback) {
  const hit = fromCatalogue(name);
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
  init() { return initI18n(); },
  /** Keys that fell through the catalogue — the live i18n backlog. */
  missing() { return Array.from(missing).sort(); },
};
