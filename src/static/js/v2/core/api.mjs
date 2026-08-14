// api.mjs — the ONLY data entry point of the production v2 frontend.
//
// Same job as the mockup's core/store.mjs (id -> Promise<any>, cached per id),
// except id resolves through GET_MAP (store-map.mjs) to a real backend
// endpoint instead of a snapshot file, and there is a companion post()/del()
// for the state-changing calls the mockup never needed (del() is what this
// task's own e2e test uses to clean up the dashboard query it creates —
// see the brief's "POST 建自訂查詢→GET 見→DELETE 清" acceptance line).
//
// CSRF semantics are transcribed from src/static/js/utils.js (:3-63):
//   - a meta[name=csrf-token] tag holds the current token (base.html renders
//     it via {{ csrf_token() }}, matching src/templates/index.html:8);
//   - every non-GET request carries it as the `X-CSRF-Token` header;
//   - on a 400 with {code: "csrf_error"} the token is refreshed (from the
//     error body if it carries one, else GET /api/csrf-token) and the
//     request is retried exactly once — utils.js's `api()` behaviour verbatim.
//
// 401/403/423 handling also transcribes utils.js's *current* behaviour, which
// is narrower than it might sound:
//   - 401/403 get NO special handling here, same as utils.js — the parsed
//     body is returned (post/put/del) or the failed response is thrown
//     (load, see below); callers decide what to show.
//   - 423 + {error: "must_change_password"} redirects the browser to /login,
//     exactly like utils.js. v2 has no login page of its own yet (that is
//     Task 10), so this intentionally lands on the existing production login
//     page — the only one that exists right now.
//
// load() vs post()/del() deliberately differ in failure shape, because they
// serve different mockup-inherited contracts:
//   - load(id) mirrors store.mjs: throws on a non-2xx response, so callers
//     written against the mockup's error-card retry pattern (`catch(e) {...
//     onRetry }`) keep working unchanged.
//   - post/del mirror utils.js's api(): never throw, always resolve with the
//     parsed JSON body (typically `{ok: true|false, ...}`), leaving the
//     ok/error check to the caller — exactly how every existing production
//     JS file already treats them.

import { GET_MAP } from "./store-map.mjs";

const cache = new Map(); // cacheKey -> Promise<any>

function csrfMeta() {
  return document.querySelector('meta[name="csrf-token"]');
}

function csrfToken() {
  const meta = csrfMeta();
  return meta ? meta.getAttribute("content") : "";
}

function setCsrfToken(token) {
  if (!token) return;
  let meta = csrfMeta();
  if (!meta) {
    meta = document.createElement("meta");
    meta.setAttribute("name", "csrf-token");
    document.head.appendChild(meta);
  }
  meta.setAttribute("content", token);
}

async function refreshCsrfToken() {
  const r = await fetch("/api/csrf-token");
  const data = await r.json();
  setCsrfToken(data.csrf_token);
  return data.csrf_token;
}

function withCsrf(opt) {
  const method = (opt.method || "GET").toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return opt;
  const headers = new Headers(opt.headers || {});
  headers.set("X-CSRF-Token", csrfToken());
  return Object.assign({}, opt, { headers });
}

async function parseJson(response) {
  try {
    return await response.json();
  } catch (e) {
    return { ok: false, error: response.statusText || ("HTTP " + response.status) };
  }
}

/** Shared request core: CSRF retry + 423 redirect. Never throws on its own. */
async function rawRequest(url, opt) {
  const method = (opt.method || "GET").toUpperCase();
  let res = await fetch(url, withCsrf(opt));
  let data = await parseJson(res);

  if (res.status === 400 && data && data.code === "csrf_error" && method !== "GET") {
    if (data.csrf_token) setCsrfToken(data.csrf_token);
    else await refreshCsrfToken();
    res = await fetch(url, withCsrf(opt));
    data = await parseJson(res);
  }

  if (res.status === 423 && data && data.error === "must_change_password") {
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }

  return { res, data };
}

/** GET a path and throw on a non-2xx response — the store.mjs contract. */
async function fetchJson(url) {
  const { res, data } = await rawRequest(url, {});
  if (!res.ok) {
    const err = new Error(url + " → HTTP " + res.status + " " + (res.statusText || ""));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/** POST/PUT/DELETE a path and always resolve with the parsed body — the utils.js api() contract. */
async function mutate(method, url, body) {
  const opt = { method };
  if (body !== undefined) {
    opt.headers = { "Content-Type": "application/json" };
    opt.body = JSON.stringify(body);
  }
  const { data } = await rawRequest(url, opt);
  return data;
}

function resolveEntry(id, params) {
  const entry = GET_MAP[id];
  if (entry === undefined) throw new Error('api.load: unknown id "' + id + '"');
  return typeof entry === "function" ? entry(params) : entry;
}

function cacheKey(id, params) {
  return params ? id + ":" + JSON.stringify(params) : id;
}

export const api = {
  /**
   * load(id, params?) -> Promise<any>. Cached per (id, params); failures are
   * not cached (matches store.mjs's reload-on-retry expectation).
   */
  load(id, params) {
    const key = cacheKey(id, params);
    if (!cache.has(key)) {
      const path = resolveEntry(id, params);
      const p = fetchJson(path).catch(function (e) { cache.delete(key); throw e; });
      cache.set(key, p);
    }
    return cache.get(key);
  },

  /** Drop the cache entry and load again — what an error card's retry calls. */
  reload(id, params) {
    cache.delete(cacheKey(id, params));
    return this.load(id, params);
  },

  /** post(path, body) -> Promise<any parsed body>. Never throws; see header. */
  post(path, body) {
    return mutate("POST", path, body === undefined ? {} : body);
  },

  /** del(path) -> Promise<any parsed body>. Same contract as post(). */
  del(path) {
    return mutate("DELETE", path, undefined);
  },

  /** Drop a cached load() entry without refetching. */
  invalidate(id, params) {
    cache.delete(cacheKey(id, params));
  },

  /** Test/dev hook: forget every cached load(). */
  clear() {
    cache.clear();
  },
};
