// investigate.mjs — #/investigate/{traffic,workloads,events}.
// Anchors IV-01…IV-15, XC-03/04/08/09/11/12 (design/v2/coverage.yaml).
//
// The three sub-views are one instrument: a query workbench.
//   sub-nav → what am I asking about
//   KPI row → what the current answer measures
//   controls → how to ask it differently
//   results → the answer, paged
//   guide rail → what the fields mean (traffic only; XC-11)
// Nothing on these pages is a summary card: every panel here either takes an
// input or shows the rows that came back. That is the whole difference between
// this area and #/overview, and it is why the layout is a single column of
// full-width instruments rather than a board of tiles.
//
// Field semantics are transcribed from the shipping GUI with the source line
// cited above each builder. Anything this design added is marked DESIGN-ADDED
// (Task 7 report §9.9). The mockup never calls an API: every figure comes from
// design/v2/snapshots via store.load(), and any control whose effect needs a
// backend says so instead of animating a lie.

import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { num, stamp, tone } from "../core/fmt.mjs";
import { store } from "../core/store.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { areaHead } from "./placeholder.mjs";
import { createFilterBar, setFilterBarText, setFilterBarSnapshots } from "../components/filter-bar.mjs";
import { setFilterBarBrowser, addPillFromBrowser, _objfbCorpus } from "../components/filter-bar.mjs";
import { verifyPane } from "../components/verifypane.mjs";

const R_TRAFFIC = "#/investigate/traffic";
const R_WORKLOADS = "#/investigate/workloads";
const R_EVENTS = "#/investigate/events";

const SUB_ROUTES = [
  [R_TRAFFIC, "gui_traffic_analyzer"],
  [R_WORKLOADS, "gui_workload_search"],
  [R_EVENTS, "gui_event_viewer"],
];

// index.html:845-850 (select#qt-mins) — the window options, value + catalogue key.
const WINDOWS = [["60", "gui_win_1h"], ["1440", "gui_win_24h"], ["10080", "gui_win_1w"], ["43200", "gui_win_1m"]];
// index.html:859-863 (select#qt-sort)
const SORTS = [["bandwidth", "gui_opt_bandwidth"], ["volume", "gui_opt_volume"], ["connections", "gui_opt_connections"]];
// index.html:868-871 (select#traffic-source) — the product's two sources are the
// live cache and the loaded archive review DB (actions.py:92-107). coverage.yaml
// calls IV-02 "cache/PCE"; the shipping control is cache/archive and inventing a
// third option to match the wording would be inventing UI.
const SOURCES = [["live", "gui_traffic_source_live"], ["archive", "gui_traffic_source_archive"]];
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
// index.html:2549-2550 (select#cb-source) / :2566-2569 (quick ranges)
const BACKFILL_SOURCES = [["events", "gui_cb_source_events"], ["traffic", "gui_cb_source_traffic"]];
const BACKFILL_RANGES = ["1", "7", "30", "60"];
// index.html:1173-1180 (select#ev-mins) / :1184-1188 (select#ev-limit)
const EV_WINDOWS = [["15", "gui_ev_window_15m"], ["60", "gui_ev_window_1h"], ["360", "gui_ev_window_6h"],
  ["1440", "gui_ev_window_24h"], ["10080", "gui_ev_window_7d"], ["43200", "gui_ev_window_30d"], ["86400", "gui_ev_window_60d"]];
const EV_LIMITS = ["25", "50", "100", "200"];
// gui/routes/events.py:165-172 — shadow_compare clamps mins to [5, 10080] and
// limit to [1, 500].
const SHADOW_MINS = ["60", "360", "1440", "10080"];
const SHADOW_LIMITS = ["50", "200", "500"];

const TRAFFIC_SNAPS = ["traffic_search", "archive_status", "cache_status", "cache_settings", "fb_suggest", "fb_browse"];
const WORKLOAD_SNAPS = ["workload_search", "status"];
const EVENT_SNAPS = ["event_catalog", "events_viewer"];

function lookup(pairs, key, fallback) {
  let hit = fallback;
  pairs.forEach(function (pair) { if (pair[0] === String(key)) hit = pair[1]; });
  return hit;
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

/** A button. Extra attributes are set afterwards so no attrs literal ever
 *  exceeds the four keys design/v2/tools/lint_no_inline_data.py allows. */
function btn(cls, text, onClick) {
  return el("button", { class: cls, type: "button", text: text, onClick: onClick });
}

function badge(text, tn) {
  return el("span", { class: "badge", "data-tone": tn }, el("i", { class: "dot" }), el("span", { text: text }));
}

function areaTop(active) {
  const head = areaHead(t("v2_nav_investigate"), active);
  const nav = el("nav", { class: "subnav", "aria-label": t("v2_nav_investigate") });
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
/** A checkbox column: header selects/clears the page, body cell picks one row.
 *  table.mjs's Column carries an optional `head` builder for exactly this. */
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

function loadAll(ids) {
  return Promise.all(ids.map(function (id) { return store.load(id); })).then(function (list) {
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
 * delta needs a previous query to compare against and the mockup has one
 * snapshot, so the slot carries what the figure is derived FROM instead. */
function kpiRow(rows) {
  const k = trafficKpis(rows);
  const basis = tf("v2_iv_kpi_basis", { n: num(rows.length) });
  return el("div", { class: "kpirow" },
    kpiCell("gui_tw_kpi_flows", num(k.flows), t("gui_flows"), basis),
    kpiCell("gui_tw_kpi_conns", fmtCompact(k.conns), null, basis),
    kpiCell("gui_tw_kpi_dst_ips", num(k.dstIps), null, basis),
    kpiCell("gui_tw_kpi_peak_bw", fmtBw(k.peakBw), null, basis)
  );
}

/* index.html:2917-2926 (gui_ta_guide_search_desc + the six list items) — the
 * product documents Filter Details as real-time matching over the returned
 * rows (top 500), on process, user, service, workload name, IP and port. That
 * is a client-side match by the product's own definition, so the mockup runs
 * exactly those six fields and nothing else. */
function rowMatches(r, q) {
  if (!q) return true;
  const needle = q.toLowerCase();
  const s = r.source || {};
  const d = r.destination || {};
  const svc = r.service || {};
  const hay = [s.process, s.user, d.process, d.user, svc.process, svc.user,
    svc.name, s.name, d.name, s.ip, d.ip, svc.port, svc.proto];
  return hay.some(function (v) { return String(v === null || v === undefined ? "" : v).toLowerCase().indexOf(needle) >= 0; });
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
// the next outside click. XC-12's popover leg.
let livePopover = null;

function cellPopover(target, title, items) {
  if (livePopover && livePopover.parentNode) livePopover.parentNode.removeChild(livePopover);
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
      if (pop.parentNode) pop.parentNode.removeChild(pop);
      if (livePopover === pop) livePopover = null;
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
    if (sort === "bandwidth") r.metric = item.formatted_bandwidth;
    else if (sort === "volume") r.metric = item.formatted_volume;
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
    // Deliberately NO row tone: in this capture every row is potentially_blocked,
    // so a per-row mark would paint the whole table amber and flag nothing
    // (components.css:110 — only exceptions wear a mark). The decision badge in
    // the Policy column is the single carrier of that tone.
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
 * (quarantine.js:14-17, toggleQChecks). A row with neither end a workload gets
 * the same dash the Actions column shows instead of a checkbox. */
function trafficColumns(onIsolate, sel) {
  const pageBoxes = [];
  return [
    col("pick", "", pickCell(
      function () {
        const all = el("input", { type: "checkbox" });
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
        cb.checked = sel.isChecked(r);
        cb.addEventListener("change", function () { sel.toggle(r, cb.checked); });
        pageBoxes.push({ r: r, cb: cb });
        return cb;
      }
    )),
    col("metric", t("gui_metric"), widthCell(185, function (r) { return el("b", { class: "mono", text: r.metric }); })),
    col("seen", t("gui_first_last_seen"), widthCell(150, function (r) {
      return el("span", { class: "idc" }, el("small", { text: "F " + r.first }), el("small", { text: "L " + r.last }));
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

/* XC-09 — an empty result is a question, not a shrug. Each candidate cause is
 * paired with the reading that supports or rules it out, taken from the
 * snapshots the appliance actually returns:
 *   cache enabled?  cache_settings.enabled + cache_status row counts
 *   inside the window? traffic_raw_retention_days / the loaded archive range
 *   filters too tight? the live pill count and the quick-search string
 * quarantine.js:402-404 already distinguishes "archive not loaded" from "no
 * traffic"; this generalises that one distinction into the three the operator
 * can act on. */
function emptyCauses(state, d) {
  const settings = d.cache_settings || {};
  const cstat = d.cache_status || {};
  const arch = d.archive_status || {};
  const list = el("ul", { class: "causes" });

  function cause(qKey, answer, tn, reason) {
    list.appendChild(el("li", { "data-tone": tn },
      el("span", { class: "q", text: t(qKey) }),
      el("span", { class: "a", "data-tone": tn, text: answer }),
      el("span", { class: "r", text: reason })
    ));
  }

  const on = settings.enabled === true;
  cause("v2_iv_cause_cache", on ? t("gui_enabled") : t("gui_state_off"), on ? "ok" : "crit",
    tf("v2_iv_cause_cache_r", { raw: num(cstat.traffic_raw), agg: num(cstat.traffic_agg) }));

  if (state.source === "archive") {
    const loaded = arch.loaded === true && Number(arch.rows) > 0;
    cause("v2_iv_cause_window", loaded ? arch.start + " → " + arch.end : t("gui_traffic_archive_none"),
      loaded ? "info" : "crit",
      loaded ? tf("v2_iv_cause_archive_r", { rows: num(arch.rows), files: num(arch.files) }) : t("gui_archive_not_loaded"));
  } else {
    const days = settings.traffic_raw_retention_days;
    cause("v2_iv_cause_window", tf("v2_iv_days", { n: days === undefined ? "—" : days }), "info",
      tf("v2_iv_cause_window_r", { mins: state.mins }));
  }

  // the quick search is a condition like any other — count it, or a lone search
  // string reads as "0 conditions" beside the very string that emptied the table
  const conditions = Object.keys(state.filters || {}).length + (state.search ? 1 : 0);
  cause("v2_iv_cause_filter",
    conditions ? tf("v2_iv_cause_filter_n", { n: conditions }) : t("v2_iv_cause_filter_none"),
    conditions ? "warn" : "neutral",
    state.search ? tf("v2_iv_cause_filter_q", { q: state.search }) : t("v2_iv_cause_filter_none"));

  return list;
}

function emptyState(state, d) {
  const box = el("div", { class: "empty", "data-cov": "XC-09" },
    el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
    el("p", { text: state.source === "archive" && !(d.archive_status || {}).loaded
      ? t("gui_archive_not_loaded") : t("gui_no_traffic") }),
    emptyCauses(state, d)
  );
  return box;
}

/* IV-06 — archive status strip. quarantine.js:783-793 (refreshArchiveStatus)
 * chooses between gui_traffic_archive_loaded_fmt {start}/{end}/{n} and
 * gui_traffic_archive_none; the load state (idle/running/error) comes from the
 * same payload's `load` object (:817-826). Always rendered, not only in archive
 * mode: knowing an archive exists is what makes the source switch meaningful.
 * DESIGN-ADDED: rendering `load.state` as a tone-coloured badge is new — the
 * product never badges this field at all (see the note on the badge line
 * below). */
function archiveStrip(d, onSwitch) {
  const a = d.archive_status || {};
  const loaded = a.loaded === true && Number(a.rows) > 0;
  const load = a.load || {};
  const strip = el("div", { class: "strip", "data-cov": "IV-06", "data-tone": loaded ? "ok" : "neutral" });
  strip.appendChild(el("span", { text: t("gui_traffic_archive_range") }));
  strip.appendChild(el("b", { text: loaded
    ? tf("gui_traffic_archive_loaded_fmt", { start: a.start, end: a.end, n: num(a.rows) })
    : t("gui_traffic_archive_none") }));
  strip.appendChild(el("span", { text: tf("v2_iv_archive_files", { files: num(a.files), skipped: num(a.skipped) }) }));
  strip.appendChild(el("span", { class: "spacer" }));
  // DESIGN-ADDED: the product surfaces `load.state` as plain text only —
  // it is never badged/toned there. The error/ok tone split here is a
  // design-time verdict, not a transcription of product behaviour.
  strip.appendChild(badge(String(load.state || "idle"), tone(load.state === "error" ? "error" : "ok")));
  strip.appendChild(el("button", { class: "btn ghost", type: "button", text: t("gui_traffic_archive_load"), onClick: onSwitch }));
  return strip;
}

/* IV-04 + XC-11 — the guide rail. Content is transcribed from the two shipping
 * help surfaces: index.html:2908-2942 (modal-qt-guide, the traffic analyzer's
 * own parameter guide) and :2871-2905 (m-help, the API parameter guide). Both
 * are modals in the product; here they are a rail, because a syntax reference
 * you have to dismiss before typing is a reference you read once. */
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

  // The quarantine half of the rail (coverage calls XC-11 "篩選語法/隔離指南"):
  // index.html:2480 (gui_q_desc_line2) and :2493 (gui_q_direction_hint) are the
  // product's own two sentences about what quarantine can and cannot touch.
  const q = panel(null, t("gui_q_title"));
  q.body.appendChild(note(t("gui_q_desc_line2")));
  q.body.appendChild(note(t("gui_q_direction_hint")));
  q.body.appendChild(el("button", { class: "btn ghost", type: "button",
    text: t("v2_health_goto") + " " + R_WORKLOADS, onClick: function () { router.go(R_WORKLOADS); } }));
  aside.appendChild(q);
  return aside;
}

/* IV-03 + XC-03 + XC-04 — the advanced filter drawer: the ported FilterBar plus
 * the two policy-decision radio groups (index.html:2417-2455, modal-qt-filters).
 * The FilterBar's serialized dict is what the product sends to
 * /api/quarantine/search (quarantine.js:293, Object.assign into the payload), so
 * the drawer shows that dict verbatim underneath — it is the only honest way to
 * demonstrate the AND/OR semantics without a backend to run them. */
function filtersDrawer(state, d, onApply) {
  const body = el("div", { "data-cov": "IV-03" });
  const barHost = el("div", { "data-cov": "XC-03" });
  body.appendChild(el("h4", { class: "eyebrow", text: t("gui_qt_object_filters") }));
  body.appendChild(barHost);

  const preview = el("pre", { class: "codepane" });
  const bar = createFilterBar(barHost, filterBarOpts(state.filters));

  function refresh() {
    state.filters = bar.getFilters();
    preview.textContent = JSON.stringify(state.filters, null, 2);
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

  body.appendChild(el("h4", { class: "eyebrow", text: t("v2_iv_payload") }));
  body.appendChild(verifyPane(preview));
  body.appendChild(note(t("v2_iv_payload_note")));

  return drawerSpec(t("gui_qt_filters_title"), body, function () {
    state.filters = bar.getFilters();
    onApply();
    return true;
  });
}

function filterBarOpts(initial) {
  const o = {};
  if (initial) o.initial = initial;
  return o;
}

/* XC-04 — the object browser. Production opens a modal (index.html:2458-2468 +
 * object-browser.js) with category tabs, a search box, a paged checkbox list and
 * an Add button. The mockup's modal component is reserved for destructive
 * confirmation (Task 7 §2), so the picker uses the drawer — same job, same
 * Add-on-save contract. Rows come from fb_browse/fb_suggest; the categories the
 * capture could not reach say so instead of showing empty tabs that look broken. */
function objectBrowser(fbState) {
  const body = el("div", { "data-cov": "XC-04" });
  const cats = ["label", "label_group", "iplist", "workload", "service"];
  const chosen = {};
  let cat = "label";
  let q = "";

  const tabs = el("div", { class: "chips" });
  const listHost = el("div");
  const meta = el("p", { class: "note" });

  const search = el("input", { class: "field", placeholder: t("gui_ob_search_ph") });
  search.addEventListener("input", function () { q = search.value.trim(); paint(); });

  function paint() {
    clear(tabs);
    cats.forEach(function (c) {
      const items = _objfbCorpus(c);
      const b = btn("btn ghost", t("gui_fb_cat_" + c), function () { cat = c; paint(); });
      b.setAttribute("aria-pressed", c === cat ? "true" : "false");
      if (!items) b.disabled = true;
      tabs.appendChild(b);
    });

    const all = _objfbCorpus(cat) || [];
    const rows = all.filter(function (it) {
      return !q || String(it.name || "").toLowerCase().indexOf(q.toLowerCase()) >= 0;
    });
    meta.textContent = rows.length
      ? tf("v2_table_rows", { total: rows.length })
      : t("gui_fb_type_to_search");

    const cols = [
      col("pick", "", widthCell(34, function (r) {
        const cb = el("input", { type: "checkbox" });
        cb.checked = !!chosen[r.href || r.name];
        cb.addEventListener("change", function () {
          if (cb.checked) chosen[r.href || r.name] = r;
          else delete chosen[r.href || r.name];
        });
        return cb;
      })),
      col("key", t("gui_col_type"), widthCell(90, function (r) { return el("span", { class: "mono", text: r.key || cat }); })),
      col("name", t("gui_col_name"), buildCell(function (r) { return r.name; })),
    ];
    table.render(listHost, buildTable(cols, rows.slice(0, 60)));
  }

  body.appendChild(tabs);
  body.appendChild(el("div", { class: "fld" }, search));
  body.appendChild(meta);
  body.appendChild(listHost);
  paint();

  return drawerSpec(t("gui_ob_title"), body, function () {
    const picked = Object.keys(chosen);
    picked.forEach(function (k) {
      const it = chosen[k];
      const obj = {};
      obj.cat = cat;
      obj.name = it.name;
      obj.href = it.href || null;
      addPillFromBrowser(fbState, obj);
    });
    if (picked.length) toast.ok(tf("v2_iv_browser_added", { n: picked.length }));
    return true;
  });
}

/* IV-07 — cache backfill. Fields transcribed from index.html:2542-2578
 * (m-cache-backfill): source select, start/end date, the four quick ranges. */
function backfillDrawer() {
  const body = el("div", { "data-cov": "IV-07" });
  body.appendChild(note(t("gui_cb_desc")));

  const state = {};
  state.source = "events";
  const start = el("input", { class: "field", type: "date" });
  const end = el("input", { class: "field", type: "date" });

  body.appendChild(el("div", { class: "fld" },
    selectField(t("gui_cb_source"), BACKFILL_SOURCES, state.source, function (v) { state.source = v; })));
  body.appendChild(el("div", { class: "fld" },
    el("div", { class: "qrow" }, field(t("gui_gen_start_date"), start), field(t("gui_gen_end_date"), end))));

  const quick = el("div", { class: "qrow" });
  BACKFILL_RANGES.forEach(function (days) {
    quick.appendChild(el("button", { class: "btn ghost", type: "button", text: days + "d", onClick: function () {
      // index.html:2566-2569 setDateRange("cb", days) — end today, start N days back
      const now = new Date();
      const from = new Date(now.getTime() - Number(days) * 86400000);
      end.value = now.toISOString().slice(0, 10);
      start.value = from.toISOString().slice(0, 10);
    } }));
  });
  body.appendChild(el("div", { class: "fld" },
    el("label", null, el("span", { text: t("gui_quick_range") })), quick));
  body.appendChild(note(t("v2_iv_backfill_note")));

  return drawerSpec(t("gui_cb_title"), body, function () {
    toast.info(tf("v2_iv_backfill_queued", { source: state.source, start: start.value || "—", end: end.value || "—" }));
    return true;
  });
}

async function mountTraffic(root, ctx) {
  const handles = {};
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
      setFilterBarSnapshots(d.fb_suggest, d.fb_browse);

      const state = {};
      state.mins = "60";
      state.sort = "bandwidth";
      state.source = "live";
      state.search = "";
      state.size = 50;
      state.page = 0;
      state.pd = "";
      state.draftPd = "";
      state.filters = {};
      // {srcHref, dstHref} pairs checked via the pick column — bulk isolation
      // contributes PAIRS here (quarantine.js:66-68, .qt-chk -> addPair), not
      // standalone hrefs the way the workloads table's .qw-chk does (:69-71).
      state.selected = [];

      const search = el("input", { class: "field", placeholder: t("gui_quick_search_placeholder") });
      const host = el("div");
      const floatHost = el("div");
      // The empty state cannot be reached by the captured query (it returned the
      // full 500-row cap), so — exactly as Task 7 does for the error card — the
      // audit hook does not fabricate one: it runs the REAL renderer over a
      // filter that genuinely matches nothing, into its own container, leaving
      // the live results (and the XC-12 anchor on them) untouched. Typing a
      // non-matching string into Filter Details produces the same panel in place.
      const probe = el("div", { class: "wb-main" });

      function currentRows() {
        const all = (d.traffic_search && d.traffic_search.data) || [];
        return all.filter(function (r) { return rowMatches(r, state.search); });
      }

      // JSON.stringify (not a joined string) so the src/dst boundary can never
      // blur -- see design/v2/mockup/js/areas/alerting.mjs ruleSignature() for
      // the same treatment and why a plain separator is unsafe.
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
      // would be a silent no-op button here and isn't rendered.
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

      function repaint() {
        clear(host);
        const rows = currentRows();
        const meta = {};
        meta.truncated = !!(d.traffic_search && d.traffic_search.truncated);
        meta.cap = (d.traffic_search && d.traffic_search.cap) || 0;
        meta.total = (d.traffic_search && d.traffic_search.total_matches) || rows.length;

        host.appendChild(kpiRow(rows));
        host.appendChild(query);
        host.appendChild(archiveStrip(d, function () { toast.info(t("v2_iv_archive_load_note")); }));
        host.appendChild(results(rows, meta));
        paintFloatTraffic();
      }

      // ── controls (IV-01 / IV-02) ──
      const query = panel("IV-01", t("gui_ta_query"));
      withAction(query, t("gui_cb_title"), function () { if (handles.openBackfill) handles.openBackfill(); });
      withAction(query, t("gui_filter_settings"), function () { if (handles.openFilters) handles.openFilters(); });
      const row = el("div", { class: "qrow" });
      row.appendChild(selectField(t("gui_window"), WINDOWS, state.mins, function (v) { state.mins = v; }));
      const src = selectField(t("gui_traffic_source"), SOURCES, state.source, function (v) {
        state.source = v;
        state.page = 0;
        repaint();
      });
      src.setAttribute("data-cov", "IV-02");
      row.appendChild(src);
      row.appendChild(selectField(t("gui_sort_by"), SORTS, state.sort, function (v) { state.sort = v; state.page = 0; repaint(); }));
      const searchField = field(t("gui_filter_details"), search);
      searchField.className = "qf grow";
      row.appendChild(searchField);
      search.addEventListener("input", function () { state.search = search.value.trim(); state.page = 0; repaint(); });
      row.appendChild(el("span", { class: "spacer" }));
      row.appendChild(el("button", { class: "btn primary", type: "button", text: t("gui_query_flow"), onClick: function () {
        state.page = 0;
        repaint();
        toast.ok(tf("v2_iv_query_snapshot", { n: num(currentRows().length) }));
      } }));
      query.body.appendChild(row);

      // ── results (IV-05 + XC-12) ──
      function results(rows, meta) {
        const p = panel("IV-05", t("gui_traffic_analyzer"));
        withMeta(p, tf("gui_total_found", { count: num(rows.length) }));
        headBox(p).appendChild(selectField(t("gui_page_size"), PAGE_SIZES, String(state.size), function (v) {
          state.size = Number(v);
          state.page = 0;
          repaint();
        }).control);
        p.body.classList.add("flush");

        if (!rows.length) {
          p.body.classList.remove("flush");
          p.body.appendChild(emptyState(state, d));
          return p;
        }
        // quarantine.js:391-394 — a truncated result is warned about ONCE, in
        // words, because every figure above it is a floor and not a total.
        if (meta.truncated) {
          p.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
            el("i", { class: "dot" }),
            el("span", { text: tf("gui_results_truncated", { cap: meta.cap, total: num(meta.total) }) })));
        }
        // The table host carries XC-12: skeleton while a page swaps, the column
        // resize grips, the service popover and the query toast all live here.
        const tblHost = el("div", { "data-cov": "XC-12" });
        p.body.appendChild(tblHost);
        const model = trafficRows(rows, state.sort);
        const shown = model.slice(state.page * state.size, (state.page + 1) * state.size);
        const sel = { isChecked: isTrafficSelected, toggle: toggleTrafficSel };
        const handle = table.render(tblHost, pagedTable(trafficColumns(function (r) { openQuarantine(r, d); }, sel),
          shown, pageSpec(state.page, state.size, model.length), function (next) {
            state.page = Math.max(0, next);
            // a page swap shows the skeleton for a frame, exactly as a refetch would
            handle.update(null);
            repaint();
          }));
        return p;
      }

      main.appendChild(host);
      main.appendChild(probe);
      main.appendChild(floatHost);
      handles.openFilters = function () {
        const h = drawer.open(filtersDrawer(state, d, function () {
          state.page = 0;
          repaint();
          toast.ok(tf("v2_iv_filters_applied", { n: Object.keys(state.filters).length }));
        }));
        h.el.classList.add("wide");        // three zones need the room
        return h;
      };
      handles.openBackfill = function () { return drawer.open(backfillDrawer()); };
      // quarantine.js:66-68 — bulk isolation off the traffic table contributes
      // src/dst PAIRS, not standalone hrefs (that's what the workloads table's
      // .qw-chk selection does, in buildQuarantineState's other bulk leg above).
      handles.openBulk = function () {
        const chosen = state.selected.length ? state.selected.slice()
          : trafficRows(currentRows(), state.sort)
            .filter(function (r) { return r.srcHref || r.dstHref; })
            .slice(0, 2)
            .map(function (r) { return { srcHref: r.srcHref, dstHref: r.dstHref }; });
        return drawer.open(quarantineDrawer(buildQuarantineState(null, true, null, null, chosen), true));
      };
      handles.probeEmpty = function () {
        if (probe.firstChild) return;                     // idempotent
        const probeState = Object.assign({}, state);
        probeState.search = "__no_such_flow__";
        const p = panel(null, t("gui_traffic_analyzer"));
        withMeta(p, tf("gui_total_found", { count: 0 }));
        p.body.appendChild(emptyState(probeState, d));
        probe.appendChild(p);
      };
      setFilterBarBrowser(function (fbState) {
        drawer.open(objectBrowser(fbState)).el.classList.add("wide");
      });
      handles.openBrowser = function () {
        // the browser needs a live bar to add pills to; open the filter drawer first
        const filters = handles.openFilters();
        const fbHost = filters.el.querySelector("[data-cov=\"XC-03\"]");
        const fbState = fbHost && window._objfbGetInstance ? window._objfbGetInstance(fbHost.dataset.objfbId) : null;
        if (!fbState) return null;
        const h = drawer.open(objectBrowser(fbState));
        h.el.classList.add("wide");
        return h;
      };
      repaint();
    });
}

// ═════════════════════════════════════════════════════ workloads ════════════

/* quarantine.js:48-79 (_buildQuarantineState) — a bulk selection contributes
 * standalone hrefs AND pairs at once: `.qw-chk` (workload table rows) adds a
 * standalone href each (:69-71), `.qt-chk` (traffic table rows) adds a
 * src/dst PAIR each (:66-68) — a bulk selection is never only one or the
 * other. A single (non-bulk) row with two distinct ends contributes one
 * pair; anything else is standalone. */
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
export function computeQuarantineTargets(state, direction) {
  const targets = [];
  const pushUnique = function (href) {
    const normalized = String(href || "").trim();
    if (normalized && !targets.includes(normalized)) targets.push(normalized);
  };
  (state.standalone || []).forEach(pushUnique);
  (state.pairs || []).forEach(function (pair) {
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

// Names for hrefs, so the confirmation can say WHICH workloads it will isolate
// instead of only how many. Filled by whichever sub-view is on screen.
const hrefNames = new Map();

function nameOf(href) {
  return hrefNames.get(href) || String(href || "").split("/").pop();
}

/* IV-09 / IV-10 / XC-08 — the quarantine drawer, then the confirmation.
 * index.html:2471-2511 (m-quarantine): the direction radios appear only when a
 * pair has two distinct ends (:141-142), and default to 'both' for a bulk
 * selection with such a pair, 'source' otherwise (:143). */
function quarantineDrawer(qstate, isBulk) {
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
    if (targets.length > 8) listBox.appendChild(el("li", { text: tf("v2_iv_more_targets", { n: targets.length - 8 }) }));
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
    if (targets.length > 6) impact.push(tf("v2_iv_more_targets", { n: targets.length - 6 }));
    modal.confirm(confirmSpec(t("gui_q_apply"), impact, function () {
      toast.warn(tf("gui_q_applied", { count: targets.length, level: view.level }));
    }));
    return true;
  });
}

function openQuarantine(row, d) {
  hrefNames.set(row.srcHref, (row.src || {}).name || row.srcHref);
  hrefNames.set(row.dstHref, (row.dst || {}).name || row.dstHref);
  const qstate = buildQuarantineState(row.srcHref || row.dstHref, false,
    row.srcHref && row.dstHref ? row.dstHref : null, null);
  drawer.open(quarantineDrawer(qstate, false));
}

/* IV-12 — the accelerate drawer. index.html:2514-2539 (m-accelerate): the
 * summary counts total / managed / skipped, the duration radios are 0 (single
 * shot) / 30 / 60 / 120 minutes, and a non-zero duration raises the countdown
 * bar (#accel-countdown) that re-issues every 10 minutes until it expires
 * (quarantine.js:732-739). The mockup runs the countdown for real and states
 * that the re-issue is what a backend would do. */
function accelerateDrawer(selected, rowsByHref, onStart) {
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
    const text = v === "0" ? t("gui_accel_single") : tf("v2_iv_minutes", { n: v });
    group.appendChild(el("label", null, input, el("span", { text: text })));
  });
  body.appendChild(el("div", { class: "fld" },
    el("label", null, el("span", { text: t("gui_accel_duration") })), group));
  body.appendChild(note(t("v2_iv_accel_note")));

  return drawerSpec(t("gui_accel_modal_title"), body, function () {
    if (!managed.length) {
      toast.warn(t("gui_accel_unmanaged_tip"));
      return false;
    }
    toast.ok(tf("gui_accel_started", { n: managed.length }));
    onStart(managed.length, Number(view.duration));
    return true;
  });
}

/* quarantine.js:750-771 (_showAccelCountdown) — mm:ss, ticking every second,
 * gone when it reaches zero. The bar removes itself if its route was left. */
function accelCountdown(host, count, minutes) {
  if (!minutes) return null;
  const endTs = Date.now() + minutes * 60000;
  const remaining = el("b");
  const bar = el("div", { class: "floatbar", "data-tone": "ok" },
    el("i", { class: "dot" }),
    el("span", { text: t("gui_accel_running_label") + " " }),
    el("b", { text: String(count) }),
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
  const timer = setInterval(function () {
    const left = endTs - Date.now();
    if (left <= 0 || !document.body.contains(bar)) { close(); return; }
    remaining.textContent = fmt(left);
  }, 1000);
  function close() {
    clearInterval(timer);
    if (bar.parentNode) bar.parentNode.removeChild(bar);
  }
  stop.addEventListener("click", close);
  return bar;
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
    // "Quarantine" label chip (:573-622 above) — it never computes a row-level
    // verdict tone. This crit/warn/null tone (quarantined -> crit, offline ->
    // warn) is a design-time reading of that same data, not a transcription.
    r._tone = r.quarantined ? "crit" : (r.online ? null : "warn");
    return r;
  });
}

async function mountWorkloads(root, ctx) {
  const handles = {};
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

  await withErrorCard(main, "workloads (" + WORKLOAD_SNAPS.length + ")",
    function () { return loadAll(WORKLOAD_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      const list = (d.workload_search && d.workload_search.data) || [];
      const model = workloadRows(list);
      const byHref = new Map();
      model.forEach(function (r) {
        byHref.set(r.href, r);
        hrefNames.set(r.href, r.name);
      });

      const state = {};
      state.name = "";
      state.ip = "";
      state.host = "";
      state.size = 50;
      state.page = 0;
      state.selected = [];

      const host = el("div");
      const floatHost = el("div");
      main.appendChild(host);
      main.appendChild(floatHost);

      function matches(r) {
        const hit = function (value, needle) {
          return !needle || String(value || "").toLowerCase().indexOf(needle.toLowerCase()) >= 0;
        };
        // index.html:947-961 — the product sends name / ip_address / hostname to
        // /api/workloads; the same three fields are matched here over the capture.
        return hit(r.name, state.name)
          && hit(r.hostname, state.host)
          && (!state.ip || r.ips.some(function (i) { return String(i.address).indexOf(state.ip) >= 0; }));
      }

      function current() { return model.filter(matches); }

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
            if (r.ips.length > 3) box.appendChild(el("small", { text: tf("v2_iv_more_ips", { n: r.ips.length - 3 }) }));
            if (!r.ips.length) box.appendChild(el("small", { text: "—" }));
            return box;
          })),
          col("labels", t("gui_ws_col_labels"), buildCell(function (r) {
            return r.labels.length ? labelChips(r.labels) : el("span", { class: "mono", text: t("gui_no_labels") });
          })),
          col("act", t("gui_actions"), widthCell(200, function (r) {
            const box = el("span");
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
        clear(host);
        const rows = current();

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
            state.page = 0;
            repaint();
          });
        });
        const f1 = field(t("gui_workload_name"), nameIn);
        const f2 = field(t("gui_ip_address"), ipIn);
        const f3 = field(t("gui_hostname"), hostIn);
        f1.className = "qf grow";
        f2.className = "qf grow";
        f3.className = "qf grow";
        row.appendChild(f1);
        row.appendChild(f2);
        row.appendChild(f3);
        row.appendChild(el("button", { class: "btn primary", type: "button", text: t("gui_find"), onClick: function () {
          toast.ok(tf("gui_total_found_ws", { count: num(rows.length) }));
        } }));
        query.body.appendChild(row);
        host.appendChild(query);

        const p = panel(null, t("gui_workload_search"));
        withMeta(p, tf("gui_total_found_ws", { count: num(rows.length) }));
        headBox(p).appendChild(selectField(t("gui_page_size"), PAGE_SIZES, String(state.size), function (v) {
          state.size = Number(v);
          state.page = 0;
          repaint();
        }).control);
        p.body.classList.add("flush");
        if (!rows.length) {
          p.body.classList.remove("flush");
          p.body.appendChild(el("div", { class: "empty" },
            el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
            el("p", { text: t("gui_ws_empty") })));
        } else {
          const shown = rows.slice(state.page * state.size, (state.page + 1) * state.size);
          table.render(p.body, pagedTable(columns(), shown,
            pageSpec(state.page, state.size, rows.length), function (next) {
              state.page = Math.max(0, next);
              repaint();
            }));
        }
        host.appendChild(p);
        paintFloat();
      }

      handles.openSingle = function (href) {
        const target = href || model[0].href;
        return drawer.open(quarantineDrawer(buildQuarantineState(target, false, null, null), false));
      };
      handles.openBulk = function () {
        const picked = state.selected.length ? state.selected : model.slice(0, 2).map(function (r) { return r.href; });
        return drawer.open(quarantineDrawer(buildQuarantineState(null, true, null, picked), true));
      };
      handles.openAccel = function (hrefs) {
        const picked = hrefs || (state.selected.length ? state.selected : model.slice(0, 2).map(function (r) { return r.href; }));
        return drawer.open(accelerateDrawer(picked, byHref, function (n, minutes) {
          accelCountdown(floatHost, n, minutes);
        }));
      };
      handles.openLift = function (r) {
        // quarantine.js:201-220 — one confirmation, then the label is removed.
        // XC-08 is anchored on the confirmation itself, not on the button that
        // raises it: the coverage item is the confirm-with-impact surface.
        const h = modal.confirm(confirmSpec(t("gui_lift_quarantine"),
          [t("gui_lift_confirm"), r.name], function () { toast.ok(t("gui_lift_done")); }));
        h.el.setAttribute("data-cov", "XC-08");
        return h;
      };
      handles.openConfirm = function () {
        const first = model.filter(function (r) { return r.quarantined; })[0] || model[0];
        return handles.openLift(first);
      };
      handles.selectSome = function () {
        state.selected = model.slice(0, 2).map(function (r) { return r.href; });
        repaint();
      };

      repaint();
    });
}

// ═════════════════════════════════════════════════════ events ═══════════════

/* events.js:11-14 (_eventViewerGroupOf) — the group is the event type's first
 * dotted segment; '*' has no group. */
export function eventGroupOf(eventType) {
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
export function flattenCatalog(response) {
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
export function filteredCatalogItems(catalog, categoryId, groupId) {
  return (catalog.items || []).filter(function (item) {
    if (item.id === "*") return false;
    if (categoryId && item.category_id !== categoryId) return false;
    if (groupId && item.group_id !== groupId) return false;
    return true;
  });
}

/* events.js:58-75 (_populateEventViewerGroupOptions) — unique group_id ->
 * group_label within the chosen category, sorted by LABEL. */
export function groupOptions(catalog, categoryId) {
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
 * error, warn and warning are all bad; anything else (including the null the
 * payload carries for 30 of the 67 captured events) is neutral. */
function statusTone(value) {
  const status = String(value || "").toLowerCase();
  if (status === "success") return "ok";
  if (["failure", "error", "warn", "warning"].indexOf(status) >= 0) return "crit";
  return "neutral";
}

/* IV-15 — shadow compare. There is NO shipping UI for this endpoint: grepping
 * src/static and src/templates for shadow_compare returns nothing, and
 * gui/routes/events.py:150 is reachable only by URL. The panel therefore renders
 * its controls (mins/limit, clamped exactly as :165-172 clamps them) and the
 * result table declared with the columns the endpoint returns — rule_name,
 * current_count, legacy_count, delta, status, events/shadow.py:79-104 — in its
 * empty state, under a strip that says why it is empty. Nothing is
 * fabricated: there is no shadow_compare snapshot to render, and inventing rows
 * that claim two matchers disagree would be inventing a security finding. */
function shadowPanel() {
  const p = panel("IV-15", t("v2_iv_shadow_title"));
  withMeta(p, "/api/events/shadow_compare");
  const view = {};
  view.mins = "60";
  view.limit = "200";

  const row = el("div", { class: "qrow" });
  row.appendChild(selectField(t("gui_window_min"), SHADOW_MINS, view.mins, function (v) { view.mins = v; }));
  row.appendChild(selectField(t("gui_rows"), SHADOW_LIMITS, view.limit, function (v) { view.limit = v; }));
  row.appendChild(el("span", { class: "spacer" }));
  const host = el("div");
  row.appendChild(el("button", { class: "btn primary", type: "button", text: t("gui_refresh"), onClick: function () {
    toast.warn(t("v2_iv_shadow_unavailable"));
    paint();
  } }));
  p.body.appendChild(row);
  p.body.appendChild(note(t("v2_iv_shadow_desc")));
  p.body.appendChild(host);

  function paint() {
    const cols = [
      col("rule", t("gui_col_name"), buildCell(function (r) { return r.rule_name; })),
      col("current", t("v2_iv_shadow_current"), numCell(function (r) { return num(r.current_count); })),
      col("legacy", t("v2_iv_shadow_legacy"), numCell(function (r) { return num(r.legacy_count); })),
      col("delta", t("v2_iv_shadow_delta"), numCell(function (r) { return num(r.delta); })),
      col("status", t("gui_col_status"), widthCell(110, function (r) { return badge(r.status, "neutral"); })),
    ];
    table.render(host, buildTable(cols, []));
    host.appendChild(el("div", { class: "strip", "data-tone": "warn" },
      el("span", { text: t("v2_iv_shadow_unavailable") })));
  }
  paint();
  return p;
}

async function mountEvents(root, ctx) {
  const handles = {};
  palette.registerFor(R_EVENTS, cmdSpec("iv:ev-reset", t("gui_ev_all_categories"), function () {
    if (handles.reset) handles.reset();
  }));

  root.appendChild(areaTop(R_EVENTS));
  const wrap = el("div", { class: "wb solo" });
  const main = el("div", { class: "wb-main" });
  wrap.appendChild(main);
  root.appendChild(wrap);

  await withErrorCard(main, "events (" + EVENT_SNAPS.length + ")",
    function () { return loadAll(EVENT_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      const catalog = flattenCatalog(d.event_catalog);
      const viewer = d.events_viewer || {};
      const summary = viewer.summary || {};
      const allItems = viewer.items || [];

      const state = {};
      state.category = "";
      state.group = "";
      state.type = "";
      state.search = "";
      state.limit = 25;
      state.shown = 25;
      state.selected = allItems.length ? allItems[0].event_id : null;

      const filterHost = el("div");
      const layout = el("div", { class: "evl", "data-cov": "IV-14" });
      const tableHost = el("div");
      const aside = el("div", { class: "wb-aside" });
      layout.appendChild(tableHost);
      layout.appendChild(aside);
      main.appendChild(filterHost);
      main.appendChild(layout);
      main.appendChild(shadowPanel());

      function current() {
        return allItems.filter(function (it) {
          // The viewer payload carries the category LABEL (item.category) while the
          // catalogue keys categories by id; in this catalogue the two are the same
          // string ("User Access"), which is why the product can filter server-side
          // on either. The type_group field is the group id.
          if (state.category && it.category !== state.category) return false;
          if (state.group && it.type_group !== state.group) return false;
          if (state.type && it.event_type !== state.type) return false;
          if (!state.search) return true;
          const n = it.normalized || {};
          const hay = [it.event_type, n.actor, n.target_name, n.source_ip, n.action];
          return hay.some(function (v) { return String(v || "").toLowerCase().indexOf(state.search.toLowerCase()) >= 0; });
        });
      }

      // ── IV-13: the three-level cascade ──
      function paintFilters() {
        clear(filterHost);
        const p = panel("IV-13", t("gui_event_viewer"));
        withMeta(p, tf("v2_iv_ev_window", { since: stamp(summary.query_since), until: stamp(summary.query_until) }));
        const row = el("div", { class: "qrow" });

        row.appendChild(selectField(t("gui_window"), EV_WINDOWS, "60", function () {
          toast.info(t("v2_iv_ev_window_note"));
        }));
        row.appendChild(selectField(t("gui_rows"), EV_LIMITS, String(state.limit), function (v) {
          state.limit = Number(v);
          state.shown = Number(v);
          paintTable();
        }));

        const catPairs = [["", "gui_ev_all_categories"]].concat((catalog.categories || []).map(function (c) {
          return [c.id, c.label];
        }));
        const catSel = el("select", { class: "field" });
        catPairs.forEach(function (pair, i) {
          const opt = el("option", { value: pair[0], text: i === 0 ? t(pair[1]) : pair[1] });
          if (pair[0] === state.category) opt.selected = true;
          catSel.appendChild(opt);
        });
        catSel.addEventListener("change", function () {
          // events.js:118-122 — a category change repopulates groups AND types,
          // then re-runs the query
          state.category = catSel.value;
          state.group = "";
          state.type = "";
          paintFilters();
          paintTable();
        });
        row.appendChild(field(t("gui_category"), catSel));

        const grpSel = el("select", { class: "field" });
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
          paintTable();
        });
        row.appendChild(field(t("gui_ev_type_group"), grpSel));

        const typeSel = el("select", { class: "field" });
        typeSel.appendChild(el("option", { value: "", text: t("gui_ev_all_event_types") }));
        filteredCatalogItems(catalog, state.category, state.group)
          .sort(function (a, b) { return a.label.localeCompare(b.label); })
          .forEach(function (item) {
            const opt = el("option", { value: item.id, text: typeOptionLabel(item) });
            if (item.id === state.type) opt.selected = true;
            typeSel.appendChild(opt);
          });
        typeSel.addEventListener("change", function () { state.type = typeSel.value; paintTable(); });
        const typeField = field(t("gui_event_type"), typeSel);
        typeField.className = "qf grow";
        row.appendChild(typeField);

        const searchIn = el("input", { class: "field", placeholder: t("gui_ev_search_placeholder"), value: state.search });
        searchIn.addEventListener("input", function () { state.search = searchIn.value.trim(); paintTable(); });
        const sf = field(t("gui_search"), searchIn);
        sf.className = "qf grow";
        row.appendChild(sf);
        p.body.appendChild(row);
        p.body.appendChild(note(tf("v2_iv_ev_catalog", {
          cats: (catalog.categories || []).length, types: (catalog.items || []).length,
        })));
        filterHost.appendChild(p);
      }

      // ── IV-14: rows, load-more, detail ──
      function paintTable() {
        clear(tableHost);
        const rows = current();
        const p = panel(null, t("gui_tab_events"));
        withMeta(p, t("gui_ev_matched") + " " + num(rows.length) + " · "
          + t("gui_ev_showing") + " " + num(Math.min(state.shown, rows.length)));
        p.body.classList.add("flush");

        if (!rows.length) {
          p.body.classList.remove("flush");
          p.body.appendChild(el("div", { class: "empty" },
            el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
            el("p", { text: t("gui_ev_no_match") })));
          tableHost.appendChild(p);
          paintDetail(null);
          return;
        }

        const shown = rows.slice(0, state.shown);
        const model = shown.map(function (it) {
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

        const cols = [
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
        const handle = table.render(p.body, buildTable(cols, model));
        handle.el.querySelectorAll("tbody tr").forEach(function (tr, i) {
          tr.style.cursor = "pointer";
          tr.addEventListener("click", function () {
            state.selected = model[i].id;
            paintTable();
          });
          if (model[i].id === state.selected) tr.setAttribute("aria-selected", "true");
        });

        // events.js:252-259 / 314-318 — load more appears only while the server
        // says there is more; here "more" is the rest of the captured page.
        const foot = el("div", { class: "panel-b" });
        if (state.shown < rows.length) {
          foot.appendChild(el("button", { class: "btn", type: "button",
            text: t("gui_load_more") + " (" + num(state.shown) + "/" + num(rows.length) + ")",
            onClick: function () { state.shown += state.limit; paintTable(); } }));
        } else {
          foot.appendChild(note(summary.has_more
            ? t("v2_iv_ev_more_server")
            : tf("v2_iv_ev_all", { n: num(rows.length) })));
        }
        p.body.appendChild(foot);
        tableHost.appendChild(p);

        const selected = rows.filter(function (it) { return it.event_id === state.selected; })[0] || rows[0];
        paintDetail(selected);
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
        // :198-200 — username comes from created_by.user, then actor, then '—'.
        // The viewer payload has neither at the top level (created_by lives inside
        // `raw`), so the product's card shows '—' here for every one of the 67
        // captured events. DESIGN-ADDED: fall back to the parsed actor, which is
        // the same person, rather than render a dash the operator cannot explain.
        const rawBy = (item.raw && item.raw.created_by) || {};
        const username = (rawBy.user && rawBy.user.username) || item.actor || n.actor || "—";
        // DESIGN-ADDED (same substitution as the username fallback above):
        // events.js:199 reads `ev.src_ip` off the top-level event object. The
        // captured snapshot payload has no such top-level field — the IP only
        // shows up as `source_ip` inside the parsed/normalized event — so this
        // reads `n.source_ip` instead. Same value the product would show, read
        // from where the mockup's data actually has it.
        const ip = n.source_ip ? " / " + n.source_ip : "";

        const dl = el("dl", { class: "evmeta" });
        function meta(label, value) {
          dl.appendChild(el("dt", { text: label }));
          dl.appendChild(el("dd", { title: String(value), text: value }));
        }
        meta("event_id", item.event_id);
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
        state.shown = state.limit;
        paintFilters();
        paintTable();
      };

      paintFilters();
      paintTable();
    });
}

export { mountTraffic, mountWorkloads, mountEvents };
