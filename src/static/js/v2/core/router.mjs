// router.mjs — hash router with per-route lazy mount.
//
// register(route, mount): `mount` is called with (el, ctx) and may `await import()`
// its area module, so nothing but the shell is fetched until a route is visited.
// Direct navigation to any hash works (the coverage gate opens every route cold),
// and unknown routes fall back to the placeholder mount instead of erroring.

import { audit } from "./audit.mjs";

const DEFAULT_ROUTE = "#/home";

const routes = new Map();       // "#/area/sub" -> mount(el, ctx)
const changeListeners = new Set();

let rootEl = null;
let fallbackMount = null;
let currentRoute = null;
let mountToken = 0;

function normalize(hash) {
  let h = String(hash || "").trim();
  if (!h || h === "#" || h === "#/") return DEFAULT_ROUTE;
  if (h.charAt(0) !== "#") h = "#" + (h.charAt(0) === "/" ? "" : "/") + h;
  return h;
}

function withQuery(route, query) {
  const base = normalize(route);
  if (query === undefined || query === null) return base;
  const params = query instanceof URLSearchParams ? query : new URLSearchParams(query);
  const qs = params.toString();
  if (!qs) return base;
  return (base.indexOf("?") >= 0 ? base + "&" : base + "?") + qs;
}

function split(route) {
  const q = route.indexOf("?");
  if (q < 0) return { path: route, query: new URLSearchParams("") };
  return { path: route.slice(0, q), query: new URLSearchParams(route.slice(q + 1)) };
}

async function mountCurrent() {
  const route = normalize(window.location.hash);
  const parts = split(route);
  const token = ++mountToken;
  currentRoute = route;

  audit.resetRoute();
  changeListeners.forEach(function (fn) { fn(parts.path, route); });

  const mount = routes.get(parts.path) || fallbackMount;
  if (!rootEl || !mount) return;

  while (rootEl.firstChild) rootEl.removeChild(rootEl.firstChild);
  const ctx = { route: parts.path, query: parts.query, stale() { return token !== mountToken; } };
  try {
    await mount(rootEl, ctx);
  } catch (e) {
    console.error("[router] mount failed for " + parts.path, e);
    if (token === mountToken && fallbackMount && mount !== fallbackMount) await fallbackMount(rootEl, ctx);
  }
}

export const router = {
  /** register(route, mount) — mount(el, ctx) => Promise<void> */
  register(route, mount) {
    routes.set(normalize(route), mount);
    return this;
  },

  /** Mount used for any route with no registration (placeholder areas). */
  setFallback(mount) { fallbackMount = mount; return this; },

  /** go(route, query?) — navigates; re-mounts even when the hash is unchanged.
   *  `query` (URLSearchParams | plain object) is serialised onto the hash so
   *  areas can hand state to each other (spec §4b) without string-building. */
  go(route, query) {
    const next = withQuery(route, query);
    if (normalize(window.location.hash) === next) mountCurrent();
    else window.location.hash = next;
    return next;
  },

  /** replace(route, query?) — like go() but rewrites the current history entry.
   *  Used by legacy-route redirects: with go() the old hash would stay in
   *  history and Back would bounce straight forward again. replaceState does
   *  not fire hashchange, so the mount is driven explicitly. */
  replace(route, query) {
    const next = withQuery(route, query);
    window.history.replaceState(window.history.state, "", next);
    currentRoute = next;
    mountCurrent();
    return next;
  },

  current() { return currentRoute || normalize(window.location.hash); },

  /** Every registered route path, in registration order. */
  known() { return Array.from(routes.keys()); },

  /** onChange(fn) -> unsubscribe. fn(path, fullRoute) fires before the mount. */
  onChange(fn) {
    changeListeners.add(fn);
    return function () { changeListeners.delete(fn); };
  },

  /** start(el) — binds #area-root and mounts whatever the URL already says. */
  start(el) {
    rootEl = el;
    window.addEventListener("hashchange", function () { mountCurrent(); });
    return mountCurrent();
  },
};
