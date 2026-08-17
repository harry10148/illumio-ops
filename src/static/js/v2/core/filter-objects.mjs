// filter-objects.mjs — the HTTP side of the object filter selector.
//
// components/filter-bar.mjs imports nothing (its parity test loads it as a
// classic script, see that file's constraint 1), so it cannot fetch: it is
// handed three functions through setFilterBarQuery() and this module is what
// those functions are. It lives in core/ rather than in the three areas that
// mount a FilterBar (areas/investigate.mjs, areas/alerting.mjs,
// areas/reports.mjs) because all three want the identical two query strings —
// one copy here beats three copies that can drift apart. The architectural
// requirement it exists to satisfy is unchanged: the HTTP stays out of the
// component, and it goes through core/api.mjs's api.get() like every other
// read in the app (same CSRF plumbing, same error contract).
//
// Endpoint contract (src/gui/routes/filter_objects.py), and the two failure
// shapes every caller has to keep apart:
//
//   GET /api/filter-objects/suggest?q=&types=&limit=
//     200 {ok: true, results: {<type>: {items: [...], truncated, error?}}}
//     `q` empty or no valid type -> results: {}
//     A cached type (label/label_group/iplist/service) whose module cache is
//     cold and whose PCE is unreachable comes back as that type's
//     {items: [], error: "pce_unreachable"} INSIDE an otherwise fine 200 —
//     one category failing does not fail the response.
//
//   GET /api/filter-objects/browse?type=&offset=&limit=
//     200 {ok: true, items: [...], total: N}
//     type=workload  -> {ok: true, browseable: false, items: [], total: null}
//                       (workloads have no browse at all, only suggest)
//     type=_totals   -> {ok: true, totals: {<type>: n}}
//     unknown type   -> 400 {ok: false, error: "unknown_type"}
//     PCE unreachable-> 502 {ok: false, error: "pce_unreachable"}
//
// api.get() throws on a non-2xx, which covers the 400/502 shape. It does NOT
// look at `ok`, and a 200 {ok: false} would otherwise reach the caller looking
// like data ("{ok:true} is not success" — the standing lesson), so ok is
// checked here and turned into a rejection: the bar's own error handling then
// has exactly one failure channel to render, and the per-category `error` key
// stays the only in-band signal it has to inspect.

import { api } from "./api.mjs";

const SUGGEST_LIMIT = 10;   // the endpoint's own default; it clamps to 1..25
const BROWSE_LIMIT = 20;    // the endpoint's own default; it clamps to 1..100

function ok(body) {
  if (!body || body.ok !== true) {
    const err = new Error("filter-objects: request did not succeed");
    err.data = body || null;
    throw err;
  }
  return body;
}

function q(value) {
  return encodeURIComponent(value === null || value === undefined ? "" : String(value));
}

export const filterObjectQuery = {
  /** suggest(q, cats, limit) -> Promise<{results: {<cat>: {items, error?}}}> */
  suggest(query, cats, limit) {
    const types = (cats || []).join(",");
    return api.get("/api/filter-objects/suggest?q=" + q(query)
      + "&types=" + q(types)
      + "&limit=" + q(limit || SUGGEST_LIMIT)).then(ok);
  },

  /** browse(cat, offset, limit) -> Promise<{items, total, browseable?}> */
  browse(cat, offset, limit) {
    return api.get("/api/filter-objects/browse?type=" + q(cat)
      + "&offset=" + q(offset || 0)
      + "&limit=" + q(limit || BROWSE_LIMIT)).then(ok);
  },

  /** totals() -> Promise<{totals: {<cat>: n}}> */
  totals() {
    return api.get("/api/filter-objects/browse?type=_totals").then(ok);
  },
};

// The categories the object browser (XC-04) offers as tabs, and whether the
// backend can list them at all: `browse` is false for workload, whose only
// access path is suggest (see the contract above). Ordered as the filter bar's
// own category pane orders them.
//
// [id, catalogue key, browseable]. The catalogue key is written out per row
// rather than composed from the id at the call site: scripts/audit_i18n_usage.py
// reads the string literal inside t(...), so a concatenated key makes it record
// the bare prefix as a referenced — and therefore missing — key. Same treatment
// components/filter-bar.mjs's _OBJFB_CATS already uses.
export const OBJECT_CATS = [
  ["label", "gui_fb_cat_label", true],
  ["label_group", "gui_fb_cat_label_group", true],
  ["iplist", "gui_fb_cat_iplist", true],
  ["workload", "gui_fb_cat_workload", false],
  ["service", "gui_fb_cat_service", true],
];
