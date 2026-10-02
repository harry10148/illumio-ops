/**
 * #/investigate/fleet — the VEN inventory page (read-only).
 *
 * Everything here reads the snapshot the ven_summary job wrote. The page never
 * asks the PCE anything and never writes to it: it shows where each VEN
 * stands, and changing enforcement mode is done in the PCE itself.
 *
 * Reading order, top to bottom:
 *   1. when the snapshot was taken — a green number from yesterday is not a
 *      green number;
 *   2. IV-16: the six figures an operator asks first (how many, how many
 *      reachable, how many silent, how many behind on version, how many
 *      unaddressable by policy, one health score), then where the estate sits
 *      on the road to enforcement, what the score is made of, and what the
 *      VENs themselves are complaining about;
 *   3. IV-18 / IV-19: version spread and label coverage;
 *   4. IV-17: the workloads behind any of those figures — every figure above
 *      is a link into this list, which can also be searched, sorted, narrowed
 *      by version/app/env and exported.
 *
 * It never renders 0 for a fleet that has not been analysed. "No snapshot
 * yet" and "nothing out there" look identical as numbers and mean opposite
 * things to whoever is on call.
 */
import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { pageHead, crumbsFor, chip } from "../components/page.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { table, col } from "../components/table.mjs";

const ROUTE = "#/investigate/fleet";
const R_PCE = "#/system/pce";
const PAGE_SIZE = 50;

const PIPELINE = [
  "idle_compat_pass", "idle_compat_warn", "idle_compat_fail", "idle_compat_unknown",
  "visibility_ready", "visibility_not_ready", "selective", "full",
];
const MODES = ["idle", "visibility_only", "selective", "full"];
const MODE_OF_STAGE = {
  idle_compat_pass: "idle", idle_compat_warn: "idle", idle_compat_fail: "idle",
  idle_compat_unknown: "idle", visibility_ready: "visibility_only",
  visibility_not_ready: "visibility_only", selective: "selective", full: "full",
};
// Further along the road to enforcement reads greener. idle is not a fault,
// so it is neutral rather than red; Visibility only is the stage that still
// lets everything through, so it carries the caution tone.
const MODE_TONE = { idle: "neutral", visibility_only: "warn", selective: "info", full: "ok" };
const SCORE_PARTS = ["online", "enforcement", "version", "heartbeat", "compat"];

// Every filter value the list understands, in the order the stage menu shows.
const LIST_BUCKETS = ["all", "online", "offline", "fresh", "stale_24h", "stale_48h",
  "no_heartbeat", "unlabeled", "needs_upgrade", "on_target"].concat(PIPELINE);

// Keys are spelled out, never glued together from a prefix and a value. The
// i18n audit reads the source for literal keys, so a key built by
// concatenation at runtime is invisible to it: a bucket whose string went
// missing would ship showing its own identifier and no gate would notice.
// These maps are also the only place the backend's vocabularies are bound
// to copy.
// BUCKET_KEYS is the enforcement pipeline — the same stages the VEN report
// prints (tests/test_fleet_report_copy_parity.py holds the two together).
// The list's other filters are not stages, so they live in FILTER_KEYS.
const FILTER_KEYS = {
  all: "gui_fleet_b_all",
  online: "gui_fleet_b_online",
  offline: "gui_fleet_b_offline",
  fresh: "gui_fleet_b_fresh",
  stale_24h: "gui_fleet_b_stale_24h",
  stale_48h: "gui_fleet_b_stale_48h",
  no_heartbeat: "gui_fleet_b_no_heartbeat",
  unlabeled: "gui_fleet_b_unlabeled",
  needs_upgrade: "gui_fleet_b_needs_upgrade",
  on_target: "gui_fleet_b_on_target",
};
const BUCKET_KEYS = {
  idle_compat_pass: "gui_fleet_b_idle_compat_pass",
  idle_compat_warn: "gui_fleet_b_idle_compat_warn",
  idle_compat_fail: "gui_fleet_b_idle_compat_fail",
  idle_compat_unknown: "gui_fleet_b_idle_compat_unknown",
  visibility_ready: "gui_fleet_b_visibility_ready",
  visibility_not_ready: "gui_fleet_b_visibility_not_ready",
  selective: "gui_fleet_b_selective",
  full: "gui_fleet_b_full",
};
const MODE_KEYS = {
  idle: "gui_fleet_mode_idle",
  visibility_only: "gui_fleet_mode_visibility_only",
  selective: "gui_fleet_mode_selective",
  full: "gui_fleet_mode_full",
};
const MODE_SHORT_KEYS = {
  idle: "gui_fleet_mode_idle",
  visibility_only: "gui_fleet_mode_visibility_short",
  selective: "gui_fleet_mode_selective",
  full: "gui_fleet_mode_full",
};
const PART_KEYS = {
  online: "gui_fleet_c_online",
  enforcement: "gui_fleet_c_enforcement",
  version: "gui_fleet_c_version",
  heartbeat: "gui_fleet_c_heartbeat",
  compat: "gui_fleet_c_compat",
};
const COMPAT_KEYS = {
  pass: "gui_fleet_compat_pass",
  warn: "gui_fleet_compat_warn",
  fail: "gui_fleet_compat_fail",
  unknown: "gui_fleet_compat_unknown",
};
const COMPAT_TONE = { pass: "ok", warn: "warn", fail: "crit", unknown: "neutral" };

function num(v) { return Number(v || 0).toLocaleString(); }
function pct(part, whole) {
  return whole ? Math.round((Number(part || 0) / whole) * 1000) / 10 : 0;
}
function bucketLabel(b) {
  const k = BUCKET_KEYS[b] || FILTER_KEYS[b];
  return k ? t(k) : String(b || "");
}
function modeLabel(m) { const k = MODE_KEYS[m]; return k ? t(k) : String(m || "—"); }
function scoreTone(v) { return v >= 80 ? "ok" : (v >= 60 ? "warn" : "crit"); }

/** A thin horizontal meter: `share` is 0-100. Tone colours the fill. */
function meter(share, tone) {
  const fill = el("i", { "data-tone": tone || "neutral" });
  fill.style.width = Math.max(0, Math.min(100, share)) + "%";
  return el("span", { class: "fl-meter", "aria-hidden": "true" }, fill);
}

function toneText(text, tone) {
  return el("span", { class: "fl-tone", "data-tone": tone || null, text: text });
}

function panel(title, meta, cov) {
  const head = el("div", { class: "panel-h" }, el("h3", { text: title }));
  if (meta) head.appendChild(el("span", { class: "meta", text: meta }));
  const body = el("div", { class: "panel-b" });
  const root = el("section", { class: "panel", "data-cov": cov || null }, head, body);
  root.head = head;
  root.body = body;
  return root;
}

// ── snapshot age ────────────────────────────────────────────────────────────

function ageText(iso) {
  const at = new Date(iso);
  if (isNaN(at.getTime())) return null;
  const min = Math.floor((Date.now() - at.getTime()) / 60000);
  if (min < 1) return t("gui_fleet_age_now");
  if (min < 120) return tf("gui_fleet_age_min", { n: min });
  return tf("gui_fleet_age_hours", { n: Math.floor(min / 60) });
}

function stamp(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return d.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function metaStrip(fleet, nextRunAt) {
  const strip = el("div", { class: "strip", "data-role": "fleet-asof" });
  const at = fleet.generated_at || fleet.updated_at;
  if (at) {
    strip.appendChild(el("span", null, el("span", { text: t("gui_fleet_asof") + " " }),
      el("b", { text: stamp(at) }), el("span", { text: " · " + (ageText(at) || "—") })));
  }
  if (nextRunAt) {
    strip.appendChild(el("span", { text: tf("gui_fleet_next_run", { at: stamp(nextRunAt) }) }));
  }
  const target = (fleet.versions || {}).target;
  strip.appendChild(el("span", { class: "spacer" }));
  strip.appendChild(target
    ? el("span", null, el("span", { text: t("gui_fleet_target") + " " }), el("b", { text: String(target) }))
    : el("a", { href: R_PCE, text: t("gui_fleet_target_unset") + " · " + t("gui_fleet_set_target") }));
  return strip;
}

// ── IV-16 · figures, distribution, health, agent reports ────────────────────

function kpiCell(label, value, detail, onPick, tone) {
  return el("button", { type: "button", class: "kpicell fl-kpi", "data-tone": tone || null,
    onClick: onPick },
  el("span", { class: "k", text: label }),
  el("span", { class: "v", text: value }),
  el("span", { class: "d", text: detail || " " }));
}

function kpiRow(fleet, pick) {
  const total = Number(fleet.total || 0);
  const online = Number(fleet.managed_online || 0);
  const offline = Number(fleet.managed_offline || 0);
  const hb = fleet.heartbeat || {};
  const silent = Number(hb.stale_24h || 0) + Number(hb.stale_48h || 0) + Number(hb.no_heartbeat || 0);
  const v = fleet.versions || {};
  const unlabeled = Number(((fleet.coverage_gaps || {}).unlabeled || {}).count || 0);
  const hs = fleet.health_score || {};
  const score = hs.score === null || hs.score === undefined ? null : Math.round(Number(hs.score));

  const row = el("div", { class: "kpirow fl-kpirow" });
  row.appendChild(kpiCell(t("gui_fleet_kpi_total"), num(total), t("gui_fleet_kpi_total_d"),
    function () { pick({ bucket: "all" }); }));
  row.appendChild(kpiCell(t("gui_fleet_kpi_online"), num(online) + " / " + num(total),
    tf("gui_fleet_kpi_offline_fmt", { n: num(offline) }),
    function () { pick({ bucket: offline ? "offline" : "online" }); }, offline ? "warn" : "ok"));
  let silentBucket = "stale_24h";
  if (Number(hb.stale_48h || 0)) silentBucket = "stale_48h";
  else if (Number(hb.no_heartbeat || 0)) silentBucket = "no_heartbeat";
  row.appendChild(kpiCell(t("gui_fleet_kpi_heartbeat"), num(silent),
    tf("gui_fleet_kpi_heartbeat_fmt", { old: num(hb.stale_48h), never: num(hb.no_heartbeat) }),
    function () { pick({ bucket: silentBucket }); }, silent ? "warn" : "ok"));
  // needs_upgrade is null, not 0, when no target is set — "nobody needs an
  // upgrade" is not something we know without a target to compare against.
  const hasTarget = !!v.target;
  row.appendChild(kpiCell(t("gui_fleet_needs_upgrade"),
    hasTarget ? num(v.needs_upgrade) : "—",
    hasTarget ? tf("gui_fleet_kpi_target_fmt", { v: String(v.target) }) : t("gui_fleet_target_unset"),
    function () { if (hasTarget) pick({ bucket: "needs_upgrade" }); else router.go(R_PCE); },
    hasTarget && Number(v.needs_upgrade) ? "warn" : null));
  row.appendChild(kpiCell(t("gui_fleet_kpi_unlabeled"), num(unlabeled), t("gui_fleet_unlabeled"),
    function () { pick({ bucket: "unlabeled" }); }, unlabeled ? "warn" : "ok"));
  row.appendChild(kpiCell(t("gui_fleet_score"), score === null ? "—" : String(score) + " / 100",
    hs.partial ? t("gui_fleet_partial") : t("gui_fleet_kpi_score_d"),
    function () {
      const target = document.querySelector('[data-role="fleet-health"]');
      if (target) target.scrollIntoView({ behavior: "smooth", block: "center" });
    },
    score === null ? null : scoreTone(score)));
  return row;
}

function stageButton(bucket, label, share, tone, count, pick) {
  return el("button", { type: "button", class: "fl-stage", "data-bucket": bucket,
    onClick: function () { pick({ bucket: bucket }); } },
  el("span", { text: label }),
  meter(share, tone),
  el("b", { text: num(count) }));
}

function distributionPanel(fleet, pick) {
  const pipe = fleet.pipeline || {};
  const count = function (b) { return Number((pipe[b] || {}).count || 0); };
  const total = PIPELINE.reduce(function (s, b) { return s + count(b); }, 0);
  const byMode = {};
  MODES.forEach(function (m) { byMode[m] = 0; });
  PIPELINE.forEach(function (b) { byMode[MODE_OF_STAGE[b]] += count(b); });

  const p = panel(t("gui_fleet_dist_title"), tf("gui_fleet_count_fmt", { n: num(total) }));
  const bar = el("div", { class: "decision-bar fl-dist-bar", role: "img",
    "aria-label": MODES.map(function (m) { return modeLabel(m) + " " + num(byMode[m]); }).join(", ") });
  MODES.forEach(function (m) {
    if (!byMode[m]) return;
    const seg = el("i", { "data-tone": MODE_TONE[m], title: modeLabel(m) + " · " + num(byMode[m]) });
    seg.style.width = pct(byMode[m], total) + "%";
    bar.appendChild(seg);
  });
  p.body.appendChild(bar);

  const list = el("div", { class: "fl-rows" });
  MODES.forEach(function (m) {
    const stages = PIPELINE.filter(function (b) { return MODE_OF_STAGE[b] === m; });
    const head = el("div", { class: "fl-group" },
      chip(modeLabel(m), MODE_TONE[m]),
      el("b", { text: num(byMode[m]) }),
      el("small", { text: pct(byMode[m], total) + "%" }));
    list.appendChild(head);
    // selective and full are one stage each; a second line under their own
    // heading would repeat it, so the heading itself is the link.
    if (stages.length === 1) {
      head.classList.add("fl-link");
      head.setAttribute("role", "button");
      head.tabIndex = 0;
      head.addEventListener("click", function () { pick({ bucket: stages[0] }); });
      head.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick({ bucket: stages[0] }); }
      });
      return;
    }
    stages.forEach(function (b) {
      list.appendChild(stageButton(b, bucketLabel(b), pct(count(b), total), MODE_TONE[m], count(b), pick));
    });
  });
  p.body.appendChild(list);
  p.body.appendChild(el("p", { class: "note", text: t("gui_fleet_dist_note") }));
  return p;
}

function healthPanel(fleet) {
  const hs = fleet.health_score || {};
  const p = panel(t("gui_fleet_score"), null);
  p.setAttribute("data-role", "fleet-health");
  if (hs.score === null || hs.score === undefined) {
    p.body.appendChild(el("p", { class: "note", text: t("gui_fleet_score_unknown") }));
    return p;
  }
  const score = Math.round(Number(hs.score));
  p.body.appendChild(el("div", { class: "gauge fl-gauge" },
    el("span", { class: "num" }, el("span", { text: String(score) }), el("s", { text: " / 100" })),
    hs.partial ? chip(t("gui_fleet_partial"), "warn") : chip(t("gui_fleet_score_complete"), scoreTone(score))));
  const comps = hs.components || {};
  SCORE_PARTS.forEach(function (k) {
    const c = comps[k] || {};
    const present = c.present !== false && c.value !== null && c.value !== undefined;
    const share = present ? Math.round(Number(c.value) * 100) : 0;
    p.body.appendChild(el("div", { class: "fl-part" },
      el("span", { text: t(PART_KEYS[k]) }),
      present ? meter(share, scoreTone(share)) : el("span", { class: "fl-meter off", "aria-hidden": "true" }),
      present ? el("b", { text: share + "%" }) : el("i", { text: t("gui_fleet_not_counted") })));
  });
  p.body.appendChild(el("p", { class: "note", text: t("gui_fleet_score_note") }));
  return p;
}

function agentPanel(fleet) {
  const ah = fleet.agent_health || {};
  const errors = ah.errors || {};
  const warnings = ah.warnings || {};
  const p = panel(t("gui_fleet_agent_title"), null);
  p.body.appendChild(el("div", { class: "fl-agent-counts" },
    el("div", null, el("span", { text: t("gui_fleet_agent_errors") }),
      toneText(num(errors.count), Number(errors.count) ? "crit" : null)),
    el("div", null, el("span", { text: t("gui_fleet_agent_warnings") }),
      toneText(num(warnings.count), Number(warnings.count) ? "warn" : null))));
  const items = (errors.sample || []).concat(warnings.sample || []).slice(0, 8);
  if (!items.length) {
    p.body.appendChild(el("p", { class: "note", text: t("gui_fleet_agent_none") }));
    return p;
  }
  const list = el("ul", { class: "fl-agent" });
  items.forEach(function (it) {
    list.appendChild(el("li", { "data-tone": it.severity === "error" ? "crit" : "warn" },
      el("b", { class: "mono", text: it.hostname || it.href || "—" }),
      el("span", { text: String(it.type || "—") })));
  });
  p.body.appendChild(list);
  const more = Number(errors.count || 0) + Number(warnings.count || 0) - items.length;
  if (more > 0) p.body.appendChild(el("p", { class: "note", text: tf("gui_fleet_agent_more", { n: num(more) }) }));
  return p;
}

// ── IV-17 · the workload list ───────────────────────────────────────────────

function heartbeatTone(h) {
  if (h === null || h === undefined || h > 48) return "crit";
  if (h > 24) return "warn";
  return null;
}

function muted(text) { return el("span", { class: "fl-muted", text: text }); }

function listColumns(target) {
  return [
    col("hostname", t("gui_fleet_col_hostname"), { sort: true, width: 200,
      cell: function (r) { return el("span", { class: "mono", text: r.hostname || "—" }); },
      title: function (r) { return r.href || ""; } }),
    col("mode", t("gui_fleet_col_mode"), { sort: true, width: 150,
      cell: function (r) { return r.mode ? chip(modeLabel(r.mode), MODE_TONE[r.mode]) : muted("—"); } }),
    col("online", t("gui_fleet_col_online"), { sort: true, width: 110,
      cell: function (r) {
        return chip(r.online ? t("gui_fleet_online_yes") : t("gui_fleet_online_no"), r.online ? "ok" : "crit");
      } }),
    col("hslh", t("gui_fleet_col_hslh"), { sort: true, align: "n", width: 170,
      cell: function (r) {
        const h = r.hslh;
        return toneText(h === null || h === undefined ? t("gui_fleet_never") : String(Math.round(h * 10) / 10),
          heartbeatTone(h));
      } }),
    col("version", t("gui_fleet_col_version"), { sort: true, width: 150,
      cell: function (r) {
        return toneText(r.version || "—", target && r.version && r.version !== target ? "warn" : null);
      } }),
    // Compatibility is only a question for workloads still in idle; for the
    // rest the PCE's verdict is "unknown" by construction, and printing it on
    // every row hides the rows where it matters.
    col("compat", t("gui_fleet_col_compat"), { sort: true, width: 130,
      cell: function (r) {
        if (r.mode !== "idle") return muted("—");
        const c = COMPAT_KEYS[r.compat] ? r.compat : "unknown";
        return chip(t(COMPAT_KEYS[c]), COMPAT_TONE[c]);
      } }),
    col("app", t("gui_fleet_col_app"), { sort: true,
      cell: function (r) { return r.app || muted("—"); } }),
    col("env", t("gui_fleet_col_env"), { sort: true,
      cell: function (r) { return r.env || muted("—"); } }),
    col("os", t("gui_fleet_col_os"), { sort: true,
      cell: function (r) { return muted(r.os || "—"); }, title: function (r) { return r.os || ""; } }),
  ];
}

function listParams(state) {
  return { bucket: state.bucket, q: state.q, version: state.version, app: state.app,
    env: state.env, sort: state.sort.key, dir: state.sort.dir,
    offset: state.page * PAGE_SIZE, limit: PAGE_SIZE };
}

function exportHref(state) {
  const p = listParams(state);
  const qs = new URLSearchParams();
  ["bucket", "q", "version", "app", "env", "sort", "dir"].forEach(function (k) { qs.set(k, p[k] || ""); });
  return "/api/fleet/export.csv?" + qs.toString();
}

function selectBox(label, options, value, onChange) {
  const sel = el("select", { class: "field", "aria-label": label });
  options.forEach(function (o) {
    const opt = el("option", { value: o[0], text: o[1] });
    if (String(o[0]) === String(value)) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.addEventListener("change", function () { onChange(sel.value); });
  return el("div", { class: "qf" }, el("label", { text: label }), sel);
}

/**
 * The list panel. `filters` is the page's state object; `rebuild` replaces
 * the whole panel (used when the menus themselves must show new values —
 * a figure was clicked, or "clear" was pressed); typing in the search box or
 * changing a menu only reloads the rows, so focus and caret stay put.
 */
function listPanel(fleet, state, rebuild) {
  const p = panel(t("gui_fleet_list_title"), null, "IV-17");
  p.setAttribute("data-role", "fleet-list");
  p.load = function () { return Promise.resolve(); };
  if (fleet.index_truncated) {
    // The counts above came from the analysis, not the index, so they stay
    // true; only the per-host list is gone. Saying nothing here would read
    // as an empty bucket.
    p.body.appendChild(el("p", { class: "note", text: t("gui_fleet_index_truncated") }));
    return p;
  }
  const v = fleet.versions || {};
  const gaps = fleet.coverage_gaps || {};
  const all = [["", t("gui_fleet_f_all")]];

  let timer = null;
  const search = el("input", { class: "field", type: "search", value: state.q,
    placeholder: t("gui_fleet_search_ph"), "aria-label": t("gui_fleet_search"),
    "data-field": "fleet-search" });
  search.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { state.q = search.value.trim(); state.page = 0; p.load(); }, 250);
  });

  const stages = LIST_BUCKETS
    .filter(function (b) { return v.target || (b !== "needs_upgrade" && b !== "on_target"); })
    .map(function (b) { return [b, bucketLabel(b)]; });
  const versions = all.concat((v.ordered || []).map(function (x) { return [x, x]; }));
  const apps = all.concat(Object.keys(gaps.by_app || {}).sort().map(function (x) { return [x, x]; }));
  const envs = all.concat(Object.keys(gaps.by_env || {}).sort().map(function (x) { return [x, x]; }));
  const setter = function (key) {
    return function (val) { state[key] = val; state.page = 0; p.load(); };
  };

  const exportLink = el("a", { class: "btn", href: exportHref(state), download: "ven_inventory.csv",
    "data-field": "fleet-export", text: t("gui_fleet_export") });
  const count = el("span", { class: "count", "data-field": "fleet-count" });
  const clearBtn = el("button", { type: "button", class: "btn", "data-field": "fleet-clear",
    text: t("gui_fleet_clear"), onClick: function () { rebuild({}); } });

  p.body.appendChild(el("div", { class: "qrow fl-controls" },
    el("div", { class: "qf grow" }, el("label", { text: t("gui_fleet_search") }), search),
    selectBox(t("gui_fleet_f_stage"), stages, state.bucket, setter("bucket")),
    selectBox(t("gui_fleet_col_version"), versions, state.version, setter("version")),
    selectBox(t("gui_fleet_col_app"), apps, state.app, setter("app")),
    selectBox(t("gui_fleet_col_env"), envs, state.env, setter("env"))));
  p.body.appendChild(el("div", { class: "toolbar fl-toolbar" }, count, el("span", { class: "spacer" }),
    clearBtn, exportLink));

  const host = el("div", { "data-field": "fleet-table" });
  p.body.appendChild(host);
  const columns = listColumns(v.target || "");

  p.load = function () {
    exportLink.setAttribute("href", exportHref(state));
    return api.load("fleet_list", listParams(state)).then(function (d) {
      if (!host.isConnected) return;
      const rows = (d && d.rows) || [];
      const total = Number((d && d.total) || 0);
      count.textContent = tf("gui_fleet_count_fmt", { n: num(total) });
      clear(host);
      if (!total) {
        host.appendChild(el("div", { class: "empty" },
          el("span", { class: "et", text: t("gui_fleet_no_match") })));
        return;
      }
      table.render(host, {
        columns: columns,
        rows: rows.map(function (r) {
          return Object.assign({}, r, { _tone: !r.online || heartbeatTone(r.hslh) === "crit" ? "crit" : null });
        }),
        page: { index: state.page, size: PAGE_SIZE, total: total },
        onPage: function (next) {
          const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
          state.page = Math.max(0, Math.min(next, pages - 1));
          p.load();
        },
        sort: state.sort,
        onSort: function (key, dir) { state.sort = { key: key, dir: dir }; state.page = 0; p.load(); },
      });
    }).catch(function (e) {
      if (!host.isConnected) return;
      clear(host);
      host.appendChild(el("p", { class: "note",
        text: t("gui_fleet_list_failed") + " " + String((e && e.message) || e) }));
    });
  };
  return p;
}

// ── IV-18 · version distribution ────────────────────────────────────────────

function versionsPanel(fleet, pick) {
  const v = fleet.versions || {};
  const dist = v.distribution || {};
  const total = Object.keys(dist).reduce(function (s, k) { return s + Number((dist[k] || {}).count || 0); }, 0);
  const p = panel(t("gui_fleet_versions"), tf("gui_fleet_versions_meta", { n: num((v.ordered || []).length) }), "IV-18");
  const list = el("div", { class: "fl-rows" });
  (v.ordered || []).forEach(function (ver) {
    const entry = dist[ver] || {};
    const n = Number(entry.count || 0);
    const isTarget = !!v.target && ver === v.target;
    const osMap = entry.os_breakdown || {};
    const os = Object.keys(osMap)
      .sort(function (a, b) { return osMap[b] - osMap[a]; })
      .map(function (k) { return k + " " + num(osMap[k]); }).join(" · ");
    list.appendChild(el("button", { type: "button", class: "fl-ver", "data-version": ver,
      onClick: function () { pick({ version: ver }); } },
    el("span", { class: "fl-ver-name" }, el("b", { class: "mono", text: ver || "—" }),
      isTarget ? chip(t("gui_fleet_target"), "ok") : null),
    meter(pct(n, total), isTarget ? "ok" : (v.target ? "warn" : "info")),
    el("b", { text: num(n) }),
    el("small", { class: "fl-ver-os", text: os || "—", title: os || "" })));
  });
  if (!(v.ordered || []).length) list.appendChild(el("p", { class: "note", text: "—" }));
  p.body.appendChild(list);
  if ((v.unparsable || []).length) {
    p.body.appendChild(el("p", { class: "note",
      text: t("gui_fleet_unparsable") + ": " + v.unparsable.join(", ") }));
  }
  return p;
}

// ── IV-19 · label coverage ──────────────────────────────────────────────────

function coveragePanel(fleet, state, pick) {
  const gaps = fleet.coverage_gaps || {};
  const p = panel(t("gui_fleet_gaps"), null, "IV-19");
  const dims = [
    { key: "app", tab: "gui_fleet_by_app", head: "gui_fleet_col_app", data: gaps.by_app || {} },
    { key: "env", tab: "gui_fleet_by_env", head: "gui_fleet_col_env", data: gaps.by_env || {} },
  ];
  const seg = el("div", { class: "seg fl-seg" });
  const host = el("div");

  function paint() {
    clear(host);
    clear(seg);
    dims.forEach(function (d) {
      seg.appendChild(el("button", { type: "button", text: t(d.tab),
        "aria-pressed": state.coverageBy === d.key ? "true" : "false",
        onClick: function () { state.coverageBy = d.key; paint(); } }));
    });
    const dim = dims.filter(function (d) { return d.key === state.coverageBy; })[0] || dims[0];
    const rows = Object.keys(dim.data).map(function (name) {
      const modes = dim.data[name] || {};
      const row = { name: name, total: 0 };
      MODES.forEach(function (m) { row[m] = Number(modes[m] || 0); row.total += row[m]; });
      row.enforced = pct(row.selective + row.full, row.total);
      return row;
    }).sort(function (a, b) { return b.total - a.total || a.name.localeCompare(b.name); });
    if (!rows.length) { host.appendChild(el("p", { class: "note", text: "—" })); return; }
    const columns = [
      col("name", t(dim.head), { width: 150,
        cell: function (r) {
          return el("a", { href: "#", class: "fl-namelink", text: r.name, onClick: function (e) {
            e.preventDefault();
            const f = {};
            f[dim.key] = r.name;
            pick(f);
          } });
        } }),
    ].concat(MODES.map(function (m) {
      // Column heads use the short mode names; "Visibility only" does not fit
      // a numeric column and the full name is in the distribution panel.
      return col(m, t(MODE_SHORT_KEYS[m]), { align: "n", width: 92,
        cell: function (r) { return r[m] ? num(r[m]) : muted("·"); } });
    })).concat([
      col("enforced", t("gui_fleet_col_enforced"), {
        cell: function (r) {
          return el("span", { class: "fl-inline" },
            meter(r.enforced, r.enforced >= 80 ? "ok" : (r.enforced ? "info" : "neutral")),
            el("small", { text: r.enforced + "%" }));
        } }),
    ]);
    table.render(host, { columns: columns, rows: rows });
  }
  paint();
  p.body.appendChild(seg);
  p.body.appendChild(host);
  const unl = Number((gaps.unlabeled || {}).count || 0);
  p.body.appendChild(el("button", { type: "button", class: "fl-stage fl-unlabeled", "data-bucket": "unlabeled",
    onClick: function () { pick({ bucket: "unlabeled" }); } },
  el("span", { text: t("gui_fleet_unlabeled") }),
  el("span"),
  toneText(num(unl), unl ? "warn" : null)));
  return p;
}

// ── mount ───────────────────────────────────────────────────────────────────

export async function mountFleet(root, ctx) {
  const state = {
    torn: false, bucket: "all", q: "", version: "", app: "", env: "",
    sort: { key: "hostname", dir: "asc" }, page: 0, coverageBy: "app",
  };
  const board = el("div", { class: "board fl-board" });
  let fleet = {};
  let listEl = null;

  root.appendChild(pageHead({
    // pageHead 不帶 cov：IV-16 指的是摘要區，一個 anchor 只能指一個東西。
    route: ROUTE, crumbs: crumbsFor(ROUTE),
    title: t("gui_fleet_title"), sub: t("gui_fleet_subtitle"),
  }));
  root.appendChild(board);

  // Every figure on the page lands here: it narrows the list to what the
  // figure counted and brings the list into view, so a number is never a
  // dead end. "Clear filters" is the same call with an empty filter.
  function pick(filter, scroll) {
    if (state.torn) return;
    state.bucket = filter.bucket || "all";
    state.version = filter.version || "";
    state.app = filter.app || "";
    state.env = filter.env || "";
    state.q = "";
    state.page = 0;
    const fresh = listPanel(fleet, state, function (f) { pick(f, false); });
    if (listEl && listEl.isConnected) listEl.replaceWith(fresh);
    listEl = fresh;
    fresh.load();
    if (scroll !== false) fresh.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function paint() {
    if (state.torn) return;
    clear(board);
    await withErrorCard(board, "fleet", function () { return api.load("fleet"); },
      function (d) {
        if (state.torn || ctx.stale()) return;
        if (!d || d.available !== true) {
          // Not analysed yet. Deliberately no numbers: a 0 here is a lie.
          const box = el("div", { class: "empty", "data-cov": "IV-16" },
            el("span", { class: "et", text: t("gui_fleet_no_snapshot") }),
            el("p", { text: t("gui_fleet_no_snapshot_body") }));
          if (d && d.next_run_at) {
            box.appendChild(el("p", { class: "note",
              text: tf("gui_fleet_next_run", { at: stamp(d.next_run_at) }) }));
          }
          board.appendChild(box);
          return;
        }
        fleet = d.fleet || {};
        if (fleet.last_error) {
          board.appendChild(el("div", { class: "strip", "data-tone": "warn",
            text: tf("gui_fleet_last_error", { error: String(fleet.last_error) }) }));
        }
        board.appendChild(metaStrip(fleet, d.next_run_at));

        const summary = el("div", { class: "fl-summary", "data-cov": "IV-16" });
        summary.appendChild(kpiRow(fleet, pick));
        summary.appendChild(el("div", { class: "brow c543" },
          distributionPanel(fleet, pick), healthPanel(fleet), agentPanel(fleet)));
        board.appendChild(summary);

        board.appendChild(el("div", { class: "brow c75" },
          coveragePanel(fleet, state, pick), versionsPanel(fleet, pick)));

        // The list comes last: it is where every figure above leads, and a
        // page of rows above the breakdowns would push them out of sight.
        listEl = listPanel(fleet, state, function (f) { pick(f, false); });
        board.appendChild(listEl);
        listEl.load();
      });
  }

  // ctx 只有 route / query / stale()；離場靠 router.onChange，比照 alerts.mjs。
  const unsubscribe = router.onChange(function () {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
  });
  await paint();
}
