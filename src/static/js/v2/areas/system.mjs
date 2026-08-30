// system.mjs — #/system/{pce,cache,siem,tls,security,display,channels,logs}.
// Anchors SY-01…SY-18 plus XC-05 (theme/density) and XC-06 (timezone/language).
//
// PORT OF design/v2/mockup/js/areas/system.mjs (1823 lines, frozen) against the
// live backend. That file's own header explains the area's one shared shape
// (sectioned cards over a docked save row) and its one deliberate device (the
// dirty ledger, naming every changed key with its old/new value). Both stand
// unchanged here — every deviation from the mockup is recorded at its precise
// location below, and summarised here:
//
//   1. store.load(id) -> api.load(id, params?); loadAll() uses api.load. Every
//      snapshot id this area needs — settings, security, tls_status,
//      cache_settings/status/lag/health/throughput,
//      siem_status/destinations/forwarder/dlq, alert_plugins, logs_index,
//      module_log_sample(params), status — is already an exact GET_MAP entry
//      (store-map.mjs); nothing here needed api.get().
//   2. verifyPane (design/v2/mockup/js/components/verifypane.mjs) is dropped —
//      same precedent investigate.mjs/automation.mjs/reports.mjs already
//      established (that component's own header says it is mockup-only). The
//      payload `<pre>` is appended directly and is now the operator's REAL
//      preview of the request the save row is about to send, not a labelled
//      mockup device — with every typed secret redacted to SECRET_MASK first
//      (redactSecrets(), below): the pane is visible DOM, so serialising the
//      raw body left credentials in plaintext on screen.
//   3. makeForm's returned object is renamed `fapi` (was `api`, mockup-only —
//      it never needed to coexist with a real network layer). fapi.save() now
//      performs the real POST/PUT and inspects the parsed response before
//      committing the ledger baseline: `res.ok !== true` is failure (A3), and
//      errorText() below reads BOTH response shapes this area's endpoints use
//      — config.py's `{error: "string"}` and settings_helpers.save_section's
//      `{errors: {field: msg}}` dict (cache/siem writes go through
//      save_section; settings/security/tls do not).
//   4. A1 — a secret box's value must reach the backend as typed, and must be
//      OMITTED (not sent as "") when left blank, or a re-save silently wipes a
//      stored credential. The mockup's own coerce() replaced any non-empty
//      secret with SECRET_MASK before it reached bodyFn — harmless there
//      (nothing was ever sent), fatal here: every secret field would have
//      shipped eight bullet characters to the backend instead of the real
//      value, and none of this area's backends recognise that mask (their own
//      redaction placeholder is ASCII asterisks — see
//      _strip_redaction_placeholders in src/gui/_helpers.py — so a bullet
//      string is stored as a literal credential, not stripped). Fixed by
//      making coerce() return the raw typed value for a secret field (kept
//      documented below at its own definition) and, at every call site that
//      builds a real body from it, sending the key ONLY when non-empty:
//        - mountPce's connection panel (api.key/api.secret) — the dangerous
//          one, since the box always starts empty ("never re-displayed") and
//          an unconditional `apiPart.key = v.key` would blank the ACTIVE PCE's
//          stored key on every save that touched any other field.
//        - destDrawer's hec_token (add/edit) — an unconditional
//          `b.hec_token = v.hec_token || null` would null out an existing
//          destination's token on every edit that did not retype it.
//        - mountChannels' secret plugin fields (SMTP password, bot tokens) —
//          same shape, same fix.
//      mountSecurity's new_password is left unconditional: config.py's
//      `if d.get("new_password")` gate already no-ops on an empty string
//      server-side.
//   5. Phase 1 defect (this task's own brief): settings.language now goes
//      through fapi.track(), via a small write-back-capable radioGroup (see
//      trackedRadioGroup below) instead of mutating a client-side `i18n.lang`
//      that does not exist in production (i18n.mjs has none — see that
//      module's own header: real language switching is "a server-side
//      settings write followed by api.invalidate + init() + remount", which
//      is exactly what this page's fapi.afterSave now does when `language` is
//      among the changed keys). Before this fix the docked form's setBody
//      always re-sent the STALE snapshot's `st.language`, so clicking Save
//      after toggling the language radio silently re-saved the OLD language —
//      the ledger showed a change that Save then failed to persist.
//      v2_sy_disp_lang_partial is dropped as no longer true: the mockup's
//      catalogue was one captured snapshot in the appliance's active language,
//      so an EN toggle only affected keys the mockup's own i18n-supplement.json
//      happened to carry; production's /api/ui_translations serves the FULL
//      catalogue for whichever language settings.language names, so a real
//      switch is complete, not partial.
//   7. The "restart monitor" banner's confirm POSTs /api/daemon/restart for
//      real (src/gui/__init__.py:607-621, @limiter.limit("5 per hour")) and
//      branches on the four outcomes that route produces: 200 (the standard
//      deployment — `illumio-ops.py --monitor-gui` goes through
//      src/cli/_runtime.py's run_daemon_with_gui, which sets _GUI_OWNS_DAEMON
//      and installs a hook that really rebuilds the scheduler), 409 (the
//      daemon IS externally managed — the only case where
//      gui_daemon_external_restart_hint is the truth), 429 (the hourly limit,
//      reachable while retuning cache settings) and anything else (the
//      server's own error). This corrects an earlier header claim that no
//      such route existed: it does, and looking only at
//      src/pce_cache/web.py + src/gui/routes/admin.py was what missed it — the
//      route is defined inline in the app factory. Still gated behind
//      modal.confirm/XC-08 like every other destructive control here.
//   8. GUI stop now inspects the real POST /api/shutdown response instead of
//      assuming success: a 200 shows the real "stopped" strip, a 403
//      (persistent mode) shows the backend's own localised error via
//      toast.crit. v2_sy_stop_swallow/v2_sy_stop_mock are dropped as no
//      longer true (legacy actions.js swallows the response; this port does
//      not).
//   9. TLS import is wrapped in a NEW modal.confirm — the mockup's bare
//      button POSTs nothing; the real endpoint overwrites the serving
//      certificate's config, so it gets the same XC-08 gate as every other
//      destructive control in this area (reports.mjs's RP-05 added a confirm
//      gate around a legacy bare-button flow for the identical reason).
//      TLS renew is genuinely destructive per this task's own brief — never
//      clicked to Confirm in the e2e, only asserted to render + Cancel.
//  10. TLS CSR generation is real and NON-destructive (writes a CSR+key file,
//      never touches the serving cert config) — exercised for real by the e2e.
//  11. Module logs: the module select's change handler now issues a real,
//      parameterised api.load("module_log_sample", {module_name}) fetch
//      instead of showing "no snapshot for this module" — GET_MAP's own
//      header already made this id a function of the caller's module_name for
//      exactly this reason. Same upgrade automation.mjs made for
//      rs_ruleset_detail (its deviation #2).
//  12. Every "this mockup writes/sends/stops nothing" string is dropped
//      (v2_sy_mock_save, v2_sy_saved's mockup framing, v2_sy_stop_mock/
//      _swallow, v2_sy_dlq_*_mock, v2_sy_ch_test_mock/_req, v2_sy_tls_csr_mock/
//      _import_mock) and replaced with the real outcome. v2_sy_cache_show_banner
//      (a demo-only "preview the banner" button with no product counterpart)
//      is dropped — the real Save flow already shows the banner for real
//      (fapi.afterSave), so the demo affordance is no longer doing anything a
//      real action does not already do.
//  13. i18n: v2_sy_* -> gui_sy_* (this task's rename, mirroring gui_au_*/
//      gui_rp_*), v2_density_* -> gui_density_*, v2_cmd_theme ->
//      gui_sy_theme_toggle, v2_nav_system -> gui_nav_system (new — every
//      other ported area already has its own gui_nav_<area>; this area did
//      not yet).
//  14. Each of the 8 mounts registers its audit openers/palette commands
//      synchronously (before sysPage's first await) and calls
//      installTeardown(state) in the same breath, on the line after `state`
//      itself: it destroys every table this mount created (the two SIEM
//      tables, the logs table), closes any drawer/modal it left open, and
//      drops this route's palette commands — same shape as
//      automation.mjs's installTeardown, shared here across all 8
//      sub-routes. It used to be called inside each build callback instead,
//      i.e. only once a board was successfully built; Task 12d moved all 8
//      up, because a mount that ends on sysPage's error card registers its
//      commands and then has nothing to drop them (the overview had the same
//      defect, found in review). tests/test_v2_teardown_registration.py is
//      the static gate that keeps them here.
//  15. Every mutating action (save, SIEM CRUD) reloads by invalidating
//      this route's snapshot ids and calling router.go(ROUTE) — a full,
//      cache-fresh remount, rather than patching the DOM in place. This
//      mirrors reports.mjs's refreshReportsList ("the server's own listing is
//      the only source of truth") without needing per-page incremental-repaint
//      plumbing none of these eight simple settings pages otherwise needs.
//  16. Snapshot loading is split into STRICT and SOFT ids (see loadAll's own
//      comment). Each of these eight pages mixes CONFIGURATION with
//      TELEMETRY, and the telemetry fails on ordinary operational conditions
//      — GET /api/cache/{status,lag,throughput,health} answer 503 the moment
//      the cache DB is unreachable (src/pce_cache/web.py's _get_sf() guard),
//      which is precisely what an operator opens #/system/cache to fix. One
//      strict Promise.all made that failure replace every configuration
//      control with an error card. The telemetry ids (CACHE_SOFT, SIEM_SOFT,
//      and `status` in PCE/SECURITY/DISPLAY/CHANNELS_SOFT) now degrade to
//      `{_error}`; their own panel states the server's real error and offers
//      a real retry that repaints that panel alone, so unsaved edits in the
//      configuration panels survive. This is the resolution overview.mjs
//      (loadOne), investigate.mjs (loadAll) and reports.mjs
//      (loadRhc/paintRhc) already reached — reports.mjs is the shape followed
//      here. The strict ids stay strict: cache_settings, siem_forwarder,
//      siem_destinations, settings, security, tls_status,
//      alert_plugins and logs_index are what each page is FOR.

import { el, clear, spacer, disclosure } from "../core/dom.mjs";
import { t, tf, i18n } from "../core/i18n.mjs";
import { num } from "../core/fmt.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { toast } from "../core/toast.mjs";
import { theme, density } from "../core/theme.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";

const R_PCE = "#/system/pce";
const R_CACHE = "#/system/cache";
const R_SIEM = "#/system/siem";
const R_TLS = "#/system/tls";
const R_SECURITY = "#/system/security";
const R_DISPLAY = "#/system/display";
const R_CHANNELS = "#/system/channels";
const R_LOGS = "#/system/logs";

// index.html:1975-1983 (integrations sub-tabs) + :1994-2008 (settings sub-tabs).
// The product splits the same concerns across two top-level tabs; v2 keeps one
// sub-nav so "where do I configure X" has a single list.
const SUB_ROUTES = [
  [R_PCE, "gui_settings_tab_pce"],
  [R_CACHE, "gui_it_cache"],
  [R_SIEM, "gui_siem_forwarder"],
  [R_TLS, "gui_tls_title"],
  [R_SECURITY, "gui_settings_tab_security"],
  [R_DISPLAY, "gui_settings_tab_display"],
  [R_CHANNELS, "gui_settings_tab_channels"],
  [R_LOGS, "gui_ml_title"],
];

/** Minimal area-head: title + route breadcrumb. Same local copy every
 *  single-route/sub-nav area keeps — shell.mjs does not exist in this app
 *  (reports.mjs/automation.mjs's own comment explains why duplicating this
 *  small a helper beats depending on one). */
/* Route as a data attribute, not visible chrome — see overview.mjs's areaHead. */
function areaHead(title, route) {
  return el("div", { class: "area-head", "data-route": route },
    el("h1", { text: title })
  );
}

// ── shared chrome ───────────────────────────────────────────────────────────
function panel(cov, title) {
  const head = el("div", { class: "panel-h" }, el("h3", { title: title, text: title }));
  const body = el("div", { class: "panel-b" });
  const root = el("section", { class: "panel", "data-cov": cov || null }, head, body);
  root.head = head;
  root.body = body;
  return root;
}

function withMeta(p, text) {
  p.head.appendChild(el("span", { class: "meta", title: text, text: text }));
  return p;
}

function note(text) { return el("p", { class: "note", text: text }); }
function btn(cls, text, onClick) { return el("button", { class: cls, type: "button", text: text, onClick: onClick }); }
function badge(text, tn) { return el("span", { class: "badge", "data-tone": tn }, el("i", { class: "dot" }), el("span", { text: text })); }
function sectionHead(text) { return el("h4", { class: "eyebrow", text: text }); }

function sysTop(active) {
  const head = areaHead(t("gui_nav_system"), active);
  const nav = el("nav", { class: "subnav wrap", "aria-label": t("gui_nav_system") });
  SUB_ROUTES.forEach(function (pair) {
    const a = el("a", { href: pair[0], text: t(pair[1]) });
    if (pair[0] === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  head.appendChild(nav);
  return head;
}

function labelled(labelText, control, hint) {
  const box = el("div", { class: "fld" });
  const lab = el("label", null, el("span", { text: labelText }));
  box.appendChild(lab);
  box.appendChild(control);
  if (hint) box.appendChild(el("small", { class: "hint", text: hint }));
  box.lab = lab;
  return box;
}

function textField(value) {
  const input = el("input", { class: "field", type: "text" });
  input.value = value === null || value === undefined ? "" : String(value);
  return input;
}

function numberField(value, min, max) {
  const input = el("input", { class: "field", type: "number" });
  if (min !== null && min !== undefined) input.min = String(min);
  if (max !== null && max !== undefined) input.max = String(max);
  input.value = value === null || value === undefined ? "" : String(value);
  return input;
}

function passwordField(placeholder) {
  const input = el("input", { class: "field", type: "password", placeholder: placeholder || "" });
  return input;
}

function checkField(value) {
  const input = el("input", { type: "checkbox" });
  input.checked = !!value;
  return input;
}

function checkRow(labelText, input, hint) {
  const row = el("div", { class: "fld" }, el("label", { class: "chk" }, input, el("span", { text: labelText })));
  if (hint) row.appendChild(el("small", { class: "hint", text: hint }));
  return row;
}

function selectField(pairs, value, translate) {
  const sel = el("select", { class: "field" });
  pairs.forEach(function (pair) {
    const opt = el("option", { value: pair[0], text: translate === false ? pair[1] : t(pair[1]) });
    if (String(value) === String(pair[0])) opt.selected = true;
    sel.appendChild(opt);
  });
  return sel;
}

/** A radioGroup whose wrapping <div> also carries a live `.value` (kept in
 *  sync on every change, dispatching its own "change" event) so it can be
 *  passed to fapi.track() like any other control — readCtl()/writeCtl() only
 *  need `.value`/`.checked`/addEventListener, which a plain <div> can carry
 *  just as well as an <input>. `__setValue` lets writeCtl() (discard) also
 *  re-check the right radio, not just update the property. See header point 5
 *  — this is what actually fixes the language-tracking defect; theme/density
 *  below stay on the untracked plain radioGroup() since they apply live and
 *  are never part of the docked ledger. */
function trackedRadioGroup(name, pairs, value, onChange) {
  const box = el("div", { class: "radios" });
  const inputs = [];
  function setValue(v) {
    box.value = v;
    inputs.forEach(function (pair) { pair[1].checked = pair[0] === v; });
  }
  pairs.forEach(function (pair) {
    const input = el("input", { type: "radio", name: name, value: pair[0] });
    if (String(value) === String(pair[0])) input.checked = true;
    input.addEventListener("change", function () {
      if (!input.checked) return;
      box.value = input.value;
      box.dispatchEvent(new Event("change"));
      if (onChange) onChange(input.value);
    });
    inputs.push([pair[0], input]);
    box.appendChild(el("label", null, input, el("span", { text: t(pair[1]) })));
  });
  box.value = value;
  box.__setValue = setValue;
  return box;
}

function radioGroup(name, pairs, value, onChange) {
  const box = el("div", { class: "radios" });
  pairs.forEach(function (pair) {
    const input = el("input", { type: "radio", name: name, value: pair[0] });
    if (String(value) === String(pair[0])) input.checked = true;
    if (onChange) input.addEventListener("change", function () { if (input.checked) onChange(input.value); });
    box.appendChild(el("label", null, input, el("span", { text: t(pair[1]) })));
  });
  return box;
}

function drawerSpec(title, body, onSave) {
  const spec = {};
  spec.title = title;
  spec.body = body;
  if (onSave) spec.onSave = onSave;
  return spec;
}

function confirmSpec(title, impact, onOk, alt) {
  const spec = {};
  spec.title = title;
  spec.impact = impact;
  spec.onOk = onOk;
  spec.alt = alt;
  return spec;
}

function cmdSpec(id, label, run) {
  const spec = {};
  spec.id = id;
  spec.label = label;
  spec.run = run;
  return spec;
}

function buildCell(fn) { const o = {}; o.cell = fn; return o; }
function widthCell(width, fn) { const o = {}; o.width = width; if (fn) o.cell = fn; return o; }
/** A checkbox column: header (de)selects every row on the page, body cell
 *  picks one row. Same shape investigate.mjs's traffic table uses. */
function pickCell(headFn, cellFn) { const o = {}; o.width = 34; o.head = headFn; o.cell = cellFn; return o; }
function buildTable(columns, rows) { const spec = {}; spec.columns = columns; spec.rows = rows; return spec; }

function pagedTable(columns, rows, page, onPage) {
  const spec = {};
  spec.columns = columns;
  spec.rows = rows;
  spec.page = page;
  spec.onPage = onPage;
  return spec;
}

function pageSpec(index, size, total) {
  const p = {};
  p.index = index;
  p.size = size;
  p.total = total;
  return p;
}

/**
 * loadAll(ids, soft) — `ids` keeps the strict Promise.all contract (any
 * failure error-cards the page, because without that snapshot the page has
 * nothing to draw), while every id ALSO listed in `soft` degrades to
 * `{_error: "…"}` instead of rejecting.
 *
 * Header point 16. Each of these eight pages mixes CONFIGURATION (the
 * settings this area exists to edit) with TELEMETRY (counters, lag, health,
 * appliance status). Telemetry here fails on ordinary operational
 * conditions — GET /api/cache/{status,lag,throughput,health} answer 503
 * whenever _get_sf() cannot open the cache DB (src/pce_cache/web.py) — and a
 * bare Promise.all made that failure replace the whole page with an error
 * card, taking away the very controls an operator needs to fix it. Exactly
 * the resolution areas/overview.mjs (loadOne), areas/investigate.mjs
 * (loadAll) and areas/reports.mjs (loadRhc/paintRhc) already reached; the
 * `_error` shape and the real-error-plus-retry rendering follow reports.mjs,
 * which is the closest match (a named panel rather than a whole board of
 * independent cards).
 */
function loadAll(ids, soft) {
  const tolerated = soft || [];
  return Promise.all(ids.map(function (id) {
    const p = api.load(id);
    if (tolerated.indexOf(id) < 0) return p;
    return p.catch(function (e) {
      console.error("[system] " + id + " failed to load", e);
      return { _error: errText(e && e.data ? e.data : e) };
    });
  })).then(function (list) {
    const out = {};
    ids.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

/** Re-fetch a set of soft ids (cache-fresh), same `_error` degradation as
 *  loadAll's — what a degraded panel's own retry button calls. Deliberately
 *  NOT refreshAndRemount(): a remount would discard whatever the operator has
 *  typed into the configuration panels this fix exists to keep usable. */
function reloadSoft(ids) {
  return Promise.all(ids.map(function (id) {
    return api.reload(id).catch(function (e) {
      return { _error: errText(e && e.data ? e.data : e) };
    });
  })).then(function (list) {
    const out = {};
    ids.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

/** The ids of `set` whose soft load failed, in order. */
function failedSoft(d, set) {
  return set.filter(function (id) { return d[id] && d[id]._error; });
}

/** One line naming each failed snapshot and the server's own error text. */
function softErrorText(d, set) {
  return failedSoft(d, set).map(function (id) { return id + ": " + d[id]._error; }).join(" · ");
}

/** Drop the cached copy of every id this route loaded, then remount from the
 *  server's fresh state — see header point 15. */
function refreshAndRemount(route, ids) {
  ids.forEach(function (id) { api.invalidate(id); });
  router.go(route);
}

function errText(value) {
  const message = value && (value.error || value.message);
  return message ? String(message) : t("gui_err_generic");
}

/** Both response shapes this area's write endpoints use: config.py's
 *  {error: "string"} (settings/security/tls) and
 *  settings_helpers.save_section's {errors: {field: msg}} dict (cache/siem
 *  writes go through save_section) — A3: inspect the real fields, not just ok. */
function errorText(res) {
  if (!res) return t("gui_err_generic");
  if (res.error) return String(res.error);
  if (res.errors && typeof res.errors === "object") {
    return Object.keys(res.errors).map(function (k) { return k + ": " + res.errors[k]; }).join("; ");
  }
  return t("gui_err_generic");
}

function showValue(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** A backend field this form deliberately does not control, with the reason. */
function roField(key, value, noteText) {
  const li = el("li");
  li.appendChild(el("code", { class: "c", text: key }));
  const v = el("span", { class: "s", text: showValue(value) });
  v.dataset.field = key;
  li.appendChild(v);
  li.appendChild(el("span", { class: "r", text: noteText }));
  return li;
}

function roList(rows) { return el("ul", { class: "stack rofields" }, rows); }

function kvRow(label, value, tn) {
  const b = el("b", { text: showValue(value) });
  if (tn) b.dataset.tone = tn;
  return el("div", { class: "kv" }, el("span", { text: label }), b);
}

/** S2 — teardown, shared by all 8 sub-mounts (same shape as automation.mjs's
 *  installTeardown). Destroys every table this mount created, closes any
 *  drawer/modal it left open, and drops this route's palette commands. */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    Object.keys(state.tableHandles || {}).forEach(function (k) {
      try { state.tableHandles[k].destroy(); } catch (e) { console.error("[system] table teardown failed", e); }
    });
    state.tableHandles = {};
    drawer.closeAll();
    modal.closeAll();
    palette.setRoute(path);
  });
}

// ══════════════════════════════════════════════════ the settings form ════════

/* readCtl / writeCtl are the only two places that know what an <input> means,
 * so a new control type is one edit rather than one edit per page. */
function readCtl(c) {
  if (c.type === "checkbox") return c.checked;
  return c.value;
}

function writeCtl(c, v) {
  if (c.type === "checkbox") c.checked = !!v;
  else if (typeof c.__setValue === "function") c.__setValue(v === null || v === undefined ? "" : String(v));
  else c.value = v === null || v === undefined ? "" : String(v);
}

// The mask a secret wears on SCREEN — the dirty ledger and the request
// preview, never the request body (see header point 4: coerce() below sends
// the raw value; only ledgerValue() and redactSecrets() show this mask).
const SECRET_MASK = "••••••••";

function coerce(item) {
  const raw = readCtl(item.c);
  // DEVIATION FROM MOCKUP (header point 4): the mockup's coerce() replaced a
  // non-empty secret with SECRET_MASK before it ever reached bodyFn — safe
  // there (nothing was sent), fatal here (it would ship 8 bullet characters
  // as the real credential). The raw typed value must reach the body; the
  // mask stays confined to what is drawn on SCREEN — ledgerValue()'s ledger
  // and redactSecrets()'s copy of the body for the preview pane.
  if (item.kind === "secret") return raw;
  if (item.kind === "number") return raw === "" ? null : Number(raw);
  if (item.kind === "bool") return !!raw;
  if (item.kind === "list") {
    return String(raw).split(",").map(function (s) { return s.trim(); }).filter(function (s) { return s.length > 0; });
  }
  if (item.kind === "ports") {
    // Trim and drop the blanks BEFORE Number(): "".split(",") is [""], and
    // Number("") is 0, so an empty field would otherwise serialise as [0] — a
    // port filter that silently matches port 0 instead of matching nothing.
    return String(raw).split(",").map(function (s) { return s.trim(); })
      .filter(function (s) { return s.length > 0; })
      .map(function (s) { return Number(s); })
      .filter(function (n) { return isFinite(n); });
  }
  return raw;
}

/** What the ledger is allowed to show for one tracked control. */
function ledgerValue(item, raw) {
  if (item.kind !== "secret") return showValue(raw);
  return String(raw === null || raw === undefined ? "" : raw).length ? SECRET_MASK : "—";
}

/** Deep copy of `body` with every string equal to a currently-typed secret
 *  replaced by SECRET_MASK. Matching on the VALUE, not on the key name, is
 *  what makes this correct for every form here: the body key a secret ends up
 *  under is not its tracked key (mountPce nests it under `api`, mountChannels
 *  writes it to the plugin's own config_path leaf, destDrawer renames
 *  nothing but omits it when blank), so a key-name allowlist would silently
 *  miss a form the next person adds. Equality only — nothing in these bodies
 *  ever embeds a secret inside a longer string, and a substring rule would
 *  mangle unrelated values. Used ONLY for the on-screen preview; fapi.save()
 *  keeps building the real body from bodyFn (see fapi.sync/fapi.save). */
function redactSecrets(value, secrets) {
  if (typeof value === "string") return secrets.indexOf(value) >= 0 ? SECRET_MASK : value;
  if (Array.isArray(value)) return value.map(function (v) { return redactSecrets(v, secrets); });
  if (value && typeof value === "object") {
    const out = {};
    Object.keys(value).forEach(function (k) { out[k] = redactSecrets(value[k], secrets); });
    return out;
  }
  return value;
}

function makeForm(method, endpoint) {
  const items = [];
  const fapi = {};
  let bodyFn = null;
  let syncFn = null;

  const count = el("b", { class: "mono" });
  const label = el("span");
  const diff = el("div", { class: "savediff" });
  const discard = btn("btn ghost", t("gui_sy_discard"), function () { fapi.discard(); });
  const save = btn("btn primary", t("gui_save"), function () { fapi.save(); });
  const bar = el("div", { class: "savebar", "data-tone": "neutral" },
    el("span", { class: "dot" }), label, count, diff, spacer(), discard, save);

  // The bar is fixed to the viewport bottom, so it would sit on top of the last
  // panel; `dock` is the in-flow placeholder that reserves its height.
  const dock = el("div", { class: "savedock" }, bar);
  fapi.bar = bar;
  fapi.dock = dock;

  /** track(key, control, kind) — kind: text|number|bool|list|ports|secret */
  fapi.track = function (key, control, kind) {
    const item = {};
    item.key = key;
    item.c = control;
    item.kind = kind || "text";
    item.base = readCtl(control);
    control.dataset.field = key;
    control.addEventListener("input", fapi.sync);
    control.addEventListener("change", fapi.sync);
    items.push(item);
    return control;
  };

  fapi.changed = function () {
    return items.filter(function (i) { return String(readCtl(i.c)) !== String(i.base); });
  };

  fapi.values = function () {
    const out = {};
    items.forEach(function (i) { out[i.key] = coerce(i); });
    return out;
  };

  /** Every non-empty value currently typed into a secret-kind control — what
   *  redactSecrets() looks for when it builds the preview. */
  fapi.secretValues = function () {
    return items.filter(function (i) { return i.kind === "secret"; })
      .map(function (i) {
        const raw = readCtl(i.c);
        return raw === null || raw === undefined ? "" : String(raw);
      })
      .filter(function (v) { return v.length > 0; });
  };

  fapi.setBody = function (fn) { bodyFn = fn; return fapi; };
  fapi.onSync = function (fn) { syncFn = fn; return fapi; };

  fapi.sync = function () {
    const changes = fapi.changed();
    bar.dataset.tone = changes.length ? "warn" : "neutral";
    count.textContent = changes.length ? String(changes.length) : "";
    label.textContent = changes.length ? t("gui_sy_dirty") : t("gui_sy_clean");
    discard.disabled = !changes.length;
    save.disabled = !changes.length;
    clear(diff);
    changes.slice(0, 5).forEach(function (i) {
      diff.appendChild(el("span", { class: "chg" },
        el("code", { text: i.key }),
        el("s", { text: ledgerValue(i, i.base) }),
        el("i", { text: "→" }),
        el("b", { text: ledgerValue(i, readCtl(i.c)) })));
    });
    if (changes.length > 5) diff.appendChild(el("span", { class: "chg", text: tf("gui_sy_more", { n: changes.length - 5 }) }));
    /* The outgoing-request preview is gone. It showed the method, the endpoint
     * and the whole JSON body under every settings form — a description of the
     * API, on a page whose job is to change a setting. The docked bar above
     * already reports what changed, field by field, in the form's own labels,
     * which is the part an operator acts on.
     *
     * Its redaction (redactSecrets, still used by the ledger) existed because
     * that pane was visible DOM and would otherwise have printed typed keys,
     * HEC tokens and new passwords in plaintext. Removing the pane removes that
     * exposure outright rather than masking it. The request itself is unchanged:
     * fapi.save() builds the body from bodyFn and never read this string. */
    if (syncFn) syncFn(changes);
  };

  fapi.discard = function () {
    items.forEach(function (i) { writeCtl(i.c, i.base); });
    fapi.sync();
    toast.info(t("gui_sy_discarded"));
  };

  /** Shared by save()/resend(): POST/PUT `body` as-is, inspect the parsed
   *  response (A3), commit the ledger baseline only on a real ok:true, and
   *  run afterSave(changedKeys, res) — the hook mountDisplay uses to detect a
   *  language change and remount (header point 5). Neither caller mutates
   *  `body` after this point, so both get the same response handling without
   *  either recomputing it. */
  function sendBody(body) {
    const changed = fapi.changed();
    const changedKeys = changed.map(function (i) { return i.key; });
    const n = changed.length;
    save.disabled = true;
    const req = method === "PUT" ? api.put(endpoint, body) : api.post(endpoint, body);
    return req.then(function (res) {
      save.disabled = !fapi.changed().length;
      if (!res || res.ok !== true) {
        /* A refusal the caller knows how to turn into a question is not an
         * error to shout about — it asks, then re-sends the same body with
         * the answer. Anything else still surfaces as a toast. */
        if (fapi.onRefused) {
          const handled = fapi.onRefused(res, body);
          if (handled) return Promise.resolve(handled);
        }
        toast.crit(errorText(res));
        return false;
      }
      items.forEach(function (i) { i.base = readCtl(i.c); });
      fapi.sync();
      toast.ok(tf("gui_sy_saved", { n: n }));
      if (!fapi.afterSave) return true;
      return Promise.resolve(fapi.afterSave(changedKeys, res)).then(function () { return true; });
    });
  }

  /** Real save: build the body from bodyFn/the tracked fields, as before. */
  fapi.save = function () {
    const body = bodyFn ? bodyFn(fapi.values()) : fapi.values();
    return sendBody(body);
  };

  /** resend(body, extra) — re-POST/PUT exactly the body a caller was handed
   *  (via onRefused's second argument), merged with `extra`, WITHOUT
   *  recomputing it from the form's current values through bodyFn. For a
   *  caller answering a refusal (mountPce's pce_target_changed prompt) this
   *  is provably the same request the appliance refused, plus the answer —
   *  not a fresh snapshot of the form that merely happens to still match
   *  today (the modal's scrim/focus-trap keep the form from being edited
   *  meanwhile, but that is an assumption elsewhere, not an invariant here). */
  fapi.resend = function (body, extra) {
    return sendBody(Object.assign({}, body, extra));
  };

  return fapi;
}

async function sysPage(root, ctx, route, snaps, build, soft) {
  root.appendChild(sysTop(route));
  const board = el("div", { class: "board" });
  root.appendChild(board);
  await withErrorCard(board, route + " (" + snaps.length + ")",
    function () { return loadAll(snaps, soft); },
    function (d) {
      if (ctx.stale()) return;
      build(board, d, root);
    });
}

// ══════════════════════════════════════════════════ SY-01 / SY-18  PCE ═══════

const PCE_SNAPS = ["settings", "status"];
/* Header point 16. `status` (GET /api/status) is the appliance's live status,
 * not configuration — and this mount reads nothing out of it (only
 * mountDisplay does), so its failure has no business replacing the PCE
 * connection form with an error card. Soft-loaded here (and in
 * SECURITY/CHANNELS/DISPLAY below) rather than dropped from the list: the
 * request is pre-existing and removing it is not this fix's business. */
const PCE_SOFT = ["status"];

async function mountPce(root, ctx) {
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);

  await sysPage(root, ctx, R_PCE, PCE_SNAPS, function (board, d, host) {
    const s = d.settings || {};
    const api_ = s.api || {};

    const form = makeForm("POST", "/api/settings");
    form.bar.dataset.cov = "SY-18";

    // ── API connection (settings.js:386-390) ───────────────────────────
    const connPanel = panel(null, t("gui_api_conn"));
    const deployment = selectField([
      ["saas", "gui_deployment_saas"],
      ["on_prem", "gui_deployment_on_prem"],
    ], api_.deployment_type || "on_prem");
    const url = textField(api_.url);
    const org = textField(api_.org_id);
    const consoleUrl = textField(api_.console_url || "");
    // Never re-displayed: the snapshot's api.key is already the server's mask
    // (config.py:428-431). An empty box plus the state row below says more and
    // leaks nothing.
    const key = passwordField(t("gui_sy_secret_keep"));
    const secret = passwordField(t("gui_sy_secret_keep"));
    const ssl = checkField(api_.verify_ssl);
    connPanel.body.appendChild(labelled(t("gui_deployment_type"),
      form.track("deployment_type", deployment)));
    connPanel.body.appendChild(labelled(t("gui_url"), form.track("url", url), t("gui_url_help")));
    connPanel.body.appendChild(labelled(t("gui_org_id"), form.track("org_id", org), t("gui_org_id_help")));
    const consoleBox = labelled(t("gui_console_url"), form.track("console_url", consoleUrl));
    const consoleHelpText = el("span");
    const statusLink = el("a", {
      href: "https://status.illumio.com/posts/dashboard",
      target: "_blank",
      rel: "noopener noreferrer",
      text: t("gui_saas_status_link"),
    });
    const statusLinkWrap = el("span", null, " · ", statusLink);
    const consoleHelp = el("small", { class: "hint" }, consoleHelpText, statusLinkWrap);
    consoleBox.appendChild(consoleHelp);
    function syncConsoleHelp() {
      const saas = deployment.value === "saas";
      consoleHelpText.textContent = t(saas ? "gui_console_url_help_saas" : "gui_console_url_help_on_prem");
      statusLinkWrap.hidden = !saas;
    }
    // Use the form's one synchronization path: it runs for native input/change
    // events and after programmatic writeCtl() calls such as Discard.
    form.onSync(syncConsoleHelp);
    connPanel.body.appendChild(consoleBox);
    connPanel.body.appendChild(labelled(t("gui_api_key"), form.track("key", key, "secret"),
      t("gui_api_key_help") + " · " + secretState(api_, "key")));
    connPanel.body.appendChild(labelled(t("gui_api_secret"), form.track("secret", secret, "secret"),
      t("gui_api_secret_help") + " · " + secretState(api_, "secret")));
    connPanel.body.appendChild(checkRow(t("gui_verify_ssl"), form.track("verify_ssl", ssl, "bool")));
    /* What is left here is the connection's own identity. The "secret field
     * state" readout that used to stand above it — one row per credential,
     * each stating set/not-set and the stored length — is gone: the length
     * was never ours to publish, and set/not-set now rides on the field it
     * describes instead of being restated in a section of its own. */
    connPanel.body.appendChild(note(t("gui_sy_secret_note")));

    const healthRow = el("div", { class: "strip", "data-role": "pce-health-status" });
    function paintHealth(stats) {
      clear(healthRow);
      const category = String((stats && stats.health_category) || "unknown");
      const status = String((stats && stats.health_status) || "unknown");
      const ok = category === "ok" && status === "ok";
      const unknown = category === "unknown" || status === "unknown";
      healthRow.dataset.tone = ok ? "ok" : (unknown ? "neutral" : "crit");
      healthRow.appendChild(el("span", { text: t("gui_health_check") }));
      healthRow.appendChild(badge(
        ok ? t("gui_status_ok") : t(unknown ? "gui_card_unknown" : "gui_pce_health_status_failed"),
        ok ? "ok" : (unknown ? "neutral" : "crit")
      ));
    }
    paintHealth((d.status && d.status.pce_stats) || {});
    connPanel.body.appendChild(healthRow);

    const healthButton = btn("btn", t("gui_pce_health_check_now"), function () {
      healthButton.disabled = true;
      return api.postStatus("/api/pce/health-check", {}).then(function (reply) {
        const res = reply.data || {};
        if (reply.status !== 200 || !res.pce_stats) {
          toast.crit(errorText(res));
          return false;
        }
        paintHealth(res.pce_stats);
        if (res.ok === true) {
          toast.ok(t("gui_pce_health_check_passed"));
          return true;
        }
        toast.crit(t("gui_pce_health_check_failed"));
        return false;
      }).finally(function () {
        healthButton.disabled = false;
      });
    });
    connPanel.head.appendChild(healthButton);
    board.appendChild(connPanel);

    // A1 fix (header point 4): key/secret are sent ONLY when the operator
    // actually typed something. An unconditional assignment here would blank
    // the ACTIVE PCE's stored credential on every save that touched url/
    // org_id/verify_ssl alone, since the box always starts empty.
    form.setBody(function (v) {
      const b = {};
      const apiPart = {};
      apiPart.deployment_type = v.deployment_type;
      apiPart.url = v.url;
      apiPart.org_id = v.org_id;
      apiPart.console_url = v.console_url;
      if (v.key) apiPart.key = v.key;
      if (v.secret) apiPart.secret = v.secret;
      apiPart.verify_ssl = v.verify_ssl;
      b.api = apiPart;
      return b;
    });
    /* 409 + pce_target_changed is the appliance refusing to guess what should
     * happen to a previous PCE's cache. Ask, then re-send with the answer. */
    form.onRefused = function (res, body) {
      if (!res || res.pce_target_changed !== true) return false;
      return new Promise(function (resolve) {
        const m = modal.confirm(confirmSpec(t("gui_sy_pce_target_title"), [
          tf("gui_sy_pce_target_from", { url: res.old.url, org: res.old.org_id }),
          tf("gui_sy_pce_target_to", { url: res.new.url, org: res.new.org_id }),
          t("gui_sy_pce_target_flush_body"),
        ], function () {
          return form.resend(body, { pce_target_change: "flush" }).then(resolve);
        }, {
          label: t("gui_sy_pce_target_same"),
          onAlt: function () {
            return form.resend(body, { pce_target_change: "same-pce" }).then(resolve);
          },
        }));
        m.onClose(function () { resolve(false); });
      });
    };
    form.afterSave = function (_changedKeys, res) {
      if (res && res.restart_required) toast.info(t("gui_pce_connection_restart_required"));
      refreshAndRemount(R_PCE, PCE_SNAPS);
    };

    host.appendChild(form.dock);
    form.sync();
  }, PCE_SOFT);
}

/** <field>__set is what the redactor leaves behind alongside the mask: whether
 *  a credential is stored, never how long it is. */
function secretState(obj, key) {
  if (obj[key + "__set"]) return t("gui_sy_secret_set");
  return t("gui_sy_secret_unset");
}

// ══════════════════════════════════════════ SY-02…06 / SY-17  cache ══════════

const CACHE_SNAPS = ["cache_settings", "cache_status", "cache_lag", "cache_throughput", "cache_health"];
/* Header point 16: cache_settings is the CONFIGURATION this page exists to
 * edit (SY-02/03/04/05/06, plus the docked save row) and stays strict — with
 * no settings there is no form to draw. The other four are TELEMETRY feeding
 * SY-17 alone, and each answers 503 the moment the cache DB is unreachable
 * (src/pce_cache/web.py's _get_sf() guard) — the very condition an operator
 * opens this page to fix. They degrade to `{_error}` so that failure costs
 * SY-17 and nothing else. */
const CACHE_SOFT = ["cache_status", "cache_lag", "cache_throughput", "cache_health"];

// integrations.js:460-461 — the two fixed checkbox sets of the traffic filter.
const TF_ACTIONS = ["blocked", "potentially_blocked", "allowed"];
const TF_PROTOCOLS = ["TCP", "UDP", "ICMP"];

/* At most one "::", every group 1-4 hex digits, and exactly 8 groups unless "::"
 * elides some. The old check was /^[\da-fA-F:]+$/ plus "has a colon", which let
 * "::::" through. Dotted IPv4-mapped forms ("::ffff:10.0.0.1") are not accepted
 * here; the old check rejected them too, and pydantic still takes them. */
function validateIpv6(s) {
  const parts = s.split("::");
  if (parts.length > 2) return false;
  const elided = parts.length === 2;
  const head = parts[0] ? parts[0].split(":") : [];
  const tail = elided && parts[1] ? parts[1].split(":") : [];
  const groups = head.concat(tail);
  if (!groups.every(function (g) { return /^[\da-fA-F]{1,4}$/.test(g); })) return false;
  return elided ? groups.length <= 7 : groups.length === 8;
}

/* Accepts an exact IP or a CIDR network, matching what
 * gui_cache_exclude_src_ips_help promises and what TrafficFilterSettings
 * accepts. This is an early hint only — pydantic's ipaddress in
 * config_models.py is the authoritative validation. */
function validateIp(s) {
  const slash = s.indexOf("/");
  const host = slash >= 0 ? s.slice(0, slash) : s;
  const prefix = slash >= 0 ? s.slice(slash + 1) : null;
  if (prefix !== null && !/^\d{1,3}$/.test(prefix)) return false;
  if (/^(\d{1,3}\.){3}\d{1,3}$/.test(host)) {
    if (!host.split(".").every(function (o) { return Number(o) <= 255; })) return false;
    return prefix === null || Number(prefix) <= 32;
  }
  if (!validateIpv6(host)) return false;
  return prefix === null || Number(prefix) <= 128;
}

/** integrations.js:528-541 — hints joined with " · ", one per offending token. */
function trafficFilterHints(ipsRaw, portsRaw) {
  const hints = [];
  String(ipsRaw || "").split(",").map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; })
    .forEach(function (ip) { if (!validateIp(ip)) hints.push(t("gui_err_invalid_ip") + ": " + ip); });
  String(portsRaw || "").split(",").map(function (s) { return s.trim(); })
    .filter(function (s) { return s.length > 0; })
    .forEach(function (p) {
      const n = Number(p);
      if (!Number.isInteger(n) || n < 1 || n > 65535) hints.push(t("gui_err_port_range") + ": " + p);
    });
  return hints;
}

/** integrations.js:161-166 — the lag readout's own duration format. */
function fmtLag(sec) {
  const s = Math.max(0, Math.floor(Number(sec) || 0));
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  return Math.floor(s / 3600) + "h";
}

async function mountCache(root, ctx) {
  const handles = {};
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  modal.registerAudit("sy-cache-retention", function () { return handles.retention ? handles.retention() : null; });
  modal.registerAudit("sy-cache-restart", function () { return handles.restart ? handles.restart() : null; });
  palette.registerFor(R_CACHE, cmdSpec("sy:retention", t("gui_retention_now"), function () { if (handles.retention) handles.retention(); }));

  await sysPage(root, ctx, R_CACHE, CACHE_SNAPS,
    function (board, d, host) {
      const s = d.cache_settings || {};
      const tf0 = s.traffic_filter || {};
      const ts = s.traffic_sampling || {};
      const form = makeForm("PUT", "/api/cache/settings");

      // ── SY-17 status cards + lag row ─────────────────────────────────
      /* The only telemetry on this page (CACHE_SOFT). paintStatus() is
       * re-runnable so its own retry can repair THIS panel in place, leaving
       * every configuration panel below — and anything already typed into
       * them — exactly as it was. Same real-error-plus-retry shape as
       * reports.mjs's paintRhc(). */
      const statPanel = panel("SY-17", t("gui_cache_status"));
      function paintStatus() {
        clear(statPanel.body);
        const st = d.cache_status && !d.cache_status._error ? d.cache_status : {};
        const tp = d.cache_throughput && !d.cache_throughput._error ? d.cache_throughput : {};
        const failed = failedSoft(d, CACHE_SOFT);
        const cards = el("div", { class: "kpirow" });
        /* integrations.js:117 — only card 1 changes tone (enabled/disabled);
         * cards 2-4 are hardcoded card-ok, so no threshold is invented here.
         * Card 1 reads cache_settings (configuration), so it stays truthful
         * even when every counter below it is unavailable. */
        cards.appendChild(kpiCell(t("gui_cache_status"), s.enabled ? t("gui_cache_enabled") : t("gui_cache_disabled"), null, s.enabled ? "ok" : "crit"));
        cards.appendChild(kpiCell(t("gui_ov_events"), num(st.events), oneHour(tp.events_1h), null));
        cards.appendChild(kpiCell(t("gui_cache_card_traffic_raw"), num(st.traffic_raw), oneHour(tp.traffic_raw_1h), null));
        cards.appendChild(kpiCell(t("gui_cache_card_traffic_agg"), num(st.traffic_agg), oneHour(tp.traffic_agg_1h), null));
        statPanel.body.appendChild(cards);

        if (failed.length) {
          // The failure is stated where it happened, in the server's own
          // words, with a real retry — never hidden behind a healthy-looking
          // zero (num(undefined) already renders "—" in the cards above).
          statPanel.dataset.tone = "crit";
          statPanel.body.appendChild(note(softErrorText(d, CACHE_SOFT)));
          statPanel.body.appendChild(btn("btn primary", t("gui_errcard_retry"), function () {
            return reloadSoft(CACHE_SOFT).then(function (fresh) {
              if (state.torn) return;
              Object.keys(fresh).forEach(function (k) { d[k] = fresh[k]; });
              paintStatus();
            });
          }));
          return;
        }
        statPanel.dataset.tone = null;

        // integrations.js:157-180 — one entry per source; last_status="error"
        // overrides the level colour and appends ⚠, because a failed ingest still
        // bumps last_sync_at and would otherwise read as healthy (:168-169).
        const lag = (d.cache_lag && d.cache_lag.sources) || [];
        const lagRow = el("div", { class: "strip", "data-tone": "info" },
          el("span", { text: t("gui_cache_ingest_lag") }));
        lag.forEach(function (row) {
          const bad = row.last_status === "error";
          const tn = bad ? "crit" : (row.level === "warning" ? "warn" : (row.level === "ok" ? "ok" : "neutral"));
          const item = el("span", { class: "lagitem", "data-tone": tn, title: row.last_error || "" },
            el("span", { text: row.source }),
            el("b", { text: fmtLag(row.lag_seconds) + (bad ? " ⚠" : "") }));
          lagRow.appendChild(item);
        });
        if (!lag.length) lagRow.appendChild(el("span", { text: t("gui_it_none") }));
        statPanel.body.appendChild(lagRow);
        /* Density spec R5 — this panel's two caveats (what the (1h) deltas are
         * measured against; why a red lag figure is not the same as a stale
         * one) are worth keeping and are not worth reading twice a day. They
         * fold into one explanation instead of sitting between the numbers. */
        statPanel.body.appendChild(disclosure(t("gui_gen_explain"),
          note(t("gui_sy_cache_1h_bug")),
          note(t("gui_sy_cache_lag_note"))));
        // The capacity figures the retention and disk-free thresholds below are
        // judged against (/api/cache/health, cache_health.json). They are the
        // reading that makes disk_free_warn_gb a number worth setting.
        const cap = (d.cache_health && d.cache_health.capacity) || {};
        statPanel.body.appendChild(sectionHead(t("gui_sy_cache_capacity")));
        statPanel.body.appendChild(kvRow(t("gui_sy_cache_db_bytes"), mib(cap.db_bytes)));
        statPanel.body.appendChild(kvRow(t("gui_sy_cache_disk_free"), mib(cap.disk_free_bytes),
          Number(cap.disk_free_bytes || 0) / 1073741824 < Number(s.disk_free_warn_gb || 0) ? "warn" : "ok"));
        statPanel.body.appendChild(kvRow(t("gui_sy_cache_siem_pending"), num(cap.siem_pending),
          Number(cap.siem_pending || 0) > Number(s.siem_pending_warn_rows || 0) ? "warn" : "ok"));
      }
      paintStatus();
      board.appendChild(statPanel);

      // ── SY-03 restart banner + SY-04 retention ───────────────────────
      const opsPanel = panel("SY-03", t("gui_it_restart_monitor"));
      const banner = el("div", { class: "strip", "data-tone": "warn", hidden: true },
        el("span", { text: t("gui_it_restart_saved") }));
      banner.appendChild(spacer());
      banner.appendChild(btn("btn primary", t("gui_it_restart_monitor"), function () { handles.restart(); }));
      banner.appendChild(btn("btn ghost", t("gui_dismiss"), function () { banner.hidden = true; }));
      opsPanel.body.appendChild(banner);
      /* showRestartBanner is called on EVERY successful save (integrations.js:300)
       * and the backend hardcodes requires_restart:true
       * (gui/settings_helpers.py:23) — there is no per-field restart detection,
       * so the banner cannot tell you whether YOUR change needs one. */
      /* The caveat is appended after the button below, not here: an
       * explanation belongs under the control it explains, and putting the
       * disclosure first left the button sitting alone under a link. */
      /* Real endpoint: POST /api/daemon/restart (gui/__init__.py:607-621,
       * rate-limited to 5/hour). It rebuilds the scheduler for real whenever
       * the GUI owns the daemon — which is the standard deployment, since
       * `--monitor-gui` (cli/_runtime.py's run_daemon_with_gui) is what the
       * systemd unit runs and what installs the restart hook. Its own
       * 409 is the ONE case where "restart it from your service manager" is
       * the truth, so that line is shown on 409 and nowhere else. 429 is
       * reachable by an operator retuning cache settings, so it gets a
       * sentence of its own instead of the raw error code. api.post() does
       * NOT throw on a non-2xx (see core/api.mjs), and the 409 body carries a
       * localised message rather than a code — hence postStatus(), which
       * hands back the status these branches are actually keyed on. */
      handles.restart = function () {
        return modal.confirm(confirmSpec(t("gui_it_restart_monitor"), [
          t("gui_sy_restart_i_poll"),
          t("gui_sy_restart_i_rate"),
          t("gui_sy_restart_i_409"),
        ], function () {
          return api.postStatus("/api/daemon/restart", {}).then(function (r) {
            const res = r.data || {};
            if (r.status === 409) {
              toast.info(t("gui_daemon_external_restart_hint"));
              banner.hidden = true;
              return true;
            }
            if (r.status === 429) {
              toast.warn(tf("gui_err_rate_limited", { description: res.description || "" }));
              return false;
            }
            if (r.status !== 200 || res.ok !== true) {
              toast.crit(errText(res));
              return false;
            }
            toast.ok(t("gui_restart_success"));
            banner.hidden = true;
            return true;
          });
        }));
      };
      opsPanel.body.appendChild(btn("btn primary", t("gui_it_restart_monitor"), function () { handles.restart(); }));
      opsPanel.body.appendChild(disclosure(t("gui_gen_explain"),
        note(t("gui_sy_cache_restart_always"))));
      /* The standing "managed externally" note that used to sit here is gone
       * with the acknowledgment-only confirm it belonged to: it is true only
       * when the backend answers 409, and that is exactly when the confirm
       * now says it. Under the standard `--monitor-gui` deployment it was a
       * flat contradiction of the button above it. */

      const retPanel = panel("SY-04", t("gui_retention_now"));
      retPanel.body.appendChild(note(t("gui_it_retention_confirm")));
      /* cacheRetentionNow (integrations.js:437-452) sends no body — the days come
       * from server-side config — and reports only four of the six counters
       * RetentionWorker.run_once returns (retention.py:67-110). Real endpoint:
       * POST /api/cache/retention/run — purges rows for real, so this stays on
       * the destructive-discipline list: the e2e asserts the confirm renders
       * and Cancel dismisses it, never clicks Confirm. */
      handles.retention = function () {
        return modal.confirm(confirmSpec(t("gui_retention_now"), [
          tf("gui_sy_ret_i_events", { n: s.events_retention_days }),
          tf("gui_sy_ret_i_raw", { n: s.traffic_raw_retention_days }),
          tf("gui_sy_ret_i_agg", { n: s.traffic_agg_retention_days }),
          t("gui_sy_ret_i_nobody"),
          t("gui_sy_ret_i_409"),
        ], function () {
          return api.post("/api/cache/retention/run", undefined).then(function (res) {
            if (!res || res.error) {
              toast.crit(errText(res));
              return false;
            }
            toast.ok(t("gui_it_retention_confirm"));
            refreshAndRemount(R_CACHE, CACHE_SNAPS);
            return true;
          });
        }));
      };
      retPanel.body.appendChild(btn("btn danger", t("gui_retention_now"), handles.retention));
      retPanel.body.appendChild(note(t("gui_sy_ret_counters")));
      const row1 = el("div", { class: "brow c2 top" }, opsPanel, retPanel);
      board.appendChild(row1);

      // ── SY-02 the settings form ──────────────────────────────────────
      const cfgPanel = panel("SY-02", t("gui_cache_settings"));
      const enabled = checkField(s.enabled);
      const dbPath = textField(s.db_path);
      const evRet = numberField(s.events_retention_days, 1, null);
      const rawRet = numberField(s.traffic_raw_retention_days, 1, null);
      const aggRet = numberField(s.traffic_agg_retention_days, 1, null);
      const arcOn = checkField(s.archive_enabled);
      const arcDir = textField(s.archive_dir);
      const arcInt = numberField(s.archive_interval_hours, 1, null);
      const arcGzip = numberField(s.archive_gzip_after_days, 1, null);
      const arcRet = numberField(s.archive_retention_days, 0, null);
      const evPoll = numberField(s.events_poll_interval_seconds, 30, null);
      const trPoll = numberField(s.traffic_poll_interval_seconds, 60, null);
      const rate = numberField(s.rate_limit_per_minute, 10, 500);
      const asyncTh = numberField(s.async_threshold_events, 1, 10000);

      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_basic")));
      cfgPanel.body.appendChild(checkRow(t("gui_cache_enabled"), form.track("enabled", enabled, "bool")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_db_path"), form.track("db_path", dbPath), t("gui_cache_db_path_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_retention")));
      cfgPanel.body.appendChild(labelled(t("gui_ov_events"), form.track("events_retention_days", evRet, "number"), t("gui_cache_events_retention_days_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_card_traffic_raw"), form.track("traffic_raw_retention_days", rawRet, "number"), t("gui_cache_traffic_raw_retention_days_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_card_traffic_agg"), form.track("traffic_agg_retention_days", aggRet, "number"), t("gui_cache_traffic_agg_retention_days_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_archive")));
      cfgPanel.body.appendChild(checkRow(t("gui_cache_archive_enabled"), form.track("archive_enabled", arcOn, "bool")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_dir"), form.track("archive_dir", arcDir), t("gui_cache_archive_dir_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_interval_hours"), form.track("archive_interval_hours", arcInt, "number"), t("gui_cache_archive_interval_hours_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_gzip_after_days"), form.track("archive_gzip_after_days", arcGzip, "number"), t("gui_cache_archive_gzip_after_days_help")));
      cfgPanel.body.appendChild(labelled(t("gui_cache_archive_retention_days"), form.track("archive_retention_days", arcRet, "number"), t("gui_cache_archive_retention_days_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_polling")));
      cfgPanel.body.appendChild(labelled(t("gui_sy_cache_ev_poll"), form.track("events_poll_interval_seconds", evPoll, "number"), t("gui_cache_events_poll_interval_seconds_help")));
      cfgPanel.body.appendChild(labelled(t("gui_sy_cache_tr_poll"), form.track("traffic_poll_interval_seconds", trPoll, "number"), t("gui_cache_traffic_poll_interval_seconds_help")));
      cfgPanel.body.appendChild(sectionHead(t("gui_cache_sec_throughput")));
      cfgPanel.body.appendChild(labelled(t("gui_sy_cache_rate"), form.track("rate_limit_per_minute", rate, "number"), t("gui_cache_rate_limit_per_minute_help")));
      cfgPanel.body.appendChild(labelled(t("gui_sy_cache_async"), form.track("async_threshold_events", asyncTh, "number"), t("gui_cache_async_threshold_events_help")));
      /* The note that used to close this section ("these four fields have real
       * labels here, the stored key is still in the <code> column") is deleted
       * rather than collapsed: it described a decision about the interface, not
       * anything an operator can act on. R5 protects explanations that answer a
       * question — not every sentence. */

      // ── SY-05 traffic filter ─────────────────────────────────────────
      const tfPanel = panel("SY-05", t("gui_cache_sec_traffic_filter"));
      const actionBoxes = [];
      const protoBoxes = [];
      const actionRow = el("div", { class: "daychips" });
      TF_ACTIONS.forEach(function (v) {
        const box = checkField((tf0.actions || []).indexOf(v) >= 0);
        box.dataset.field = "traffic_filter.actions";
        box.addEventListener("change", form.sync);
        actionBoxes.push([v, box]);
        actionRow.appendChild(el("label", null, box, el("span", { text: v })));
      });
      const protoRow = el("div", { class: "daychips" });
      TF_PROTOCOLS.forEach(function (v) {
        const box = checkField((tf0.protocols || []).indexOf(v) >= 0);
        box.dataset.field = "traffic_filter.protocols";
        box.addEventListener("change", form.sync);
        protoBoxes.push([v, box]);
        protoRow.appendChild(el("label", null, box, el("span", { text: v })));
      });
      const tfEnv = textField((tf0.workload_label_env || []).join(","));
      const tfPorts = textField((tf0.ports || []).join(","));
      const tfIps = textField((tf0.exclude_src_ips || []).join(","));
      const hintBox = el("p", { class: "note", "data-tone": "crit" });

      tfPanel.body.appendChild(labelled(t("gui_cache_tf_actions"), actionRow));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_protocols"), protoRow));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_workload_env"), form.track("traffic_filter.workload_label_env", tfEnv, "list"), t("gui_cache_workload_label_env_help")));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_ports"), form.track("traffic_filter.ports", tfPorts, "ports"), t("gui_cache_ports_help")));
      tfPanel.body.appendChild(labelled(t("gui_cache_tf_exclude_ips"), form.track("traffic_filter.exclude_src_ips", tfIps, "list"), t("gui_cache_exclude_src_ips_help")));
      tfPanel.body.appendChild(hintBox);
      tfPanel.body.appendChild(note(t("gui_sy_tf_presave")));

      // ── SY-06 sampling ───────────────────────────────────────────────
      const tsPanel = panel("SY-06", t("gui_cache_sec_traffic_sampling"));
      const tsRatio = numberField(ts.sample_ratio_allowed, 1, null);
      const tsMax = numberField(ts.max_rows_per_batch, 1, 200000);
      tsPanel.body.appendChild(labelled(t("gui_cache_ts_ratio"), form.track("traffic_sampling.sample_ratio_allowed", tsRatio, "number"), t("gui_cache_ts_ratio_help")));
      tsPanel.body.appendChild(labelled(t("gui_cache_ts_max_rows"), form.track("traffic_sampling.max_rows_per_batch", tsMax, "number"), t("gui_cache_ts_max_rows_help")));
      tsPanel.body.appendChild(note(t("gui_sy_ts_note")));

      board.appendChild(el("div", { class: "brow c2 top" }, cfgPanel, el("div", { class: "board" }, tfPanel, tsPanel)));

      /* Five keys of PceCacheSettings have no control anywhere in buildCacheForm
       * (integrations.js:182-262). They survive only because cacheSave merges
       * over the cached settings object (:269). Dropping a backend field on the
       * floor is exactly how the previous redesign lost data, so they are listed
       * here with their values and the reason they are read-only. */
      const gapPanel = panel(null, t("gui_sy_cache_nogui"));
      gapPanel.body.appendChild(roList([
        roField("cache_read_max_rows", s.cache_read_max_rows, t("gui_sy_cache_nogui_note")),
        roField("disk_free_warn_gb", s.disk_free_warn_gb, t("gui_sy_cache_nogui_note")),
        roField("flow_delta_enabled", s.flow_delta_enabled, t("gui_sy_cache_nogui_note")),
        roField("flow_obs_retention_hours", s.flow_obs_retention_hours, t("gui_sy_cache_nogui_note")),
        roField("siem_pending_warn_rows", s.siem_pending_warn_rows, t("gui_sy_cache_nogui_note")),
      ]));
      gapPanel.body.appendChild(note(t("gui_sy_cache_nogui_body")));
      board.appendChild(gapPanel);

      /* cacheSave (integrations.js:264-297) starts from the cached settings
       * object and overwrites the controlled keys, so the body always carries
       * every key of the section — including the six above. Real endpoint:
       * PUT /api/cache/settings, validated + saved by save_section (A3: its
       * failure shape is {ok:false, errors:{field:msg}} — errorText() above
       * reads it). */
      form.setBody(function (v) {
        const b = {};
        Object.keys(s).forEach(function (k) { b[k] = s[k]; });
        Object.keys(v).forEach(function (k) { if (k.indexOf(".") < 0) b[k] = v[k]; });
        const filter = {};
        filter.actions = actionBoxes.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
        filter.protocols = protoBoxes.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
        filter.workload_label_env = v["traffic_filter.workload_label_env"];
        filter.ports = v["traffic_filter.ports"];
        filter.exclude_src_ips = v["traffic_filter.exclude_src_ips"];
        b.traffic_filter = filter;
        const sampling = {};
        sampling.sample_ratio_allowed = v["traffic_sampling.sample_ratio_allowed"];
        sampling.max_rows_per_batch = v["traffic_sampling.max_rows_per_batch"];
        b.traffic_sampling = sampling;
        return b;
      });
      form.onSync(function () {
        const hints = trafficFilterHints(tfIps.value, tfPorts.value);
        hintBox.textContent = hints.join(" · ");
        hintBox.hidden = !hints.length;
      });
      form.afterSave = function () { banner.hidden = false; };

      host.appendChild(form.dock);
      form.sync();
    }, CACHE_SOFT);
}

/** Bytes as GiB — the unit disk_free_warn_gb is expressed in. */
function mib(bytes) {
  const n = Number(bytes);
  if (!isFinite(n) || n <= 0) return "—";
  return (n / 1073741824).toFixed(1) + " GiB";
}

function oneHour(v) {
  if (v === null || v === undefined) return null;
  return tf("gui_ov_cache_ingest_1h", { n: num(v) });
}

function kpiCell(k, v, d, tn) {
  const cell = el("div", { class: "kpicell", "data-tone": tn || null });
  cell.appendChild(el("span", { class: "k", text: k }));
  cell.appendChild(el("span", { class: "v", text: v }));
  cell.appendChild(el("span", { class: "d", text: d || "" }));
  return cell;
}

// ══════════════════════════════════════════ SY-07…10  SIEM forwarder ═════════

const SIEM_SNAPS = ["siem_forwarder", "siem_destinations", "siem_status", "siem_dlq"];
/* Header point 16, same split as CACHE_SOFT: siem_forwarder and
 * siem_destinations are the configuration (SY-07/SY-08's form, table and CRUD
 * buttons) and stay strict; siem_status (per-destination counters) and
 * siem_dlq (the queue's own rows) are telemetry read out of the cache DB, so
 * they carry the same 503 as the cache endpoints do. */
const SIEM_SOFT = ["siem_status", "siem_dlq"];

// integrations.js:858 (select#md-transport) / :861 (select#md-format).
const SIEM_TRANSPORTS = [["udp", "udp"], ["tcp", "tcp"], ["tls", "tls"], ["hec", "hec"]];
const SIEM_FORMATS = [["cef", "cef"], ["json", "json"], ["syslog_cef", "syslog_cef"], ["syslog_json", "syslog_json"]];
// integrations.js:817 (_SIEM_DEFAULT_PORTS) — the port is only rewritten when the
// current value is still one of the defaults (:914-922).
const SIEM_PORTS = [["udp", 514], ["tcp", 514], ["tls", 6514], ["hec", 8088]];
const SIEM_SOURCE_TYPES = [["audit", "gui_sy_siem_st_audit"], ["traffic", "gui_sy_siem_st_traffic"]];

function defaultPort(transport) {
  let hit = 514;
  SIEM_PORTS.forEach(function (p) { if (p[0] === transport) hit = p[1]; });
  return hit;
}

/* buildDestModal, integrations.js:819-904. Every field of the modal is here in
 * its order, plus the two keys the modal never shows (`profile`, `mask_pii`,
 * config_models.py:285/302-310) as read-only rows — a create silently accepts
 * their defaults, and that is worth seeing before you press save. Real
 * endpoint: POST /api/siem/destinations (add) or
 * PUT /api/siem/destinations/<name> (edit). */
function destDrawer(dest, isEdit) {
  const body = el("div", { "data-cov": "SY-08" });
  const dst = dest || {};
  const form = makeForm(isEdit ? "PUT" : "POST",
    isEdit ? "/api/siem/destinations/" + encodeURIComponent(dst.name || "") : "/api/siem/destinations");

  const name = textField(dst.name || "");
  if (isEdit) name.readOnly = true;
  const enabled = checkField(dst.enabled === undefined ? true : dst.enabled);
  const transport = selectField(SIEM_TRANSPORTS, dst.transport || "udp", false);
  const format = selectField(SIEM_FORMATS, dst.format || "cef", false);
  const hostField = textField(dst.host || "");
  hostField.placeholder = "192.168.1.10";
  const port = numberField(dst.port === undefined ? 514 : dst.port, 1, 65535);
  const tlsVerify = checkField(dst.tls_verify === undefined ? true : dst.tls_verify);
  const tlsCa = textField(dst.tls_ca_bundle || "");
  tlsCa.placeholder = "/etc/ssl/certs/ca-bundle.crt";
  const hecToken = passwordField(t("gui_sy_secret_keep"));
  const batch = numberField(dst.batch_size === undefined ? 100 : dst.batch_size, 1, 10000);
  const retries = numberField(dst.max_retries === undefined ? 10 : dst.max_retries, 0, null);

  const stBoxes = [];
  const stRow = el("div", { class: "daychips" });
  SIEM_SOURCE_TYPES.forEach(function (pair) {
    const box = checkField((dst.source_types || ["audit", "traffic"]).indexOf(pair[0]) >= 0);
    box.dataset.field = "source_types";
    box.addEventListener("change", form.sync);
    stBoxes.push([pair[0], box]);
    stRow.appendChild(el("label", null, box, el("span", { text: t(pair[1]) })));
  });

  const tlsSection = el("div", null,
    sectionHead(t("gui_siem_sec_tls")),
    checkRow(t("gui_siem_tls_verify"), form.track("tls_verify", tlsVerify, "bool"), t("gui_sy_siem_tls_prod")),
    labelled(t("gui_siem_ca_bundle"), form.track("tls_ca_bundle", tlsCa)));
  const hecSection = el("div", null,
    sectionHead(t("gui_siem_sec_hec")),
    labelled(t("gui_siem_hec_token"), form.track("hec_token", hecToken, "secret"), t("gui_sy_secret_hint")),
    roList([roField("hec_token", secretState(dst, "hec_token"), t("gui_sy_secret_short"))]));

  /* siemToggleCondFields, integrations.js:906-923 — TLS block for tls|hec, HEC
   * block for hec only, and the port default swap. The hidden sections are still
   * SUBMITTED by siemSaveDest (:941-943), which is why they stay in the payload
   * pane instead of disappearing from it. */
  function onTransport() {
    const v = transport.value;
    tlsSection.hidden = !(v === "tls" || v === "hec");
    hecSection.hidden = v !== "hec";
    const cur = Number(port.value);
    if (cur === 514 || cur === 6514 || cur === 8088) port.value = String(defaultPort(v));
    form.sync();
  }
  transport.addEventListener("change", onTransport);

  form.setBody(function (v) {
    const b = {};
    b.name = v.name;
    b.enabled = v.enabled;
    b.transport = v.transport;
    b.format = v.format;
    b.host = String(v.host || "").trim();
    b.port = v.port;
    b.tls_verify = v.tls_verify;
    b.tls_ca_bundle = String(v.tls_ca_bundle || "").trim() || null;
    // A1 fix (header point 4): omit hec_token entirely when the box is empty
    // — the mockup's `v.hec_token || null` sends an explicit null, which
    // update_destination's merge (siem/web.py:88 `{**dests[idx], **stripped}`)
    // would write straight over an existing stored token on every edit that
    // did not retype it.
    if (v.hec_token) b.hec_token = v.hec_token;
    b.batch_size = v.batch_size;
    b.max_retries = v.max_retries;
    b.source_types = stBoxes.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
    if (!b.source_types.length) b.source_types = ["audit", "traffic"];
    return b;
  });

  body.appendChild(note(t("gui_sy_siem_dest_src")));
  body.appendChild(sectionHead(t("gui_siem_sec_basic")));
  body.appendChild(labelled(t("gui_siem_name"), form.track("name", name), isEdit ? t("gui_sy_siem_name_ro") : t("gui_sy_siem_name_new")));
  body.appendChild(checkRow(t("gui_siem_enabled"), form.track("enabled", enabled, "bool")));
  body.appendChild(labelled(t("gui_siem_source_types"), stRow, t("gui_sy_siem_st_fallback")));
  body.appendChild(sectionHead(t("gui_siem_sec_transport")));
  body.appendChild(labelled(t("gui_siem_transport"), form.track("transport", transport), t("gui_siem_transport_help")));
  body.appendChild(labelled(t("gui_siem_format"), form.track("format", format), t("gui_siem_format_help")));
  body.appendChild(labelled(t("gui_siem_host"), form.track("host", hostField)));
  body.appendChild(labelled(t("gui_siem_port"), form.track("port", port, "number"), t("gui_sy_siem_port_auto")));
  body.appendChild(tlsSection);
  body.appendChild(hecSection);
  body.appendChild(sectionHead(t("gui_siem_sec_advanced")));
  body.appendChild(labelled(t("gui_siem_batch_size"), form.track("batch_size", batch, "number")));
  body.appendChild(labelled(t("gui_siem_max_retries"), form.track("max_retries", retries, "number")));
  body.appendChild(note(t("gui_sy_secret_note")));
  body.appendChild(sectionHead(t("gui_sy_siem_nomodal")));
  body.appendChild(roList([
    roField("profile", dst.profile, t("gui_sy_siem_profile_note")),
    roField("mask_pii", dst.mask_pii, t("gui_sy_siem_maskpii_note")),
  ]));
  body.appendChild(el("div", { class: "typechips" },
    btn("btn", t("gui_siem_test_inline"), function () {
      if (!isEdit) { toast.info(t("gui_sy_siem_test_saved")); return; }
      testDestination(dst.name);
    })));
  body.appendChild(note(t("gui_sy_siem_test_saved")));

  onTransport();
  form.sync();
  return drawerSpec(t(isEdit ? "gui_siem_modal_title_edit" : "gui_siem_modal_title_add"), body, function () {
    return form.save().then(function (ok) {
      if (ok) refreshAndRemount(R_SIEM, SIEM_SNAPS);
      return ok;
    });
  });
}

/* SY-09 — the product's test posts to the SAVED destination
 * (integrations.js:976-990); real endpoint POST
 * /api/siem/destinations/<name>/test. Not wrapped in modal.confirm (matches
 * both the legacy product and alerting.mjs's own test-alert precedent — a
 * live network probe, not a config mutation) and never clicked by the e2e
 * (it dials the destination's real host:port). */
function testDestination(name) {
  return api.post("/api/siem/destinations/" + encodeURIComponent(name) + "/test", undefined).then(function (res) {
    if (res && res.ok) toast.ok(tf("gui_sy_siem_test_result_ok", { name: name, ms: res.latency_ms }));
    else toast.crit(tf("gui_sy_siem_test_result_fail", { name: name, error: (res && res.error) || t("gui_err_generic") }));
  });
}

/** _siemStatusBadge, integrations.js:665-676 — disabled beats failed beats ok. */
function destTone(dest, st) {
  if (!dest.enabled) return "warn";
  if (Number((st && st.failed) || 0) > 0) return "crit";
  return "ok";
}

function destStatusText(dest, st) {
  if (!dest.enabled) return t("gui_siem_status_disabled");
  if (Number((st && st.failed) || 0) > 0) return t("gui_siem_status_error");
  return t("gui_siem_status_healthy");
}

/* The DLQ detail view (dlqView, integrations.js:1290-1376). The list endpoint
 * (siem/web.py:227-255) does not carry `payload` — only a preview — so a real
 * per-row "view" fetches the real single-item detail, GET
 * /api/siem/dlq/<id> (siem/web.py:258-286), which rebuilds the payload from
 * the source table when it still exists. `entry` here is the summary row
 * from the list; `entry.id` is what the detail fetch needs. */
function dlqDrawer(entry) {
  const body = el("div", { "data-cov": "SY-10" });
  if (!entry) {
    body.appendChild(el("div", { class: "empty" },
      el("span", { class: "et", text: t("gui_it_dlq_empty_title") }),
      el("p", { text: t("gui_it_dlq_empty_body") })));
    body.appendChild(sectionHead(t("gui_sy_dlq_fields")));
    body.appendChild(roList([
      roField("destination", null, t("gui_sy_dlq_f_dest")),
      roField("source_id", null, t("gui_sy_dlq_f_id")),
      roField("quarantined_at", null, t("gui_sy_dlq_f_at")),
      roField("retries", null, t("gui_sy_dlq_f_retries")),
      roField("last_error", null, t("gui_sy_dlq_f_err")),
      roField("payload", null, t("gui_sy_dlq_f_payload")),
      roField("payload_source", null, t("gui_sy_dlq_f_src")),
    ]));
    body.appendChild(note(t("gui_sy_dlq_src_dropped")));
    return drawerSpec(t("gui_dlq_modal_title"), body);
  }
  body.appendChild(el("p", { class: "note", text: t("gui_app_loading") }));
  api.get("/api/siem/dlq/" + encodeURIComponent(entry.id)).then(function (full) {
    clear(body);
    body.appendChild(kvRow(t("gui_dlq_dt_destination"), full.destination || full.source_table));
    body.appendChild(kvRow(t("gui_dlq_dt_event_id"), full.source_id));
    body.appendChild(kvRow(t("gui_dlq_dt_failed_at"), full.quarantined_at));
    body.appendChild(kvRow(t("gui_dlq_dt_retries"), full.retries));
    body.appendChild(sectionHead(t("gui_dlq_dt_reason")));
    body.appendChild(el("pre", { class: "codepane", text: String(full.last_error || "—") }));
    body.appendChild(sectionHead(t("gui_dlq_dt_payload")));
    body.appendChild(el("pre", { class: "codepane tall", text: JSON.stringify(full.payload || null, null, 2) }));
    body.appendChild(note(tf("gui_sy_dlq_payload_source", { source: full.payload_source || "—" })));
  }).catch(function (e) {
    clear(body);
    body.appendChild(note(errText(e && e.data ? e.data : e)));
  });
  return drawerSpec(t("gui_dlq_modal_title"), body);
}

async function mountSiem(root, ctx) {
  const handles = {};
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  drawer.registerAudit("sy-siem-dest", function () { return handles.editDest ? handles.editDest() : null; });
  drawer.registerAudit("sy-siem-dlq", function () { return drawer.open(dlqDrawer(null)); });
  modal.registerAudit("sy-siem-purge", function () { return handles.purge ? handles.purge() : null; });
  palette.registerFor(R_SIEM, cmdSpec("sy:siem-add", t("gui_siem_add"), function () { drawer.open(destDrawer(null, false)); }));

  await sysPage(root, ctx, R_SIEM, SIEM_SNAPS,
    function (board, d, host) {
      const fw = d.siem_forwarder || {};
      const dests = (d.siem_destinations && d.siem_destinations.destinations) || [];
      /* byName is refilled in place by applyStatuses() so the destination
       * table's own status cell (rendered once, below) reads whatever the
       * latest successful siem_status load produced — including after the
       * telemetry strip's retry. statusUnknown() is what stops a failed load
       * from being read as "no failures recorded, therefore healthy". */
      const byName = {};
      function statusUnknown() { return !!(d.siem_status && d.siem_status._error); }
      function applyStatuses() {
        Object.keys(byName).forEach(function (k) { delete byName[k]; });
        const list = statusUnknown() ? [] : ((d.siem_status && d.siem_status.status) || []);
        list.forEach(function (s) { byName[s.destination] = s; });
        return list;
      }
      const form = makeForm("PUT", "/api/siem/forwarder");

      // KPI strip — integrations.js:607-652. Telemetry (SIEM_SOFT): repainted
      // in place by its own retry, exactly like #/system/cache's SY-17.
      const kpis = el("div", { class: "kpirow sy-siem-telemetry" });
      function paintKpis() {
        clear(kpis);
        const statuses = applyStatuses();
        if (statusUnknown()) {
          kpis.dataset.tone = "crit";
          kpis.appendChild(note(softErrorText(d, ["siem_status"])));
          kpis.appendChild(btn("btn primary", t("gui_errcard_retry"), function () {
            return reloadSoft(["siem_status"]).then(function (fresh) {
              if (state.torn) return;
              d.siem_status = fresh.siem_status;
              paintKpis();
              applyStatuses();
              state.tableHandles.dests = table.render(destHost, buildTable(columns, dests));
            });
          }));
          return;
        }
        kpis.dataset.tone = null;
        let sent = 0;
        let dlq = 0;
        let sent1h = 0;
        let failed1h = 0;
        let latencyNum = 0;
        let latencyDen = 0;
        statuses.forEach(function (s) {
          sent += Number(s.sent || 0);
          dlq += Number(s.dlq || 0);
          sent1h += Number(s.sent_1h || 0);
          failed1h += Number(s.failed_1h || 0);
          latencyNum += Number(s.avg_latency_ms || 0) * Number(s.sent_1h || 0);
          latencyDen += Number(s.sent_1h || 0);
        });
        const rate1h = sent1h + failed1h > 0 ? (sent1h / (sent1h + failed1h) * 100).toFixed(1) + "%" : "—";
        const avgMs = latencyDen > 0 ? Math.round(latencyNum / latencyDen) : null;
        kpis.appendChild(kpiCell(t("gui_sy_siem_sent"), num(sent), null, null));
        kpis.appendChild(kpiCell(t("gui_ov_siem_success_1h"), rate1h, null, failed1h > 0 ? "crit" : "ok"));
        kpis.appendChild(kpiCell(t("gui_ov_dlq_total"), num(dlq), null, dlq > 0 ? "warn" : null));
        kpis.appendChild(kpiCell(t("gui_ov_siem_latency"), avgMs === null ? "—" : (avgMs < 1000 ? avgMs + "ms" : (avgMs / 1000).toFixed(1) + "s"), null, null));
      }
      paintKpis();
      board.appendChild(kpis);

      // ── SY-07 forwarder ──────────────────────────────────────────────
      const fwPanel = panel("SY-07", t("gui_siem_forwarder"));
      const fwOn = checkField(fw.enabled);
      const tick = numberField(fw.dispatch_tick_seconds, 1, null);
      const dlqMax = numberField(fw.dlq_max_per_dest, 100, null);
      fwPanel.body.appendChild(checkRow(t("gui_siem_enabled"), form.track("enabled", fwOn, "bool")));
      fwPanel.body.appendChild(labelled(t("gui_siem_dispatch_tick"), form.track("dispatch_tick_seconds", tick, "number"), t("gui_siem_dispatch_tick_help")));
      fwPanel.body.appendChild(labelled(t("gui_siem_dlq_max"), form.track("dlq_max_per_dest", dlqMax, "number"), t("gui_siem_dlq_max_help")));
      // R4: gui_sy_siem_fw_src just restated the raw PUT /api/siem/forwarder
      // body as prose — the payload panel at the foot of this page already
      // shows the real outgoing request, so this was a second, decorative
      // copy of the same technical detail. Dropped rather than collapsed:
      // there is nothing here an operator needs that the payload panel does
      // not already give them on demand.
      form.setBody(function (v) {
        const b = {};
        b.enabled = v.enabled;
        b.dispatch_tick_seconds = v.dispatch_tick_seconds;
        b.dlq_max_per_dest = v.dlq_max_per_dest;
        return b;
      });

      // ── SY-08 / SY-09 destinations ───────────────────────────────────
      const destPanel = panel("SY-08", t("gui_siem_destinations"));
      withMeta(destPanel, tf("gui_sy_siem_dest_meta", { n: dests.length }));
      destPanel.head.appendChild(btn("btn", t("gui_siem_add"), function () { drawer.open(destDrawer(null, false)); }));
      handles.editDest = function () { return drawer.open(destDrawer(dests[0] || null, dests.length > 0)); };
      const destHost = el("div");
      destPanel.body.appendChild(destHost);
      const columns = [
        col("name", t("gui_siem_th_name"), buildCell(function (p) {
          return el("span", { class: "idc" }, el("b", { text: p.name }),
            el("small", { text: p.enabled ? t("gui_enabled") : t("gui_disabled") }));
        })),
        col("transport", t("gui_siem_th_transport"), widthCell(120, function (p) {
          const box = el("span", { class: "chips" }, el("span", null, el("b", { text: p.transport })));
          // integrations.js:736-737 — UDP has no ACK, so DLQ confirmation cannot exist.
          if (/udp/i.test(String(p.transport))) box.appendChild(el("span", { class: "off", title: t("gui_sy_siem_noack_help"), text: t("gui_sy_siem_noack") }));
          return box;
        })),
        col("format", t("gui_siem_th_format"), widthCell(110, function (p) { return el("code", { class: "mono", text: p.format }); })),
        col("host", t("gui_siem_th_host"), widthCell(160)),
        col("port", t("gui_siem_th_port"), widthCell(70)),
        col("status", t("gui_siem_th_status"), widthCell(120, function (p) {
          // An unavailable siem_status is NOT "no failures recorded": with no
          // counters, destTone()'s `failed > 0` test is unanswerable, so the
          // cell says unknown rather than reporting a healthy destination the
          // page has heard nothing about.
          if (statusUnknown()) return badge(t("gui_card_unknown"), "neutral");
          return badge(destStatusText(p, byName[p.name]), destTone(p, byName[p.name]));
        })),
        col("act", t("gui_siem_th_actions"), widthCell(200, function (p) {
          const box = el("div", { class: "rowacts" });
          box.appendChild(btn("btn ghost", t("gui_siem_test"), function () { testDestination(p.name); }));
          box.appendChild(btn("btn ghost", t("gui_siem_edit"), function () { drawer.open(destDrawer(p, true)); }));
          box.appendChild(btn("btn danger", t("gui_siem_delete"), function () {
            modal.confirm(confirmSpec(t("gui_confirm_delete"),
              [tf("gui_sy_siem_i_del", { name: p.name }), t("gui_sy_siem_i_dlq")], function () {
                return api.del("/api/siem/destinations/" + encodeURIComponent(p.name)).then(function (res) {
                  if (!res || res.ok !== true) {
                    toast.crit(errorText(res));
                    return false;
                  }
                  toast.ok(tf("gui_deleted_ok", { filename: p.name }));
                  refreshAndRemount(R_SIEM, SIEM_SNAPS);
                  return true;
                });
              }));
          }));
          return box;
        })),
      ];
      state.tableHandles.dests = table.render(destHost, buildTable(columns, dests));
      /* R4 — this panel used to lay the raw test endpoint and its response
       * field names (ok/latency_ms/error) flat on the page: a developer-mode
       * reference, not something an operator reads to decide anything. Each
       * per-destination "Test" button (SY-08's row actions) already toasts a
       * localised result built from those exact fields, so the panel now
       * states what a test click does in one line and folds the field-by-
       * field breakdown into the explanation for whoever wants to verify a
       * toast against the raw response shape. */
      const testPanel = panel("SY-09", t("gui_siem_test"));
      testPanel.body.appendChild(note(t("gui_sy_siem_test_body")));
      testPanel.body.appendChild(note(t("gui_sy_siem_test_saved")));

      board.appendChild(el("div", { class: "brow c2" }, fwPanel, testPanel));
      board.appendChild(destPanel);

      // ── SY-10 DLQ ────────────────────────────────────────────────────
      const dlqPanel = panel("SY-10", t("gui_sy_dlq_title"));
      const destPairs = [["", t("gui_dlq_filter_all")]].concat(dests.map(function (p) { return [p.name, p.name]; }));
      const destSel = selectField(destPairs, "", false);
      const reason = el("input", { class: "field", placeholder: t("gui_dlq_filter_reason") });
      const dlqHost = el("div");
      /* The ids the operator has ticked. "Purge Selected" used to be a lie:
       * the table had no selection column at all and the button posted
       * {dest, older_than_days: 0}, purging the WHOLE destination. Selection
       * is cleared on every repaint and on every destination change, so the
       * set can never carry an id the operator can no longer see. */
      const dlqSel = new Set();
      /** Rebuilt per render: the header checkbox has to own the boxes of the
       *  page it is actually heading, not of every page rendered so far. */
      function dlqColumns() {
        const pageBoxes = [];
        return [
        col("pick", "", pickCell(
          function () {
            const all = el("input", { type: "checkbox" });
            all.setAttribute("aria-label", t("gui_selected"));
            all.addEventListener("change", function () {
              pageBoxes.forEach(function (entry) {
                entry.cb.checked = all.checked;
                if (all.checked) dlqSel.add(entry.id);
                else dlqSel.delete(entry.id);
              });
              syncPurge();
            });
            return all;
          },
          function (e) {
            const cb = el("input", { type: "checkbox" });
            cb.setAttribute("aria-label", t("gui_selected"));
            cb.checked = dlqSel.has(e.id);
            cb.addEventListener("change", function () {
              if (cb.checked) dlqSel.add(e.id);
              else dlqSel.delete(e.id);
              syncPurge();
            });
            pageBoxes.push({ id: e.id, cb: cb });
            return cb;
          }
        )),
        col("destination", t("gui_dlq_th_dest"), widthCell(140)),
        col("source_id", t("gui_dlq_th_event_id"), widthCell(160)),
        col("last_error", t("gui_dlq_th_reason")),
        col("quarantined_at", t("gui_dlq_th_failed_at"), widthCell(150)),
        col("retries", t("gui_dlq_th_retries"), widthCell(70)),
        col("act", "", widthCell(150, function (e) {
          const box = el("div", { class: "rowacts" });
          box.appendChild(btn("btn ghost", t("gui_dlq_view"), function () { drawer.open(dlqDrawer(e)); }));
          /* A3, with the twist this endpoint carries: replay_dlq
           * (src/siem/web.py:289-306) answers {status:"ok", requeued:N} on
           * success — no `ok` field at all — and only _err_with_log's
           * {ok:false, error, description} on failure. So `error` is the field
           * that separates them; `res.ok !== true` would call every success a
           * failure. Same shape as SY-04 retention's check above. */
          box.appendChild(btn("btn ghost", t("gui_dlq_replay"), function () {
            api.post("/api/siem/dlq/replay", { ids: [e.id] }).then(function (res) {
              if (!res || res.error) {
                toast.crit(errText(res));
                return;
              }
              /* The `ids` branch answers `requeued` as replay_ids' per-item
               * result LIST (src/siem/dlq.py:52-74), not a count — and an id
               * that is already gone comes back {ok:false, error:"not found"}
               * inside an HTTP 200, which no top-level check can see. Count
               * what really requeued; let a per-item failure speak. (The
               * dest/limit branch of the same route does answer a plain
               * count, hence the shape check rather than an assumption.) */
              const items = Array.isArray(res.requeued) ? res.requeued : null;
              const failed = items ? items.filter(function (r) { return r && r.ok === false; }) : [];
              if (failed.length) {
                toast.crit(errText(failed[0]));
                paintDlq();
                return;
              }
              toast.ok(tf("gui_sy_dlq_replayed", { n: num(items ? items.length : res.requeued) }));
              paintDlq();
            });
          }));
          return box;
        })),
        ];
      }
      /** Real GET /api/siem/dlq?dest=&limit= — a dynamic query on an id
       *  GET_MAP only carries with its default params, so this calls api.get()
       *  directly per store-map.mjs's own documented escape hatch. `reason` is
       *  filtered client-side over the fetched page — matches
       *  gui_sy_dlq_reason_client's documented real behaviour. */
      function paintDlq() {
        const q = "dest=" + encodeURIComponent(destSel.value) + "&limit=50";
        // A repaint replaces the rows, so any earlier tick refers to a row
        // the operator is no longer looking at — start the new page empty.
        dlqSel.clear();
        syncPurge();
        return api.get("/api/siem/dlq?" + q).then(function (res) {
          if (state.torn) return;
          let entries = (res && res.entries) || [];
          const needle = reason.value.toLowerCase().trim();
          if (needle) entries = entries.filter(function (e) { return String(e.last_error || "").toLowerCase().indexOf(needle) >= 0; });
          state.tableHandles.dlq = table.render(dlqHost, buildTable(dlqColumns(), entries));
        }).catch(function (e) {
          // Same source as the soft-loaded siem_dlq snapshot, same treatment:
          // this is the DLQ's own live query, so its failure states itself
          // here instead of rejecting into nothing.
          if (state.torn) return;
          paintDlqError(errText(e && e.data ? e.data : e));
        });
      }

      /** The DLQ table area, replaced by the real error and a real retry. */
      function paintDlqError(message) {
        clear(dlqHost);
        dlqHost.appendChild(note(message));
        dlqHost.appendChild(btn("btn primary", t("gui_errcard_retry"), function () { paintDlq(); }));
      }
      /* Changing the destination repaints instead of leaving the previous
       * destination's rows on screen: the purge confirm names the selected
       * destination, so the filter and the rows under it have to agree. */
      destSel.addEventListener("change", function () { paintDlq(); });
      dlqPanel.body.appendChild(el("div", { class: "qrow" },
        el("div", { class: "qf" }, el("label", { text: t("gui_dlq_filter_dest") }), destSel),
        el("div", { class: "qf grow" }, el("label", { text: t("gui_dlq_filter_reason") }), reason),
        el("div", { class: "qf" }, el("label", { text: " " }), btn("btn", t("gui_dlq_search"), function () { paintDlq(); }))));
      dlqPanel.body.appendChild(dlqHost);
      if (d.siem_dlq && d.siem_dlq._error) paintDlqError(d.siem_dlq._error);
      else state.tableHandles.dlq = table.render(dlqHost, buildTable(dlqColumns(), (d.siem_dlq && d.siem_dlq.entries) || []));
      /* Purge is now what its label always claimed: the ticked entries, by id,
       * and nothing else. It used to post {dest, older_than_days: 0} with no
       * ids at all — the whole destination — and with "All" selected that
       * body purged destination "" instead, i.e. nothing, so the operator was
       * told "0 entries removed" whatever the queue held.
       *
       * "All" stays unavailable for purging on purpose (Task 12 Step 1): a
       * purge cannot be undone, so it is issued against one named destination
       * the operator has actually chosen, never against a mixed view. The
       * guard lives here rather than only on the button because
       * modal.registerAudit calls this handler directly. */
      function syncPurge() {
        const why = !destSel.value ? t("gui_sy_dlq_purge_pick_dest")
          : (!dlqSel.size ? t("gui_sy_dlq_purge_pick_rows") : "");
        purgeBtn.disabled = !!why;
        purgeBtn.title = why || t("gui_dlq_purge_selected");
      }
      handles.purge = function () {
        if (!destSel.value) { toast.warn(t("gui_sy_dlq_purge_pick_dest")); return null; }
        if (!dlqSel.size) { toast.warn(t("gui_sy_dlq_purge_pick_rows")); return null; }
        const ids = Array.from(dlqSel);
        return modal.confirm(confirmSpec(t("gui_dlq_purge_selected"), [
          tf("gui_sy_dlq_i_all", { n: num(ids.length), dest: destSel.value }),
          t("gui_sy_dlq_i_body"),
          t("gui_sy_dlq_i_norecover"),
        ], function () {
          return api.post("/api/siem/dlq/purge", { ids: ids }).then(function (res) {
            /* Same A3 twist as replay above: purge_dlq (src/siem/web.py)
             * answers {status:"ok", removed:...} on success — no `ok` field —
             * and {ok:false, error, description} on failure. Returning false
             * keeps the confirm open so the operator sees the failure next to
             * the control that caused it (SY-04 retention's shape). */
            if (!res || res.error) {
              toast.crit(errText(res));
              return false;
            }
            /* And the same polymorphism the replay handler documents: the ids
             * branch answers `removed` as purge_ids' per-item result LIST
             * (src/siem/dlq.py), while the dest branch answers a plain count.
             * An id another operator already purged comes back
             * {ok:false, error:"not found"} inside an HTTP 200. */
            const items = Array.isArray(res.removed) ? res.removed : null;
            const failed = items ? items.filter(function (r) { return r && r.ok === false; }) : [];
            if (failed.length) {
              toast.crit(errText(failed[0]));
              paintDlq();
              return false;
            }
            toast.ok(tf("gui_sy_dlq_purged", { n: num(items ? items.length : res.removed) }));
            paintDlq();
            return true;
          });
        }));
      };
      const purgeBtn = btn("btn", t("gui_dlq_purge_selected"), handles.purge);
      syncPurge();
      dlqPanel.body.appendChild(el("div", { class: "typechips" },
        purgeBtn,
        el("a", { class: "btn ghost", href: "/api/siem/dlq/export?dest=" + encodeURIComponent(destSel.value), text: t("gui_dlq_export") })));
      dlqPanel.body.appendChild(note(t("gui_sy_dlq_paging")));
      dlqPanel.body.appendChild(note(t("gui_sy_dlq_reason_client")));
      board.appendChild(dlqPanel);

      host.appendChild(form.dock);
      form.sync();
    }, SIEM_SOFT);
}

// ══════════════════════════════════════════════════════ SY-11  TLS ═══════════

const TLS_SNAPS = ["tls_status"];
const CSR_ALGS = [["rsa-2048", "RSA-2048"], ["ecdsa-p256", "ECDSA P-256"]];

/** humanizeDays, settings.js:114-127 — months under 60 days, years above. */
function humanizeDays(n) {
  const days = Number(n);
  if (!isFinite(days) || days < 0) return "";
  if (days < 60) {
    const months = Math.max(1, Math.round(days / 30));
    return tf("gui_tls_days_humanized", { n: days, label: tf("gui_tls_days_label_months", { m: months }) });
  }
  const years = Math.floor(days / 365);
  const months = Math.round((days % 365) / 30);
  const label = years >= 1 ? tf("gui_tls_days_label_years", { y: years, m: months }) : tf("gui_tls_days_label_months", { m: months });
  return tf("gui_tls_days_humanized", { n: days, label: label });
}

async function mountTls(root, ctx) {
  const handles = {};
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  modal.registerAudit("sy-tls-renew", function () { return handles.renew ? handles.renew() : null; });
  // No audit opener for the import confirm: it only opens once the PEM box
  // has text (handles.importConfirm's own guard), which a cold audit sweep
  // never provides, and SY-11's anchor is already visible on the static
  // status panel without it.
  palette.registerFor(R_TLS, cmdSpec("sy:tls-renew", t("gui_tls_renew"), function () { if (handles.renew) handles.renew(); }));

  await sysPage(root, ctx, R_TLS, TLS_SNAPS, function (board, d, host) {
    const s = d.tls_status || {};
    const info = s.cert_info || {};
    const form = makeForm("POST", "/api/tls/config");

    // ── status card (settings.js:558-591) ────────────────────────────
    const statPanel = panel("SY-11", t("gui_tls_cert_info"));
    const tn = info.expired ? "crit" : (info.expiring_soon ? "warn" : "ok");
    statPanel.dataset.tone = tn;
    if (!info.exists) {
      statPanel.body.appendChild(el("div", { class: "empty" }, el("span", { class: "et", text: t("gui_tls_no_cert") })));
    } else {
      statPanel.body.appendChild(el("div", { class: "lead" },
        el("span", { class: "n", text: String(s.days_remaining === undefined ? "—" : s.days_remaining) }),
        el("span", { class: "u", text: t("gui_tls_days_remaining") }),
        badge(info.expired ? t("gui_tls_expired") : (info.expiring_soon ? t("gui_tls_expiring_soon") : t("gui_enabled")), tn)));
      statPanel.body.appendChild(note(humanizeDays(s.days_remaining)));
      statPanel.body.appendChild(kvRow(t("gui_sy_tls_subject"), info.subject));
      statPanel.body.appendChild(kvRow(t("gui_tls_valid_from"), info.not_before));
      statPanel.body.appendChild(kvRow(t("gui_tls_valid_until"), info.not_after));
      statPanel.body.appendChild(kvRow(t("gui_sy_tls_path"), info.path));
      statPanel.body.appendChild(kvRow(t("gui_tls_self_signed"), String(!!s.self_signed)));
      statPanel.body.appendChild(kvRow(t("gui_sy_tls_validity"), s.default_validity_days));
    }
    /* renewTlsCert (settings.js:593-607) is offered only for a self-signed cert;
     * config.py:339-340 rejects the call for a CA-signed one. Real endpoint:
     * POST /api/tls/renew — overwrites the serving cert in place with no
     * backup. Genuinely destructive per this task's own brief: the e2e never
     * clicks past this confirm. */
    handles.renew = function () {
      return modal.confirm(confirmSpec(t("gui_tls_renew"), [
        t("gui_tls_renew_confirm"),
        t("gui_sy_tls_i_restart"),
        t("gui_sy_tls_i_selfonly"),
        t("gui_sy_tls_i_rate"),
      ], function () {
        return api.post("/api/tls/renew", undefined).then(function (res) {
          if (!res || res.ok !== true) {
            toast.crit(errorText(res));
            return false;
          }
          toast.ok(res.message || t("gui_msg_cert_renewed_restart"));
          refreshAndRemount(R_TLS, TLS_SNAPS);
          return true;
        });
      }));
    };
    if (s.self_signed) statPanel.body.appendChild(btn("btn primary", t("gui_tls_renew"), handles.renew));
    else statPanel.body.appendChild(note(t("gui_sy_tls_no_renew")));
    /* Density spec R5 — this is the page's status card (SY-11, read at a
     * glance for expiry), same shape as #/system/cache's SY-17: the one
     * caveat about the subject string not being reliably formatted is worth
     * keeping but not worth sitting permanently under the status card. */
    statPanel.body.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_sy_tls_subject_literal"))));
    board.appendChild(statPanel);

    // ── TLS config form ──────────────────────────────────────────────
    const cfgPanel = panel(null, t("gui_tls_title"));
    const enabled = checkField(s.enabled);
    const selfSigned = checkField(s.self_signed);
    const certFile = textField(s.cert_file);
    certFile.placeholder = "/path/to/cert.pem";
    const keyFile = textField(s.key_file);
    keyFile.placeholder = "/path/to/key.pem";
    const autoRenew = checkField(s.auto_renew !== false);
    const autoDays = numberField(s.auto_renew_days === undefined ? 30 : s.auto_renew_days, 1, 365);

    const customBox = el("div", null,
      labelled(t("gui_tls_cert_file"), form.track("cert_file", certFile), t("gui_tls_cert_file_help")),
      labelled(t("gui_tls_key_file"), form.track("key_file", keyFile), t("gui_tls_key_file_help")));
    const renewBox = el("div", null,
      checkRow(t("gui_tls_auto_renew"), form.track("auto_renew", autoRenew, "bool")),
      labelled(t("gui_tls_auto_renew_days"), form.track("auto_renew_days", autoDays, "number"), t("gui_tls_auto_renew_hint")));

    // toggleTlsMode settings.js:548-556 — custom paths for a CA cert, auto-renew
    // for a self-signed one; never both.
    function onMode() {
      customBox.hidden = !!selfSigned.checked;
      renewBox.hidden = !selfSigned.checked;
    }
    selfSigned.addEventListener("change", onMode);

    cfgPanel.body.appendChild(checkRow(t("gui_tls_enable"), form.track("enabled", enabled, "bool")));
    cfgPanel.body.appendChild(checkRow(t("gui_tls_self_signed"), form.track("self_signed", selfSigned, "bool")));
    cfgPanel.body.appendChild(customBox);
    cfgPanel.body.appendChild(renewBox);
    cfgPanel.body.appendChild(note(t("gui_tls_saved_restart_hint")));
    onMode();

    form.setBody(function (v) {
      const b = {};
      b.enabled = v.enabled;
      b.self_signed = v.self_signed;
      b.cert_file = v.cert_file;
      b.key_file = v.key_file;
      b.auto_renew = v.auto_renew;
      b.auto_renew_days = v.auto_renew_days;
      return b;
    });
    form.afterSave = function () { refreshAndRemount(R_TLS, TLS_SNAPS); };

    // ── CSR (settings.js:483-512, generateCsr :609-632) ──────────────
    // Real and NON-destructive (header point 10): POST /api/tls/generate-csr
    // writes a CSR+key file and returns PEM; it never touches the serving
    // cert, so this stays outside the destructive-discipline list — the e2e
    // exercises it for real.
    const csrPanel = panel(null, t("gui_tls_csr_title"));
    csrPanel.body.appendChild(note(t("gui_tls_csr_hint")));
    const cn = textField("");
    cn.placeholder = "pce.example.com";
    const org = textField("");
    org.placeholder = "Example Corp";
    const country = textField("");
    country.maxLength = 2;
    const sanDns = textField("");
    sanDns.placeholder = "pce.example.com, pce2.example.com";
    const sanIp = textField("");
    sanIp.placeholder = "192.168.1.10, 10.0.0.5";
    const alg = selectField(CSR_ALGS, "rsa-2048", false);
    const csrOut = el("pre", { class: "codepane" });
    function paintCsr() {
      const b = {};
      b.cn = cn.value;
      b.o = org.value;
      b.c = country.value;
      b.san_dns = sanDns.value;
      b.san_ip = sanIp.value;
      b.key_algorithm = alg.value;
      csrOut.textContent = "POST /api/tls/generate-csr\n" + JSON.stringify(b, null, 2);
    }
    [cn, org, country, sanDns, sanIp, alg].forEach(function (c) {
      c.addEventListener("input", paintCsr);
      c.addEventListener("change", paintCsr);
    });
    cn.dataset.field = "cn";
    org.dataset.field = "o";
    country.dataset.field = "c";
    sanDns.dataset.field = "san_dns";
    sanIp.dataset.field = "san_ip";
    alg.dataset.field = "key_algorithm";
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_cn"), cn, t("gui_sy_tls_cn_required")));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_o"), org));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_c"), country));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_san_dns"), sanDns));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_san_ip"), sanIp));
    csrPanel.body.appendChild(labelled(t("gui_tls_csr_key_alg"), alg));
    csrPanel.body.appendChild(el("div", { class: "typechips" },
      btn("btn primary", t("gui_tls_csr_generate"), function () {
        if (!cn.value.trim()) {
          toast.crit(t("gui_tls_csr_cn_required"));
          return;
        }
        api.post("/api/tls/generate-csr", {
          cn: cn.value.trim(), o: org.value, ou: "", c: country.value,
          san_dns: sanDns.value, san_ip: sanIp.value, key_algorithm: alg.value,
        }).then(function (res) {
          if (!res || res.ok !== true) {
            toast.crit(errorText(res));
            return;
          }
          csrOut.textContent = res.csr_pem || "";
          toast.ok(t("gui_tls_csr_title"));
        });
      })));
    csrPanel.body.appendChild(el("div", { class: "fld" },
      el("label", null, el("span", { text: t("gui_tls_csr_pem_label") })), csrOut));
    // config.py:373 accepts an `ou` field that no input in the product produces.
    csrPanel.body.appendChild(roList([roField("ou", null, t("gui_sy_tls_ou_note"))]));
    paintCsr();

    // ── import (settings.js:513-520, importSignedCert :652-671) ──────
    // Real endpoint POST /api/tls/import-cert overwrites the serving cert's
    // config — wrapped in a NEW modal.confirm the mockup's bare button did
    // not have (header point 9). Genuinely destructive: the e2e never clicks
    // past the confirm.
    const impPanel = panel(null, t("gui_tls_import_title"));
    impPanel.body.appendChild(note(t("gui_tls_import_hint")));
    const pem = el("textarea", { class: "field ta", rows: "6", placeholder: "-----BEGIN CERTIFICATE-----" });
    pem.dataset.field = "cert_pem";
    impPanel.body.appendChild(pem);
    handles.importConfirm = function () {
      if (!pem.value.trim()) {
        toast.crit(t("gui_tls_import_pem_required"));
        return null;
      }
      return modal.confirm(confirmSpec(t("gui_tls_import_btn"), [
        t("gui_tls_import_hint"),
        t("gui_tls_saved_restart_hint"),
      ], function () {
        return api.post("/api/tls/import-cert", { cert_pem: pem.value }).then(function (res) {
          if (!res || res.ok !== true) {
            toast.crit(errorText(res));
            return false;
          }
          toast.ok(res.message || t("gui_tls_saved_restart_hint"));
          refreshAndRemount(R_TLS, TLS_SNAPS);
          return true;
        });
      }));
    };
    impPanel.body.appendChild(btn("btn primary", t("gui_tls_import_btn"), handles.importConfirm));
    impPanel.body.appendChild(note(t("gui_sy_tls_import_paste")));

    board.appendChild(el("div", { class: "brow c2 top" }, cfgPanel, el("div", { class: "board" }, csrPanel, impPanel)));
    host.appendChild(form.dock);
    form.sync();
  });
}

// ═══════════════════════════════════════════ SY-12 / SY-16  security ═════════

const SECURITY_SNAPS = ["security", "status"];
// Header point 16 (see PCE_SOFT): `status` is telemetry this mount does not read.
const SECURITY_SOFT = ["status"];

async function mountSecurity(root, ctx) {
  const handles = {};
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  modal.registerAudit("sy-stop-gui", function () { return handles.stop ? handles.stop() : null; });
  palette.registerFor(R_SECURITY, cmdSpec("sy:stop-gui", t("gui_sy_stop_btn"), function () { if (handles.stop) handles.stop(); }));

  await sysPage(root, ctx, R_SECURITY, SECURITY_SNAPS, function (board, d, host) {
    const sec = d.security || {};
    const form = makeForm("POST", "/api/security");

    const secPanel = panel("SY-12", t("gui_web_security"));
    const user = textField(sec.username || "illumio");
    const ips = textField((sec.allowed_ips || []).join(", "));
    ips.placeholder = "192.168.1.100, 10.0.0.0/8";
    const pw = passwordField("");
    const pw2 = passwordField("");
    const pwHint = el("p", { class: "note", "data-tone": "crit", hidden: true });

    secPanel.body.appendChild(labelled(t("gui_username"), form.track("username", user), t("gui_sy_sec_user_default")));
    secPanel.body.appendChild(labelled(t("gui_allowed_ips"), form.track("allowed_ips", ips, "list"), t("gui_sy_sec_lockout")));
    secPanel.body.appendChild(note(t("gui_leave_blank_pass")));
    secPanel.body.appendChild(labelled(t("gui_new_password"), form.track("new_password", pw, "secret"), t("gui_sy_sec_pw_rule")));
    secPanel.body.appendChild(labelled(t("gui_new_password_confirm"), form.track("confirm_password", pw2, "secret")));
    secPanel.body.appendChild(pwHint);
    /* auth_setup is returned by GET /api/security (config.py:50) and rendered
     * nowhere in settings.js — the operator cannot tell whether the appliance
     * still holds its bootstrap password. It is a status row here. */
    secPanel.body.appendChild(sectionHead(t("gui_sy_sec_state")));
    secPanel.body.appendChild(roList([
      roField("auth_setup", sec.auth_setup, t("gui_sy_sec_authsetup")),
      roField("old_password", null, t("gui_sy_sec_oldpw")),
    ]));
    secPanel.body.appendChild(note(t("gui_sy_sec_rotate")));
    board.appendChild(secPanel);

    // confirm_password is compared on the client and NEVER sent — matches
    // both the mockup and the real handler (config.py:98-109 reads only
    // new_password/old_password from the body).
    form.setBody(function (v) {
      const b = {};
      b.username = String(v.username || "").trim();
      b.new_password = v.new_password;
      b.allowed_ips = v.allowed_ips;
      return b;
    });
    form.afterSave = function () { refreshAndRemount(R_SECURITY, SECURITY_SNAPS); };
    // saveSettings settings.js:675-680 blocks the POST when the two boxes differ.
    /* settings.js:675-680 checks the mismatch and nothing else, so a seven-
     * character password with an empty confirm box reports "does not match" —
     * true, but not the reason the save will fail. Length is reported first, and
     * the mismatch only once the confirm box has something in it. */
    form.onSync(function () {
      const short = pw.value.length > 0 && pw.value.length < 12;
      const bad = pw2.value.length > 0 && pw.value !== pw2.value;
      pwHint.hidden = !(short || bad);
      pwHint.textContent = short ? t("gui_login_err_pw_short") : (bad ? t("gui_password_mismatch") : "");
    });

    // ── SY-16 stop the GUI ───────────────────────────────────────────
    const stopPanel = panel("SY-16", t("gui_sy_stop_btn"));
    stopPanel.dataset.tone = "crit";
    stopPanel.body.appendChild(note(t("gui_action_stop_gui_confirm")));
    const stopped = el("div", { class: "strip", "data-tone": "crit", hidden: true },
      el("b", { text: t("gui_action_gui_stopped_title") }),
      el("span", { text: t("gui_action_gui_stopped_body") }));
    /* stopGui (actions.js:118-127) swallows the response; this port does not
     * (header point 8) — real endpoint POST /api/shutdown. A 200 shows the
     * real "stopped" strip; a 403 (persistent mode) shows the backend's own
     * localised error. Genuinely destructive: the e2e never clicks past the
     * confirm. */
    handles.stop = function () {
      return modal.confirm(confirmSpec(t("gui_sy_stop_btn"), [
        t("gui_action_stop_gui_confirm"),
        t("gui_sy_stop_i_sigint"),
        t("gui_sy_stop_i_persistent"),
        t("gui_sy_stop_i_cli"),
      ], function () {
        return api.post("/api/shutdown", undefined).then(function (res) {
          if (!res || res.ok !== true) {
            toast.crit(errorText(res));
            return false;
          }
          stopped.hidden = false;
          toast.warn(t("gui_action_gui_stopped_title"));
          return true;
        });
      }));
    };
    stopPanel.body.appendChild(btn("btn danger", t("gui_sy_stop_btn"), handles.stop));
    stopPanel.body.appendChild(stopped);
    board.appendChild(stopPanel);

    host.appendChild(form.dock);
    form.sync();
  }, SECURITY_SOFT);
}

// ═════════════════════════════════════ SY-13 / XC-05 / XC-06  display ════════

const DISPLAY_SNAPS = ["settings", "status"];
/* Header point 16 (see PCE_SOFT). This is the ONE mount that reads `status`
 * (the live UI language/timezone readouts), so its degraded branch is handled
 * explicitly below rather than just tolerated. */
const DISPLAY_SOFT = ["status"];

/* settings.js:407-436 — the timezone list, in the product's own order. `local`
 * means "use the browser's zone" and is what an unset value falls back to. */
const TIMEZONES = ["local", "UTC", "UTC-12", "UTC-11", "UTC-10", "UTC-9", "UTC-8", "UTC-7", "UTC-6",
  "UTC-5", "UTC-4", "UTC-3", "UTC-2", "UTC-1", "UTC+1", "UTC+2", "UTC+3", "UTC+4", "UTC+5", "UTC+5.5",
  "UTC+6", "UTC+7", "UTC+8", "UTC+9", "UTC+9.5", "UTC+10", "UTC+11", "UTC+12", "UTC+13", "UTC+14"];

const LANG_OPTS = [["en", "gui_lang_en"], ["zh_TW", "gui_lang_zh"]];
const THEME_OPTS = [["dark", "gui_theme_dark"], ["light", "gui_theme_light"]];
const DENSITY_OPTS = [["cozy", "gui_density_cozy"], ["compact", "gui_density_compact"]];

async function mountDisplay(root, ctx) {
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  palette.registerFor(R_DISPLAY, cmdSpec("sy:theme", t("gui_sy_theme_toggle"), function () { theme.toggle(); }));

  await sysPage(root, ctx, R_DISPLAY, DISPLAY_SNAPS, function (board, d, host) {
    const s = d.settings || {};
    const st = s.settings || {};
    const rpt = s.report || {};
    const form = makeForm("POST", "/api/settings");

    // ── XC-05 theme + density: these two switch the page for real ────
    const skinPanel = panel("XC-05", t("gui_theme"));
    const themeCtl = radioGroup("sy-theme", THEME_OPTS, theme.get(), function (v) { theme.set(v); });
    const densityCtl = radioGroup("sy-density", DENSITY_OPTS, density.get(), function (v) { density.set(v); });
    themeCtl.dataset.field = "settings.theme";
    densityCtl.dataset.field = "v2.density";
    skinPanel.body.appendChild(labelled(t("gui_theme"), themeCtl, t("gui_sy_disp_theme_live")));
    skinPanel.body.appendChild(labelled(t("gui_density"), densityCtl, t("gui_sy_disp_density_new")));
    skinPanel.body.appendChild(kvRow(t("gui_sy_disp_stored_theme"), st.theme));
    // settings.js:448 rendered this label as a raw literal "Theme" with no
    // data-i18n; the density control has no product counterpart at all.
    skinPanel.body.appendChild(note(t("gui_sy_disp_theme_apply")));

    // ── XC-06 timezone + language ────────────────────────────────────
    const localePanel = panel("XC-06", t("gui_lang_settings"));
    const tzPairs = TIMEZONES.map(function (v) { return [v, v === "local" ? t("gui_local_browser_time") : v]; });
    const tz = selectField(tzPairs, st.timezone || "local", false);
    /* Phase 1 defect fix (header point 5): seeded from the REAL current
     * language (status.language, itself derived from the saved settings —
     * dashboard.py:439), and tracked through fapi.track() via
     * trackedRadioGroup rather than mutated through a client-side i18n.lang
     * that does not exist in production. Before this fix the docked form's
     * setBody always re-sent st.language (the stale settings snapshot) no
     * matter what the radio showed, so the dirty ledger could show
     * "settings.language changed" while Save silently re-saved the OLD
     * language. */
    /* Header point 16: `status` is soft-loaded, so it can be absent. Falling
     * back to a literal "en" would be actively dangerous here — a wrong seed
     * enters the dirty ledger the moment the page paints, and the next Save
     * would switch the appliance's language as a side effect of a status
     * outage. `st.language` is the SAVED setting the status payload derives
     * from (dashboard.py:439), which makes it the correct fallback, not a
     * guess. */
    const liveStatus = d.status && !d.status._error ? d.status : null;
    const langSource = liveStatus ? liveStatus.language : st.language;
    const currentLang = langSource === "zh_TW" ? "zh_TW" : "en";
    const langCtl = trackedRadioGroup("sy-lang", LANG_OPTS, currentLang, null);
    localePanel.body.appendChild(labelled(t("gui_timezone"), form.track("settings.timezone", tz), t("gui_sy_disp_tz_local")));
    localePanel.body.appendChild(labelled(t("gui_language"), form.track("settings.language", langCtl), t("gui_sy_disp_lang_reload")));
    localePanel.body.appendChild(kvRow(t("gui_sy_disp_ui_lang"), (liveStatus && liveStatus.language) || "—"));
    localePanel.body.appendChild(kvRow(t("gui_sy_disp_ui_tz"), (liveStatus && liveStatus.timezone) || "—"));
    // The two readouts above are the only thing on this page that needs the
    // live status; state its failure rather than showing a bare em dash.
    if (d.status && d.status._error) localePanel.body.appendChild(note(softErrorText(d, DISPLAY_SOFT)));
    board.appendChild(el("div", { class: "brow c2" }, skinPanel, localePanel));

    // ── SY-13 the rest of the display section ────────────────────────
    const dispPanel = panel("SY-13", t("gui_settings_tab_display"));
    const health = checkField(st.enable_health_check);
    const outDir = textField(rpt.output_dir || "reports/");
    const keepDays = numberField(rpt.retention_days === undefined ? 30 : rpt.retention_days, 0, null);
    dispPanel.body.appendChild(sectionHead(t("gui_report_output")));
    dispPanel.body.appendChild(labelled(t("gui_report_output_dir"), form.track("report.output_dir", outDir), t("gui_report_output_dir_hint")));
    dispPanel.body.appendChild(labelled(t("gui_retention_days"), form.track("report.retention_days", keepDays, "number"), t("gui_retention_hint")));
    dispPanel.body.appendChild(note(t("gui_err_report_output_dir_forbidden")));
    dispPanel.body.appendChild(sectionHead(t("gui_sy_disp_other")));
    // enable_health_check lives in settings.settings but has no control in
    // _renderDisplaySection; it is editable here rather than dropped.
    dispPanel.body.appendChild(checkRow(t("gui_sy_disp_health"), form.track("settings.enable_health_check", health, "bool"), t("gui_sy_disp_health_new")));
    dispPanel.body.appendChild(note(t("gui_sy_disp_dashq")));
    board.appendChild(dispPanel);

    form.setBody(function (v) {
      const b = {};
      const settingsPart = {};
      settingsPart.language = v["settings.language"] === "zh_TW" ? "zh_TW" : "en";
      settingsPart.theme = theme.get();
      settingsPart.timezone = v["settings.timezone"];
      settingsPart.enable_health_check = v["settings.enable_health_check"];
      b.settings = settingsPart;
      const reportPart = {};
      reportPart.output_dir = String(v["report.output_dir"] || "").trim();
      reportPart.retention_days = v["report.retention_days"];
      b.report = reportPart;
      return b;
    });

    /* Real language switching (i18n.mjs's own header): a server-side settings
     * write followed by api.invalidate("ui_translations") + i18n.init() +
     * a remount. Only done when `settings.language` was actually among the
     * committed changes — every other save on this page (timezone, health
     * check, report output) just needs the plain refresh every other page's
     * afterSave already does. v2_sy_disp_lang_partial (header point 5) no
     * longer applies: /api/ui_translations serves the FULL catalogue for
     * whichever language is now saved, not one captured snapshot. */
    form.afterSave = function (changedKeys) {
      if (changedKeys.indexOf("settings.language") < 0) {
        refreshAndRemount(R_DISPLAY, DISPLAY_SNAPS);
        return;
      }
      toast.info(t("gui_sy_lang_switched"));
      api.invalidate("ui_translations");
      return i18n.init().then(function () { refreshAndRemount(R_DISPLAY, DISPLAY_SNAPS); });
    };

    host.appendChild(form.dock);
    form.sync();
  }, DISPLAY_SOFT);
}

// ═══════════════════════════════════════════════ SY-14  alert channels ═══════

const CHANNELS_SNAPS = ["alert_plugins", "settings", "status"];
// Header point 16 (see PCE_SOFT): `status` is telemetry this mount does not read.
const CHANNELS_SOFT = ["status"];

/* _renderPluginField, settings.js:180-226. input_type drives the control;
 * value_type drives the coercion at collect time (:274-287). A `secret` field
 * is a password box in the product WITH the server's mask inside it — here the
 * box is empty and the mask's own metadata (__set/__length) is stated instead. */
function pluginControl(field, value) {
  const kind = field.input_type || (field.secret ? "password" : "text");
  if (kind === "checkbox") return checkField(!!value);
  if (kind === "list") {
    const area = el("textarea", { class: "field ta", rows: "2", placeholder: field.placeholder || "" });
    area.value = Array.isArray(value) ? value.join((field.list_delimiter || ",") + " ") : String(value || "");
    return area;
  }
  if (field.secret) {
    const box = passwordField(t("gui_sy_secret_keep"));
    return box;
  }
  if (kind === "number") {
    const n = numberField(value, null, null);
    n.placeholder = field.placeholder || "";
    return n;
  }
  const input = textField(value === null || value === undefined ? "" : value);
  input.placeholder = field.placeholder || "";
  return input;
}

function fieldKind(field) {
  if (field.secret) return "secret";
  const vt = field.value_type || "";
  if (vt === "boolean" || field.input_type === "checkbox") return "bool";
  if (vt === "integer" || vt === "number" || field.input_type === "number") return "number";
  if (vt === "string_list" || field.input_type === "list") return "list";
  return "text";
}

/** _pluginFieldValue settings.js:166-178 — the value lives at config_path. */
function nestedValue(root, path) {
  let cur = root;
  (path || []).forEach(function (seg) {
    cur = cur && typeof cur === "object" ? cur[seg] : undefined;
  });
  return cur;
}

async function mountChannels(root, ctx) {
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  // DEVIATION: the mockup registered a page-level "test all channels" palette
  // command wired to a toast stub. The only real endpoint shape that matches
  // "test all" is POST /api/actions/test-alert with no `channel` — which
  // dispatches through EVERY active channel at once, no confirmation, from a
  // keyboard shortcut. That is exactly the kind of live external side effect
  // this task's destructive discipline exists to keep out of a bare command;
  // dropped rather than wired to something this consequential. Each card's
  // own per-channel test button (below) already covers SY-14's real
  // requirement.

  await sysPage(root, ctx, R_CHANNELS, CHANNELS_SNAPS, function (board, d, host) {
    const plugins = (d.alert_plugins && d.alert_plugins.plugins) || {};
    const s = d.settings || {};
    const active = (s.alerts && s.alerts.active) || [];
    const form = makeForm("POST", "/api/settings");
    const names = Object.keys(plugins).sort();
    const toggles = [];
    const fieldItems = [];

    const wrap = panel("SY-14", t("gui_alert_channels"));
    withMeta(wrap, tf("gui_sy_ch_meta", { live: active.length, total: names.length }));
    const grid = el("div", { class: "chgrid" });
    names.forEach(function (name) {
      const p = plugins[name] || {};
      const on = active.indexOf(name) >= 0;
      const card = el("article", { class: "chcard", "data-tone": on ? "ok" : "neutral" });
      const toggle = checkField(on);
      toggles.push([name, toggle]);
      form.track("active." + name, toggle, "bool");
      /* actions.py:568-595 POST /api/actions/test-alert {channel:name} — real
       * and, like alerting.mjs's own run-once/test-alert, a live external
       * side effect (it really dispatches through the configured channel).
       * No modal.confirm (matches both the legacy product and alerting.mjs's
       * precedent) — the e2e never clicks it. The response's own `output`/
       * `error` is already localised server-side, so it is toasted as-is. */
      card.appendChild(el("div", { class: "chcard-h" },
        el("span", { class: "dot" }),
        el("b", { text: p.display_name || name }),
        el("code", { text: name }),
        spacer(),
        btn("btn ghost", t("gui_set_test_send"), function () {
          api.post("/api/actions/test-alert", { channel: name }).then(function (res) {
            if (res && res.ok) toast.ok(res.output || t("gui_set_test_send"));
            else toast.crit(errorText(res));
          });
        })));
      card.appendChild(note(p.description || ""));
      card.appendChild(el("label", { class: "chk" }, toggle, el("span", { text: t("gui_enabled") })));
      (p.fields || []).forEach(function (f) {
        const value = nestedValue(s, f.config_path);
        const ctl = pluginControl(f, value);
        const kind = fieldKind(f);
        form.track(f.key, ctl, kind);
        fieldItems.push([f, ctl]);
        const labelText = f.label + (f.required ? " *" : "");
        if (kind === "bool") card.appendChild(checkRow(labelText, ctl, f.help || null));
        else card.appendChild(labelled(labelText, ctl, f.help || null));
        if (f.secret) {
          const holder = nestedValue(s, (f.config_path || []).slice(0, -1)) || {};
          const leaf = (f.config_path || [])[(f.config_path || []).length - 1];
          card.appendChild(roList([roField(f.key, secretState(holder, leaf), t("gui_sy_secret_short"))]));
        }
      });
      grid.appendChild(card);
    });
    wrap.body.appendChild(grid);
    // R5: gui_sy_ch_schema_src described how THIS PAGE builds its own form
    // (input_type/value_type/config_path are the plugin schema's field
    // names, not anything an operator acts on) — a decision about the
    // interface, not an answer to an operator's question. Dropped rather
    // than collapsed, same call as cache's gui_sy_cache_label_fix.
    wrap.body.appendChild(note(t("gui_sy_ch_secret_fix")));
    wrap.body.appendChild(note(t("gui_sy_ch_test_skipped")));
    board.appendChild(wrap);

    /* _collectAlertPluginConfig settings.js:263-292 writes each value back to
     * its config_path and collects the enabled names into alerts.active; the
     * POST body then merges email / smtp / alerts (settings.js:689-698).
     * A1 fix (header point 4): a secret field is skipped entirely when left
     * blank — an unconditional assignment here would blank a stored SMTP
     * password or bot token on every save that touched any other plugin
     * field, since the box always starts empty. */
    form.setBody(function (v) {
      const b = {};
      const parts = {};
      fieldItems.forEach(function (pair) {
        const f = pair[0];
        if (f.secret && !v[f.key]) return;
        const path = f.config_path || [];
        const section = path.length > 1 ? path[0] : "alerts";
        const leaf = path[path.length - 1];
        if (!parts[section]) parts[section] = {};
        parts[section][leaf] = v[f.key];
      });
      Object.keys(parts).forEach(function (k) { b[k] = parts[k]; });
      if (!b.alerts) b.alerts = {};
      b.alerts.active = toggles.filter(function (p) { return p[1].checked; }).map(function (p) { return p[0]; });
      return b;
    });
    form.afterSave = function () { refreshAndRemount(R_CHANNELS, CHANNELS_SNAPS); };

    host.appendChild(form.dock);
    form.sync();
  }, CHANNELS_SOFT);
}

// ══════════════════════════════════════════════════ SY-15  module logs ═══════

// module_log_sample is deliberately NOT eager-loaded here: it is a
// parameterised GET_MAP entry (params.module_name) fetched lazily per
// selected module via loadModule() below (header point 11). Including it in
// this list would make sysPage's loadAll() call api.load("module_log_sample")
// with NO params, which store-map.mjs's own function resolves to
// "/api/logs/undefined" — a real 404 this task's own test caught (RED before
// this fix), error-carding the whole page before SY-15 ever renders.
const LOGS_SNAPS = ["logs_index"];
const LOG_LEVELS = [["", "gui_sy_log_all"], ["INFO", "INFO"], ["WARNING", "WARNING"], ["ERROR", "ERROR"], ["DEBUG", "DEBUG"]];

function logDrawer(entry, moduleName) {
  const body = el("div", { "data-cov": "SY-15" });
  if (!entry) {
    body.appendChild(el("div", { class: "empty" }, el("span", { class: "et", text: t("gui_ml_empty") })));
    return drawerSpec(t("gui_ml_title"), body);
  }
  body.appendChild(kvRow(t("gui_sy_log_module"), moduleName));
  body.appendChild(kvRow(t("gui_sy_log_ts"), entry.ts));
  body.appendChild(kvRow(t("gui_sy_log_level"), entry.level));
  body.appendChild(sectionHead(t("gui_sy_log_msg")));
  body.appendChild(el("pre", { class: "codepane tall", text: String(entry.msg || "") }));
  // module-log.js:84 — the product's whole rendering of a line.
  body.appendChild(sectionHead(t("gui_sy_log_raw")));
  body.appendChild(el("pre", { class: "codepane", text: entry.ts + " [" + entry.level + "] " + entry.msg }));
  body.appendChild(note(t("gui_sy_log_raw_note")));
  return drawerSpec(t("gui_ml_title"), body);
}

async function mountLogs(root, ctx) {
  const handles = {};
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  drawer.registerAudit("sy-log-detail", function () { return handles.first ? handles.first() : null; });

  await sysPage(root, ctx, R_LOGS, LOGS_SNAPS, function (board, d, host) {
    const modules = (d.logs_index && d.logs_index.modules) || [];
    // DEVIATION (header point 11): module_log_sample is a parameterised
    // GET_MAP entry (store-map.mjs) fetched per selected module — real, not
    // one static captured snapshot — so switching modules loads that
    // module's REAL recent entries instead of showing "no snapshot for this
    // module". api.load() caches per (id, params), so revisiting a module
    // already fetched this mount is free.
    const cache = {};
    const firstModule = (modules[0] && modules[0].name) || "";

    const p = panel("SY-15", t("gui_ml_title"));
    const meta = el("span", { class: "meta" });
    p.head.appendChild(meta);
    const modSel = selectField(modules.map(function (m) {
      const label = (m.i18n_key ? t(m.i18n_key) : (m.label || m.name)) + (m.count ? " (" + m.count + ")" : "");
      return [m.name, label];
    }), firstModule, false);
    const levelPairs = LOG_LEVELS.map(function (pair) { return [pair[0], pair[0] ? pair[1] : t(pair[1])]; });
    const levelSel = selectField(levelPairs, "", false);
    const search = el("input", { class: "field", placeholder: t("gui_search") });
    // "sy-logs-body": a stable hook the e2e waits on (table.tbl or an error
    // note lands inside it once the real, per-module fetch resolves — see
    // header point 11) distinct from this panel's own static notes below it.
    const host2 = el("div", { class: "sy-logs-body" });
    const raw = el("pre", { class: "console" });

    function loadModule(name) {
      if (!name) return Promise.resolve({ entries: [] });
      if (cache[name]) return cache[name];
      const req = api.load("module_log_sample", { module_name: name }).catch(function (e) {
        return { _error: errText(e && e.data ? e.data : e) };
      });
      cache[name] = req;
      return req;
    }

    function rows(sample) {
      const lvl = levelSel.value;
      const q = search.value.toLowerCase().trim();
      const entries = ((sample && sample.entries) || []).slice().reverse(); // module-log.js:81-86, newest first
      return entries.filter(function (e) {
        if (lvl && e.level !== lvl) return false;
        if (q && String(e.msg).toLowerCase().indexOf(q) < 0) return false;
        return true;
      });
    }

    const PAGE = 40;
    let pageIndex = 0;

    function paint() {
      const modName = modSel.value;
      loadModule(modName).then(function (sample) {
        if (state.torn || modSel.value !== modName) return;
        if (sample && sample._error) {
          clear(host2);
          host2.appendChild(note(sample._error));
          raw.textContent = sample._error;
          meta.textContent = "—";
          return;
        }
        const list = rows(sample);
        // The endpoint hands back up to 500 lines in one response; rendering
        // all of them as table rows makes an 8000px page nobody scrolls. The
        // product's own viewer gets away with it by being a fixed-height
        // <pre> — the table pages.
        const pages = Math.max(1, Math.ceil(list.length / PAGE));
        if (pageIndex >= pages) pageIndex = pages - 1;
        const slice = list.slice(pageIndex * PAGE, pageIndex * PAGE + PAGE);
        const columns = [
          col("ts", t("gui_sy_log_ts"), widthCell(170, function (e) { return el("code", { class: "mono", text: e.ts }); })),
          col("level", t("gui_sy_log_level"), widthCell(90, function (e) {
            return badge(e.level, e.level === "ERROR" ? "crit" : (e.level === "WARNING" ? "warn" : "info"));
          })),
          col("msg", t("gui_sy_log_msg"), buildCell(function (e) { return el("span", { title: e.msg, text: e.msg }); })),
          col("act", "", widthCell(80, function (e) {
            return btn("btn ghost", t("gui_dlq_view"), function () { drawer.open(logDrawer(e, modName)); });
          })),
        ];
        state.tableHandles.logs = table.render(host2, pagedTable(columns, slice, pageSpec(pageIndex, PAGE, list.length), function (next) {
          pageIndex = Math.max(0, Math.min(next, pages - 1));
          paint();
        }));
        raw.textContent = list.map(function (e) { return e.ts + " [" + e.level + "] " + e.msg; }).join("\n") || t("gui_ml_empty");
        meta.textContent = tf("gui_sy_log_meta", { n: list.length });
        handles.first = function () { return drawer.open(logDrawer(list[0] || null, modName)); };
      });
    }

    function reset() { pageIndex = 0; paint(); }
    modSel.addEventListener("change", reset);
    levelSel.addEventListener("change", reset);
    search.addEventListener("input", reset);

    p.body.appendChild(el("div", { class: "qrow" },
      el("div", { class: "qf" }, el("label", { text: t("gui_ml_title") }), modSel),
      el("div", { class: "qf" }, el("label", { text: t("gui_sy_log_level") }), levelSel),
      el("div", { class: "qf grow" }, el("label", { text: t("gui_search") }), search),
      el("div", { class: "qf" }, el("label", { text: " " }), btn("btn", t("gui_rs_refresh"), function () { delete cache[modSel.value]; paint(); }))));
    p.body.appendChild(host2);
    p.body.appendChild(note(t("gui_sy_log_filters_new")));
    p.body.appendChild(sectionHead(t("gui_sy_log_raw")));
    p.body.appendChild(raw);
    /* Density spec R5 — these two caveats (why the raw view's count can read
     * lower than the module list's own count; why two module names show up
     * in English) both explain a real discrepancy an operator might
     * otherwise read as a bug. Folded into one explanation rather than left
     * standing under the raw console, R4's own remedy for the "?n=" and
     * "logs_index" implementation detail gui_sy_log_cap still names. */
    p.body.appendChild(disclosure(t("gui_gen_explain"),
      note(t("gui_sy_log_cap")),
      note(t("gui_sy_log_i18n_gap"))));
    board.appendChild(p);
    paint();
  });
}

export { mountPce, mountCache, mountSiem, mountTls, mountSecurity, mountDisplay, mountChannels, mountLogs };
