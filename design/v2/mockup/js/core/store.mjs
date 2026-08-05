// store.mjs — the ONLY data entry point of the mockup.
// Every figure on screen comes from design/v2/snapshots/<id>.json, captured from
// the real appliance by design/v2/tools/capture_snapshots.py. Nothing is typed by
// hand (design/v2/tools/lint_no_inline_data.py enforces that mechanically).
//
// Path resolution: the documented base is "../snapshots/" (relative to
// mockup/index.html), which is what a server rooted at design/v2 answers.
// design/v2/tools/gate_coverage.py instead serves design/v2/mockup as the web
// root, where a browser clamps "../snapshots/" to "/snapshots/" and nothing can
// reach outside the root — so design/v2/mockup/snapshots is a symlink to
// ../snapshots, and both server roots resolve. "snapshots/" is probed as a second
// base for robustness; whichever answers first is remembered for the session.

const BASES = ["../snapshots/", "snapshots/"];

const cache = new Map();      // id -> Promise<any>
let base = null;              // resolved on first successful fetch

function detail(id, tried) {
  return "store.load(\"" + id + "\")\n" + tried.join("\n");
}

async function fetchFrom(prefix, id) {
  const url = prefix + id + ".json";
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(url + " → HTTP " + res.status + " " + res.statusText);
  return res.json();
}

async function fetchSnapshot(id) {
  const tried = [];
  const order = base ? [base].concat(BASES.filter(function (b) { return b !== base; })) : BASES;
  for (let i = 0; i < order.length; i++) {
    try {
      const data = await fetchFrom(order[i], id);
      base = order[i];
      return data;
    } catch (e) {
      tried.push("  " + String((e && e.message) || e));
    }
  }
  const err = new Error("snapshot \"" + id + "\" is not reachable");
  err.detail = detail(id, tried);
  throw err;
}

export const store = {
  /** load(id) -> Promise<any>. Cached per id; failures are not cached. */
  load(id) {
    const key = String(id);
    if (!cache.has(key)) {
      const p = fetchSnapshot(key).catch(function (e) { cache.delete(key); throw e; });
      cache.set(key, p);
    }
    return cache.get(key);
  },

  /** Drop the cache entry and load again — what the error card's retry calls. */
  reload(id) {
    cache.delete(String(id));
    return this.load(id);
  },

  /** Synchronous "is it already loaded" probe; returns undefined if not. */
  loaded(id) {
    return cache.has(String(id));
  },

  /** Test/dev hook: forget everything. */
  clear() {
    cache.clear();
  },
};
