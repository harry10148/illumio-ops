// investigate.mjs — #/investigate/{traffic,workloads,events}.
// Anchors IV-01…IV-15, XC-03/04/08/09/11/12 (design/v2/coverage.yaml).
//
// PORT OF design/v2/mockup/js/areas/investigate.mjs against the live backend.
// The three sub-views are one instrument: a query workbench. Field semantics
// are transcribed from the shipping GUI with the source line cited above each
// builder, exactly as the mockup did; what follows is only what this port
// CHANGES, each item also flagged at its own call site.
//
//   1. `store.load(id)` -> `api.load(id, params?)` (core/api.mjs). Two ids
//      grew a params argument in core/store-map.mjs — `workload_search`
//      (name/ip_address/hostname) and `events_viewer` (mins/limit/offset/
//      search/category/type_group/event_type) — because those two panels are
//      exactly the "real interactivity" that file's header predicted would
//      need its own query string. With no params both still resolve to the
//      captured path in design/v2/tools/endpoints.yaml byte for byte.
//
//   2. traffic_search is a real POST /api/quarantine/search (endpoints.yaml's
//      `traffic_search` entry; payload transcribed from quarantine.js:271-296
//      runTrafficAnalyzer, which is also what actions.py:79-216 reads). The
//      mockup filtered ONE captured page client-side; here every control —
//      window, source, sort, quick search, the two policy-decision radio
//      groups and the FilterBar dict — rides in the request body, and the
//      KPI strip is recomputed from whatever comes back. `search` therefore
//      round-trips (actions.py:141 params["search"]) instead of matching
//      rows locally, so the mockup's rowMatches() is gone.
//
//   3. NEITHER traffic nor workloads nor events auto-runs its query on mount.
//      All three are live PCE queries (a traffic flow search is the most
//      expensive call this product makes), and the shipping GUI makes each
//      one an explicit click for that reason. Every panel, empty state and
//      coverage anchor renders immediately; the rows arrive when the
//      operator asks for them. A query in flight paints the real loading
//      state: table skeleton (table.render(host, rows=null)) plus
//      data-loading="true" on the KPI strip and a disabled run button.
//
//   4. Quarantine apply / bulk apply / lift and traffic acceleration call
//      their real endpoints (actions.py:301/347/407/463). Every one of them
//      is behind the same confirm-modal-with-impact the mockup built, and
//      every one reports the backend's own `ok:false` error instead of a
//      success toast it did not earn. Two backend response shapes matter
//      here and are handled explicitly rather than assumed:
//        - /api/quarantine/apply and /api/workloads/accelerate answer 200
//          with {ok:false, error} for an operational failure;
//        - /api/quarantine/lift can answer 500 with {ok:false, error,
//          request_id} (actions.py:407-461 has no APIError branch, unlike
//          apply's :319-321), and api.post() resolves either way — so the
//          caller checks `ok`, never the HTTP status.
//
//   5. Backfill posts to POST /api/cache/backfill (pce_cache/web.py:47-98).
//      That route answers with NO `ok` key in either direction — success is
//      {total_rows, inserted, duplicates, elapsed_seconds}, failure is
//      {error} with a 4xx/5xx — so the caller tests for `error`, not for
//      `ok`. The date fields are deliberately NOT pre-validated client-side
//      (the shipping GUI's gui_cb_dates_required check): `since` missing is
//      the route's own documented 400 (:57-58), and letting the authority
//      answer is both simpler and honest about who decides.
//
//   6. IV-15 shadow compare binds to GET /api/events/shadow_compare
//      (events.py:150-201) with the mins/limit clamps that route applies,
//      and renders the real rule_name/current_count/legacy_count/delta/
//      status rows (events/shadow.py:78-104). It is loaded ON DEMAND, not at
//      mount: the route fetches up to 500 events from the PCE per call, and
//      making that automatic would tax every visit to #/investigate/events
//      for a panel most visits do not read. The mockup's
//      "v2_iv_shadow_unavailable" wall is replaced by a real idle note, real
//      rows, or the backend's real error.
//
//   7. IV-06's archive strip keeps its real status readout
//      (GET /api/cache/archive/status). Task 7 repurposed that endpoint:
//      choosing "archive" as the source makes /api/quarantine/search stream
//      the daily archive files directly (Task 4/5's actions.py:92-110), not
//      a review DB, so the endpoint — and this strip — now report the
//      archive FILES themselves (directory exists?, file count, earliest/
//      latest date covered), which is what an operator needs before picking
//      a date range. The mockup's "load archive" button is now a jump to
//      #/system/cache: archive collection settings (archive_dir,
//      archive_enabled, ...) are a cache management operation that the
//      System area owns, so pretending to offer a load action from a
//      read-only status strip would be the same lie the mockup's toast was.
//
//   8. IV-12's persistent mode is now real. The backend is explicitly
//      stateless about it ("Persistent mode (re-issue every 10 min) is
//      handled by the frontend via setInterval", actions.py:465-470), so a
//      countdown with no re-issue would make every non-zero duration a
//      decoration. Transcribed from quarantine.js:719-771: fire once, then
//      re-fire every 10 minutes until the deadline, with a 1-second display
//      tick. Both timers are cleared by cancel, by the deadline, and by this
//      area's teardown.
//
//   9. The mockup's verification pane (components/verifypane.mjs) is dropped.
//      That component's own header says it is a mockup verification device
//      and "Phase 2 will NOT build them into the product". The serialized
//      FilterBar dict it wrapped is not shown at all any more: the filters
//      drawer states the query in pills, and the request format is not
//      operator-facing copy (density spec R4).
//
//  10. i18n keys renamed v2_* -> gui_*. gui_health_goto and gui_table_rows
//      reuse the keys earlier tasks already minted for the same text; every
//      other one is a new gui_iv_* / gui_nav_investigate pair in
//      src/i18n_en.json + src/i18n_zh_TW.json, transcribed from
//      design/v2/mockup/i18n-supplement.json except where the mockup string
//      described the mockup ("this page does not re-query the PCE", "needs a
//      real backend") and is now false — those are reworded to describe what
//      the live screen does.
//
//  11. Teardown (S2): each of the three mounts registers a self-unsubscribing
//      router.onChange that destroys this mount's table handles, clears the
//      accelerate timers and the cell popover, closes any drawer/modal it
//      left open, clears the injected FilterBar browser callback and drops
//      its route-scoped palette commands. See installTeardown() at the bottom.
//
//  12. The object browser captures each selected item's category at selection
//      time, rather than reading the currently active tab when saving. The
//      frozen mockup only exposed label rows, so its late-tab switch could not
//      reveal that category mismatch.
//
//  13. The workloads action column uses a flex row and 260px width. The
//      shipping three-button action set otherwise wraps inside the table's
//      fixed-height cell and makes the lift action unreachable.

import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { num, stamp, tone } from "../core/fmt.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { mountRankingsAndQueries } from "./cards.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { createFilterBar, setFilterBarText, setFilterBarQuery } from "../components/filter-bar.mjs";
import { setFilterBarBrowser, addPillFromBrowser } from "../components/filter-bar.mjs";
import { filterObjectQuery, OBJECT_CATS } from "../core/filter-objects.mjs";

const R_TRAFFIC = "#/investigate/traffic";
const R_WORKLOADS = "#/investigate/workloads";
const R_EVENTS = "#/investigate/events";

// Where the archive strip hands archive LOADING off to — see header note 7.
const GO_CACHE = "#/system/cache";

const SUB_ROUTES = [
  [R_TRAFFIC, "gui_traffic_analyzer"],
  [R_WORKLOADS, "gui_workload_search"],
  [R_EVENTS, "gui_event_viewer"],
];

// index.html:845-850 (select#qt-mins) — the window options, value + catalogue key.
const WINDOWS = [["60", "gui_win_1h"], ["1440", "gui_win_24h"], ["10080", "gui_win_1w"], ["43200", "gui_win_1m"]];
// index.html:859-863 (select#qt-sort)
const SORTS = [["bandwidth", "gui_opt_bandwidth"], ["volume", "gui_opt_volume"], ["connections", "gui_opt_connections"]];
// Task 4's archive_query.py deliberately has no "bandwidth" sort: bandwidth is
// a RATE (bytes / time window, calculate_mbps) and archive rows carry nothing
// to compute one from — see archive_query.py's _SORT_FIELD comment. Offering
// it here and translating on submit would be the same "looks right but isn't"
// number this whole task exists to remove, so the control itself narrows.
const ARCHIVE_SORTS = SORTS.filter(function (p) { return p[0] !== "bandwidth"; });
// index.html:868-871 (select#traffic-source) — three request-honest choices,
// replacing the old two ("live"/"archive") whose "live" value actually meant
// the local cache and whose label said so ("Live cache"), not the PCE. Task 4
// gave the backend an explicit data_source preference
// (hybrid|cache|live|no-cache|api, actions.py's _TRAFFIC_DATA_SOURCE_VALUES)
// and an `actual_source` readout of which path really answered; this control
// exposes the two the GUI supports — hybrid (cache first, PCE for the gap;
// resolve_data_source's own default when unset) and live (skip the cache,
// query the PCE directly) — plus the real archive, backed by Task 4/5's
// direct date-range scan of the archive's daily files (no more separately
// loaded review DB).
const SOURCES = [["hybrid", "gui_traffic_source_hybrid"], ["live", "gui_traffic_source_api"], ["archive", "gui_traffic_source_archive"]];
// index.html:932-934 / :996-997
const PAGE_SIZES = ["50", "100"];
// index.html:2433-2436 (input[name=qt-pd-radio])
const PD_REPORTED = [["", "gui_pd_all"], ["blocked", "gui_pd_blocked"], ["potentially_blocked", "gui_pd_potential"], ["allowed", "gui_pd_allowed"]];
// index.html:2440-2447 (input[name=qt-dpd-radio])
const PD_DRAFT = [
  ["", "gui_pd_all"],
  ["blocked_by_boundary", "pd_blocked_by_boundary"],
  ["blocked_by_override_deny", "pd_blocked_by_override_deny"],
  ["potentially_blocked", "gui_pd_potential"],
  ["potentially_blocked_by_boundary", "pd_potentially_blocked_by_boundary"],
  ["potentially_blocked_by_override_deny", "pd_potentially_blocked_by_override_deny"],
  ["allowed", "gui_pd_allowed"],
  ["allowed_across_boundary", "pd_allowed_across_boundary"],
];
// quarantine.js:459-469 (makePdBadge) — decision -> catalogue key + tone, digit
// for digit: the three *_boundary / *_override_deny variants inherit the tone of
// the decision they qualify.
const PD_LABELS = [
  ["blocked", "gui_pd_blocked"],
  ["potentially_blocked", "gui_pd_potential"],
  ["allowed", "gui_pd_allowed"],
  ["blocked_by_boundary", "pd_blocked_by_boundary"],
  ["blocked_by_override_deny", "pd_blocked_by_override_deny"],
  ["potentially_blocked_by_boundary", "pd_potentially_blocked_by_boundary"],
  ["potentially_blocked_by_override_deny", "pd_potentially_blocked_by_override_deny"],
];
const PD_TONES = [
  ["blocked", "crit"],
  ["potentially_blocked", "warn"],
  ["allowed", "ok"],
  ["blocked_by_boundary", "crit"],
  ["blocked_by_override_deny", "crit"],
  ["potentially_blocked_by_boundary", "warn"],
  ["potentially_blocked_by_override_deny", "warn"],
];
// index.html:2498-2502 (select#q-severity)
const SEVERITIES = [["Mild", "gui_opt_mild"], ["Moderate", "gui_opt_moderate"], ["Severe", "gui_opt_severe"]];
// index.html:2486-2491 (input[name=q-dir])
const DIRECTIONS = [["source", "gui_q_src"], ["destination", "gui_q_dst"], ["both", "gui_q_both"]];
// index.html:2520-2523 (input[name=accel-dur]) — 0 means a single shot
const ACCEL_DURATIONS = ["0", "30", "60", "120"];
// quarantine.js:731 — persistent mode re-issues every 10 minutes.
const ACCEL_REISSUE_MS = 600000;
// index.html:2549-2550 (select#cb-source) / :2566-2569 (quick ranges)
const BACKFILL_SOURCES = [["events", "gui_cb_source_events"], ["traffic", "gui_cb_source_traffic"]];
const BACKFILL_RANGES = ["1", "7", "30", "60"];
// index.html:1173-1180 (select#ev-mins) / :1184-1188 (select#ev-limit). The
// viewer route clamps mins to [5, 10080] and limit to [1, 200]
// (events.py:37-43), so the 30d/60d options the shipping select offers are
// clamped server-side; they are kept because the shipping select has them.
const EV_WINDOWS = [["15", "gui_ev_window_15m"], ["60", "gui_ev_window_1h"], ["360", "gui_ev_window_6h"],
  ["1440", "gui_ev_window_24h"], ["10080", "gui_ev_window_7d"], ["43200", "gui_ev_window_30d"], ["86400", "gui_ev_window_60d"]];
const EV_LIMITS = ["25", "50", "100", "200"];
// events.py:162-168 — shadow_compare clamps mins to [5, 10080] and limit to [1, 500].
const SHADOW_MINS = ["60", "360", "1440", "10080"];
const SHADOW_LIMITS = ["50", "200", "500"];

// The three fast, non-PCE GETs the traffic view needs before it can render its
// controls and its empty-state reasoning. Everything PCE-backed on this route
// is fetched separately, on demand: the flow search on click, and the filter
// objects only once a filters drawer or the object browser is opened (the bar
// issues those itself — core/filter-objects.mjs).
const TRAFFIC_SNAPS = ["archive_status", "cache_status", "cache_settings", "dashboard_queries"];

function lookup(pairs, key, fallback) {
  let hit = fallback;
  pairs.forEach(function (pair) { if (pair[0] === String(key)) hit = pair[1]; });
  return hit;
}

/** A no-op selection, for the skeleton table that has no rows to select. */
const emptySel = { isChecked: function () { return false; }, toggle: function () { } };

/** The backend's own error text, or a generic fallback when it sent none. */
function errText(r) {
  const msg = r && (r.error || r.message);
  return msg ? String(msg) : t("gui_err_generic");
}

/* Task 6 constraint 2 — archive_query.py's UNSUPPORTED_ARCHIVE_FILTER_KEYS
 * (and actions.py's own `search` addition) are internal API parameter names
 * ("src_ams", "ex_dst_label_group") and must never reach an operator as-is.
 * Rather than hand-write new prose per key, each is composed from catalogue
 * text the FilterBar already shows for the same condition: the zone label
 * (gui_fb_dir_src/dst — components/filter-bar.mjs's _OBJFB_ZONES) plus the
 * category label (gui_fb_cat_label_group — its _OBJFB_CATS). The AMS and
 * include_groups families have no FilterBar pill of their own (the v2 bar
 * never emits those keys — grep confirms), but archive_query.py's own
 * comment groups them with label_group as one "actor groups / ams" PCE-only
 * concept, so they compose the same way. draft_policy_decision reuses the
 * label this same file already shows beside the draft-decision radios
 * (gui_pd_draft_label). The map is exhaustive against
 * UNSUPPORTED_ARCHIVE_FILTER_KEYS; the `key` fallback is defensive only — it
 * would mean archive_query.py's list and this one drifted apart, which
 * tests/test_archive_query.py's drift test guards against independently. */
function unsupportedLabel(key) {
  const bare = key.replace(/^ex_/, "");
  if (bare === "draft_policy_decision") return t("gui_pd_draft_label");
  // port_range / ex_port_range (Final review F4): PCE-native execution, no
  // archive fallback — reuse the FilterBar's own "Port" category label
  // (gui_fb_cat_port) rather than inventing new prose, same pattern as the
  // label_group/AMS branch below.
  if (bare === "port_range") return t("gui_fb_cat_port");
  const dir = bare.indexOf("src_") === 0 ? t("gui_fb_dir_src") + " "
    : bare.indexOf("dst_") === 0 ? t("gui_fb_dir_dst") + " " : "";
  if (/label_group/.test(bare) || /_ams$/.test(bare) || /include_groups$/.test(bare)) {
    return dir + t("gui_fb_cat_label_group");
  }
  return key;
}

// actual_source (Task 4/5 contract) -> catalogue key, all four values.
// Fix round 1, Minor 5: "archive" used to reuse the source-select's own
// short label (gui_traffic_source_archive, "Archive"/"封存 (Archive)"), which
// read as a category name sitting next to three full sentences ("Answered
// from the cache", ...) — an inconsistent voice for what is supposed to be
// one set of four readouts. It now has its own sentence-shaped key like the
// other three. Looked up via `lookup()`, not by building the key with string
// concatenation directly inside a translate call: scripts/audit_i18n_usage.py's
// category G regex matches a literal quoted first argument to the translate
// helper, and a concatenated literal prefix there trips it into treating the
// bare prefix as a referenced-but-missing key.
const ACTUAL_SOURCE_LABELS = [
  ["cache", "gui_traffic_actual_source_cache"],
  ["api", "gui_traffic_actual_source_api"],
  ["mixed", "gui_traffic_actual_source_mixed"],
  ["archive", "gui_traffic_actual_source_archive"],
];

function actualSourceText(v) {
  return t(lookup(ACTUAL_SOURCE_LABELS, v, v), v);
}

// ── shared chrome ───────────────────────────────────────────────────────────

/** Minimal area-head: title + route breadcrumb. Same local copy areas/
 *  overview.mjs keeps, for the same reason (the mockup's placeholder.mjs
 *  pulls in a shell.mjs that does not exist here). */
/* Route as a data attribute, not visible chrome — see overview.mjs's areaHead. */
function areaHead(title, route) {
  return el("div", { class: "area-head", "data-route": route },
    el("h1", { text: title })
  );
}

function panel(cov, title) {
  const head = el("div", { class: "panel-h" }, el("h3", { title: title, text: title }));
  const body = el("div", { class: "panel-b" });
  const root = el("section", { class: "panel", "data-cov": cov || null }, head, body);
  root.head = head;
  root.body = body;
  return root;
}

function headBox(p) {
  if (!p.hact) {
    p.hact = el("span", { class: "hact" });
    p.head.appendChild(p.hact);
  }
  return p.hact;
}

function withMeta(p, text) {
  p.head.appendChild(el("span", { class: "meta", title: text, text: text }));
  return p;
}

function withAction(p, label, onClick) {
  headBox(p).appendChild(el("button", { class: "btn", type: "button", text: label, onClick: onClick }));
  return p;
}

function note(text) {
  return el("p", { class: "note", text: text });
}

function btn(cls, text, onClick) {
  return el("button", { class: cls, type: "button", text: text, onClick: onClick });
}

function badge(text, tn) {
  return el("span", { class: "badge", "data-tone": tn }, el("i", { class: "dot" }), el("span", { text: text }));
}

function areaTop(active) {
  const head = areaHead(t("gui_nav_investigate"), active);
  const nav = el("nav", { class: "subnav", "aria-label": t("gui_nav_investigate") });
  SUB_ROUTES.forEach(function (pair) {
    const a = el("a", { href: pair[0], text: t(pair[1]) });
    if (pair[0] === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  head.appendChild(nav);
  return head;
}

function field(labelText, control) {
  return el("div", { class: "qf" }, el("label", { text: labelText }), control);
}

function selectField(labelText, pairs, value, onChange) {
  const sel = el("select", { class: "field" });
  pairs.forEach(function (pair) {
    const key = Array.isArray(pair) ? pair[0] : pair;
    const text = Array.isArray(pair) ? t(pair[1]) : pair;
    const opt = el("option", { value: key, text: text });
    if (String(value) === String(key)) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.setAttribute("aria-label", labelText);
  sel.addEventListener("change", function () { onChange(sel.value); });
  const wrap = field(labelText, sel);
  wrap.control = sel;
  return wrap;
}

function radioGroup(name, pairs, value, onChange) {
  const box = el("div", { class: "radios" });
  pairs.forEach(function (pair) {
    const input = el("input", { type: "radio", name: name, value: pair[0] });
    if (String(value) === String(pair[0])) input.checked = true;
    input.addEventListener("change", function () { if (input.checked) onChange(input.value); });
    box.appendChild(el("label", null, input, el("span", { text: t(pair[1]) })));
  });
  return box;
}

function buildCell(fn) { const o = {}; o.cell = fn; return o; }
function numCell(fn) { const o = {}; o.cell = fn; o.align = "n"; return o; }
function widthCell(width, fn) { const o = {}; o.width = width; if (fn) o.cell = fn; return o; }
/** A checkbox column: header selects/clears the page, body cell picks one row. */
function pickCell(headFn, cellFn) { const o = {}; o.width = 34; o.head = headFn; o.cell = cellFn; return o; }

function buildTable(columns, rows) {
  const spec = {};
  spec.columns = columns;
  spec.rows = rows;
  return spec;
}

function pagedTable(columns, rows, page, onPage) {
  const spec = buildTable(columns, rows);
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

function drawerSpec(title, body, onSave) {
  const spec = {};
  spec.title = title;
  spec.body = body;
  if (onSave) spec.onSave = onSave;
  return spec;
}

function confirmSpec(title, impact, onOk) {
  const spec = {};
  spec.title = title;
  spec.impact = impact;
  spec.onOk = onOk;
  return spec;
}

function cmdSpec(id, label, run) {
  const spec = {};
  spec.id = id;
  spec.label = label;
  spec.run = run;
  return spec;
}

/**
 * loadAll(ids) — every id caught independently, exactly like
 * areas/overview.mjs's loadOne(): api.load() throws on any non-2xx and several
 * of these are live PCE-backed endpoints whose non-2xx is an ordinary
 * operational condition, so a bare Promise.all would blank the whole view over
 * one struggling source. Every consumer below tolerates a falsy payload.
 */
function loadAll(ids) {
  return Promise.all(ids.map(function (id) {
    return api.load(id).catch(function (e) {
      return { ok: false, error: String((e && e.message) || e) };
    });
  })).then(function (list) {
    const out = {};
    ids.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

/** utils.js:260-269 (renderLabelsHtml) — key:value chips; Quarantine is the one
 *  key the product marks out (`lbl-quarantine`), so it is the one that gets a tone. */
function labelChips(labels) {
  const box = el("div", { class: "lbls" });
  (labels || []).forEach(function (l) {
    box.appendChild(el("span", { "data-tone": l.key === "Quarantine" ? "crit" : null,
      title: l.key + ":" + l.value, text: l.key + ":" + l.value }));
  });
  return box;
}

/** A two-line identity cell: name over its address. */
function identity(name, sub, extra) {
  return el("span", { class: "idc" },
    el("b", { title: name, text: name || "—" }),
    sub ? el("small", { text: sub }) : null,
    extra || null
  );
}

// Names for hrefs, so a confirmation can say WHICH workloads it will isolate
// instead of only how many. Filled by whichever sub-view is on screen.
const hrefNames = new Map();

function nameOf(href) {
  return hrefNames.get(href) || String(href || "").split("/").pop();
}

// ═════════════════════════════════════════════════════ traffic ══════════════

/* quarantine.js:323-330 (fmtCompact) */
function fmtCompact(n) {
  if (n === null || n === undefined || isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

/* quarantine.js:331-335 (fmtBw) */
function fmtBw(mbps) {
  if (mbps === null || mbps === undefined || mbps === 0) return "—";
  if (mbps >= 1000) return (mbps / 1000).toFixed(2) + " Gbps";
  return mbps.toFixed(1) + " Mbps";
}

/* quarantine.js:337-351 (updateTrafficKpis body) — all four figures are derived
 * from the SAME row set the table renders, which is the point of the strip: the
 * numbers can never disagree with the rows underneath them. */
function trafficKpis(rows) {
  const out = {};
  out.flows = rows.length;
  out.conns = 0;
  out.peakBw = 0;
  const dstSet = new Set();
  rows.forEach(function (r) {
    if (!r || typeof r !== "object") return;
    out.conns += Number(r.num_connections || r.connections || 0);
    const bw = Number(r.max_bandwidth_mbps || r.avg_bandwidth_mbps || 0);
    if (bw > out.peakBw) out.peakBw = bw;
    const dstIps = (r.destination && (r.destination.ip || r.destination.ip_list)) || r.dst_ip;
    if (typeof dstIps === "string") dstIps.split(/[,\s]+/).filter(Boolean).forEach(function (ip) { dstSet.add(ip); });
    else if (Array.isArray(dstIps)) dstIps.forEach(function (ip) { dstSet.add(ip); });
  });
  out.dstIps = dstSet.size;
  return out;
}

function kpiCell(labelKey, value, unit, detail) {
  const v = el("span", { class: "v" }, el("span", { text: value }), unit ? el("s", { text: unit }) : null);
  return el("div", { class: "kpicell" },
    el("span", { class: "k", text: t(labelKey) }),
    v,
    el("span", { class: "d", title: detail, text: detail })
  );
}

/* index.html:817-838 — the four cells, in the product's order. The product's
 * fourth line (tw-kpi-*-delta) is a placeholder that no code ever fills; a
 * delta needs a previous query to compare against, so the slot carries what the
 * figure is derived FROM instead.
 *
 * PORT: `phase` drives the real loading state (header note 3). "idle" = no
 * query has been run yet, "busy" = one is in flight, "done" = these are the
 * figures of the result now on screen. The strip is the only place the three
 * are distinguishable, which is why data-loading lives here. */
function kpiRow(rows, phase) {
  const k = trafficKpis(rows);
  const busy = phase === "busy";
  const idle = phase === "idle";
  const basis = busy ? t("gui_querying")
    : (idle ? t("gui_iv_not_run") : tf("gui_iv_kpi_basis", { n: num(rows.length) }));
  const cell = function (key, value, unit) {
    return kpiCell(key, busy || idle ? "—" : value, unit, basis);
  };
  const box = el("div", { class: "kpirow" },
    cell("gui_tw_kpi_flows", num(k.flows), t("gui_flows")),
    cell("gui_tw_kpi_conns", fmtCompact(k.conns), null),
    cell("gui_tw_kpi_dst_ips", num(k.dstIps), null),
    cell("gui_tw_kpi_peak_bw", fmtBw(k.peakBw), null)
  );
  box.setAttribute("data-phase", phase);
  if (busy) box.setAttribute("data-loading", "true");
  return box;
}

/* quarantine.js:433-436 — the service cell string. */
function serviceText(svc) {
  const namePart = svc.name ? svc.name + " " : "";
  if (svc.port !== "All") return namePart + svc.proto + "/" + svc.port;
  return namePart ? namePart + t("gui_all_services") : t("gui_all_services");
}

/* quarantine.js:438-443 + utils.js:275-300 (showCellPopover) — a service string
 * over 25 characters is truncated and opens a popover listing the parts. */
function serviceCell(svc) {
  const text = serviceText(svc);
  const extra = [];
  if (svc.process) extra.push(t("gui_fb_cat_process") + ": " + svc.process);
  if (svc.user) extra.push(t("gui_user") + ": " + svc.user);
  const wrap = el("span", { class: "idc" });
  if (text.length > 25) {
    const parts = text.split(",").map(function (s) { return s.trim(); });
    const more = btn("linkish", text.substring(0, 23) + "…", function (e) {
      cellPopover(e.currentTarget, "SVC", parts);
    });
    more.title = text;
    wrap.appendChild(more);
  } else {
    wrap.appendChild(el("b", { text: text }));
  }
  extra.forEach(function (line) { wrap.appendChild(el("small", { text: line })); });
  return wrap;
}

// utils.js:275-300 — one popover at a time, positioned under the cell, closed on
// the next outside click. XC-12's popover leg. Module-level (there is only ever
// one) so this area's teardown can close it, which the mockup never had to do.
let livePopover = null;

function closePopover() {
  if (livePopover && livePopover.parentNode) livePopover.parentNode.removeChild(livePopover);
  livePopover = null;
}

function cellPopover(target, title, items) {
  closePopover();
  const pop = el("div", { class: "popover", "data-tone": "info" },
    el("h4", { text: title + " (" + items.length + ")" }),
    el("ul", null, items.map(function (line) { return el("li", { text: line }); }))
  );
  const rect = target.getBoundingClientRect();
  pop.style.position = "fixed";
  pop.style.left = Math.round(rect.left) + "px";
  pop.style.top = Math.round(rect.bottom + 6) + "px";
  document.body.appendChild(pop);
  livePopover = pop;
  setTimeout(function () {
    document.addEventListener("click", function close() {
      if (livePopover === pop) closePopover();
      else if (pop.parentNode) pop.parentNode.removeChild(pop);
      document.removeEventListener("click", close);
    }, { once: true });
  }, 0);
  return pop;
}

function pdBadge(pd, isReported) {
  if (!pd) return null;
  const label = t(lookup(PD_LABELS, pd, pd), pd);
  const tn = lookup(PD_TONES, pd, "neutral");
  const text = isReported ? label : t("gui_draft") + " " + label;
  return badge(text, tn);
}

/* quarantine.js:409-492 (renderQtPage row) — one table row per flow. */
function trafficRows(rows, sort) {
  return rows.map(function (item) {
    const r = {};
    // :427-431 — the metric column shows whichever figure the sort ranked by
    if (sort === "bandwidth") r.metric = item.formatted_bandwidth || "—";
    else if (sort === "volume") r.metric = item.formatted_volume || "—";
    else r.metric = item.formatted_connections + " " + t("gui_flows");
    const range = item.timestamp_range || {};
    r.first = stamp(range.first_detected || "");
    r.last = stamp(range.last_detected || "");
    r.src = item.source || {};
    r.dst = item.destination || {};
    r.svc = item.service || {};
    r.pd = item.policy_decision || "";
    r.draftPd = item.draft_policy_decision || "";
    r.srcHref = r.src.href || "";
    r.dstHref = r.dst.href || "";
    return r;
  });
}

function actorCell(actor) {
  const extra = el("span");
  // :417-425 — process and user ride along with the identity when the VEN
  // reported them; the label chips sit underneath either way.
  if (actor.process) extra.appendChild(el("small", { text: t("gui_fb_cat_process") + ": " + actor.process }));
  if (actor.user) extra.appendChild(el("small", { text: t("gui_user") + ": " + actor.user }));
  extra.appendChild(labelChips(actor.labels));
  return identity(actor.name, actor.ip, extra);
}

/* index.html:903-907 (#qt-chkall / .qt-chk) — a checkbox per row that carries a
 * workload target, plus a header checkbox that (de)selects every checkbox
 * currently on the page, exactly like #qt-chkall does over the DOM's .qt-chk
 * (quarantine.js:14-17, toggleQChecks). */
function trafficColumns(onIsolate, sel) {
  const pageBoxes = [];
  return [
    col("pick", "", pickCell(
      function () {
        const all = el("input", { type: "checkbox" });
        all.setAttribute("aria-label", t("gui_selected"));
        all.addEventListener("change", function () {
          pageBoxes.forEach(function (entry) {
            entry.cb.checked = all.checked;
            sel.toggle(entry.r, all.checked);
          });
        });
        return all;
      },
      function (r) {
        if (!r.srcHref && !r.dstHref) {
          return el("span", { class: "mono", title: t("gui_q_workload_only"), text: "—" });
        }
        hrefNames.set(r.srcHref, (r.src || {}).name || r.srcHref);
        hrefNames.set(r.dstHref, (r.dst || {}).name || r.dstHref);
        const cb = el("input", { type: "checkbox" });
        cb.setAttribute("aria-label", t("gui_selected"));
        cb.checked = sel.isChecked(r);
        cb.addEventListener("change", function () { sel.toggle(r, cb.checked); });
        pageBoxes.push({ r: r, cb: cb });
        return cb;
      }
    )),
    col("metric", t("gui_metric"), widthCell(185, function (r) { return el("b", { class: "mono", text: r.metric }); })),
    col("seen", t("gui_first_last_seen"), widthCell(150, function (r) {
      return el("span", { class: "idc" },
        el("small", { text: tf("gui_iv_first_seen", { value: r.first }) }),
        el("small", { text: tf("gui_iv_last_seen", { value: r.last }) }));
    })),
    col("src", t("gui_source_identity"), buildCell(function (r) { return actorCell(r.src); })),
    col("dst", t("gui_destination_identity"), buildCell(function (r) { return actorCell(r.dst); })),
    col("svc", t("gui_service_port"), widthCell(150, function (r) { return serviceCell(r.svc); })),
    col("pd", t("gui_policy_dec"), widthCell(170, function (r) {
      return el("span", { class: "idc" }, pdBadge(r.pd, true), r.draftPd ? pdBadge(r.draftPd, false) : null);
    })),
    col("act", t("gui_actions"), widthCell(90, function (r) {
      // :474-476 — a row can only be isolated when at least one end is a workload
      if (!r.srcHref && !r.dstHref) {
        return el("span", { class: "mono", title: t("gui_q_workload_only"), text: "—" });
      }
      return btn("btn danger", t("gui_btn_isolate"), function () { onIsolate(r); });
    })),
  ];
}

/* Fix round 1, Important 2 — the archive branch's OWN scanned/matched counts
 * (Task 4's ArchiveQueryResult, surfaced on the response as `scanned`/
 * `matched`) are the true reason an empty archive query came back empty, not
 * the old review-DB `archive_status`/`not_loaded` flags: the new direct
 * date-range scan never sets `not_loaded` and does not depend on any review
 * DB being "loaded" at all, so reasoning from that status always reads as
 * "archive not loaded" even when the query genuinely ran. Distinct facts,
 * previously collapsed into that one wrong claim:
 *   scanned == 0               -> no archive files cover this date range at all
 *   scanned > 0, matched == 0  -> files were read; nothing matched the query
 * Before any archive query has run in this session (`scanned` still
 * undefined — e.g. XC-09's audit probe forcing phase "done" without a real
 * query), neither fact is known yet, so this reads neutrally rather than
 * guessing. Shared by emptyCauses() and emptyState() so both read the same
 * distinction the same way.
 *
 * Final review F2 — a FOURTH fact, checked first: the scan may have stopped
 * partway through the range (deadline or the memory-bound size cap,
 * actions.py's `incomplete_after`/`stop_reason`) before it ever got to
 * "nothing matched". Without this check, a 90-day query that only managed to
 * scan the first day before timing out told the operator the same sentence
 * as a query that genuinely read all 90 days and found nothing — a real
 * false claim ("files for this range were read; none matched"), not just an
 * omission. */
function archiveEmptyReason(state) {
  const meta = state.meta || {};
  const scanned = meta.scanned;
  if (typeof scanned !== "number") return { tone: "neutral", key: "gui_traffic_archive_scan_pending" };
  if (meta.incompleteAfter) {
    const key = meta.stopReason === "size_cap"
      ? "gui_traffic_archive_scan_incomplete_size_cap"
      : "gui_traffic_archive_scan_incomplete_deadline";
    return { tone: "warn", key: key, date: meta.incompleteAfter };
  }
  if (scanned === 0) return { tone: "crit", key: "gui_traffic_archive_scan_empty" };
  return { tone: "warn", key: "gui_traffic_archive_scan_no_match" };
}

/** archiveEmptyReason()'s key, translated — with the {date} param when the
 * reason carries one (the two "stopped partway" reasons). */
function archiveReasonText(reason) {
  return reason.date ? tf(reason.key, { date: reason.date }) : t(reason.key);
}

/* XC-09 — an empty result is a question, not a shrug. Each candidate cause is
 * paired with the reading that supports or rules it out, taken from the real
 * endpoints the appliance answers with:
 *   cache enabled?  cache_settings.enabled + cache_status row counts
 *   inside the window? traffic_raw_retention_days, or (archive) the real
 *     scanned/matched counts from the query that just ran — see
 *     archiveEmptyReason() above
 *   filters too tight? the live pill count and the quick-search string
 * quarantine.js:402-404 already distinguishes "archive not loaded" from "no
 * traffic"; this generalises that one distinction into the three the operator
 * can act on. */
function emptyCauses(state, d) {
  const settings = d.cache_settings || {};
  const cstat = d.cache_status || {};
  const list = el("ul", { class: "causes" });

  function cause(qKey, answer, tn, reason) {
    list.appendChild(el("li", { "data-tone": tn },
      el("span", { class: "q", text: t(qKey) }),
      el("span", { class: "a", "data-tone": tn, text: answer }),
      el("span", { class: "r", text: reason })
    ));
  }

  const on = settings.enabled === true;
  cause("gui_iv_cause_cache", on ? t("gui_enabled") : t("gui_state_off"), on ? "ok" : "crit",
    tf("gui_iv_cause_cache_r", { raw: num(cstat.traffic_raw), agg: num(cstat.traffic_agg) }));

  if (state.source === "archive") {
    const range = (state.archiveStart || "—") + " → " + (state.archiveEnd || "—");
    const reason = archiveEmptyReason(state);
    cause("gui_iv_cause_window", range, reason.tone, archiveReasonText(reason));
  } else {
    const days = settings.traffic_raw_retention_days;
    cause("gui_iv_cause_window", tf("gui_iv_days", { n: days === undefined ? "—" : days }), "info",
      tf("gui_iv_cause_window_r", { mins: state.mins }));
  }

  // the quick search is a condition like any other — count it, or a lone search
  // string reads as "0 conditions" beside the very string that emptied the table
  const conditions = Object.keys(state.filters || {}).length + (state.search ? 1 : 0);
  cause("gui_iv_cause_filter",
    conditions ? tf("gui_iv_cause_filter_n", { n: conditions }) : t("gui_iv_cause_filter_none"),
    conditions ? "warn" : "neutral",
    state.search ? tf("gui_iv_cause_filter_q", { q: state.search }) : t("gui_iv_cause_filter_none"));

  return list;
}

/* Density spec R1/R3 for a work page: the causes list below answers "why did
 * my query come back empty", which only means something once a query has
 * actually run. Before that, the honest answer is "you have not asked yet" —
 * showing the same diagnostic (cache on? window? filter count?) at page load,
 * with nothing queried, reads as a wall of caveats in front of an empty form.
 * workloads and events already draw this idle/empty distinction (their own
 * phase === "idle" checks below); this brings traffic in line with them. */
function emptyState(state, d) {
  if (state.phase === "idle") {
    return el("div", { class: "empty", "data-cov": "XC-09" },
      el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
      el("p", { text: t("gui_iv_search_prompt") })
    );
  }
  const archiveReason = state.source === "archive" ? archiveEmptyReason(state) : null;
  return el("div", { class: "empty", "data-cov": "XC-09" },
    el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
    el("p", { text: archiveReason ? archiveReasonText(archiveReason) : t("gui_no_traffic") }),
    emptyCauses(state, d)
  );
}

/* IV-06 — archive status strip, from the real GET /api/cache/archive/status.
 * Task 7: that endpoint no longer reports a review-DB "loaded" flag or a
 * background load's progress — there is no more review DB and no more load
 * to report progress on (archive queries stream the daily archive files
 * directly, Task 4/5). It now reports the archive FILES themselves:
 * `exists` (does the configured archive_dir exist), `files` (how many day
 * files are in it), and `earliest`/`latest` (the date range they cover).
 * Fix round 1, Important 2 previously hid this strip for source==="archive"
 * because the old "loaded review DB" reading was meaningless there (and
 * could contradict a real archive query's own results); that reading is
 * gone along with the review DB, so repaint() below renders this strip for
 * every source now — file coverage is exactly what an operator wants to see
 * before picking a date range on the archive source. */
function archiveStrip(d) {
  const a = d.archive_status || {};
  const has = a.exists === true && Number(a.files) > 0;
  const strip = el("div", { class: "strip", "data-cov": "IV-06", "data-tone": has ? "ok" : "neutral" });
  strip.appendChild(el("span", { text: t("gui_traffic_archive_range") }));
  strip.appendChild(el("b", { text: has
    ? tf("gui_traffic_archive_loaded_fmt", { start: a.earliest, end: a.latest, n: num(a.files) })
    : t("gui_traffic_archive_none") }));
  strip.appendChild(el("span", { class: "spacer" }));
  // PORT (header note 7): archive collection settings (archive_dir,
  // archive_enabled, ...) belong to the cache management page, so this is a
  // jump, not a fake action.
  strip.appendChild(el("button", { class: "btn link goto", type: "button",
    text: t("gui_health_goto") + " " + GO_CACHE, onClick: function () { router.go(GO_CACHE); } }));
  return strip;
}

/* IV-04 + XC-11 — the guide rail. Content is transcribed from the two shipping
 * help surfaces: index.html:2908-2942 (modal-qt-guide) and :2871-2905 (m-help).
 * Both are modals in the product; here they are a rail, because a syntax
 * reference you have to dismiss before typing is a reference you read once. */
function guideSection(cov, titleKey, descKey, groups) {
  const p = panel(cov, t(titleKey));
  p.body.appendChild(note(t(descKey)));
  const box = el("div", { class: "guide" });
  groups.forEach(function (grp) {
    const d = el("details");
    d.appendChild(el("summary", { text: t(grp[0]) }));
    const ul = el("ul");
    grp[1].forEach(function (key) { ul.appendChild(el("li", { text: t(key) })); });
    d.appendChild(ul);
    box.appendChild(d);
  });
  p.body.appendChild(box);
  return p;
}

function guideRail() {
  const aside = el("aside", { class: "wb-aside", "data-cov": "XC-11" });

  const traffic = guideSection("IV-04", "gui_ta_guide_title", "gui_ta_guide_desc", [
    ["gui_ta_guide_sec_search", ["gui_ta_guide_search_desc", "gui_ta_guide_li_proc", "gui_ta_guide_li_user",
      "gui_ta_guide_li_svc", "gui_ta_guide_li_wn", "gui_ta_guide_li_ip", "gui_ta_guide_li_port"]],
    ["gui_ta_guide_sec_adv", ["gui_ta_guide_adv_desc", "gui_ta_guide_li_labels", "gui_ta_guide_li_excludes", "gui_ta_guide_li_pd"]],
    ["gui_help_filters", ["gui_help_lf", "gui_help_ipf", "gui_help_pf"]],
    ["gui_help_pd", ["gui_help_pd_blk", "gui_help_pd_pot", "gui_help_pd_all"]],
  ]);
  aside.appendChild(traffic);

  // The quarantine half of the rail (coverage calls XC-11 the filter-syntax /
  // quarantine guide): index.html:2480 (gui_q_desc_line2) and :2493
  // (gui_q_direction_hint) are the product's own two sentences about what
  // quarantine can and cannot touch.
  const q = panel(null, t("gui_q_title"));
  q.body.appendChild(note(t("gui_q_desc_line2")));
  q.body.appendChild(note(t("gui_q_direction_hint")));
  q.body.appendChild(el("button", { class: "btn ghost", type: "button",
    text: t("gui_health_goto") + " " + R_WORKLOADS, onClick: function () { router.go(R_WORKLOADS); } }));
  aside.appendChild(q);
  return aside;
}

/* IV-03 + XC-03 + XC-04 — the advanced filter drawer: the ported FilterBar plus
 * the two policy-decision radio groups (index.html:2417-2455, modal-qt-filters).
 * The FilterBar's serialized dict is what goes into the POST body
 * (quarantine.js:293, Object.assign into the payload); the drawer does NOT show
 * that dict — the pills are what the operator reads (see refresh() below).
 * Returns {spec, bar} so the opener can destroy the bar on close
 * (components/drawer.mjs's documented onClose contract). */
function filtersDrawer(state, onApply) {
  const body = el("div", { "data-cov": "IV-03" });
  const barHost = el("div", { "data-cov": "XC-03" });
  body.appendChild(el("h4", { class: "eyebrow", text: t("gui_qt_object_filters") }));
  body.appendChild(barHost);

  const bar = createFilterBar(barHost, filterBarOpts(state.filters));

  /* The JSON echo of state.filters below the bar is gone, along with the note
   * that explained FilterBar's own key scheme (side-specific keys in AND mode,
   * any_* in OR mode). That was a description of the request format on a
   * surface whose job is to build a query — and the FilterBar above already
   * shows the operator what they picked, in the terms they picked it. */
  function refresh() {
    state.filters = bar.getFilters();
  }
  bar.onChange(refresh);
  refresh();

  body.appendChild(el("h4", { class: "eyebrow", text: t("gui_policy_dec") }));
  body.appendChild(el("div", { class: "fld" },
    el("label", null, el("span", { text: t("gui_pd_reported_label") })),
    radioGroup("iv-pd", PD_REPORTED, state.pd, function (v) { state.pd = v; })));
  body.appendChild(el("div", { class: "fld" },
    el("label", null, el("span", { text: t("gui_pd_draft_label") })),
    radioGroup("iv-dpd", PD_DRAFT, state.draftPd, function (v) { state.draftPd = v; })));


  const out = {};
  out.bar = bar;
  out.spec = drawerSpec(t("gui_qt_filters_title"), body, function () {
    state.filters = bar.getFilters();
    onApply();
    return true;
  });
  return out;
}

function filterBarOpts(initial) {
  const o = {};
  if (initial) o.initial = initial;
  return o;
}

/* XC-04 — the object browser. Production opens a modal (index.html:2458-2468 +
 * object-browser.js) with category tabs, a search box, a paged checkbox list and
 * an Add button; the mockup's modal component is reserved for destructive
 * confirmation, so the picker uses the drawer — same job, same Add-on-save
 * contract. Returns {spec, destroy} so the opener can drop the table.
 *
 * It reads the same two endpoints the filter bar does, through the same query
 * module (core/filter-objects.mjs), and keeps the same distinction the bar
 * keeps: an empty box BROWSES the category (paged, with a load-more), typed
 * text SEARCHES it server-side (debounced), a category the backend cannot list
 * at all — workload — says "search only" instead of showing an empty table,
 * and a failed lookup says so with a retry rather than rendering as zero rows.
 * Searching goes to the server rather than filtering the loaded page, because
 * the loaded page is one page: filtering it locally would silently answer "no
 * such object" for everything past the first sixty. */
const OB_PAGE = 60;
const OB_SEARCH_LIMIT = 25;
// Same 250 ms as the bar's own typing debounce — one box, one feel.
const OB_DEBOUNCE_MS = 250;

function obRec(cat, browseable) {
  const r = {};
  r.cat = cat;
  r.items = [];
  r.total = null;
  r.browseable = browseable;
  r.loading = false;
  r.error = null;
  return r;
}

function obFound(cat, query, items, loading, error) {
  const f = {};
  f.cat = cat;
  f.q = query;
  f.items = items;
  f.loading = loading;
  f.error = error;
  return f;
}

function obCanBrowse(cat) {
  let hit = true;
  OBJECT_CATS.forEach(function (row) { if (row[0] === cat) hit = row[2]; });
  return hit;
}

function objectBrowser(fbState) {
  const body = el("div", { "data-cov": "XC-04" });
  const chosen = {};
  const browsed = {};        // cat -> obRec, so switching tabs back re-reads nothing
  let cat = "label";
  let q = "";
  let found = null;          // the current search's obFound, or null while browsing
  let handle = null;
  let torn = false;
  let timer = null;
  let searchSeq = 0;

  const tabs = el("div", { class: "chips" });
  const listHost = el("div");
  const meta = el("p", { class: "note" });
  const statusHost = el("div");

  const search = el("input", { class: "field", placeholder: t("gui_ob_search_ph") });
  search.setAttribute("aria-label", t("gui_ob_search_ph"));
  search.addEventListener("input", function () { onSearchInput(); });

  function pick(item, category) {
    const o = {};
    o.item = item;
    o.cat = category;
    return o;
  }

  function rec(c) {
    if (!browsed[c]) browsed[c] = obRec(c, obCanBrowse(c));
    return browsed[c];
  }

  function loadBrowse(c) {
    const r = rec(c);
    if (r.loading || !r.browseable) return;
    r.loading = true;
    r.error = null;
    const offset = r.items.length;
    filterObjectQuery.browse(c, offset, OB_PAGE).then(function (b) {
      if (torn) return;
      r.loading = false;
      if (b && b.browseable === false) {
        r.browseable = false;
        r.total = null;
      } else {
        r.items = r.items.concat((b && b.items) || []);
        r.total = typeof (b || {}).total === "number" ? b.total : r.items.length;
      }
      if (cat === c && !q) paint();
    }, function () {
      if (torn) return;
      r.loading = false;
      r.error = "pce_unreachable";
      if (cat === c && !q) paint();
    });
    paint();
  }

  function runSearch(c, query) {
    const mySeq = ++searchSeq;
    filterObjectQuery.suggest(query, [c], OB_SEARCH_LIMIT).then(function (b) {
      if (torn || mySeq !== searchSeq) return;
      const r = ((b && b.results) || {})[c] || {};
      found = obFound(c, query, r.items || [], false, r.error || null);
      paint();
    }, function () {
      if (torn || mySeq !== searchSeq) return;
      found = obFound(c, query, [], false, "pce_unreachable");
      paint();
    });
  }

  function onSearchInput() {
    q = search.value.trim();
    if (timer) { clearTimeout(timer); timer = null; }
    searchSeq++;                       // any answer still in flight is stale now
    if (!q) {
      found = null;
      if (!rec(cat).items.length && rec(cat).browseable) loadBrowse(cat);
      else paint();
      return;
    }
    found = obFound(cat, q, [], true, null);
    paint();
    timer = setTimeout(function () { timer = null; runSearch(cat, q); }, OB_DEBOUNCE_MS);
  }

  function selectCat(c) {
    if (c === cat) return;
    cat = c;
    q = "";
    search.value = "";
    found = null;
    if (timer) { clearTimeout(timer); timer = null; }
    searchSeq++;
    if (obCanBrowse(c) && !rec(c).items.length && !rec(c).error) loadBrowse(c);
    else paint();
  }

  function retry() {
    if (q) { found = obFound(cat, q, [], true, null); paint(); runSearch(cat, q); return; }
    rec(cat).error = null;
    loadBrowse(cat);
  }

  /** The rows on screen, plus the one-line status above them. */
  function view() {
    const v = {};
    v.rows = [];
    v.status = "";
    v.error = null;
    v.more = false;
    if (q) {
      const f = found;
      v.rows = (f && !f.loading) ? f.items : [];
      if (f && f.loading) v.status = t("gui_fb_searching");
      else if (f && f.error) v.error = tf("gui_fb_offline_cats", { cats: t(catKey(cat)) });
      else v.status = v.rows.length ? tf("gui_table_rows", { total: v.rows.length }) : t("gui_fb_no_match");
      return v;
    }
    const r = rec(cat);
    if (!r.browseable) {
      v.status = t("gui_fb_search_only");
      return v;
    }
    v.rows = r.items;
    if (r.error) v.error = t("gui_fb_browse_error");
    else if (r.loading) v.status = t("gui_fb_loading");
    else if (typeof r.total === "number" && r.items.length < r.total) {
      v.status = tf("gui_fb_shown_of", { shown: r.items.length, total: r.total });
      v.more = true;
    } else {
      v.status = r.items.length ? tf("gui_table_rows", { total: r.items.length }) : t("gui_fb_no_match");
    }
    return v;
  }

  function catKey(c) {
    let key = "gui_fb_cat_label";
    OBJECT_CATS.forEach(function (row) { if (row[0] === c) key = row[1]; });
    return key;
  }

  function detailOf(r) {
    if (r.summary) return String(r.summary);
    const parts = [];
    if (r.hostname && r.hostname !== r.name) parts.push(r.hostname);
    if (r.ip) parts.push(r.ip);
    return parts.length ? parts.join(" · ") : "";
  }

  function paint() {
    if (handle) { handle.destroy(); handle = null; }
    clear(tabs);
    clear(statusHost);
    OBJECT_CATS.forEach(function (row) {
      const b = btn("btn ghost", t(row[1]), function () { selectCat(row[0]); });
      b.setAttribute("aria-pressed", row[0] === cat ? "true" : "false");
      tabs.appendChild(b);
    });

    const v = view();
    meta.textContent = v.status;
    if (v.error) {
      const box = el("div", { class: "fb-dd-err", "data-tone": "warn" },
        el("span", { class: "fb-dd-err-txt", text: v.error }));
      box.appendChild(btn("fb-dd-retry", t("gui_fb_retry"), retry));
      statusHost.appendChild(box);
    }

    const cols = [
      col("pick", "", widthCell(34, function (r) {
        const cb = el("input", { type: "checkbox" });
        cb.setAttribute("aria-label", String(r.name || ""));
        cb.checked = !!chosen[r.href || r.name];
        cb.addEventListener("change", function () {
          // The category is captured WITH the item, not read at save time: a
          // selection made under one tab and saved after switching to another
          // would otherwise be added as a pill of the wrong category.
          if (cb.checked) chosen[r.href || r.name] = pick(r, cat);
          else delete chosen[r.href || r.name];
        });
        return cb;
      })),
      col("key", t("gui_col_type"), widthCell(90, function (r) { return el("span", { class: "mono", text: r.key || cat }); })),
      col("name", t("gui_col_name"), buildCell(function (r) {
        const detail = detailOf(r);
        if (!detail) return r.name;
        return el("span", null, el("span", { text: String(r.name || "") }),
          el("span", { class: "s mono", text: " " + detail }));
      })),
    ];
    // No rows means one of four things — search-only category, still loading,
    // a lookup that failed, or genuinely nothing found — and the line above
    // says which. Rendering the table's own "no data" card underneath any of
    // them would state the one thing that is not known to be true.
    clear(listHost);
    if (v.rows.length) handle = table.render(listHost, buildTable(cols, v.rows));
    if (v.more) statusHost.appendChild(btn("btn ghost", t("gui_fb_load_more"), function () { loadBrowse(cat); }));
  }

  body.appendChild(tabs);
  body.appendChild(el("div", { class: "fld" }, search));
  body.appendChild(meta);
  body.appendChild(statusHost);
  body.appendChild(listHost);
  if (obCanBrowse(cat)) loadBrowse(cat);
  else paint();

  const out = {};
  out.destroy = function () {
    torn = true;
    if (timer) { clearTimeout(timer); timer = null; }
    if (handle) handle.destroy();
    handle = null;
  };
  out.spec = drawerSpec(t("gui_ob_title"), body, function () {
    const picked = Object.keys(chosen);
    picked.forEach(function (k) {
      const entry = chosen[k];
      const obj = {};
      obj.cat = entry.cat;
      obj.name = entry.item.name;
      obj.href = entry.item.href || null;
      addPillFromBrowser(fbState, obj);
    });
    if (picked.length) toast.ok(tf("gui_iv_browser_added", { n: picked.length }));
    return true;
  });
  return out;
}

/* IV-07 — cache backfill. Fields transcribed from index.html:2542-2578
 * (m-cache-backfill): source select, start/end date, the four quick ranges.
 * PORT: Save posts to the real POST /api/cache/backfill. See header note 5 for
 * why the response is checked for `error` rather than `ok`, and why the dates
 * are not pre-validated here. */
function backfillDrawer(state) {
  const body = el("div", { "data-cov": "IV-07" });
  body.appendChild(note(t("gui_cb_desc")));

  const view = {};
  view.source = "events";
  const start = el("input", { class: "field", type: "date" });
  start.setAttribute("aria-label", t("gui_gen_start_date"));
  const end = el("input", { class: "field", type: "date" });
  end.setAttribute("aria-label", t("gui_gen_end_date"));

  body.appendChild(el("div", { class: "fld" },
    selectField(t("gui_cb_source"), BACKFILL_SOURCES, view.source, function (v) { view.source = v; })));
  body.appendChild(el("div", { class: "fld" },
    el("div", { class: "qrow" }, field(t("gui_gen_start_date"), start), field(t("gui_gen_end_date"), end))));

  const quick = el("div", { class: "qrow" });
  BACKFILL_RANGES.forEach(function (days) {
    quick.appendChild(el("button", { class: "btn ghost", type: "button", text: tf("gui_iv_days_short", { n: days }), onClick: function () {
      // index.html:2566-2569 setDateRange("cb", days) — end today, start N days back
      const now = new Date();
      const from = new Date(now.getTime() - Number(days) * 86400000);
      end.value = now.toISOString().slice(0, 10);
      start.value = from.toISOString().slice(0, 10);
    } }));
  });
  body.appendChild(el("div", { class: "fld" },
    el("label", null, el("span", { text: t("gui_quick_range") })), quick));
  body.appendChild(note(t("gui_iv_backfill_note")));

  return drawerSpec(t("gui_cb_title"), body, async function () {
    const payload = {};
    payload.source = view.source;
    payload.since = start.value;
    payload.until = end.value;
    toast.info(t("gui_cb_running"));
    const r = await api.post("/api/cache/backfill", payload);
    if (state.torn) return true;
    // pce_cache/web.py:47-98 answers with no `ok` key either way — `error` is
    // the only discriminator, in both the 400 and the 5xx branch.
    if (r && r.error) {
      toast.crit(errText(r));
      return false;
    }
    toast.ok(tf("gui_iv_backfill_done", {
      total: num((r || {}).total_rows), inserted: num((r || {}).inserted), duplicates: num((r || {}).duplicates),
    }));
    return true;
  });
}

/**
 * IV-01/IV-02/IV-05 — the real flow search.
 * Payload transcribed from quarantine.js:271-296 runTrafficAnalyzer:
 *   {mins, sort_by, search, source|data_source, policy_decision} +
 *   draft_policy_decision only when one is chosen + the FilterBar dict spread
 *   on top.
 * Backend contract (actions.py:79-320, Task 4/5) checked key by key before
 * writing this:
 *   - most keys are read with defaults, so an ABSENT key is identical to an
 *     empty one (data_source -> resolve_data_source's own "hybrid" default,
 *     policy_decision -> "-1" = all, every filter list -> []). `mins` is the
 *     exception: absent defaults to 30, but an explicit empty value fails
 *     integer parsing (actions.py:113). The runtime always sends a number.
 *     That is why the FilterBar's dict is spread as-is: it omits a key
 *     entirely when no pill sets it, and omission is the documented "no
 *     filter" state, not a fall-through to another branch. (The one place in
 *     this codebase where that assumption did NOT hold is dashboard.py's save
 *     endpoint — see areas/overview.mjs — so it was verified here rather than
 *     assumed.)
 *   - policy_decision "" would fall into the else branch = all four decisions,
 *     the same as "-1"; "-1" is sent anyway because that is what the shipping
 *     GUI sends.
 *   - `source` selects the backend BRANCH: "archive" streams the archive's
 *     daily files for [archive_start, archive_end]; anything else (this GUI
 *     never sends "source" for hybrid/live — see header note) is the live
 *     branch, which reads the separate `data_source` field
 *     (hybrid|cache|live|no-cache|api, actions.py's
 *     _TRAFFIC_DATA_SOURCE_VALUES — this control only ever sends "hybrid" or
 *     "live") to decide cache vs. PCE. Task 6's SOURCES control conflates
 *     both under one operator-facing choice; this function is where they
 *     split back apart.
 *   - a live-source failure answers 502 {ok:false,error}; an archive source
 *     with unsupported filter keys answers 400 {ok:false,unsupported,error}
 *     (see runQuery's translation of `unsupported` — Task 6 constraint 2).
 */
function trafficPayload(state) {
  const payload = {};
  payload.mins = Number(state.mins);
  payload.sort_by = state.sort;
  payload.search = state.search;
  if (state.source === "archive") {
    payload.source = "archive";
    payload.archive_start = state.archiveStart;
    payload.archive_end = state.archiveEnd;
  } else {
    payload.data_source = state.source; // "hybrid" | "live"
  }
  payload.policy_decision = state.pd || "-1";
  if (state.draftPd) payload.draft_policy_decision = state.draftPd;
  return Object.assign(payload, state.filters || {});
}

async function mountTraffic(root, ctx) {
  const handles = {};
  const state = {};
  state.torn = false;
  state.tables = [];
  installTeardown(state);
  audit.register("iv-traffic-empty", function () { if (handles.probeEmpty) handles.probeEmpty(); });
  drawer.registerAudit("iv-traffic-filters", function () { return handles.openFilters ? handles.openFilters() : null; });
  drawer.registerAudit("iv-traffic-browser", function () { return handles.openBrowser ? handles.openBrowser() : null; });
  drawer.registerAudit("iv-traffic-backfill", function () { return handles.openBackfill ? handles.openBackfill() : null; });
  drawer.registerAudit("iv-traffic-bulk", function () { return handles.openBulk ? handles.openBulk() : null; });
  palette.registerFor(R_TRAFFIC, cmdSpec("iv:filters", t("gui_filter_settings"), function () {
    if (handles.openFilters) handles.openFilters();
  }));
  palette.registerFor(R_TRAFFIC, cmdSpec("iv:backfill", t("gui_cb_title"), function () {
    if (handles.openBackfill) handles.openBackfill();
  }));

  root.appendChild(areaTop(R_TRAFFIC));
  const wrap = el("div", { class: "wb" });
  const main = el("div", { class: "wb-main" });
  wrap.appendChild(main);
  wrap.appendChild(guideRail());
  root.appendChild(wrap);

  await withErrorCard(main, "traffic (" + TRAFFIC_SNAPS.length + ")",
    function () { return loadAll(TRAFFIC_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      setFilterBarText(t);
      // The bar asks the server itself, per keystroke and per category opened
      // (core/filter-objects.mjs) — nothing PCE-backed is fetched until a
      // filters drawer is actually opened, so the traffic view still paints
      // without waiting on the PCE.
      setFilterBarQuery(filterObjectQuery);

      state.mins = "60";
      state.sort = "bandwidth";
      // "hybrid" — cache first, PCE for the gap — is resolve_data_source's
      // own default when data_source is absent, so this default preserves
      // the old unlabelled behaviour; it is just named honestly now.
      state.source = "hybrid";
      state.archiveStart = "";
      state.archiveEnd = "";
      state.search = "";
      state.size = 50;
      state.page = 0;
      state.pd = "";
      state.draftPd = "";
      state.filters = {};
      state.phase = "idle";     // idle | busy | done
      state.rows = [];
      state.meta = {};
      state.seq = 0;
      // {srcHref, dstHref} pairs checked via the pick column — bulk isolation
      // contributes PAIRS here (quarantine.js:66-68, .qt-chk -> addPair), not
      // standalone hrefs the way the workloads table's .qw-chk does (:69-71).
      state.selected = [];

      const search = el("input", { class: "field", placeholder: t("gui_quick_search_placeholder") });
      search.setAttribute("aria-label", t("gui_filter_details"));
      const host = el("div");
      const floatHost = el("div");
      // The empty state is reachable in the normal course of events here (a
      // query that matches nothing), but not once the PCE returns the 500-row
      // cap — so, exactly as the mockup did, the audit hook runs the REAL
      // renderer over a filter that genuinely matches nothing, into its own
      // container, leaving the live results (and XC-12 on them) untouched.
      const probe = el("div", { class: "wb-main" });

      function pairKey(p) { return JSON.stringify([p.srcHref || "", p.dstHref || ""]); }

      function isTrafficSelected(r) {
        const key = pairKey(r);
        return state.selected.some(function (p) { return pairKey(p) === key; });
      }

      function toggleTrafficSel(r, on) {
        const key = pairKey(r);
        const at = state.selected.findIndex(function (p) { return pairKey(p) === key; });
        if (on && at < 0) state.selected.push({ srcHref: r.srcHref, dstHref: r.dstHref });
        if (!on && at >= 0) state.selected.splice(at, 1);
        paintFloatTraffic();
      }

      // index.html:1131-1148 (#bulk-bar) shared by both tables in production;
      // this route's slice of it only offers Apply Quarantine — the bulk
      // Accelerate action reads .qw-chk exclusively (quarantine.js:685), so it
      // would be a silent no-op button here and is not rendered.
      function paintFloatTraffic() {
        clear(floatHost);
        if (!state.selected.length) return;
        const bar = el("div", { class: "floatbar", "data-tone": "crit" },
          el("span", { text: t("gui_selected") + " " }),
          el("b", { text: String(state.selected.length) }),
          el("span", { text: " " + t("gui_flows") }),
          el("button", { class: "btn danger", type: "button", text: t("gui_q_apply"),
            onClick: function () { handles.openBulk(); } })
        );
        floatHost.appendChild(bar);
      }

      const rankHost = el("div", { class: "rankings" });
      state.rankState = state.rankState || { torn: false, chartHandles: [] };

      function repaint() {
        state.tables.forEach(function (h) { h.destroy(); });
        state.tables = [];
        clear(host);
        host.appendChild(kpiRow(state.rows, state.phase));
        host.appendChild(query);
        // Task 7 — see archiveStrip()'s own header: it now reports real
        // archive-file coverage, not a review-DB "loaded" flag, so it is
        // useful (and rendered) for every source, including "archive".
        host.appendChild(archiveStrip(d));
        host.appendChild(results());
        // v3: the Top10 ranking + saved-query widgets (OV-05 / OV-04) moved here
        // from the overview; mounted once, re-attached on every repaint.
        host.appendChild(rankHost);
        paintFloatTraffic();
      }

      /** The real POST. One sequence number guards against an earlier, slower
       *  query landing after a later one (the PCE search can take seconds). */
      async function runQuery() {
        const seq = ++state.seq;
        state.phase = "busy";
        state.page = 0;
        state.selected = [];
        repaint();
        const r = await api.post("/api/quarantine/search", trafficPayload(state));
        if (state.torn || seq !== state.seq) return;
        state.phase = "done";
        if (!r || r.ok !== true) {
          state.rows = [];
          // Task 6 constraint 2: an archive query rejected for unsupported
          // filter keys carries those RAW keys in both r.unsupported and
          // (interpolated) r.error — actions.py:197-206. errText(r) must
          // never be used for this branch; the message is rebuilt from
          // translated display names instead, mirroring the backend's own
          // search-vs-other-keys branch (actions.py:197-201) so the wording
          // still distinguishes "can't search archived text" from "can't
          // evaluate these conditions" without ever printing a field name.
          const unsupported = (r && Array.isArray(r.unsupported)) ? r.unsupported : [];
          if (unsupported.indexOf("search") >= 0) {
            state.meta = { error: t("gui_err_archive_search_unsupported") };
          } else if (unsupported.length) {
            state.meta = { error: tf("gui_err_archive_filter_unsupported", {
              keys: unsupported.map(unsupportedLabel).join(", "),
            }) };
          } else {
            state.meta = { error: errText(r) };
          }
          repaint();
          toast.crit(state.meta.error);
          return;
        }
        // live answers {data, total_matches, cap}; archive answers {rows,
        // matched, scanned} (actions.py:266-279) — neither field name exists
        // on the other branch's response.
        state.rows = r.data || r.rows || [];
        state.meta = {};
        state.meta.truncated = !!r.truncated;
        state.meta.actualSource = r.actual_source || "";
        // Fix round 1, Important 2 — `scanned`/`matched` (archive only; both
        // undefined on a live response) are the real reason an archive query
        // came back empty: how many daily files covered the date range, and
        // how many of their rows matched. Replaces the old `not_loaded`
        // reading, which the new direct date-range scan never sends —
        // archiveEmptyReason() below is the sole consumer.
        state.meta.scanned = r.scanned;
        state.meta.matched = r.matched;
        // Final review F3 — how many rows/files the scan itself discarded
        // (archive_query.py's ArchiveQueryResult.skipped/files_incomplete):
        // a result computed after quietly dropping rows must say so.
        state.meta.skipped = r.skipped || 0;
        state.meta.filesIncomplete = r.files_incomplete || 0;
        // Final review F2/F5 — the scan gave up partway through the date
        // range (deadline or the memory-bound size cap, actions.py's
        // stop_reason): before this, the backend computed and returned
        // `incomplete_after` but nothing here ever read it, so a 27-day
        // truncated scan and a genuinely complete one rendered identically.
        state.meta.incompleteAfter = r.incomplete_after || null;
        state.meta.stopReason = r.stop_reason || null;
        repaint();
        toast.ok(tf("gui_iv_query_done", { n: num(state.rows.length) }));
      }

      // ── controls (IV-01 / IV-02) ──
      const query = panel("IV-01", t("gui_ta_query"));
      withAction(query, t("gui_cb_title"), function () { if (handles.openBackfill) handles.openBackfill(); });
      withAction(query, t("gui_filter_settings"), function () { if (handles.openFilters) handles.openFilters(); });
      const searchField = field(t("gui_filter_details"), search);
      searchField.className = "qf grow";
      // PORT: `search` is a request field (actions.py:141), not a local filter,
      // so it takes effect on the next run — Enter runs it, like any query box.
      search.addEventListener("input", function () { state.search = search.value.trim(); });
      search.addEventListener("keydown", function (e) { if (e.key === "Enter") runQuery(); });
      const runBtn = el("button", { class: "btn primary", type: "button", text: t("gui_query_flow"),
        onClick: function () { runQuery(); } });

      /* Task 6 constraint 1 — the row is REBUILT (not just mutated) whenever
       * the source changes, because two things depend on it: the sort options
       * (archive drops "bandwidth" — ARCHIVE_SORTS) and the archive date
       * inputs. Switching TO archive while the pending sort is still
       * "bandwidth" (the page's default) moves it to the archive's first
       * supported option BEFORE the row is rebuilt, so the dropdown never
       * shows — and runQuery() never sends — a value the archive endpoint
       * would reject with sort_by_substituted or a 400. searchField/runBtn
       * are built once above and re-appended (not recreated) on each rebuild,
       * so their listeners and the search box's typed value survive a
       * source switch. */
      let queryRow = null;
      function buildQueryRow() {
        const row = el("div", { class: "qrow" });
        // Fix round 1, Important 1 — actions.py reads `mins` only after the
        // archive branch's own early return (actions.py:~293 vs. the archive
        // branch's returns around :202-279), so it is never honoured for an
        // archive query. The archive's date range has taken over the window
        // control's job; a control that does nothing when used is worse than
        // an absent one, so it is not rendered at all in archive mode.
        // `state.mins` itself is untouched by this — only the DOM node is
        // omitted — so the operator's prior pick is still there, selected,
        // the moment the source switches back to a live one.
        if (state.source !== "archive") {
          row.appendChild(selectField(t("gui_window"), WINDOWS, state.mins, function (v) { state.mins = v; }));
        }
        const src = selectField(t("gui_traffic_source"), SOURCES, state.source, function (v) {
          state.source = v;
          if (state.source === "archive" && state.sort === "bandwidth") state.sort = "volume";
          const next = buildQueryRow();
          query.body.replaceChild(next, queryRow);
          queryRow = next;
        });
        src.setAttribute("data-cov", "IV-02");
        row.appendChild(src);
        const sortOpts = state.source === "archive" ? ARCHIVE_SORTS : SORTS;
        row.appendChild(selectField(t("gui_sort_by"), sortOpts, state.sort, function (v) { state.sort = v; }));
        if (state.source === "archive") {
          const start = el("input", { class: "field", type: "date" });
          start.setAttribute("aria-label", t("gui_gen_start_date"));
          start.value = state.archiveStart;
          start.addEventListener("change", function () { state.archiveStart = start.value; });
          const end = el("input", { class: "field", type: "date" });
          end.setAttribute("aria-label", t("gui_gen_end_date"));
          end.value = state.archiveEnd;
          end.addEventListener("change", function () { state.archiveEnd = end.value; });
          row.appendChild(field(t("gui_gen_start_date"), start));
          row.appendChild(field(t("gui_gen_end_date"), end));
        }
        row.appendChild(searchField);
        row.appendChild(el("span", { class: "spacer" }));
        row.appendChild(runBtn);
        return row;
      }
      queryRow = buildQueryRow();
      query.body.appendChild(queryRow);

      // ── results (IV-05 + XC-12) ──
      function results() {
        const p = panel("IV-05", t("gui_traffic_analyzer"));
        withMeta(p, tf("gui_total_found", { count: num(state.rows.length) }));
        headBox(p).appendChild(selectField(t("gui_page_size"), PAGE_SIZES, String(state.size), function (v) {
          state.size = Number(v);
          state.page = 0;
          repaint();
        }).control);

        if (state.meta.error) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "crit" },
            el("i", { class: "dot" }), el("span", { text: state.meta.error })));
        }
        // actual_source (Task 4/5): which path really answered — cache, a
        // live PCE query, a mix of the two, or the archive. Rendered
        // whenever the field is present, independent of source/tone above.
        if (state.meta.actualSource) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "info" },
            el("i", { class: "dot" }), el("span", { text: actualSourceText(state.meta.actualSource) })));
        }
        // quarantine.js:391-394 — a truncated result is warned about ONCE, in
        // words, because every figure above it is a floor and not a total.
        // Kept param-free (unlike gui_results_truncated, used elsewhere in
        // this file): live returns {cap,total_matches}, archive returns
        // {matched,scanned} — no single pair of numbers exists on both.
        if (state.meta.truncated) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
            el("i", { class: "dot" }), el("span", { text: t("gui_traffic_truncated") })));
        }
        // Final review F2/F5 — the scan stopped before reaching the end of
        // the requested date range (deadline, or the memory-bound size cap
        // — archive_query.py's MAX_TRACKED_FLOWS). A partial result must not
        // look identical to a complete one, and which reason it stopped for
        // is itself a different fact from how far it got: a size cap means
        // this query's own result set is large — a narrower range would
        // help; a deadline may just mean this run was slow.
        if (state.meta.incompleteAfter) {
          const stopKey = state.meta.stopReason === "size_cap"
            ? "gui_traffic_archive_incomplete_size_cap"
            : "gui_traffic_archive_incomplete_deadline";
          p.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
            el("i", { class: "dot" }),
            el("span", { text: tf(stopKey, { date: state.meta.incompleteAfter }) })));
        }
        // Final review F3 — rows the scan could not parse, and archive files
        // (or the truncated remainder of one) it could not read at all,
        // while producing this result (archive_query.py's skipped /
        // files_incomplete). Spec §4.3: a result computed after discarding
        // rows must say so — these were silently dropped before, visible
        // only in a server log the operator never sees.
        if (state.meta.skipped) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
            el("i", { class: "dot" }),
            el("span", { text: tf("gui_traffic_archive_skipped_rows", { n: num(state.meta.skipped) }) })));
        }
        if (state.meta.filesIncomplete) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
            el("i", { class: "dot" }),
            el("span", { text: tf("gui_traffic_archive_files_incomplete", { n: num(state.meta.filesIncomplete) }) })));
        }
        // Final review F8 — summary_omitted (Task 4's SUMMARY_TOP_K bound)
        // used to be announced here even though the aggregate summary it
        // refers to is never rendered (spec §5 defers that to a later
        // phase): telling the operator "N groups were left out" of a
        // summary they cannot see is a notice about nothing they can act
        // on. The response still carries `summary_omitted` for whenever
        // that summary view lands; this view just does not narrate it yet.
        // The table host carries XC-12 — the skeleton while a query runs, the
        // column resize grips, the service popover and the query toast all
        // live in it. It is created unconditionally, including for the empty
        // state: the mockup could anchor XC-12 on the table alone because its
        // snapshot always had rows, but here "no rows yet" is the state the
        // page opens in, and an anchor that only exists once a live PCE
        // answers is an anchor the coverage gate can never see.
        const tblHost = el("div", { "data-cov": "XC-12" });
        p.body.appendChild(tblHost);
        if (state.phase !== "busy" && !state.rows.length) {
          tblHost.appendChild(emptyState(state, d));
          return p;
        }
        p.body.classList.add("flush");
        if (state.phase === "busy") {
          state.tables.push(table.render(tblHost, buildTable(trafficColumns(function () { }, emptySel), null)));
          return p;
        }
        const model = trafficRows(state.rows, state.sort);
        const shown = model.slice(state.page * state.size, (state.page + 1) * state.size);
        const sel = { isChecked: isTrafficSelected, toggle: toggleTrafficSel };
        state.tables.push(table.render(tblHost, pagedTable(
          trafficColumns(function (r) { handles.openIsolate(r); }, sel),
          shown, pageSpec(state.page, state.size, model.length), function (next) {
            state.page = Math.max(0, next);
            repaint();
          })));
        return p;
      }

      main.appendChild(host);
      main.appendChild(probe);
      main.appendChild(floatHost);

      handles.openFilters = function () {
        const built = filtersDrawer(state, function () {
          toast.ok(tf("gui_iv_filters_applied", { n: Object.keys(state.filters).length }));
          runQuery();
        });
        const h = drawer.open(built.spec);
        h.el.classList.add("wide");        // three zones need the room
        // components/drawer.mjs's documented teardown contract for a stateful
        // component mounted in a drawer body.
        h.onClose(function () { built.bar.destroy(); });
        return h;
      };
      handles.openBackfill = function () { return drawer.open(backfillDrawer(state)); };
      handles.openIsolate = function (r) {
        hrefNames.set(r.srcHref, (r.src || {}).name || r.srcHref);
        hrefNames.set(r.dstHref, (r.dst || {}).name || r.dstHref);
        const qstate = buildQuarantineState(r.srcHref || r.dstHref, false,
          r.srcHref && r.dstHref ? r.dstHref : null, null);
        return drawer.open(quarantineDrawer(state, qstate, false));
      };
      // quarantine.js:66-68 — bulk isolation off the traffic table contributes
      // src/dst PAIRS, not standalone hrefs (that is what the workloads table's
      // .qw-chk selection does).
      handles.openBulk = function () {
        const chosen = state.selected.slice();
        return drawer.open(quarantineDrawer(state, buildQuarantineState(null, true, null, null, chosen), true));
      };
      handles.probeEmpty = function () {
        if (probe.firstChild) return;                     // idempotent
        const probeState = Object.assign({}, state);
        probeState.search = "__no_such_flow__";
        // The idle/empty split above reads phase, and this probe runs
        // whenever the audit is triggered — including before any real query,
        // when state.phase is still "idle". The probe's whole point is to
        // exercise the real causes-diagnostic renderer, so it always presents
        // as a query that ran and matched nothing, regardless of what has
        // actually happened on screen yet.
        probeState.phase = "done";
        const p = panel(null, t("gui_traffic_analyzer"));
        withMeta(p, tf("gui_total_found", { count: 0 }));
        p.body.appendChild(emptyState(probeState, d));
        probe.appendChild(p);
      };
      setFilterBarBrowser(function (fbState) {
        const built = objectBrowser(fbState);
        const h = drawer.open(built.spec);
        h.el.classList.add("wide");
        h.onClose(built.destroy);
      });
      handles.openBrowser = function () {
        // the browser needs a live bar to add pills to; open the filter drawer first
        const filters = handles.openFilters();
        const fbHost = filters.el.querySelector("[data-cov=\"XC-03\"]");
        const fbState = fbHost && window._objfbGetInstance ? window._objfbGetInstance(fbHost.dataset.objfbId) : null;
        if (!fbState) return null;
        const built = objectBrowser(fbState);
        const h = drawer.open(built.spec);
        h.el.classList.add("wide");
        h.onClose(built.destroy);
        return h;
      };
      // A quarantine applied from this table changes the labels its rows show,
      // so re-run the same query rather than patching a row locally.
      state.onQuarantined = function () { if (state.phase === "done") runQuery(); };

      repaint();
      // v3: mount the rankings row once the first paint has attached rankHost
      mountRankingsAndQueries(rankHost, d, state.rankState);
    });
}

// ═════════════════════════════════════════════════════ workloads ════════════

/* quarantine.js:48-79 (_buildQuarantineState) — a bulk selection contributes
 * standalone hrefs AND pairs at once: `.qw-chk` (workload table rows) adds a
 * standalone href each (:69-71), `.qt-chk` (traffic table rows) adds a
 * src/dst PAIR each (:66-68). A single (non-bulk) row with two distinct ends
 * contributes one pair; anything else is standalone. */
function buildQuarantineState(href, isBulk, altHref, selectedHrefs, selectedPairs) {
  const state = {};
  state.pairs = [];
  state.standalone = [];
  const addPair = function (sourceHref, destinationHref) {
    const source = String(sourceHref || "").trim();
    const destination = String(destinationHref || "").trim();
    if (!source && !destination) return;
    if (state.pairs.some(function (p) { return p.source === source && p.destination === destination; })) return;
    const pair = {};
    pair.source = source;
    pair.destination = destination;
    state.pairs.push(pair);
  };
  const addStandalone = function (targetHref) {
    const normalized = String(targetHref || "").trim();
    if (!normalized || state.standalone.includes(normalized)) return;
    state.standalone.push(normalized);
  };
  if (isBulk) {
    (selectedHrefs || []).forEach(addStandalone);
    (selectedPairs || []).forEach(function (p) { addPair(p.srcHref, p.dstHref); });
  } else if (altHref && href && altHref !== href) {
    addPair(href, altHref);
  } else {
    addStandalone(href);
  }
  return state;
}

/* quarantine.js:86-112 (_computeQuarantineTargets) — transcribed. The order is
 * load-bearing (standalone first, then pairs) and so is the collapse rule: a
 * pair missing an end, or whose ends are the same workload, contributes ONE
 * target regardless of the chosen direction. */
function computeQuarantineTargets(qstate, direction) {
  const targets = [];
  const pushUnique = function (href) {
    const normalized = String(href || "").trim();
    if (normalized && !targets.includes(normalized)) targets.push(normalized);
  };
  (qstate.standalone || []).forEach(pushUnique);
  (qstate.pairs || []).forEach(function (pair) {
    if (!pair.source || !pair.destination || pair.source === pair.destination) {
      pushUnique(pair.source || pair.destination);
      return;
    }
    if (direction === "both") {
      pushUnique(pair.source);
      pushUnique(pair.destination);
      return;
    }
    if (direction === "destination") {
      pushUnique(pair.destination);
      return;
    }
    pushUnique(pair.source);
  });
  return targets;
}

/**
 * The real quarantine call. One target goes through POST /api/quarantine/apply
 * ({href, level}); several go through POST /api/quarantine/bulk_apply
 * ({hrefs, level}) — the same split quarantine.js makes, and the same one the
 * two routes are written for (actions.py:301 vs :347).
 *
 * Backend contract, read before writing this (actions.py:301-405):
 *   - `level` is looked up in the Quarantine label map with .get(level), so an
 *     ABSENT or unknown level yields None and the route refuses with
 *     gui_label_fetch_failed rather than doing anything — the level is always
 *     sent, and this function never omits it.
 *   - `href` absent -> _is_workload_href(None) is False -> the route refuses
 *     with gui_q_invalid_target before contacting the PCE at all.
 *   - bulk answers 200 {ok:true, results:{success, failed[], skipped_invalid}}
 *     even when every single target failed, so success is reported from
 *     `results`, never from `ok` alone.
 */
async function applyQuarantine(targets, level) {
  if (targets.length === 1) {
    const r = await api.post("/api/quarantine/apply", { href: targets[0], level: level });
    if (!r || r.ok !== true) return { ok: false, error: errText(r) };
    return { ok: true, success: 1, failed: 0 };
  }
  const r = await api.post("/api/quarantine/bulk_apply", { hrefs: targets, level: level });
  if (!r || r.ok !== true) return { ok: false, error: errText(r) };
  const res = r.results || {};
  return { ok: true, success: Number(res.success || 0), failed: (res.failed || []).length };
}

/* IV-09 / IV-10 / XC-08 — the quarantine drawer, then the confirmation, then
 * the real call. index.html:2471-2511 (m-quarantine): the direction radios
 * appear only when a pair has two distinct ends (:141-142), and default to
 * 'both' for a bulk selection with such a pair, 'source' otherwise (:143). */
function quarantineDrawer(areaState, qstate, isBulk) {
  const cov = isBulk ? "IV-10" : "IV-09";
  const body = el("div", { "data-cov": cov });
  const hasDualPair = (qstate.pairs || []).some(function (p) {
    return p.source && p.destination && p.source !== p.destination;
  });
  const view = {};
  view.direction = isBulk && hasDualPair ? "both" : "source";
  view.level = "Mild";

  const count = el("b", { class: "mono" });
  const listBox = el("ul", { class: "impact" });

  function refresh() {
    const targets = computeQuarantineTargets(qstate, view.direction);
    count.textContent = String(targets.length);
    clear(listBox);
    targets.slice(0, 8).forEach(function (h) { listBox.appendChild(el("li", { text: nameOf(h) })); });
    if (!targets.length) listBox.appendChild(el("li", { text: t("gui_q_no_targets") }));
    if (targets.length > 8) listBox.appendChild(el("li", { text: tf("gui_iv_more_targets", { n: targets.length - 8 }) }));
    return targets;
  }

  body.appendChild(el("p", null,
    el("span", { text: t("gui_q_desc_prefix") + " " }), count,
    el("span", { text: " " + t("gui_q_desc_suffix") })));
  body.appendChild(note(t("gui_q_desc_line2")));

  if (hasDualPair) {
    body.appendChild(el("div", { class: "fld" },
      el("label", null, el("span", { text: t("gui_q_which") })),
      radioGroup("iv-qdir", DIRECTIONS, view.direction, function (v) { view.direction = v; refresh(); })));
    body.appendChild(note(t("gui_q_direction_hint")));
  }

  body.appendChild(el("div", { class: "fld" },
    selectField(t("gui_q_sev"), SEVERITIES, view.level, function (v) { view.level = v; })));
  body.appendChild(el("h4", { class: "eyebrow", text: t("gui_target") }));
  body.appendChild(listBox);
  refresh();

  return drawerSpec(t("gui_q_title"), body, function () {
    const targets = refresh();
    if (!targets.length) {
      toast.warn(t("gui_q_no_targets"));
      return false;
    }
    const impact = [tf("gui_q_confirm_apply", { count: targets.length, level: t(lookup(SEVERITIES, view.level, "gui_opt_mild")) })];
    if (hasDualPair) impact.push(t("gui_q_which") + " " + t(lookup(DIRECTIONS, view.direction, "gui_q_src")));
    targets.slice(0, 6).forEach(function (h) { impact.push(nameOf(h)); });
    if (targets.length > 6) impact.push(tf("gui_iv_more_targets", { n: targets.length - 6 }));
    modal.confirm(confirmSpec(t("gui_q_apply"), impact, async function () {
      toast.info(t("gui_q_applying"));
      const r = await applyQuarantine(targets, view.level);
      if (areaState.torn) return;
      if (!r.ok) {
        toast.crit(t("gui_q_apply_error") + ": " + r.error);
        return;
      }
      if (r.failed) toast.warn(t("gui_q_apply_error") + ": " + r.failed);
      if (r.success) toast.warn(tf("gui_q_applied", { count: r.success, level: view.level }));
      if (areaState.onQuarantined) areaState.onQuarantined();
    }));
    return true;
  });
}

/* IV-12 — the accelerate drawer. index.html:2514-2539 (m-accelerate): the
 * summary counts total / managed / skipped, the duration radios are 0 (single
 * shot) / 30 / 60 / 120 minutes.
 * PORT: Save posts to the real POST /api/workloads/accelerate. There is
 * deliberately NO client-side "nothing selected" pre-check: that route already
 * drops every non-workload href and answers {ok:false, gui_accel_no_targets}
 * when nothing survives (actions.py:479-483), so the authority on what is
 * accelerable is the backend, not this form's `managed` reading of a possibly
 * stale row. The summary still states how many will be skipped. */
function accelerateDrawer(areaState, selected, rowsByHref, onStart) {
  const body = el("div", { "data-cov": "IV-12" });
  const all = selected.map(function (h) { return rowsByHref.get(h) || {}; });
  const managed = all.filter(function (w) { return w.managed === true; });
  const skipped = all.length - managed.length;
  const view = {};
  view.duration = "0";

  body.appendChild(note(tf("gui_accel_modal_summary", { total: all.length, managed: managed.length, skipped: skipped })));
  const group = el("div", { class: "radios" });
  ACCEL_DURATIONS.forEach(function (v) {
    const input = el("input", { type: "radio", name: "iv-accel", value: v });
    if (v === view.duration) input.checked = true;
    input.addEventListener("change", function () { if (input.checked) view.duration = input.value; });
    const text = v === "0" ? t("gui_accel_single") : tf("gui_iv_minutes", { n: v });
    group.appendChild(el("label", null, input, el("span", { text: text })));
  });
  body.appendChild(el("div", { class: "fld" },
    el("label", null, el("span", { text: t("gui_accel_duration") })), group));
  body.appendChild(note(t("gui_iv_accel_note")));

  return drawerSpec(t("gui_accel_modal_title"), body, async function () {
    const minutes = Number(view.duration);
    // The summary is deliberately explicit about skipped unmanaged rows;
    // submit only the same managed hrefs, or the backend would receive rows
    // the operator was told would be skipped.
    const hrefs = managed.map(function (w) { return w.href; }).filter(Boolean);
    const r = await fireAccelerate(hrefs, minutes);
    if (areaState.torn) return true;
    if (!r.ok) {
      toast.crit(errText(r));
      return false;
    }
    const success = Number(r.success || 0);
    const failed = Number(r.failed || 0);
    if (failed) toast.warn(tf("gui_accel_failed", { n: failed }));
    if (!success) return false;
    toast.ok(tf("gui_accel_started", { n: success }));
    onStart(hrefs, minutes);
    return true;
  });
}

/* quarantine.js:703-716 (_fireAccelerate) — one POST per issue. */
function fireAccelerate(hrefs, minutes) {
  return api.post("/api/workloads/accelerate", { hrefs: hrefs, duration_minutes: minutes })
    .then(function (r) { return r && r.ok === true ? r : { ok: false, error: errText(r) }; });
}

/* quarantine.js:719-771 (confirmAccelerate + _showAccelCountdown) — persistent
 * mode is a browser-side loop by the backend's own design (actions.py:465-470):
 * re-issue every 10 minutes until the deadline, with a 1-second display tick.
 * Both timers hang off `areaState` so this area's teardown clears them; the
 * mockup only had the display tick and nothing to tear down. */
function startAccelCountdown(areaState, host, hrefs, minutes) {
  cancelAccel(areaState);
  if (!minutes) return null;
  const endTs = Date.now() + minutes * 60000;
  const remaining = el("b");
  const bar = el("div", { class: "floatbar", "data-tone": "ok" },
    el("i", { class: "dot" }),
    el("span", { text: t("gui_accel_running_label") + " " }),
    el("b", { text: String(hrefs.length) }),
    el("span", { text: " · " }),
    remaining
  );
  const stop = el("button", { class: "btn ghost", type: "button", text: t("gui_cancel") });
  bar.appendChild(stop);
  host.appendChild(bar);

  function fmt(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  remaining.textContent = fmt(endTs - Date.now());
  areaState.accelBar = bar;
  areaState.accelTick = setInterval(function () {
    const left = endTs - Date.now();
    if (left <= 0 || !document.body.contains(bar)) { cancelAccel(areaState); return; }
    remaining.textContent = fmt(left);
  }, 1000);
  areaState.accelTimer = setInterval(function () {
    if (Date.now() >= endTs) { cancelAccel(areaState); return; }
    fireAccelerate(hrefs, minutes);
  }, ACCEL_REISSUE_MS);
  stop.addEventListener("click", function () { cancelAccel(areaState); });
  return bar;
}

function cancelAccel(areaState) {
  if (areaState.accelTick) { clearInterval(areaState.accelTick); areaState.accelTick = null; }
  if (areaState.accelTimer) { clearInterval(areaState.accelTimer); areaState.accelTimer = null; }
  const bar = areaState.accelBar;
  areaState.accelBar = null;
  if (bar && bar.parentNode) bar.parentNode.removeChild(bar);
}

/* quarantine.js:573-622 (renderQwPage) — status dot + name over hostname,
 * management, every IPv4 interface with its name, the label chips, and the row
 * actions (isolate always, accelerate only when managed :602-604, lift only
 * when a Quarantine label is present :579-584, :620). */
function workloadRows(list) {
  return list.map(function (w) {
    const r = {};
    r.href = w.href;
    r.name = w.name || w.hostname;
    r.hostname = w.hostname;
    r.online = w.online === true;
    r.managed = w.managed === true;
    r.labels = w.labels || [];
    r.quarantined = (w.labels || []).some(function (l) { return l.key === "Quarantine"; });
    // :590 — IPv6 and link-local addresses are skipped by the product
    r.ips = (w.interfaces || []).filter(function (i) {
      return i.address && i.address.indexOf(".") >= 0 && i.address.indexOf(":") < 0;
    });
    r.enforcement = w.enforcement_mode || "";
    // DESIGN-ADDED: the product renders only a status dot plus a red
    // "Quarantine" label chip — it never computes a row-level verdict tone.
    r._tone = r.quarantined ? "crit" : (r.online ? null : "warn");
    return r;
  });
}

async function mountWorkloads(root, ctx) {
  const handles = {};
  const state = {};
  state.torn = false;
  state.tables = [];
  installTeardown(state);
  drawer.registerAudit("iv-wl-quarantine", function () { return handles.openSingle ? handles.openSingle() : null; });
  drawer.registerAudit("iv-wl-bulk", function () { return handles.openBulk ? handles.openBulk() : null; });
  drawer.registerAudit("iv-wl-accel", function () { return handles.openAccel ? handles.openAccel() : null; });
  modal.registerAudit("iv-wl-confirm", function () { return handles.openConfirm ? handles.openConfirm() : null; });
  audit.register("iv-wl-select", function () { if (handles.selectSome) handles.selectSome(); });
  palette.registerFor(R_WORKLOADS, cmdSpec("iv:accel", t("gui_accel_bulk_btn"), function () {
    if (handles.openAccel) handles.openAccel();
  }));

  root.appendChild(areaTop(R_WORKLOADS));
  const wrap = el("div", { class: "wb solo" });
  const main = el("div", { class: "wb-main" });
  wrap.appendChild(main);
  root.appendChild(wrap);

  state.name = "";
  state.ip = "";
  state.host = "";
  state.size = 50;
  state.page = 0;
  state.phase = "idle";
  state.rows = [];
  state.truncated = false;
  state.error = "";
  state.seq = 0;
  state.selected = [];

  const model = [];
  const byHref = new Map();

  const host = el("div");
  const floatHost = el("div");
  // The countdown gets its own host, NOT floatHost: paintFloat() clears its
  // host on every selection change, and the countdown bar detaching is what
  // its own tick reads as "this run is over" (quarantine.js:750-771's bar
  // check, kept here) — so sharing them would make ticking a checkbox
  // silently cancel a persistent acceleration run.
  const accelHost = el("div");
  main.appendChild(host);
  main.appendChild(floatHost);
  main.appendChild(accelHost);

  /** IV-08 — the real GET /api/workloads?name=&ip_address=&hostname=
   *  (quarantine.js:518-534 runWorkloadSearch; actions.py:218-299). Every field
   *  is sent, empty or not, exactly as the shipping GUI sends it: the route
   *  only adds a PCE parameter for a NON-empty value (:230-232), so an empty
   *  field and an absent one mean the same thing there. api.reload, not
   *  api.load, so pressing Find twice really asks again. */
  async function runSearch() {
    const seq = ++state.seq;
    const params = {};
    params.name = state.name;
    params.ip_address = state.ip;
    params.hostname = state.host;
    state.phase = "busy";
    state.page = 0;
    state.selected = [];
    repaint();
    let r = null;
    try {
      r = await api.reload("workload_search", params);
    } catch (e) {
      r = { ok: false, error: String((e && e.message) || e) };
    }
    if (state.torn || seq !== state.seq) return;
    state.phase = "done";
    if (!r || r.ok !== true) {
      state.rows = [];
      state.error = errText(r);
      rebuildModel();
      repaint();
      toast.crit(state.error);
      return;
    }
    state.error = "";
    state.rows = r.data || [];
    state.truncated = !!r.truncated;
    rebuildModel();
    repaint();
    toast.ok(tf("gui_total_found_ws", { count: num(model.length) }));
  }

  function rebuildModel() {
    model.length = 0;
    byHref.clear();
    workloadRows(state.rows).forEach(function (r) {
      model.push(r);
      byHref.set(r.href, r);
      hrefNames.set(r.href, r.name);
    });
  }

  function toggle(href, on) {
    const at = state.selected.indexOf(href);
    if (on && at < 0) state.selected.push(href);
    if (!on && at >= 0) state.selected.splice(at, 1);
    paintFloat();
  }

  function paintFloat() {
    clear(floatHost);
    if (!state.selected.length) return;
    // index.html:1131-1148 (#bulk-bar) — count, bulk quarantine, bulk accelerate
    const bar = el("div", { class: "floatbar", "data-tone": "crit" },
      el("span", { text: t("gui_selected") + " " }),
      el("b", { text: String(state.selected.length) }),
      el("span", { text: " " + t("gui_workloads") }),
      el("button", { class: "btn danger", type: "button", text: t("gui_q_apply"),
        onClick: function () { handles.openBulk(); } }),
      el("button", { class: "btn", type: "button", text: t("gui_accel_bulk_btn"),
        onClick: function () { handles.openAccel(); } })
    );
    floatHost.appendChild(bar);
  }

  function columns() {
    return [
      col("pick", "", widthCell(34, function (r) {
        const cb = el("input", { type: "checkbox" });
        cb.setAttribute("aria-label", String(r.name || ""));
        cb.checked = state.selected.indexOf(r.href) >= 0;
        cb.addEventListener("change", function () { toggle(r.href, cb.checked); });
        return cb;
      })),
      col("name", t("gui_ws_col_status"), widthCell(210, function (r) {
        return el("span", { class: "idc", "data-tone": r.online ? "ok" : "warn" },
          el("b", null, el("i", { class: "dot" }), el("span", { text: " " + r.name })),
          el("small", { text: r.hostname || "" }));
      })),
      col("mgmt", t("gui_ws_col_management"), widthCell(120, function (r) {
        return badge(r.managed ? t("gui_management_managed") : t("gui_management_unmanaged"), r.managed ? "ok" : "neutral");
      })),
      col("ip", t("gui_ws_col_ip"), widthCell(180, function (r) {
        const box = el("span", { class: "idc" });
        r.ips.slice(0, 3).forEach(function (i) {
          box.appendChild(el("small", { text: i.address + " (" + i.name + ")" }));
        });
        if (r.ips.length > 3) box.appendChild(el("small", { text: tf("gui_iv_more_ips", { n: r.ips.length - 3 }) }));
        if (!r.ips.length) box.appendChild(el("small", { text: "—" }));
        return box;
      })),
      col("labels", t("gui_ws_col_labels"), buildCell(function (r) {
        return r.labels.length ? labelChips(r.labels) : el("span", { class: "mono", text: t("gui_no_labels") });
      })),
      // 260, and app.css's own .rowacts flex row: three buttons in a bare
      // inline span inside a `table-layout: fixed` 200px cell wrapped onto a
      // second line and, because td keeps a fixed row height, spilled OUT of
      // the table over the pager underneath it — where the pager's own spans
      // then swallowed the clicks (reproduced: Playwright reported
      // "<span> intercepts pointer events" on the lift button).
      col("act", t("gui_actions"), widthCell(260, function (r) {
        const box = el("span", { class: "rowacts" });
        box.appendChild(btn("btn danger", t("gui_btn_isolate"), function () { handles.openSingle(r.href); }));
        const acc = btn("btn ghost", t("gui_btn_accelerate"), function () { handles.openAccel([r.href]); });
        acc.disabled = !r.managed;
        acc.title = r.managed ? t("gui_btn_accelerate_tip") : t("gui_accel_unmanaged_tip");
        box.appendChild(acc);
        // IV-11 — lift only exists on a workload that carries the label
        if (r.quarantined) {
          const lift = btn("btn", t("gui_lift_quarantine"), function () { handles.openLift(r); });
          lift.setAttribute("data-cov", "IV-11");
          box.appendChild(lift);
        }
        return box;
      })),
    ];
  }

  function repaint() {
    state.tables.forEach(function (h) { h.destroy(); });
    state.tables = [];
    clear(host);

    const query = panel("IV-08", t("gui_ws_search"));
    const row = el("div", { class: "qrow" });
    const nameIn = el("input", { class: "field", placeholder: t("gui_ws_name_placeholder"), value: state.name });
    const ipIn = el("input", { class: "field", placeholder: t("gui_ws_ip_placeholder"), value: state.ip });
    const hostIn = el("input", { class: "field", placeholder: t("gui_ws_hostname_placeholder"), value: state.host });
    [nameIn, ipIn, hostIn].forEach(function (input) {
      input.addEventListener("input", function () {
        state.name = nameIn.value.trim();
        state.ip = ipIn.value.trim();
        state.host = hostIn.value.trim();
      });
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") runSearch(); });
    });
    const f1 = field(t("gui_workload_name"), nameIn);
    const f2 = field(t("gui_ip_address"), ipIn);
    const f3 = field(t("gui_hostname"), hostIn);
    f1.className = "qf grow";
    f2.className = "qf grow";
    f3.className = "qf grow";
    nameIn.setAttribute("aria-label", t("gui_workload_name"));
    ipIn.setAttribute("aria-label", t("gui_ip_address"));
    hostIn.setAttribute("aria-label", t("gui_hostname"));
    row.appendChild(f1);
    row.appendChild(f2);
    row.appendChild(f3);
    const find = el("button", { class: "btn primary", type: "button", text: t("gui_find"),
      onClick: function () { runSearch(); } });
    find.disabled = state.phase === "busy";
    row.appendChild(find);
    query.body.appendChild(row);
    host.appendChild(query);

    const p = panel(null, t("gui_workload_search"));
    withMeta(p, tf("gui_total_found_ws", { count: num(model.length) }));
    headBox(p).appendChild(selectField(t("gui_page_size"), PAGE_SIZES, String(state.size), function (v) {
      state.size = Number(v);
      state.page = 0;
      repaint();
    }).control);

    if (state.error) {
      p.body.appendChild(el("div", { class: "strip", "data-tone": "crit" },
        el("i", { class: "dot" }), el("span", { text: state.error })));
    }
    // actions.py:267 — a full 500-row page is the route's own truncation signal.
    if (state.truncated) {
      p.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
        el("i", { class: "dot" }), el("span", { text: tf("gui_results_truncated", { cap: 500, total: num(model.length) }) })));
    }
    if (state.phase === "busy") {
      p.body.classList.add("flush");
      state.tables.push(table.render(p.body, buildTable(columns(), null)));
    } else if (!model.length) {
      p.body.appendChild(el("div", { class: "empty" },
        el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
        el("p", { text: state.phase === "idle" ? t("gui_iv_search_prompt") : t("gui_ws_empty") })));
    } else {
      p.body.classList.add("flush");
      const shown = model.slice(state.page * state.size, (state.page + 1) * state.size);
      state.tables.push(table.render(p.body, pagedTable(columns(), shown,
        pageSpec(state.page, state.size, model.length), function (next) {
          state.page = Math.max(0, next);
          repaint();
        })));
    }
    host.appendChild(p);
    paintFloat();
  }

  // After a successful quarantine the labels this table shows are stale — the
  // Quarantine chip and the lift button both key off them. Re-run the same
  // search rather than patching the row locally.
  state.onQuarantined = function () { if (state.phase === "done") runSearch(); };

  handles.openSingle = function (href) {
    const target = href || (model.length ? model[0].href : "");
    return drawer.open(quarantineDrawer(state, buildQuarantineState(target, false, null, null), false));
  };
  handles.openBulk = function () {
    return drawer.open(quarantineDrawer(state, buildQuarantineState(null, true, null, state.selected.slice()), true));
  };
  handles.openAccel = function (hrefs) {
    const picked = hrefs || state.selected.slice();
    return drawer.open(accelerateDrawer(state, picked, byHref, function (sent, minutes) {
      startAccelCountdown(state, accelHost, sent, minutes);
    }));
  };
  /* IV-11 + XC-08 — one confirmation, then the real POST /api/quarantine/lift.
   * XC-08 is anchored on the confirmation itself (the coverage item is the
   * confirm-with-impact surface); IV-11 rides the same modal's body so the
   * lift flow carries its own anchor even on an install with nothing
   * quarantined to put a row-level button on. */
  handles.openLift = function (r) {
    const target = r && r.href ? r.href : "";
    const impact = [t("gui_lift_confirm"), target ? r.name : t("gui_q_no_targets")];
    const h = modal.confirm(confirmSpec(t("gui_lift_quarantine"), impact, async function () {
      if (!target) {
        toast.warn(t("gui_q_no_targets"));
        return false;
      }
      // actions.py:407-461 answers {ok:true, results:{success, failed[],
      // not_quarantined}} — and, unlike apply, has no APIError branch, so a
      // PCE failure surfaces as a 500 whose body is still {ok:false, error}.
      const res = await api.post("/api/quarantine/lift", { hrefs: [target] });
      if (state.torn) return;
      if (!res || res.ok !== true) {
        toast.crit(errText(res));
        return;
      }
      const out = res.results || {};
      const success = Number(out.success || 0);
      const failed = Array.isArray(out.failed) ? out.failed.length : Number(out.failed || 0);
      const notQuarantined = Number(out.not_quarantined || 0);
      if (failed) toast.warn(tf("gui_lift_failed", { n: failed }));
      if (notQuarantined) toast.warn(tf("gui_lift_not_quarantined", { n: notQuarantined }));
      if (success) {
        toast.ok(t("gui_lift_done"));
        if (state.onQuarantined) state.onQuarantined();
      } else if (!failed && !notQuarantined) {
        toast.warn(t("gui_q_no_targets"));
      }
    }));
    h.el.setAttribute("data-cov", "XC-08");
    const inner = h.el.querySelector(".modal-b");
    if (inner) inner.setAttribute("data-cov", "IV-11");
    return h;
  };
  handles.openConfirm = function () {
    return handles.openLift(model.filter(function (r) { return r.quarantined; })[0] || model[0] || null);
  };
  handles.selectSome = function () {
    state.selected = model.slice(0, 2).map(function (r) { return r.href; });
    repaint();
  };

  repaint();
}

// ═════════════════════════════════════════════════════ events ═══════════════

/* events.js:11-14 (_eventViewerGroupOf) — the group is the event type's first
 * dotted segment; '*' has no group. */
function eventGroupOf(eventType) {
  if (!eventType || eventType === "*") return "*";
  return String(eventType).split(".")[0];
}

/* events.js:16-24 (_humanizeEventViewerGroup) — the local fallback for payloads
 * that predate the server-translated group_label. */
function humanizeGroup(groupId) {
  if (!groupId || groupId === "*") return t("gui_ev_all_groups");
  const pretty = String(groupId).split("_").filter(Boolean).map(function (part) {
    return part.charAt(0).toUpperCase() + part.slice(1);
  }).join(" ");
  return pretty + " (" + groupId + ".*)";
}

/* events.js:91-116 (ensureEventViewerCatalog) — categories are flattened into a
 * single item list carrying category_id / category_label / group_id /
 * group_label, and every downstream option list reads THAT list. */
function flattenCatalog(response) {
  const categories = (response && response.categories) || [];
  const items = [];
  categories.forEach(function (category) {
    (category.events || []).forEach(function (item) {
      const groupId = item.group_id || eventGroupOf(item.id);
      const row = {};
      row.id = item.id;
      row.label = item.label;
      row.category_id = category.id;
      row.category_label = category.label;
      row.group_id = groupId;
      row.group_label = item.group_label || humanizeGroup(groupId);
      items.push(row);
    });
  });
  const out = {};
  out.categories = categories;
  out.items = items;
  return out;
}

/* events.js:33-42 (_eventViewerFilteredCatalogItems) — '*' is never an option,
 * and both filters are applied conjunctively. */
function filteredCatalogItems(catalog, categoryId, groupId) {
  return (catalog.items || []).filter(function (item) {
    if (item.id === "*") return false;
    if (categoryId && item.category_id !== categoryId) return false;
    if (groupId && item.group_id !== groupId) return false;
    return true;
  });
}

/* events.js:58-75 (_populateEventViewerGroupOptions) — unique group_id ->
 * group_label within the chosen category, sorted by LABEL. */
function groupOptions(catalog, categoryId) {
  const groups = new Map();
  (catalog.items || []).forEach(function (item) {
    if (item.id === "*") return;
    if (categoryId && item.category_id !== categoryId) return;
    groups.set(item.group_id, item.group_label);
  });
  return Array.from(groups.entries()).sort(function (a, b) { return a[1].localeCompare(b[1]); });
}

/* events.js:26-31 (_eventViewerTypeOptionLabel) */
function typeOptionLabel(item) {
  if (!item) return "";
  if (item.id === "*") return item.label || t("gui_ev_all_event_types");
  if (item.label && item.label !== item.id) return item.label + " · " + item.id;
  return item.id;
}

/* events.js:141-146 (_evStatusTone) — success is the only good status; failure,
 * error, warn and warning are all bad; anything else is neutral. */
function statusTone(value) {
  const status = String(value || "").toLowerCase();
  if (status === "success") return "ok";
  if (["failure", "error", "warn", "warning"].indexOf(status) >= 0) return "crit";
  return "neutral";
}

/* IV-15 — shadow compare, bound to GET /api/events/shadow_compare
 * (events.py:150-201). There is no shipping UI for this endpoint: grepping
 * src/static and src/templates for shadow_compare returns nothing, so the
 * controls are this design's, clamped exactly as :162-168 clamps them, and the
 * columns are the ones events/shadow.py:78-104 returns. Loaded on demand —
 * each call fetches up to `limit` events from the PCE (header note 6). */
function shadowPanel(areaState) {
  // R4 — this used to carry the endpoint path (/api/events/shadow_compare)
  // as the panel's meta caption. The description note right below already
  // says what the panel does in one sentence; the route it hits is not
  // something an operator acts on.
  const p = panel("IV-15", t("gui_iv_shadow_title"));
  const view = {};
  view.mins = "60";
  view.limit = "200";
  let handle = null;

  const row = el("div", { class: "qrow" });
  row.appendChild(selectField(t("gui_window_min"), SHADOW_MINS, view.mins, function (v) { view.mins = v; }));
  row.appendChild(selectField(t("gui_rows"), SHADOW_LIMITS, view.limit, function (v) { view.limit = v; }));
  row.appendChild(el("span", { class: "spacer" }));
  const host = el("div");
  const refresh = el("button", { class: "btn primary", type: "button", text: t("gui_refresh"),
    onClick: function () { run(); } });
  row.appendChild(refresh);
  p.body.appendChild(row);
  p.body.appendChild(note(t("gui_iv_shadow_desc")));
  p.body.appendChild(host);

  const cols = [
    col("rule", t("gui_col_name"), buildCell(function (r) { return r.rule_name; })),
    col("current", t("gui_iv_shadow_current"), numCell(function (r) { return num(r.current_count); })),
    col("legacy", t("gui_iv_shadow_legacy"), numCell(function (r) { return num(r.legacy_count); })),
    col("delta", t("gui_iv_shadow_delta"), numCell(function (r) { return num(r.delta); })),
    col("status", t("gui_col_status"), widthCell(110, function (r) { return badge(r.status, "neutral"); })),
  ];

  function paint(rows, message, tn) {
    if (handle) handle.destroy();
    clear(host);
    handle = table.render(host, buildTable(cols, rows));
    areaState.shadowTable = handle;
    if (message) {
      host.appendChild(el("div", { class: "strip", "data-tone": tn },
        el("i", { class: "dot" }), el("span", { text: message })));
    }
  }

  async function run() {
    refresh.disabled = true;
    paint(null, null, null);
    let r = null;
    try {
      // Task 5 brief authorises this live read-only endpoint; it is deliberately
      // reached through the generic GET path because frozen endpoints.yaml has
      // no snapshot entry for shadow_compare and GET_MAP must match it exactly.
      const path = "/api/events/shadow_compare?mins=" + encodeURIComponent(view.mins)
        + "&limit=" + encodeURIComponent(view.limit);
      r = await api.get(path);
    } catch (e) {
      r = { ok: false, error: String((e && e.message) || e) };
    }
    if (areaState.torn) return;
    refresh.disabled = false;
    if (!r || r.ok !== true) {
      paint([], errText(r), "crit");
      return;
    }
    const items = r.items || [];
    const summary = r.summary || {};
    paint(items, tf("gui_iv_shadow_summary", {
      rules: num(summary.rule_count), divergent: num(summary.divergent_rules), events: num(summary.fetched_events),
    }), Number(summary.divergent_rules) ? "warn" : "ok");
  }

  paint([], t("gui_iv_shadow_idle"), "info");
  return p;
}

async function mountEvents(root, ctx) {
  const handles = {};
  const state = {};
  state.torn = false;
  state.tables = [];
  installTeardown(state);
  palette.registerFor(R_EVENTS, cmdSpec("iv:ev-reset", t("gui_ev_all_categories"), function () {
    if (handles.reset) handles.reset();
  }));

  root.appendChild(areaTop(R_EVENTS));
  const wrap = el("div", { class: "wb solo" });
  const main = el("div", { class: "wb-main" });
  wrap.appendChild(main);
  root.appendChild(wrap);

  await withErrorCard(main, "event_catalog",
    function () { return api.load("event_catalog"); },
    function (raw) {
      if (ctx.stale()) return;
      const catalog = flattenCatalog(raw);

      state.category = "";
      state.group = "";
      state.type = "";
      state.search = "";
      state.mins = "60";
      state.limit = 25;
      state.items = [];
      state.summary = {};
      state.phase = "idle";
      state.error = "";
      state.seq = 0;
      state.selected = null;

      const filterHost = el("div");
      const layout = el("div", { class: "evl", "data-cov": "IV-14" });
      const tableHost = el("div");
      const aside = el("div", { class: "wb-aside" });
      layout.appendChild(tableHost);
      layout.appendChild(aside);
      main.appendChild(filterHost);
      main.appendChild(layout);
      main.appendChild(shadowPanel(state));

      /**
       * IV-13/IV-14 — the real GET /api/events/viewer. Every filter is a
       * request parameter (events.py:37-52 mins/limit/offset/search/category/
       * type_group/event_type), so the three-level cascade and the search box
       * narrow the query at the source instead of hiding rows locally, and
       * load-more is real offset paging driven by the route's own
       * summary.has_more (:141).
       *
       * `append` distinguishes "load more" (keep what is on screen, add the
       * next page) from any filter change (start over at offset 0).
       */
      async function runQuery(append) {
        const seq = ++state.seq;
        const offset = append ? state.items.length : 0;
        const params = {};
        params.mins = state.mins;
        params.limit = state.limit;
        params.offset = offset;
        params.search = state.search;
        params.category = state.category;
        params.type_group = state.group;
        params.event_type = state.type;
        state.phase = "busy";
        if (!append) state.items = [];
        paintTable();
        let r = null;
        try {
          r = await api.reload("events_viewer", params);
        } catch (e) {
          r = { ok: false, error: String((e && e.message) || e) };
        }
        if (state.torn || seq !== state.seq) return;
        state.phase = "done";
        if (!r || r.ok !== true) {
          state.error = errText(r);
          paintFilters();
          paintTable();
          toast.crit(state.error);
          return;
        }
        state.error = "";
        state.summary = r.summary || {};
        const incoming = r.items || [];
        state.items = append ? state.items.concat(incoming) : incoming;
        if (!state.selected && state.items.length) state.selected = state.items[0].event_id;
        paintFilters();
        paintTable();
      }

      // ── IV-13: the three-level cascade ──
      function paintFilters() {
        clear(filterHost);
        const p = panel("IV-13", t("gui_event_viewer"));
        const s = state.summary;
        withMeta(p, s.query_since
          ? tf("gui_iv_ev_window", { since: stamp(s.query_since), until: stamp(s.query_until) })
          : t("gui_iv_not_run"));
        const row = el("div", { class: "qrow" });

        row.appendChild(selectField(t("gui_window"), EV_WINDOWS, state.mins, function (v) {
          state.mins = v;
          runQuery(false);
        }));
        row.appendChild(selectField(t("gui_rows"), EV_LIMITS, String(state.limit), function (v) {
          state.limit = Number(v);
          runQuery(false);
        }));

        const catSel = el("select", { class: "field" });
        catSel.setAttribute("aria-label", t("gui_category"));
        catSel.appendChild(el("option", { value: "", text: t("gui_ev_all_categories") }));
        (catalog.categories || []).forEach(function (c) {
          const opt = el("option", { value: c.id, text: c.label });
          if (c.id === state.category) opt.selected = true;
          catSel.appendChild(opt);
        });
        catSel.addEventListener("change", function () {
          // events.js:118-122 — a category change repopulates groups AND types,
          // then re-runs the query
          state.category = catSel.value;
          state.group = "";
          state.type = "";
          paintFilters();
          runQuery(false);
        });
        row.appendChild(field(t("gui_category"), catSel));

        const grpSel = el("select", { class: "field" });
        grpSel.setAttribute("aria-label", t("gui_ev_type_group"));
        grpSel.appendChild(el("option", { value: "", text: t("gui_ev_all_groups") }));
        groupOptions(catalog, state.category).forEach(function (pair) {
          const opt = el("option", { value: pair[0], text: pair[1] });
          if (pair[0] === state.group) opt.selected = true;
          grpSel.appendChild(opt);
        });
        grpSel.addEventListener("change", function () {
          // events.js:124-127 — a group change repopulates types only
          state.group = grpSel.value;
          state.type = "";
          paintFilters();
          runQuery(false);
        });
        row.appendChild(field(t("gui_ev_type_group"), grpSel));

        const typeSel = el("select", { class: "field" });
        typeSel.setAttribute("aria-label", t("gui_event_type"));
        typeSel.appendChild(el("option", { value: "", text: t("gui_ev_all_event_types") }));
        filteredCatalogItems(catalog, state.category, state.group)
          .sort(function (a, b) { return a.label.localeCompare(b.label); })
          .forEach(function (item) {
            const opt = el("option", { value: item.id, text: typeOptionLabel(item) });
            if (item.id === state.type) opt.selected = true;
            typeSel.appendChild(opt);
          });
        typeSel.addEventListener("change", function () {
          state.type = typeSel.value;
          runQuery(false);
        });
        const typeField = field(t("gui_event_type"), typeSel);
        typeField.className = "qf grow";
        row.appendChild(typeField);

        const searchIn = el("input", { class: "field", placeholder: t("gui_ev_search_placeholder"), value: state.search });
        searchIn.setAttribute("aria-label", t("gui_search"));
        searchIn.addEventListener("input", function () { state.search = searchIn.value.trim(); });
        searchIn.addEventListener("keydown", function (e) { if (e.key === "Enter") runQuery(false); });
        const sf = field(t("gui_search"), searchIn);
        sf.className = "qf grow";
        row.appendChild(sf);
        row.appendChild(el("span", { class: "spacer" }));
        row.appendChild(el("button", { class: "btn primary", type: "button", text: t("gui_refresh"),
          onClick: function () { runQuery(false); } }));
        p.body.appendChild(row);
        p.body.appendChild(note(tf("gui_iv_ev_catalog", {
          cats: (catalog.categories || []).length, types: (catalog.items || []).length,
        })));
        filterHost.appendChild(p);
      }

      // ── IV-14: rows, load-more, detail ──
      function paintTable() {
        state.tables.forEach(function (h) { h.destroy(); });
        state.tables = [];
        clear(tableHost);
        const rows = state.items;
        const p = panel(null, t("gui_tab_events"));
        withMeta(p, t("gui_ev_matched") + " " + num(state.summary.matched_count || rows.length)
          + " · " + t("gui_ev_showing") + " " + num(rows.length));

        if (state.error) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "crit" },
            el("i", { class: "dot" }), el("span", { text: state.error })));
        }
        if (state.phase === "busy" && !rows.length) {
          p.body.classList.add("flush");
          state.tables.push(table.render(p.body, buildTable(eventColumns(), null)));
          tableHost.appendChild(p);
          paintDetail(null);
          return;
        }
        if (!rows.length) {
          p.body.appendChild(el("div", { class: "empty" },
            el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
            el("p", { text: state.phase === "idle" ? t("gui_ev_load_prompt") : t("gui_ev_no_match") })));
          if (state.phase === "idle") {
            p.body.appendChild(el("button", { class: "btn primary", type: "button", text: t("gui_refresh"),
              onClick: function () { runQuery(false); } }));
          }
          tableHost.appendChild(p);
          paintDetail(null);
          return;
        }

        const model = rows.map(function (it) {
          const n = it.normalized || {};
          const r = {};
          r.id = it.event_id;
          r.time = stamp(it.timestamp);
          r.type = it.event_type;
          r.resource = n.resource_type ? (n.resource_type + (n.resource_name ? " | " + n.resource_name : "")) : "";
          r.status = it.status || "n/a";
          r.actor = n.actor || "-";
          r.target = n.target_name || "-";
          r.action = n.action || "-";
          r.item = it;
          // The severity bar is the product's row mark (index.html:542-556);
          // status only escalates it on an explicit failure (events.js:141-146).
          r._tone = statusTone(it.status) === "crit" ? "crit" : tone(it.severity);
          return r;
        });

        p.body.classList.add("flush");
        const handle = table.render(p.body, buildTable(eventColumns(), model));
        state.tables.push(handle);
        handle.el.querySelectorAll("tbody tr").forEach(function (tr, i) {
          tr.style.cursor = "pointer";
          tr.addEventListener("click", function () {
            state.selected = model[i].id;
            paintTable();
          });
          if (model[i].id === state.selected) tr.setAttribute("aria-selected", "true");
        });

        // events.js:252-259 / 314-318 — load more exists exactly while the
        // SERVER says there is more (summary.has_more), and asks for the next
        // offset rather than revealing rows already fetched.
        const foot = el("div", { class: "panel-b" });
        if (state.summary.has_more) {
          const more = el("button", { class: "btn", type: "button", "data-role": "load-more",
            text: t("gui_load_more") + " (" + num(rows.length) + "/" + num(state.summary.matched_count || rows.length) + ")",
            onClick: function () { runQuery(true); } });
          more.disabled = state.phase === "busy";
          foot.appendChild(more);
        } else {
          foot.appendChild(note(tf("gui_iv_ev_all", { n: num(rows.length) })));
        }
        p.body.appendChild(foot);
        tableHost.appendChild(p);

        const selected = rows.filter(function (it) { return it.event_id === state.selected; })[0] || rows[0];
        paintDetail(selected);
      }

      function eventColumns() {
        return [
          col("time", t("gui_time"), widthCell(150, function (r) { return el("span", { class: "mono", text: r.time }); })),
          col("type", t("gui_event"), widthCell(220, function (r) {
            return el("span", { class: "idc" }, el("b", { class: "mono", text: r.type }),
              r.resource ? el("small", { text: r.resource }) : null);
          })),
          col("status", t("gui_col_status"), widthCell(100, function (r) { return badge(r.status, statusTone(r.status)); })),
          col("actor", t("gui_actor"), widthCell(130, function (r) { return r.actor; })),
          col("target", t("gui_target"), widthCell(170, function (r) { return r.target; })),
          col("action", t("gui_action"), buildCell(function (r) { return r.action; })),
        ];
      }

      /* events.js:177-202 (_renderEventDetailCard) + 161-175 (parsed / raw panes) */
      function paintDetail(item) {
        clear(aside);
        const p = panel(null, t("gui_ev_detail_title"));
        if (!item) {
          p.body.appendChild(el("div", { class: "empty" },
            el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
            el("p", { text: t("gui_ev_select_parsed") })));
          aside.appendChild(p);
          return;
        }
        const n = item.normalized || {};
        withMeta(p, item.event_type);
        // :198-200 — username comes from created_by.user, then actor, then a dash.
        const rawBy = (item.raw && item.raw.created_by) || {};
        const username = (rawBy.user && rawBy.user.username) || item.actor || n.actor || "—";
        // DESIGN-ADDED: events.js:199 reads `ev.src_ip` off the top-level event
        // object; the viewer payload has no such field (the IP only appears as
        // `source_ip` inside the normalized event), so this reads it from where
        // the data actually is.
        const ip = n.source_ip ? " / " + n.source_ip : "";

        const dl = el("dl", { class: "evmeta" });
        function meta(label, value) {
          dl.appendChild(el("dt", { text: label }));
          dl.appendChild(el("dd", { title: String(value), text: value }));
        }
        // R4/R6 — the raw field name used to be the label text itself; the
        // DLQ table already minted a human label for the same field.
        meta(t("gui_dlq_th_event_id"), item.event_id);
        meta(t("gui_ev_detail_time"), stamp(item.timestamp));
        meta(t("gui_ev_detail_sev"), item.severity || "—");
        meta(t("gui_ev_detail_user_ip"), username + ip);
        p.body.appendChild(dl);
        p.body.appendChild(badge(item.status || "n/a", statusTone(item.status)));
        p.body.appendChild(el("h4", { class: "eyebrow", text: t("gui_ev_parsed_event") }));
        p.body.appendChild(el("pre", { class: "codepane", text: JSON.stringify(n, null, 2) }));
        p.body.appendChild(el("h4", { class: "eyebrow", text: t("gui_ev_raw_event") }));
        p.body.appendChild(el("pre", { class: "codepane", text: JSON.stringify(item.raw || {}, null, 2) }));
        aside.appendChild(p);
      }

      handles.reset = function () {
        state.category = "";
        state.group = "";
        state.type = "";
        state.search = "";
        paintFilters();
        runQuery(false);
      };

      paintFilters();
      paintTable();
    });
}

// ═════════════════════════════════════════════════════ teardown ═════════════

/**
 * S2 — one self-unsubscribing router.onChange per mount.
 *
 * Registered SYNCHRONOUSLY, before the mount's first await, next to the audit
 * and palette registrations it is responsible for undoing. It first sat inside
 * the render callback (after the ctx.stale() guard, mirroring
 * areas/overview.mjs), and the e2e caught what that costs: the palette
 * commands are registered before the await and the teardown after it, so a
 * mount that was abandoned mid-load — navigate away while the catalogue or the
 * flow search is still in flight, which on this route takes seconds — left its
 * route-scoped commands in the palette forever, because palette.setRoute() is
 * only ever called from an area's own teardown. Registering both at the same
 * moment closes that window. The abandoned mount's teardown then fires on the
 * next navigation with an empty state object, which is a no-op by
 * construction: nothing to destroy, and closeAll()/setRoute() are idempotent
 * and always correct for the route being navigated TO.
 *
 * The three sub-routes are separate mounts of the same area, so this fires on
 * traffic -> workloads too, not only on investigate -> elsewhere: every
 * sub-route tears its own instruments down before the next one builds its own.
 *
 * What it releases, and why each one needs releasing:
 *   - table handles: components/table.mjs's destroy() detaches the table from
 *     its host. Held in state.tables (plus the shadow panel's own handle),
 *     which every repaint also drains — so a repaint leaks nothing either.
 *   - the accelerate timers: a 10-minute re-issue interval that outlives the
 *     page would keep writing to the PCE from a route the operator has left.
 *     This is the one genuinely harmful leak in this area.
 *   - the cell popover: it is appended to document.body, not to the area root
 *     the router clears, so it would survive the navigation on screen.
 *   - drawer/modal: both are page-global singletons with no per-area scoping,
 *     so closeAll() is the only way to guarantee nothing this mount opened
 *     survives. A FilterBar or an object-browser table mounted in a drawer
 *     body is destroyed by that drawer's own onClose hook, registered by
 *     whichever opener mounted it.
 *   - palette: setRoute drops this route's scoped commands.
 * state.torn also stops every in-flight query/POST from repainting a torn-down
 * view when it finally resolves.
 */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    if (state.rankState) {
      state.rankState.torn = true;
      (state.rankState.chartHandles || []).forEach(function (h) {
        try { h.destroy(); } catch (e) { console.error("[investigate] chart teardown failed", e); }
      });
      state.rankState.chartHandles = [];
    }
    (state.tables || []).forEach(function (h) {
      try { h.destroy(); } catch (e) { console.error("[investigate] table teardown failed", e); }
    });
    state.tables = [];
    if (state.shadowTable) {
      try { state.shadowTable.destroy(); } catch (e) { console.error("[investigate] table teardown failed", e); }
      state.shadowTable = null;
    }
    cancelAccel(state);
    closePopover();
    setFilterBarBrowser(null);
    drawer.closeAll();
    modal.closeAll();
    palette.setRoute(path);
  });
}

// unsupportedLabel is exported test-only, for the drift guard in
// tests/test_v2_investigate_e2e.py (Fix round 1, Minor 3) that ties it to
// archive_query.py's UNSUPPORTED_ARCHIVE_FILTER_KEYS the same way
// test_archive_query.py's own drift test ties that constant to the
// analyzer's — nothing else in this module imports it.
export { mountTraffic, mountWorkloads, mountEvents, unsupportedLabel };
