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
//   - initI18n(seedCatalogue?) (Task 10): GET /api/ui_translations sits
//     behind the same auth gate as every other /api/* route, which the v2
//     login page (areas/login.mjs) hits before the operator has
//     authenticated. The optional `seedCatalogue` argument is used ONLY when
//     the live fetch fails — it lets a caller that already has a real,
//     server-rendered catalogue in hand (login.html embeds one via Jinja,
//     see v2.py's v2_login()) hand it over instead of falling back to
//     English literals. Every other caller (app.mjs boots after the operator
//     is authenticated, so its own fetch always succeeds) passes nothing,
//     which is exactly the old no-argument behaviour.

import { api } from "./api.mjs";

let catalogue = null; // ui_translations response: key -> string
const missing = new Set();

export async function initI18n(seedCatalogue) {
  try {
    catalogue = await api.load("ui_translations");
  } catch (e) {
    catalogue = (seedCatalogue && typeof seedCatalogue === "object") ? seedCatalogue : null;
    // A boot-time catalogue failure must be visible — every t() call falls
    // back to its `fallback` argument (or the raw key) until the next
    // successful init(), which is silent unless something logs it here.
    console.warn(
      catalogue
        ? "[i18n] failed to load ui_translations catalogue; using the caller-supplied seed catalogue instead:"
        : "[i18n] failed to load ui_translations catalogue; every t() call will use its fallback:",
      e,
    );
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
 * tf(name, values, fallback?) -> string with {placeholders} substituted.
 * values: object ({source: "traffic"}) or array (positional, in appearance order).
 * fallback, when the key is unresolved, is used exactly like t()'s own
 * `fallback` argument (and may itself contain {placeholder} tokens — they
 * are substituted the same as a resolved catalogue string). Without this,
 * an unresolved key renders as the literal key text on screen instead of
 * degrading gracefully, which is what happened before this parameter
 * existed (a Task 2 review finding).
 */
export function tf(name, values, fallback) {
  const raw = t(name, fallback);
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
  init(seedCatalogue) { return initI18n(seedCatalogue); },
  /** Keys that fell through the catalogue — the live i18n backlog. */
  missing() { return Array.from(missing).sort(); },
};
