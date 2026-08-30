// overview.mjs — #/overview. Anchors OV-01…OV-16 (design/v2/coverage.yaml).
//
// PORT OF design/v2/mockup/js/areas/overview.mjs against the live backend.
// Differences from the frozen mockup:
//   1. `store.load(id)` -> `api.load(id)` (core/api.mjs, real GET endpoints
//      transcribed in core/store-map.mjs from design/v2/tools/endpoints.yaml).
//   2. top10 is no longer a captured snapshot: endpoints.yaml's `top10` entry
//      is `POST /api/dashboard/top10`, called with the flat saved-query dict
//      spread + `mins` (dashboard.js:2048-2058 runTop10Query — the payload
//      that route actually reads, per dashboard.py:649-729 which pulls
//      `port`/`proto`/`src_labels`/... straight off the flat body; the
//      endpoints.yaml `payload:` block is only the one example query it used
//      to capture a snapshot, not a field whitelist). There is no live
//      concept of "the" saved query the way a page load has one, so this
//      area runs it for the FIRST saved query (state.queries[0]) and shows
//      the "no records" empty state when there is none yet.
//   3. Custom-query CRUD (OV-04) goes through the real backend instead of a
//      locally-mutated copy: POST /api/dashboard/queries (idx present ->
//      update in place, per dashboard.py:486-575) and DELETE
//      /api/dashboard/queries/<idx> (dashboard.py:577-591). The mockup's
//      "this note only edits the on-screen copy" note is dropped — it would
//      be a lie against a real backend.
//   4. i18n keys renamed v2_* -> gui_* (this task's global rename). Five keys
//      (gui_health_goto/queue_idle/queue_active/clear/jobs_ok) reuse the
//      identical keys design/v2's Task 3 healthbar.mjs port already minted
//      for the same v2_health_* family, rather than duplicating them; two
//      more (gui_table_rows, gui_status_version) reuse existing product
//      keys with matching text. Every other v2_* key here is newly minted
//      under gui_ov_*/gui_col_age/gui_nav_overview, text transcribed
//      verbatim from design/v2/mockup/i18n-supplement.json.
//   5. Teardown: OV-05's chart.rankedBars() handle is now captured (the
//      mockup discarded it — harmless there, a real ResizeObserver leak
//      here) and destroyed both on repaint and on leaving the route; a
//      self-unsubscribing router.onChange also closes any drawer/modal this
//      area left open and drops this route's two palette commands.
//   6. fieldKeys([]) falls back to the full FIELD_ORDER instead of yielding
//      no fields at all. The mockup always had a captured example query, so
//      "no queries yet" never had to open the "add query" drawer; a fresh
//      live install can start with zero, and the mockup's original
//      behaviour would render that drawer with no inputs at all — a dead
//      end for creating the very first query.
//   7. loadAll() catches each of the 14 GET sources independently
//      (loadOne()) instead of a bare Promise.all(). The mockup's snapshots
//      never fail, so it never had to handle this; several live sources are
//      PCE-backed and DO return a non-2xx on an ordinary operational
//      condition — verified empirically (GET /api/events/viewer -> 502
//      whenever the PCE is unreachable) — and api.load() throws on any
//      non-2xx, so an unguarded Promise.all would blank all 16 cards over
//      one struggling endpoint. Every card already tolerates a missing/
//      falsy payload, so degrading just the failed source is strictly
//      better than the mockup's all-or-nothing load.
//   8. top10 is no longer part of the initial load or of refreshQueries()'s
//      critical path: it rides that same live PCE flow-search and can take
//      several seconds (or fail) on its own, verified the same way, so it
//      is fetched in the background (refreshTop10(), buildBoard) both at
//      mount and after a query CRUD op, guarded against out-of-order
//      resolution (state.top10Seq) and against repainting a torn-down area
//      (state.torn).

import { el, clear, disclosure } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { num, dur, stamp, since, tone, atLeast, firstLine } from "../core/fmt.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { chart } from "../components/chart.mjs";

const ROUTE = "#/overview";

/** Minimal area-head: title + route breadcrumb. Small enough (mockup's
 * areas/placeholder.mjs, 5 lines) that duplicating it locally beats pulling
 * in that module's own shell.mjs dependency, which does not exist here. */
/* The route used to be printed next to the title as `<code>#/overview</code>`.
 * It is plumbing, not information an operator acts on (UI density spec R4), so
 * it now rides as a data attribute: still a stable hook for the e2e suite's
 * "has this area finished mounting" wait, no longer chrome on the screen. */
function areaHead(title, route) {
  return el("div", { class: "area-head", "data-route": route },
    el("h1", { text: title })
  );
}

// Where each read-only card hands off to. Kept in one place so a route rename is
// one edit, and so the report can state the mapping without reading the builders.
const GO_PCE = "#/system/pce";
const GO_SIEM = "#/system/siem";
const GO_TLS = "#/system/tls";
const GO_CHANNELS = "#/system/channels";
const GO_JOBS = "#/automation/jobs";
const GO_REPORTS = "#/reports";
const GO_TRAFFIC = "#/investigate/traffic";
const GO_EVENTS = "#/investigate/events";

// top10 is fetched separately (POST, see loadTop10) — every other id here is
// a plain GET already in store-map.mjs's GET_MAP.
const SNAPS = [
  "status", "dashboard_overview", "dashboard_queries",
  "dashboard_audit", "dashboard_pu", "dashboard_snapshot", "reports_list",
  "events_viewer", "tls_status", "alert_plugins",
  "cache_status", "cache_throughput", "siem_status", "siem_destinations",
];

// dashboard.js:317-329 (typeLabels) — the report_type -> catalogue key map,
// transcribed as pairs so no object literal exceeds the inline-data lint cap.
const REPORT_TYPE_KEYS = [
  ["traffic", "gui_sched_rt_traffic"],
  ["security_risk", "gui_sched_rt_security"],
  ["network_inventory", "gui_sched_rt_inventory"],
  ["audit", "gui_sched_rt_audit"],
  ["ven_status", "gui_sched_rt_ven"],
  ["policy_usage", "gui_sched_rt_pu"],
  ["rule_hit_count", "gui_sched_rt_rhc"],
  ["readiness", "gui_sched_rt_readiness"],
  ["policy_diff", "gui_sched_rt_policy_diff"],
  ["policy_resolver", "gui_sched_rt_policy_resolver"],
  ["app_summary", "gui_sched_rt_app_summary"],
];

// index.html:2397-2400 (input[name="dq-pd"]) + dashboard.js:1428 — pd is an int,
// and the label/colour mapping below is the product's, digit for digit.
const PD_KEYS = [["3", "gui_pd_all"], ["2", "gui_pd_blocked"], ["1", "gui_pd_potential"], ["0", "gui_pd_allowed"]];
const PD_TONES = [["3", "info"], ["2", "crit"], ["1", "warn"], ["0", "ok"]];

// index.html:2389-2391 (select#dq-rank) — value + catalogue key, in DOM order.
const RANK_KEYS = [["count", "gui_rank_count"], ["volume", "gui_rank_volume"], ["bandwidth", "gui_rank_bw"]];

// dashboard_queries stores a FLAT query_def (dashboard.py:539-546 flattens the FilterBar dict into
// query_def at save time), so the drawer edits flat keys — that is what the next
// GET returns and what /api/dashboard/top10 reads (dashboard.py:649-729).
const FIELD_ORDER = ["name", "rank_by", "pd", "src_labels", "dst_labels", "any_label", "ports", "port", "proto", "ex_port"];
const FIELD_LABELS = [
  ["name", "gui_query_widget_name"],
  ["rank_by", "gui_rank_by"],
  ["pd", "gui_policy_dec"],
  ["any_label", "gui_any_label"],
  ["ports", "gui_fb_cat_port"],
  ["port", "gui_port"],
  ["proto", "gui_protocol"],
  ["ex_port", "gui_ex_port"],
];
// src_label/dst_label/ex_src_label/ex_dst_label are the pre-Phase-4b legacy
// singular label fields (dashboard.py:548-558's `else` branch) — a query
// saved before that migration carries these instead of src_labels/dst_labels.
// Rendered as comma-separated list inputs, same as their plural siblings
// (fieldLabel() below gives them the same composed label), so editing one is
// no different from editing a new-format query — and so buildSavePayload's
// LEGACY_LABEL_KEYS wrap below always receives an array, never a bare string.
const LIST_FIELDS = [
  "src_labels", "dst_labels", "ports",
  "src_label", "dst_label", "ex_src_label", "ex_dst_label",
];

// dashboard.py:539-546 (api_save_dashboard_query) — top-level scalar keys the
// save endpoint reads straight off the body, plus the `filters` dict it
// flattens through a fixed whitelist (fb_keys). FILTER_SAVE_KEYS are the
// members of that whitelist this form's own (post-Phase-4b) fields write
// directly (src_labels/dst_labels/any_label/ports); the whitelist has more
// members than this form exposes, which is fine — a key this form never
// writes never appears in the body.
//
// LEGACY_SCALAR_FILTER_KEYS and LEGACY_LABEL_KEYS exist for one reason: a
// query saved before Phase 4b (dashboard.py:548-558's `else` branch) has
// NONE of the FILTER_SAVE_KEYS above — it carries src_label/dst_label
// (singular) and src_ip_in/dst_ip_in/ex_src_ip/ex_dst_ip instead. Without
// forwarding those too, editing a legacy query — even just renaming it —
// would save an empty filters dict and silently unscope it (review finding,
// Important 1: this is a real defect this port introduces by ALWAYS sending
// `filters` now — see the comment on that below — combined with never
// reading these keys back out).
//   - src_ip_in/dst_ip_in/ex_src_ip/ex_dst_ip whitelist verbatim under their
//     legacy name (dashboard.py's _fb_keys tuple), so they need no renaming.
//   - src_label/dst_label/ex_src_label/ex_dst_label wrap into the plural
//     whitelisted name as a list — the exact transform
//     filter-bar.js:187-200's _objfbDeserialize already performs when
//     reading a legacy query back into pills (a singular label spec is
//     `.concat`ed onto the plural list, i.e. treated as one more element of
//     it, not a structurally different value).
const TOP_LEVEL_SAVE_KEYS = ["name", "rank_by", "pd", "port", "proto", "ex_port"];
const FILTER_SAVE_KEYS = ["src_labels", "dst_labels", "any_label", "ports"];
const LEGACY_SCALAR_FILTER_KEYS = ["src_ip_in", "dst_ip_in", "ex_src_ip", "ex_dst_ip"];
const LEGACY_LABEL_KEYS = [
  ["src_label", "src_labels"],
  ["dst_label", "dst_labels"],
  ["ex_src_label", "ex_src_labels"],
  ["ex_dst_label", "ex_dst_labels"],
];

function lookup(pairs, key, fallback) {
  let hit = fallback;
  pairs.forEach(function (pair) { if (pair[0] === String(key)) hit = pair[1]; });
  return hit;
}

// ── panel plumbing ──────────────────────────────────────────────────────────
function panel(cov, title) {
  const head = el("div", { class: "panel-h" }, el("h3", { title: title, text: title }));
  const body = el("div", { class: "panel-b" });
  const root = el("section", { class: "panel", "data-cov": cov }, head, body);
  root.head = head;
  root.body = body;
  return root;
}

function withMeta(p, text) {
  p.head.appendChild(el("span", { class: "meta", title: text, text: text }));
  return p;
}

/** One right-aligned action group per header, so meta never lands mid-header. */
function headBox(p) {
  if (!p.hact) {
    p.hact = el("span", { class: "hact" });
    p.head.appendChild(p.hact);
  }
  return p.hact;
}

function withAction(p, label, onClick) {
  headBox(p).appendChild(el("button", { class: "btn", type: "button", text: label, onClick: onClick }));
  return p;
}

function withGoto(p, route) {
  headBox(p).appendChild(el("button", {
    class: "btn link goto",
    type: "button",
    text: t("gui_health_goto") + " " + route,
    onClick: function () { router.go(route); },
  }));
  return p;
}

function withTone(p, tn) {
  p.setAttribute("data-tone", tn);
  return p;
}

function kv(label, value, tn) {
  const b = el("b", { class: "mono", "data-tone": tn || null, title: String(value) });
  if (tn) b.appendChild(el("i", { class: "dot" }));
  b.appendChild(el("span", { text: value }));
  return el("div", { class: "kv" }, el("span", { text: label }), b);
}

function badge(text, tn) {
  return el("span", { class: "badge", "data-tone": tn }, el("i", { class: "dot" }), el("span", { text: text }));
}

function lead(value, unit, trailing) {
  return el("div", { class: "lead" },
    el("span", { class: "n", text: value }),
    unit ? el("span", { class: "u", text: unit }) : null,
    trailing || null
  );
}

function note(text) {
  return el("p", { class: "note", text: text });
}

function emptyState(text, route, label) {
  return el("div", { class: "empty" },
    el("span", { class: "et", text: t("gui_empty_state_no_data_title") }),
    el("p", { text: text }),
    route ? el("button", {
      class: "btn",
      type: "button",
      text: label || (t("gui_health_goto") + " " + route),
      onClick: function () { router.go(route); },
    }) : null
  );
}

function chips(items) {
  return el("div", { class: "chips" }, items.map(function (pair) {
    return el("span", { class: pair[2] ? "off" : null },
      el("span", { text: pair[0] + " " }), el("b", { text: pair[1] }));
  }));
}

// Severity words (CRITICAL / HIGH / MEDIUM / LOW / INFO) need no mapping of their
// own: fmt.tone already speaks that vocabulary (high -> crit, medium -> warn,
// low/info -> info), so severities go straight through tone().

// ── OV-01 系統狀態總覽 ← status.json ────────────────────────────────────────
// status.pce_stats is the appliance's own view of its PCE loop; the rail (XC-01)
// shows only the resulting light, so this card carries the readings behind it.
function deploymentLabel(value) {
  return value === "saas" ? t("gui_deployment_saas") : t("gui_deployment_on_prem");
}

function healthProbeLabel(value) {
  const raw = String(value || "").trim();
  if (!raw) return "—";
  return raw.split("+").filter(Boolean).map(function (part) {
    return "/" + part.replace(/^\/+/, "");
  }).join(" + ");
}

function pceCategoryState(pce) {
  const category = String(pce.health_category || "unknown").toLowerCase();
  const health = String(pce.health_status || "unknown").toLowerCase();
  if (category === "auth_failed") return ["crit", t("gui_health_pce_auth_failed")];
  if (category === "authorization_failed") return ["crit", t("gui_health_pce_authorization_failed")];
  if (category === "transport_error") return ["crit", t("gui_health_pce_unreachable")];
  if (category === "server_error") return ["crit", t("gui_health_pce_server_error")];
  if (category === "rate_limited") return ["warn", t("gui_health_pce_rate_limited")];
  if (category === "error" || category === "critical") {
    return ["crit", tf("gui_health_pce_reported_status", { status: category })];
  }
  if (category === "warning" || category === "degraded") {
    return ["warn", tf("gui_health_pce_reported_status", { status: category })];
  }
  if (category !== "ok" && category !== "unknown") {
    return ["warn", tf("gui_health_pce_http_error", { status: pce.last_error_status || "—" })];
  }
  if (health === "error" || health === "critical") return ["crit", t("gui_status_fail")];
  if (health === "warning" || health === "degraded") return ["warn", health.toUpperCase()];
  if (category === "ok" || health === "ok") return ["ok", t("gui_status_ok")];
  return ["neutral", "—"];
}

function cardSystem(st, ov) {
  const pce = st.pce_stats || {};
  const fails = Number(pce.consecutive_failures) || 0;
  const control = pceCategoryState(pce);
  const deployment = st.deployment_type || pce.deployment_type || "on_prem";
  const probe = healthProbeLabel(st.health_probe || pce.health_probe);

  const p = panel("OV-01", t("gui_ov_system_status"));
  withMeta(p, String(st.api_url || "").replace(/^https?:\/\//, ""));
  withGoto(p, GO_PCE);
  withTone(p, control[0]);

  p.body.appendChild(lead(control[1], t("gui_health_pce_api_access"),
    badge(deploymentLabel(deployment) + " · " + probe, control[0])));
  p.body.appendChild(kv(t("gui_deployment_type"), deploymentLabel(deployment)));
  p.body.appendChild(kv(t("gui_health_check"), probe));
  p.body.appendChild(kv(t("gui_ov_pce_failures"), String(fails),
    pce.last_error_stage === "health" && fails > 0 ? "crit" : null));
  p.body.appendChild(kv(t("gui_ov_last_poll"), since(pce.last_event_poll, ov.as_of)));
  p.body.appendChild(kv(t("gui_ov_last_batch"),
    tf("gui_ov_last_batch_fmt", { total: num(pce.last_batch_total), unknown: num(pce.last_batch_unknown) })));
  p.body.appendChild(kv(t("gui_dashboard_rules"), num(st.rules_count)));
  p.body.appendChild(kv(t("gui_status_version"), "v" + (st.version || "—")));
  p.body.appendChild(kv(t("gui_ov_watermark"), stamp(st.event_watermark) || "—"));
  if (String(st.provider_status_url || "").startsWith("https://")) {
    p.body.appendChild(el("p", { class: "note" }, el("a", {
      href: st.provider_status_url,
      target: "_blank",
      rel: "noopener noreferrer",
      text: t("gui_saas_status_link"),
    })));
  }
  return p;
}

// ── OV-16 Integrations 狀態卡摘要 ← integrations.js:1426-1466 (_buildOvCards) ─
// Same four cards the product renders, from the same four endpoints it calls:
// /api/cache/status, /api/siem/destinations, /api/siem/status, /api/cache/throughput.
function cardIntegrations(d) {
  const cache = d.cache_status || {};
  const thr = d.cache_throughput || {};
  const rows = (d.siem_status && d.siem_status.status) || [];
  const dests = (d.siem_destinations && d.siem_destinations.destinations) || [];

  let pending = 0, sent = 0, failed = 0, dlq = 0;
  rows.forEach(function (r) {
    pending += Number(r.pending) || 0;
    sent += Number(r.sent) || 0;
    failed += Number(r.failed) || 0;
    dlq += Number(r.dlq) || 0;
  });
  // integrations.js:1427-1428 — failed>0 paints the SIEM card err, dlq>0 warns.
  const tn = failed > 0 ? "crit" : (dlq > 0 ? "warn" : "ok");

  const p = panel("OV-16", t("gui_tab_integrations", "Integrations"));
  withMeta(p, tf("gui_ov_destinations_fmt", { n: dests.length }));
  withGoto(p, GO_SIEM);
  withTone(p, tn);

  p.body.appendChild(lead(num(sent), t("gui_ov_sent"),
    badge(t("gui_ov_dlq") + " " + num(dlq), dlq > 0 ? "warn" : "ok")));
  p.body.appendChild(kv(t("gui_ov_pending"), num(pending)));
  p.body.appendChild(kv(t("gui_ov_failed"), num(failed), failed > 0 ? "crit" : null));
  p.body.appendChild(kv(t("gui_ov_events"), num(cache.events)));
  p.body.appendChild(kv(t("gui_ov_traffic"),
    num(Number(cache.traffic_raw || 0) + Number(cache.traffic_agg || 0))));
  if (thr.traffic_raw_24h !== null && thr.traffic_raw_24h !== undefined) {
    p.body.appendChild(note(tf("gui_ov_traffic_24h", { n: num(thr.traffic_raw_24h) })));
  }
  return p;
}

// ── OV-10 pipeline 健康摘要 ← integrations.js:1391-1424 ─────────────────────
// Verdict drives the tone (1406-1410); the reason strings are _pipelineReasons
// (1391-1404) verbatim, including the same {hours} = round(lag_s/3600) arithmetic.
function pipelineReasons(pipe) {
  const out = [];
  (pipe.cache_lag || []).forEach(function (l) {
    if (l.last_status === "error") {
      out.push(tf("gui_health_source_failed", { source: l.source }));
    } else if (l.level === "error" || l.level === "warning") {
      out.push(tf("gui_pl_reason_lag", { source: l.source, hours: Math.round(l.lag_s / 3600) }));
    }
  });
  if (pipe.siem_success_1h !== null && pipe.siem_success_1h !== undefined && pipe.siem_success_1h < 95) {
    out.push(tf("gui_pl_reason_siem", { pct: pipe.siem_success_1h }));
  }
  if (pipe.dlq > 0) out.push(tf("gui_pl_reason_dlq", { n: pipe.dlq }));
  return out;
}

function cardPipeline(ov) {
  const pipe = ov.pipeline || {};
  const verdict = String(pipe.verdict || "ok");
  const reasons = pipelineReasons(pipe);

  const p = panel("OV-10", t("gui_ov_pipeline_health"));
  withGoto(p, GO_SIEM);
  withTone(p, tone(verdict));

  p.body.appendChild(lead(verdict.toUpperCase(), null,
    badge(pipe.siem_idle ? t("gui_health_queue_idle") : t("gui_health_queue_active"), "neutral")));
  const lag = (pipe.cache_lag || []).map(function (c) {
    return tf("gui_health_source_freshness", {
      source: c.source, status: c.last_status || "—", age: dur(c.lag_s),
    });
  }).join(" · ");
  p.body.appendChild(kv(t("gui_ov_cache_lag_label"), lag || "—"));
  p.body.appendChild(kv(t("gui_ov_siem_success_1h"),
    pipe.siem_success_1h === null || pipe.siem_success_1h === undefined ? "—" : pipe.siem_success_1h + "%"));
  p.body.appendChild(kv(t("gui_ov_dlq_label"), num(pipe.dlq)));
  p.body.appendChild(note(reasons.length ? reasons.join(" · ") : t("gui_health_clear")));
  return p;
}

// ── OV-14 TLS 卡 ← tls_status.json + integrations.js:1542-1560 ──────────────
// The product's card reads dashboard_overview.tls (days/expiring_soon/check_failed);
// tls_status carries the same numbers plus the certificate itself, so the card
// states which certificate the countdown belongs to.
function cardTls(tls, ovTls) {
  const info = tls.cert_info || {};
  let tn = "ok";
  if (!tls.enabled) tn = "neutral";
  else if (ovTls && ovTls.check_failed) tn = "warn";
  else if (info.expired) tn = "crit";
  else if (info.expiring_soon) tn = "warn";

  const p = panel("OV-14", t("gui_ov_tls_cert"));
  withMeta(p, tls.self_signed ? t("gui_tls_self_signed") : t("gui_tls_cert_info"));
  withGoto(p, GO_TLS);
  withTone(p, tn);

  if (ovTls && ovTls.check_failed) {
    p.body.appendChild(emptyState(t("gui_tls_check_failed"), GO_TLS));
    return p;
  }
  if (!info.exists) {
    p.body.appendChild(emptyState(t("gui_tls_no_cert"), GO_TLS));
    return p;
  }
  const days = tls.days_remaining === null || tls.days_remaining === undefined ? "—" : String(tls.days_remaining);
  p.body.appendChild(lead(days, t("gui_ov_tls_days"),
    info.expiring_soon ? badge(t("gui_tls_expiring_soon"), "warn") : null));
  p.body.appendChild(kv(t("gui_ov_cert_subject"), info.subject || "—"));
  p.body.appendChild(kv(t("gui_ov_cert_valid_until"), info.not_after || "—"));
  p.body.appendChild(kv(t("gui_tls_auto_renew"),
    tls.auto_renew ? t("gui_state_on") + " · " + tls.auto_renew_days + " " + t("gui_ov_tls_days") : t("gui_state_off")));
  return p;
}

// ── OV-02 posture score 卡＋詳情 ← dashboard.js:1496-1640 ───────────────────
// Component tone thresholds are dashboard.js:1530 (>=70 ok, >=40 warn, else crit).
// DESIGN-ADDED: the same thresholds are applied to `score` itself, which the
// product leaves un-toned (it only greys it when stale). Same 0-100 scale, so the
// extension is consistent rather than invented — but it is still an addition.
function compTone(value) {
  const v = Number(value);
  if (!isFinite(v)) return "neutral";
  return v >= 70 ? "ok" : (v >= 40 ? "warn" : "crit");
}

// dashboard.js:1511-1514 — posture rides a daily traffic snapshot, so freshness is
// judged on source_date with a 26h budget. The product measures against wall clock;
// a live page must measure against the payload's own as_of the same way, or a
// snapshot viewed the moment it lands would spuriously read as stale by clock skew.
function postureAge(po, asOf) {
  const ts = po.source_date || po.generated_at;
  const a = Date.parse(ts), b = Date.parse(asOf);
  if (!isFinite(a) || !isFinite(b)) return null;
  return (b - a) / 1000;
}

function postureDetail(po) {
  const box = el("div");
  box.appendChild(el("p", { class: "note", text: po.formula || "" }));

  const comps = po.components || [];
  const cols = [
    col("label", t("gui_posture_modal_col_component"), buildCell(function (r) { return t(r.label_key, r.key); })),
    col("value", t("gui_posture_modal_col_value"), numCell(function (r) { return (r.value === null || r.value === undefined ? "—" : r.value) + (r.unit || ""); })),
    col("weight", t("gui_posture_modal_col_weight"), numCell(function (r) { return r.weight === null || r.weight === undefined ? "—" : Math.round(r.weight * 100) + "%"; })),
    col("points", t("gui_posture_modal_col_points"), numCell(function (r) { return r.points === null || r.points === undefined ? "—" : Number(r.points).toFixed(1); })),
  ];
  const tblHost = el("div");
  box.appendChild(tblHost);
  table.render(tblHost, buildTable(cols, comps));

  const rh = comps.filter(function (c) { return c.key === "risk_health"; })[0];
  const subs = (rh && rh.risk_subscores) || [];
  if (subs.length) {
    box.appendChild(el("h4", { class: "eyebrow", text: t("gui_posture_sub_title") }));
    subs.forEach(function (s) {
      box.appendChild(kv(t(s.label_key, s.key),
        (s.value === null || s.value === undefined ? "—" : s.value) + (s.unit || ""),
        compTone(s.value)));
    });
  }
  const det = (rh && rh.detail) || null;
  if (det) {
    box.appendChild(el("h4", { class: "eyebrow", text: t("gui_story_group_risk") }));
    if (det.ransomware_apps !== undefined) {
      box.appendChild(kv(t("gui_ov_posture_modal_ransomware"), num(det.ransomware_apps),
        det.ransomware_apps > 0 ? "crit" : "ok"));
    }
    if (det.lateral_control_ratio !== undefined) {
      box.appendChild(kv(t("gui_ov_posture_modal_lateral"), Math.round(det.lateral_control_ratio * 100) + "%",
        compTone(det.lateral_control_ratio * 100)));
    }
    if (det.uncovered_pct !== undefined) {
      box.appendChild(kv(t("gui_ov_posture_modal_uncovered"), det.uncovered_pct + "%"));
    }
  }

  box.appendChild(el("h4", { class: "eyebrow", text: t("gui_posture_rmd_title") + " · " + t("gui_posture_rmd_points") }));
  const rmd = el("ul", { class: "stack" });
  (po.remediation || []).forEach(function (r) {
    rmd.appendChild(el("li", null,
      el("span", { class: "c", text: "+" + Number(r.recoverable_points).toFixed(1) }),
      el("span", { class: "s", text: t(r.recommendation_key, t(r.label_key, r.key)) }),
      el("span", { class: "c", text: "" }),
      el("span", { class: "r", text: t("gui_ov_current") + " " + r.current + " → " + t("gui_target") + " " + r.target })
    ));
  });
  box.appendChild(rmd);
  box.appendChild(note(t("gui_snap_generated") + " " + stamp(po.generated_at)));
  return box;
}

function cardPosture(ov, openDetail) {
  const po = ov.posture || {};
  const p = panel("OV-02", t("gui_ov_posture_score_label"));
  withMeta(p, stamp(po.source_date));
  if (po.available) withAction(p, t("gui_ov_detail"), openDetail);
  withGoto(p, GO_REPORTS);

  if (!po.available || po.score === null || po.score === undefined) {
    withTone(p, "neutral");
    p.body.appendChild(emptyState(t("gui_ov_posture_unavailable"), GO_REPORTS, t("gui_ov_posture_run_now")));
    return p;
  }

  const score = Number(po.score) || 0;
  withTone(p, compTone(score));

  const segs = el("span", { class: "segbar" });
  const litCount = Math.round(score / 5);
  for (let i = 0; i < 20; i++) segs.appendChild(el("i", { class: i < litCount ? "on" : null }));

  p.body.appendChild(el("div", { class: "gauge" },
    el("span", { class: "num" }, el("span", { text: String(score) }), el("s", { text: "/100" })),
    el("span", { class: "side" }, segs, el("p", { text: po.formula || "" }))
  ));

  (po.components || []).forEach(function (c) {
    const pct = Math.max(0, Math.min(100, Number(c.value) || 0));
    const bar = el("span", { class: "cb" }, el("i", { style: "width:" + pct + "%" }));
    p.body.appendChild(el("div", { class: "comp", "data-tone": compTone(c.value) },
      el("span", { class: "cn", text: t(c.label_key, c.key) }),
      el("b", { text: (c.value === null || c.value === undefined ? "—" : c.value) + (c.unit || "") }),
      el("em", { text: "w" + c.weight }),
      bar
    ));
  });

  const rmd = el("ul", { class: "stack" });
  (po.remediation || []).slice(0, 3).forEach(function (r) {
    rmd.appendChild(el("li", null,
      el("span", { class: "c", text: "+" + Number(r.recoverable_points).toFixed(1) }),
      el("span", { class: "s", text: t(r.recommendation_key, t(r.label_key, r.key)) }),
      el("span", { class: "c", text: "" })
    ));
  });
  p.body.appendChild(el("h4", { class: "eyebrow", text: t("gui_posture_rmd_title") }));
  p.body.appendChild(rmd);

  const age = postureAge(po, ov.as_of);
  if (age !== null && age > 26 * 3600) {
    p.body.appendChild(note(t("gui_ov_stale_since") + " " + dur(age)));
  }
  return p;
}

// ── OV-03 Top Actions ← dashboard_snapshot.snapshot.action_matrix ───────────
// The product's panel (index.html:1023-1028, heading gui_top_actions_heading) is
// never populated: no JS in src/static/js references d-top-actions-grid, and
// nothing renders #snap-content at all. Its intended feed is the same one the
// report builder uses — mod12_executive_summary.py:353,357-362 takes
// attack_summary.action_matrix ranked, limit 3 — so this reads
// dashboard_snapshot's action_matrix, already in rank order.
function cardTopActions(snap) {
  const rows = (snap.action_matrix || []).slice(0, 3);
  const p = panel("OV-03", t("gui_top_actions_heading"));
  withMeta(p, t("gui_top_actions_meta"));
  withGoto(p, GO_REPORTS);
  withTone(p, rows.length ? tone(rows[0].severity) : "neutral");

  if (!rows.length) {
    p.body.appendChild(emptyState(t("gui_snap_no_data"), GO_REPORTS));
    return p;
  }
  const list = el("ul", { class: "stack" });
  rows.forEach(function (r) {
    list.appendChild(el("li", { "data-tone": tone(r.severity) },
      badge(String(r.severity || ""), tone(r.severity)),
      el("span", { class: "s", title: r.action, text: r.action }),
      el("span", { class: "c", text: t("gui_count") + " " + num(r.count) }),
      el("span", { class: "r", text: r.action_code + " · " + t("gui_snap_col_flows") + " " + num(r.flow_total) + " · " + (r.apps || []).join(", ") })
    ));
  });
  p.body.appendChild(list);
  return p;
}

// dashboard.py's api_dashboard_top10 never echoes which rank_by produced the
// payload, and for rank_by=volume every row's val_fmt is independently scaled
// to whichever of B/KB/MB/GB/TB fits its magnitude -- e.g. "1.20 GB" and
// "980.00 MB" would compare as 1.20 vs 980.00 under a bare parseFloat, which is
// wrong on both axes (bar length AND the "rank" label, which was hardcoded
// regardless of what was actually ranked). This reads the unit off each row's
// own val_fmt: Mbps -> bandwidth (already comparable as-is), a byte unit ->
// volume (normalised to bytes so every row shares one basis), no unit -> count.
const VOLUME_UNITS = [["B", 1], ["KB", 1024], ["MB", 1024 * 1024], ["GB", 1024 * 1024 * 1024], ["TB", 1024 * 1024 * 1024 * 1024]];

function parseTopValue(fmt) {
  const s = String(fmt || "").trim();
  const m = s.match(/^([\d.]+)\s*(TB|GB|MB|KB|B|Mbps)?$/);
  if (!m) return { basis: parseFloat(s) || 0, rankBy: "count" };
  const n = parseFloat(m[1]) || 0;
  if (m[2] === "Mbps") return { basis: n, rankBy: "bandwidth" };
  if (m[2]) return { basis: n * lookup(VOLUME_UNITS, m[2], 1), rankBy: "volume" };
  return { basis: n, rankBy: "count" };
}

// ── OV-05 Top10 圖表 ← POST /api/dashboard/top10 (state.queries[0]) ─────────
// chartHandles, when given, receives the chart.rankedBars() handle so the
// caller (buildBoard) can destroy its ResizeObserver on repaint/unmount.
function cardTop10(top, chartHandles) {
  const data = top.data || [];
  const parsed = data.map(function (r) { return parseTopValue(r.val_fmt); });
  // rank_by is not in the response, so the label is read off the data actually
  // observed (first row's detected unit), not assumed to be bandwidth.
  const rankBy = parsed.length ? parsed[0].rankBy : "bandwidth";
  const rankLabel = lookup(RANK_KEYS, rankBy, "gui_rank_bw");
  const p = panel("OV-05", t("gui_top10_title") + " · " + t(rankLabel));
  /* `cap` is absent from the response whenever the query has not run (no saved
   * query, or the PCE call failed), and went to the screen as the literal word
   * "undefined". Every other field on this card already has an em-dash
   * fallback; this one did not. */
  withMeta(p, tf("gui_ov_top10_meta_fmt", {
    source: top.source || "—",
    cap: (top.cap === null || top.cap === undefined) ? "—" : top.cap,
    rows: tf("gui_table_rows", { total: num(top.total) }),
  }));
  withGoto(p, GO_TRAFFIC);
  withTone(p, "info");

  if (!top.ok || !data.length) {
    p.body.appendChild(emptyState(t("gui_top10_no_records"), GO_TRAFFIC));
    return p;
  }

  const rows = data.map(function (r, i) {
    return [
      r.s_name + "  " + r.dir + "  " + r.d_name,
      r.svc + "   " + r.s_ip + " → " + r.d_ip,
      parsed[i].basis,
      r.val_fmt,
    ];
  });

  function tip(row, i) {
    const r = data[i];
    const pairs = [];
    pairs.push([t(rankLabel), r.val_fmt]);
    pairs.push([t("gui_service_port"), r.svc]);
    pairs.push([t("gui_source_identity"), r.s_name + " · " + r.s_ip]);
    pairs.push([t("gui_destination_identity"), r.d_name + " · " + r.d_ip]);
    pairs.push([t("gui_policy_dec"), t(lookup(PD_KEYS, r.pd, "gui_pd_all"))]);
    pairs.push([t("gui_first_last_seen"), stamp(r.first_seen) + " → " + stamp(r.last_seen)]);
    return pairs;
  }

  const host = el("div");
  p.body.appendChild(host);
  const handle = chart.rankedBars(host, rows, tip);
  if (chartHandles) chartHandles.push(handle);

  // Two rows can carry the same source/destination/service and different values:
  // the analyzer derives per-window traffic from successive cache observations,
  // so one flow yields one row per observation window (first_seen → last_seen).
  const seen = [];
  let repeated = false;
  data.forEach(function (r) {
    const key = r.s_href + "|" + r.d_href + "|" + r.svc;
    if (seen.indexOf(key) >= 0) repeated = true;
    else seen.push(key);
  });
  if (repeated) p.body.appendChild(note(t("gui_ov_top10_windows")));
  if (top.truncated) p.body.appendChild(note(tf("gui_top10_truncated", { cap: top.cap })));
  return p;
}

// dashboard.js:2047-2058 runTop10Query() — payload = {...q, mins}. There is no
// live equivalent of "the query the page happens to have open"; this runs the
// FIRST saved query, same as the dashboard's own top-of-list ordering.
function loadTop10(queries) {
  if (!queries.length) return Promise.resolve({ ok: false, data: [] });
  return api.post("/api/dashboard/top10", Object.assign({}, queries[0], { mins: 1440 }));
}

// ── OV-04 自訂查詢卡＋新增/編輯 drawer ← /api/dashboard/queries (real CRUD) ──
function fieldKeys(queries) {
  const seen = [];
  const first = queries[0];
  if (first) {
    Object.keys(first).forEach(function (k) { if (seen.indexOf(k) < 0) seen.push(k); });
  } else {
    // No stored query to derive the field set from (a fresh install starts
    // with none) — fall back to the full schema so "add query" still has
    // inputs to fill in. The mockup never hit this path: its captured
    // snapshot always had at least one example query.
    FIELD_ORDER.forEach(function (k) { seen.push(k); });
  }
  const ordered = [];
  FIELD_ORDER.forEach(function (k) { if (seen.indexOf(k) >= 0) ordered.push(k); });
  seen.forEach(function (k) { if (ordered.indexOf(k) < 0) ordered.push(k); });
  return ordered;
}

function fieldLabel(key) {
  if (key === "src_labels" || key === "src_label") return t("gui_fb_dir_src") + " " + t("gui_fb_cat_label");
  if (key === "dst_labels" || key === "dst_label") return t("gui_fb_dir_dst") + " " + t("gui_fb_cat_label");
  // Legacy-only fields (pre-Phase-4b; see LIST_FIELDS/LEGACY_* above) reuse
  // existing catalogue keys rather than minting new ones — same composed
  // pattern as src_labels/dst_labels just above, "not"-flavoured for the
  // ex_ (exclude) fields and IP-flavoured for the ip_in fields. Falling
  // through to t(key) here (a raw field name, never a catalogue key) would
  // land "src_label" et al. in i18n.missing() every time a legacy query's
  // edit drawer opens.
  if (key === "ex_src_label" || key === "ex_src_labels") return t("gui_fb_col_src_not") + " " + t("gui_fb_cat_label");
  if (key === "ex_dst_label" || key === "ex_dst_labels") return t("gui_fb_col_dst_not") + " " + t("gui_fb_cat_label");
  if (key === "src_ip_in") return t("gui_fb_dir_src") + " " + t("gui_fb_cat_ip");
  if (key === "dst_ip_in") return t("gui_fb_dir_dst") + " " + t("gui_fb_cat_ip");
  if (key === "ex_src_ip") return t("gui_fb_col_src_not") + " " + t("gui_fb_cat_ip");
  if (key === "ex_dst_ip") return t("gui_fb_col_dst_not") + " " + t("gui_fb_cat_ip");
  return t(lookup(FIELD_LABELS, key, key));
}

function fieldValue(q, key) {
  const v = q[key];
  if (v === null || v === undefined) return "";
  return Array.isArray(v) ? v.join(", ") : String(v);
}

function fieldRow(key, control) {
  return el("div", { class: "fld" },
    el("label", null,
      el("span", { text: fieldLabel(key) }),
      el("code", { text: key })
    ),
    control
  );
}

// Radio `name` groups by document, not by container: two <input type=radio>
// with the same name are one mutually-exclusive group even when they live in
// unrelated drawers. __openAllForAudit opens the "new" and "edit" query drawers
// at once, so a shared literal "ov-dq-pd" name merged their pd radios into one
// group -- checking one cleared the other, and inputs.pd() silently fell back
// to "3" for whichever drawer lost the check. Each buildQueryForm() call now
// gets its own instance-scoped name.
let queryFormSeq = 0;

function buildQueryForm(q, fields) {
  const form = el("div");
  const inputs = {};
  const keys = fields.slice();
  const pdName = "ov-dq-pd-" + (++queryFormSeq);

  keys.forEach(function (key) {
    if (key === "pd") {
      const group = el("div", { class: "radios" });
      const radios = [];
      PD_KEYS.forEach(function (pair) {
        const input = el("input", { type: "radio", name: pdName, value: pair[0] });
        if (String(q.pd === undefined ? 3 : q.pd) === pair[0]) input.checked = true;
        radios.push(input);
        group.appendChild(el("label", null, input, el("span", { text: t(pair[1]) })));
      });
      inputs.pd = function () {
        let out = "3";
        radios.forEach(function (r) { if (r.checked) out = r.value; });
        return parseInt(out, 10);
      };
      form.appendChild(fieldRow(key, group));
      return;
    }
    if (key === "rank_by") {
      const sel = el("select", { class: "field", "data-field": key });
      RANK_KEYS.forEach(function (pair) {
        const opt = el("option", { value: pair[0], text: t(pair[1]) });
        if ((q.rank_by || "count") === pair[0]) opt.selected = true;
        sel.appendChild(opt);
      });
      inputs.rank_by = function () { return sel.value; };
      form.appendChild(fieldRow(key, sel));
      return;
    }
    const isList = LIST_FIELDS.indexOf(key) >= 0 || Array.isArray(q[key]);
    const input = el("input", {
      class: "field",
      "data-field": key,
      placeholder: key === "name" ? t("gui_ph_query_name") : "",
      value: fieldValue(q, key),
    });
    inputs[key] = function () {
      const raw = input.value.trim();
      if (!raw) return isList ? [] : null;
      return isList ? raw.split(",").map(function (s) { return s.trim(); }).filter(Boolean) : raw;
    };
    const wrap = fieldRow(key, input);
    if (isList) wrap.appendChild(el("span", { class: "hint", text: t("gui_ov_list_hint") }));
    form.appendChild(wrap);
  });

  form.read = function () {
    const out = {};
    keys.forEach(function (key) { out[key] = inputs[key] ? inputs[key]() : q[key]; });
    return out;
  };
  // The pd radios carry no data-field of their own (they are four inputs), so the
  // group is tagged on the wrapper for anyone auditing field coverage.
  const pdWrap = form.querySelector(".radios");
  if (pdWrap) pdWrap.setAttribute("data-field", "pd");
  return form;
}

// The summary line must read the query's OWN keys, not the card's field list:
// the two captured queries differ exactly there — the AND sample carries
// src_labels + dst_labels, the OR sample carries any_label ("任一端 Label
// (src 或 dst)"), which is where the OR lives. Iterating a shared key list would
// silently drop it and make the two queries look identical.
function queryConditions(q) {
  const parts = [];
  fieldKeys([q]).forEach(function (key) {
    if (key === "name" || key === "rank_by" || key === "pd") return;
    const v = fieldValue(q, key);
    if (!v) return;
    parts.push(fieldLabel(key) + " = " + v);
  });
  return parts.length ? parts.join("  " + t("gui_ov_cond_and") + "  ") : t("gui_ov_cond_none");
}

function cardQueries(state, onEdit, onNew) {
  const p = panel("OV-04", t("gui_top10_widgets"));
  withMeta(p, tf("gui_table_rows", { total: state.queries.length }));
  withAction(p, t("gui_add_query_widget"), onNew);
  withGoto(p, GO_TRAFFIC);
  withTone(p, "info");

  if (!state.queries.length) {
    p.body.appendChild(emptyState(t("gui_top10_empty"), GO_TRAFFIC));
    return p;
  }
  const list = el("ul", { class: "stack" });
  state.queries.forEach(function (q, i) {
    const pd = String(q.pd === undefined ? 3 : q.pd);
    const head = el("span", { class: "s" },
      el("b", { text: q.name || "—" }),
      badge(t(lookup(PD_KEYS, pd, "gui_pd_all")), lookup(PD_TONES, pd, "info")),
      el("span", { class: "c", text: t(lookup(RANK_KEYS, q.rank_by, "gui_rank_count")) })
    );
    const act = el("span", { class: "c" },
      el("button", { class: "btn link", type: "button", text: t("gui_edit_query_widget"), onClick: function () { onEdit(i); } })
    );
    list.appendChild(el("li", null,
      el("i", { class: "dot", "data-tone": lookup(PD_TONES, pd, "info") }),
      head,
      act,
      el("span", { class: "r", title: queryConditions(q), text: t("gui_filter_details") + "：" + queryConditions(q) })
    ));
  });
  p.body.appendChild(list);
  return p;
}

// ── OV-06 audit 摘要 ← dashboard_audit.json ────────────────────────────────
function cardAudit(au) {
  const su = au.summary || {};
  const p = panel("OV-06", t("gui_dashboard_audit_summary"));
  withGoto(p, GO_REPORTS);

  if (!au.ok || !su.kpis) {
    withTone(p, "neutral");
    p.body.appendChild(emptyState(au.error || t("gui_dashboard_no_audit_summary"), GO_REPORTS));
    return p;
  }
  const range = Array.isArray(su.date_range) ? su.date_range.join(" → ") : String(su.date_range || "");
  withMeta(p, range);
  const attention = su.attention_items || [];
  withTone(p, attention.length ? tone(attention[0].risk) : "ok");

  // /api/dashboard/audit_summary localises `label` server-side
  // (dashboard.py::_retranslate_kpi_labels), which is why the GUI catalogue does
  // not carry the rpt_au_kpi_* keys at all. The payload's own label is therefore
  // the primary; label_key is the fallback for payloads that predate it.
  const grid = el("dl", { class: "kpi" });
  (su.kpis || []).slice(0, 8).forEach(function (k) {
    const label = k.label || t(k.label_key);
    grid.appendChild(el("div", null,
      el("dt", { title: label, text: label }),
      el("dd", { text: k.value })
    ));
  });
  p.body.appendChild(grid);

  p.body.appendChild(el("h4", { class: "eyebrow", text: t("gui_dashboard_audit_attention") }));
  const list = el("ul", { class: "stack" });
  attention.slice(0, 4).forEach(function (a) {
    list.appendChild(el("li", { "data-tone": tone(a.risk) },
      badge(String(a.risk || ""), tone(a.risk)),
      el("span", { class: "s", title: a.summary, text: a.summary }),
      el("span", { class: "c", text: num(a.count) }),
      el("span", { class: "r", text: a.event_type + " · " + a.recommendation })
    ));
  });
  p.body.appendChild(list);

  p.body.appendChild(el("h4", { class: "eyebrow", text: t("gui_dashboard_audit_top_events") }));
  p.body.appendChild(chips((su.top_events || []).slice(0, 5).map(function (e) {
    return [e["Event Type"], num(e.Count), false];
  })));
  return p;
}

// ── OV-08 dashboard snapshot ← dashboard_snapshot.json ─────────────────────
function cardSnapshot(ds) {
  const snap = ds.snapshot || {};
  const p = panel("OV-08", t("gui_snap_title"));
  withGoto(p, GO_REPORTS);

  if (!ds.ok || !ds.snapshot) {
    withTone(p, "neutral");
    p.body.appendChild(emptyState(ds.error || t("gui_snap_no_data"), GO_REPORTS));
    return p;
  }
  withMeta(p, String(snap.generated_at || ""));
  const score = Number(snap.maturity_score);
  const grade = String(snap.maturity_grade || "?");
  const highRisk = (snap.hero && snap.hero.high_risk_count) || 0;
  withTone(p, compTone(score));

  p.body.appendChild(lead(isFinite(score) ? String(score) : "—", "/100 " + grade,
    badge(t("gui_ov_risk_tag_hi") + " " + highRisk, highRisk > 0 ? "crit" : "ok")));
  p.body.appendChild(note(tf("gui_hero_sentence", { score: score, grade: grade, high_risk: highRisk })));
  p.body.appendChild(kv(t("gui_posture_coverage"), snap.policy_coverage_pct + "%", compTone(snap.policy_coverage_pct)));
  p.body.appendChild(kv(t("gui_snap_col_flows"), num(snap.total_flows)));
  p.body.appendChild(kv(t("gui_snap_col_connections"), num(snap.total_connections)));
  p.body.appendChild(kv(t("gui_pd_allowed") + " / " + t("gui_pd_blocked"),
    num(snap.allowed_flows) + " / " + num(snap.blocked_flows)));

  p.body.appendChild(el("h4", { class: "eyebrow", text: t("gui_snap_col_finding") }));
  const list = el("ul", { class: "stack" });
  (snap.key_findings || []).slice(0, 3).forEach(function (f) {
    list.appendChild(el("li", { "data-tone": tone(f.severity) },
      badge(String(f.severity || ""), tone(f.severity)),
      el("span", { class: "s", title: f.finding, text: f.finding }),
      el("span", { class: "c", text: "" }),
      el("span", { class: "r", text: f.action })
    ));
  });
  p.body.appendChild(list);
  p.body.appendChild(note(t("gui_ov_hero_recomputed")));
  return p;
}

// ── OV-07 policy usage 摘要 ← dashboard_pu.json ────────────────────────────
// A {ok:false, error:"…"} response means the appliance has never produced a
// Policy Usage report. The card renders that verdict and the product's own
// sentence; inventing a number here would be the one unforgivable thing.
function cardPolicyUsage(pu) {
  const p = panel("OV-07", t("gui_sched_rt_pu"));
  withGoto(p, GO_REPORTS);
  withTone(p, "neutral");
  if (pu && pu.ok) {
    const su = pu.summary || {};
    const grid = el("dl", { class: "kpi" });
    (su.kpis || []).slice(0, 8).forEach(function (k) {
      const label = k.label || t(k.label_key);
      grid.appendChild(el("div", null,
        el("dt", { title: label, text: label }),
        el("dd", { text: k.value })
      ));
    });
    p.body.appendChild(grid);
    return p;
  }
  p.body.appendChild(emptyState((pu && pu.error) || t("gui_dashboard_no_policy_usage_summary"), GO_REPORTS));
  return p;
}

// ── table helpers (kept ≤4 keys per literal for the inline-data lint) ───────
function buildCell(fn) {
  const o = {};
  o.cell = fn;
  return o;
}

function numCell(fn) {
  const o = {};
  o.cell = fn;
  o.align = "n";
  return o;
}

function widthCell(width, fn) {
  const o = {};
  o.width = width;
  if (fn) o.cell = fn;
  return o;
}

function buildTable(columns, rows) {
  const spec = {};
  spec.columns = columns;
  spec.rows = rows;
  return spec;
}

// ── OV-11 job 健康摘要 ← integrations.js:1504-1539 (_buildOvJobHealth) ──────
// level is the backend's verdict (comment at 1502-1503: error = last run failed,
// warn = never ran or overdue, ok = healthy); appends gui_jh_overdue only when
// the job is warn AND has actually run before.
function cardJobs(ov) {
  const jobs = ov.job_health || [];
  const okCount = jobs.filter(function (j) { return j.level === "ok"; }).length;
  const p = panel("OV-11", t("gui_ov_job_health"));
  withMeta(p, tf("gui_health_jobs_ok", { ok: okCount, total: jobs.length }));
  withGoto(p, GO_JOBS);
  withTone(p, jobs.some(function (j) { return j.level === "error"; }) ? "crit"
    : (jobs.some(function (j) { return j.level === "warn"; }) ? "warn" : "ok"));

  p.body.classList.add("flush");
  if (!jobs.length) {
    p.body.appendChild(emptyState(t("gui_no_data"), GO_JOBS));
    return p;
  }
  const rows = jobs.map(function (j) {
    const r = {};
    r.job = j.job_id;
    r.interval = Number(j.interval_seconds) ? dur(j.interval_seconds) : "—";
    r.last = j.last_run ? since(j.last_run, ov.as_of) : t("gui_jh_never_ran");
    r.status = (j.level === "warn" && j.last_run) ? (j.last_status + " · " + t("gui_jh_overdue")) : (j.last_status || "");
    r._tone = tone(j.level);
    r._detail = j.detail || "";
    return r;
  });
  const cols = [
    col("job", t("gui_jh_th_job"), buildCell(function (r) {
      return el("span", { class: "mono", "data-tone": r._tone }, el("i", { class: "dot" }), el("span", { text: " " + r.job }));
    })),
    col("interval", t("gui_jh_th_interval"), numCell(function (r) { return r.interval; })),
    col("last", t("gui_jh_th_last_run"), numCell(function (r) { return r.last; })),
    col("status", t("gui_jh_th_status"), widthCell(120, function (r) { return r._detail ? r.status + " · " + r._detail : r.status; })),
  ];
  table.render(p.body, buildTable(cols, rows));
  return p;
}

// ── OV-13 近期事件表 ← events_viewer.json ──────────────────────────────────
function cardEvents(ev) {
  const items = ev.items || [];
  const su = ev.summary || {};
  const p = panel("OV-13", t("gui_tab_events"));
  withMeta(p, t("gui_ev_showing") + " " + Math.min(8, items.length) + " / " + t("gui_ev_matched") + " " + num(su.matched_count));
  withGoto(p, GO_EVENTS);
  withTone(p, "info");

  p.body.classList.add("flush");
  if (!ev.ok || !items.length) {
    p.body.classList.remove("flush");
    p.body.appendChild(emptyState(t("gui_ev_no_match"), GO_EVENTS));
    return p;
  }
  const rows = items.slice(0, 8).map(function (it) {
    const n = it.normalized || {};
    const r = {};
    r.time = stamp(it.timestamp);
    r.type = it.event_type;
    r.sev = it.severity;
    r.target = (n.target_name || "—") + (n.target_type ? " (" + n.target_type + ")" : "");
    // severity drives the badge; status only escalates on an explicit failure.
    // status is null on events where the notion does not apply — null is not
    // a failure.
    r._tone = (it.status && tone(it.status) === "crit") ? "crit" : tone(it.severity);
    return r;
  });
  const cols = [
    col("time", t("gui_time"), widthCell(150)),
    col("type", t("gui_event_type"), buildCell(function (r) { return el("span", { class: "mono", text: r.type }); })),
    col("sev", t("gui_ev_detail_sev"), widthCell(84, function (r) { return badge(r.sev, r._tone); })),
    col("target", t("gui_target"), buildCell(function (r) { return r.target; })),
  ];
  table.render(p.body, buildTable(cols, rows));
  p.body.appendChild(el("div", { class: "panel-b" },
    note(tf("gui_ov_events_window", { since: stamp(su.query_since), until: stamp(su.query_until) }))));
  return p;
}

// ── OV-12 資料完整性卡 ← integrations.js:1562-1583 (_buildOvDataIntegrity) ──
// Source semantics: collections whose GET was truncated and whose fallback did
// not recover, over the last 7 days; every entry is warn because truncation
// means report data is incomplete. The product returns '' for an empty list —
// the card vanishes. Here it stays and states the negative result, because a
// coverage anchor that only exists during an incident cannot be reviewed.
function cardIntegrity(ov) {
  const items = ov.data_integrity || [];
  const p = panel("OV-12", t("gui_ov_data_integrity"));
  withMeta(p, tf("gui_table_rows", { total: items.length }));
  withGoto(p, GO_PCE);
  withTone(p, items.length ? "warn" : "ok");

  if (!items.length) {
    p.body.appendChild(emptyState(t("gui_ov_no_truncation"), GO_PCE));
    return p;
  }
  p.body.classList.add("flush");
  const rows = items.map(function (e) {
    const r = {};
    r.path = tf("gui_ov_truncated_fmt", { path: e.path, got: e.got, total: e.total });
    r.last = e.last_seen || "";
    r._tone = "warn";
    return r;
  });
  const cols = [
    col("path", t("gui_ov_di_th_collection"), buildCell(function (r) { return r.path; })),
    col("last", t("gui_ov_di_th_last_seen"), widthCell(170)),
  ];
  table.render(p.body, buildTable(cols, rows));
  return p;
}

// ── OV-09 報表最近產出 meta ← /api/reports (reports_list) ──────────────────
// One row per report_type, newest first. report_type is "" whenever the file
// has no .metadata.json sidecar (reports.py:215) — shown as one "untyped" row
// rather than dropped.
function cardReports(rl, ov) {
  const reports = (rl.reports || []).slice().sort(function (a, b) { return b.mtime - a.mtime; });
  const byType = new Map();
  reports.forEach(function (r) {
    const key = r.report_type || "";
    if (!byType.has(key)) byType.set(key, []);
    byType.get(key).push(r);
  });

  const p = panel("OV-09", t("gui_tab_reports"));
  withMeta(p, t("gui_ov_latest_per_type"));
  withGoto(p, GO_REPORTS);
  withTone(p, "info");

  if (!reports.length) {
    p.body.appendChild(emptyState(t("gui_reports_empty"), GO_REPORTS));
    return p;
  }
  p.body.classList.add("flush");
  const rows = [];
  byType.forEach(function (list, key) {
    const newest = list[0];
    const r = {};
    r.type = key ? t(lookup(REPORT_TYPE_KEYS, key, key)) : t("gui_ov_report_untyped");
    r.file = newest.filename;
    r.size = (newest.size / 1024).toFixed(1) + " KB";
    r.age = since(new Date(newest.mtime * 1000).toISOString(), ov.as_of);
    r.count = list.length;
    r._untyped = key ? 0 : 1;
    r._tone = key ? null : "neutral";
    rows.push(r);
  });
  // byType was filled from a newest-first list, so insertion order is already
  // "most recent type first"; a stable sort only moves the untyped bucket last.
  rows.sort(function (a, b) { return a._untyped - b._untyped; });
  const cols = [
    col("type", t("gui_col_type"), widthCell(150, function (r) {
      return el("span", null, el("span", { text: r.type + " " }),
        el("span", { class: "mono", text: tf("gui_ov_report_count", { n: r.count }) }));
    })),
    col("file", t("gui_col_filename"), buildCell(function (r) { return el("span", { class: "mono", title: r.file, text: r.file }); })),
    col("size", t("gui_col_size"), numCell(function (r) { return r.size; })),
    // Age, not a wall-clock stamp: mtime is epoch seconds and the filenames carry
    // appliance-local time, so rendering a UTC stamp beside a filename that says
    // 1532 would read as a contradiction. Age is timezone-free.
    col("age", t("gui_col_age"), numCell(function (r) { return r.age; })),
  ];
  table.render(p.body, buildTable(cols, rows));
  return p;
}

// ── OV-15 告警管道卡（唯讀）← status.alert_channels + alert_plugins.json ────
// integrations.js — a channel wears the "ok" chip when it is configured,
// "muted" otherwise; status.alert_channels already carries the authoritative
// configured/enabled pair plus the last dispatch outcome.
function cardChannels(st, plugins) {
  const chans = st.alert_channels || [];
  const live = chans.filter(function (c) { return c.enabled && c.configured; });
  const failed = live.filter(function (c) { return c.last_status && c.last_status !== "success"; });

  const p = panel("OV-15", t("gui_ov_alert_channels"));
  withMeta(p, live.length + " / " + chans.length);
  withGoto(p, GO_CHANNELS);
  withTone(p, failed.length ? "crit" : (live.length ? "ok" : "neutral"));

  if (!chans.length) {
    p.body.appendChild(emptyState(t("gui_action_no_plugins"), GO_CHANNELS));
    return p;
  }
  const list = el("ul", { class: "stack" });
  chans.forEach(function (c) {
    const ready = !!(c.enabled && c.configured);
    const bad = ready && c.last_status && c.last_status !== "success";
    const tn = bad ? "crit" : (ready ? "ok" : "neutral");
    const plugin = (plugins.plugins || {})[c.name] || {};
    const detail = ready
      ? t("gui_ov_last_dispatch") + " " + (c.last_status || "—")
        + (c.last_timestamp ? " · " + stamp(c.last_timestamp) : "")
        + (c.last_target ? " · " + firstLine(c.last_target, 42) : "")
      : tf("gui_ov_missing_fields", { fields: (c.missing_required || []).join(", ") || "—" });
    list.appendChild(el("li", { "data-tone": tn },
      badge(ready ? t("gui_ov_ch_verified") : t("gui_ov_ch_not_configured"), tn),
      el("span", { class: "s", text: c.display_name || c.name }),
      el("span", { class: "c", text: tf("gui_ov_plugin_fields", { n: (plugin.fields || []).length }) }),
      el("span", { class: "r", title: detail, text: detail })
    ));
  });
  p.body.appendChild(list);
  return p;
}

// ── board ───────────────────────────────────────────────────────────────────
function brow(cls, panels) {
  return el("div", { class: "brow " + cls }, panels);
}

function buildBoard(host, d, state) {
  const ov = d.dashboard_overview || {};
  const st = d.status || {};

  // The previous repaint's OV-05 chart (if any) is about to be discarded with
  // the rest of `host`'s children — destroy its ResizeObserver first so it
  // does not keep firing against a detached host.
  (state.chartHandles || []).forEach(function (h) {
    try { h.destroy(); } catch (e) { console.error("[overview] chart teardown failed", e); }
  });
  state.chartHandles = [];

  function openPostureDetail() {
    return drawer.open(drawerSpec(t("gui_ov_posture_score_label"), postureDetail(ov.posture || {})));
  }

  // top10 (OV-05) rides a live PCE flow-search (POST /api/dashboard/top10)
  // that can take several seconds, or fail outright when the PCE is
  // unreachable (verified empirically against an unresolvable PCE host:
  // ~6s before the backend's own try/except turns the DNS failure into a
  // {ok:false} response) — no query CRUD interaction may block on it.
  // refreshTop10() therefore runs in the background and repaints once more
  // when it settles, never awaited by a save/delete handler. state.top10Seq
  // makes only the MOST RECENTLY issued fetch allowed to apply its result:
  // without it, a slow fetch from an earlier (now stale) query list could
  // resolve after a faster later one and clobber the display with data for
  // a query that no longer exists.
  function refreshTop10() {
    // No saved query -> loadTop10() would resolve immediately with the exact
    // {ok:false, data:[]} placeholder d.top10 already holds (see loadAll()).
    // Skip the no-op fetch-and-repaint entirely rather than churn the board
    // (clear + rebuild all 16 cards) for a result that cannot have changed.
    if (!state.queries.length) return;
    state.top10Seq = (state.top10Seq || 0) + 1;
    const seq = state.top10Seq;
    loadTop10(state.queries).then(function (top) {
      if (state.torn || seq !== state.top10Seq) return;
      d.top10 = top;
      state.repaint();
    });
  }

  // Re-fetches the saved-query list from the real backend after a CRUD call,
  // repaints immediately with it, then kicks off a top10 refresh in the
  // background (see refreshTop10() above). state.fields is NOT recomputed
  // here — it is the form's fixed field schema, set once at mount from
  // whatever shape the backend had at load time; if a delete empties the
  // list, "add query" must keep offering the full schema, not shrink to
  // nothing (see fieldKeys()'s empty-input fallback above).
  async function refreshQueries() {
    // api.reload() throws on a non-2xx GET (core/api.mjs's load()/fetchJson()
    // contract). The POST/DELETE this always follows has already succeeded
    // by the time refreshQueries() runs — only the re-read can fail here —
    // but drawer.mjs's Save button has no catch around `await o.onSave()`
    // (only a `finally`), so letting this throw would escape as an
    // unhandled rejection: the drawer stays open, no toast fires, and the
    // user has no way to tell the write actually went through (review
    // finding, promoted from Minor). Caught and surfaced distinctly instead.
    let queries;
    try {
      queries = await api.reload("dashboard_queries");
    } catch (e) {
      toast.crit(tf("error_generic", { error: (e && e.message) || String(e) }));
      return;
    }
    // A save/delete can still be in flight when the user navigates away;
    // state.torn (set by installTeardown's callback) stops a late
    // resolution from repainting a torn-down board — same reasoning as
    // refreshTop10()'s guard above.
    if (state.torn) return;
    d.dashboard_queries = queries;
    state.queries = queries.slice();
    state.repaint();
    refreshTop10();
  }

  function openQuery(index) {
    const isNew = index < 0;
    if (!isNew && !state.queries[index]) return null;
    const source = isNew ? {} : state.queries[index];
    const keys = isNew ? state.fields : fieldKeys([source]).concat(
      state.fields.filter(function (k) { return Object.keys(source).indexOf(k) < 0; }));
    const form = buildQueryForm(source, keys);
    const spec = drawerSpec(isNew ? t("gui_add_query_widget") : t("gui_edit_query_widget"), form);
    spec.onSave = async function () {
      const next = form.read();
      const payload = buildSavePayload(next, isNew ? undefined : index);
      const r = await api.post("/api/dashboard/queries", payload);
      if (!r || r.ok !== true) {
        toast.crit(tf("error_generic", { error: (r && r.error) || t("gui_err_generic") }));
        return false;
      }
      await refreshQueries();
      toast.ok(tf(isNew ? "gui_ov_query_added" : "gui_ov_query_saved", { name: next.name || "—" }));
      return true;
    };
    if (!isNew) {
      const handle = drawer.open(spec);
      const del = el("button", { class: "btn danger", type: "button", text: t("gui_delete") });
      del.addEventListener("click", function () {
        modal.confirm(confirmSpec(t("gui_confirm_delete_widget"), [source.name || "—"], async function () {
          const r = await api.del("/api/dashboard/queries/" + index);
          if (!r || r.ok !== true) {
            toast.crit(tf("error_generic", { error: (r && r.error) || t("gui_err_generic") }));
            return false;
          }
          handle.close();
          await refreshQueries();
          toast.warn(tf("gui_ov_query_deleted", { name: source.name || "—" }));
        }));
      });
      const foot = handle.el.querySelector(".drawer-f");
      if (foot) foot.insertBefore(del, foot.firstChild);
      return handle;
    }
    return drawer.open(spec);
  }

  state.repaint = function () {
    buildBoard(host, d, state);
  };

  clear(host);

  /* Density spec R1/R2 on the one page an operator lands on.
   *
   * This board used to open with sixteen cards in six rows, led by four status
   * cards that restate what the health rail directly above them already shows
   * (PCE, pipeline, cache, alert channels). The question someone opens the
   * overview with is "how are we doing, and what should I do next" — so the
   * posture score and the ranked actions lead, the traffic ranking they are
   * usually chasing stays with them, and the remaining eleven cards become two
   * named groups, present and one click away.
   *
   * Every data-cov anchor still renders: a closed <details> keeps its children
   * in the DOM, so the coverage gate's 102 are all still there and the cards
   * are still built from the same data. Nothing was dropped to make this fit. */
  host.appendChild(brow("c75", [
    cardPosture(ov, openPostureDetail),
    cardTopActions((d.dashboard_snapshot && d.dashboard_snapshot.snapshot) || {}),
  ]));
  host.appendChild(brow("c75", [
    cardTop10(d.top10 || {}, state.chartHandles),
    cardQueries(state, openQuery, function () { openQuery(-1); }),
  ]));

  host.appendChild(disclosure(t("gui_ov_group_system"),
    brow("c4", [
      cardSystem(st, ov),
      cardIntegrations(d),
      cardPipeline(ov),
      cardTls(d.tls_status || {}, ov.tls),
    ]),
    brow("c2", [
      cardChannels(st, d.alert_plugins || {}),
      cardIntegrity(ov),
    ])));

  host.appendChild(disclosure(t("gui_ov_group_activity"),
    brow("c3", [
      cardAudit(d.dashboard_audit || {}),
      cardSnapshot(d.dashboard_snapshot || {}),
      cardPolicyUsage(d.dashboard_pu || {}),
    ]),
    // Both of these are four-column tables; three to a row squeezed job names
    // and event targets to ellipses, so they get half the board each.
    brow("c2", [
      cardJobs(ov),
      cardEvents(d.events_viewer || {}),
    ]),
    brow("c2", [
      cardReports(d.reports_list || {}, ov),
    ])));

  return { openPostureDetail: openPostureDetail, openQuery: openQuery, refreshTop10: refreshTop10 };
}

function drawerSpec(title, body) {
  const spec = {};
  spec.title = title;
  spec.body = body;
  return spec;
}

function confirmSpec(title, impact, onOk) {
  const spec = {};
  spec.title = title;
  spec.impact = impact;
  spec.onOk = onOk;
  return spec;
}

function buildSavePayload(def, idx) {
  const body = {};
  TOP_LEVEL_SAVE_KEYS.forEach(function (k) {
    if (def[k] !== undefined && def[k] !== null && def[k] !== "") body[k] = def[k];
  });
  const filters = {};
  FILTER_SAVE_KEYS.forEach(function (k) {
    const v = def[k];
    if (v === undefined || v === null) return;
    if (Array.isArray(v) && !v.length) return;
    filters[k] = v;
  });
  LEGACY_SCALAR_FILTER_KEYS.forEach(function (k) {
    const v = def[k];
    if (v === undefined || v === null || v === "") return;
    filters[k] = v;
  });
  LEGACY_LABEL_KEYS.forEach(function (pair) {
    const src = pair[0], dest = pair[1];
    const v = def[src];
    if (v === undefined || v === null) return;
    const vals = (Array.isArray(v) ? v : [v]).filter(function (s) { return s !== "" && s !== null && s !== undefined; });
    if (!vals.length) return;
    const existing = filters[dest] || [];
    vals.forEach(function (item) { if (existing.indexOf(item) < 0) existing.push(item); });
    filters[dest] = existing;
  });
  // ALWAYS send `filters`, even {}: dashboard.py:519-546 only takes the
  // flat-whitelist dict branch when `d.get('filters')` is a dict at all
  // (isinstance check) — omitting the key for a filter-less query would
  // fall through to dashboard.py:547-558's legacy branch, which rebuilds
  // query_def from combined `src`/`dst`/`ex_src`/`ex_dst` strings this form
  // never sends, blanking every filter field (not just the legacy ones the
  // LEGACY_* forwarding above targets) — the exact bug this fix closes.
  body.filters = filters;
  if (idx !== undefined && idx !== null) body.idx = idx;
  return body;
}

// top10 is deliberately NOT part of the initial load: it rides a live PCE
// flow-search that can be slow or fail outright (see refreshTop10()'s
// comment in buildBoard), and the other 16 cards must not wait on it for
// their first paint. loadAll() seeds an empty/not-ok placeholder; buildBoard
// (called from mountOverview, and again by refreshQueries after a CRUD op)
// requests the real thing in the background via refreshTop10().
// Each source is caught independently: unlike the mockup's static snapshots
// (which never fail), several of these are live PCE-backed endpoints that
// return a non-2xx status on a real, ordinary operational condition (e.g.
// GET /api/events/viewer -> 502 whenever the PCE is unreachable — verified
// against this exact codepath, not hypothetical). api.load() throws on any
// non-2xx, and Promise.all rejects on the FIRST rejection — so a bare
// Promise.all over all 14 sources would let one struggling endpoint blank
// every other, unrelated card on the board. Every card here already
// tolerates a missing/falsy payload (the emptyState()/`!x.ok` branches
// throughout this file exist for exactly this), so degrading a failed
// source to {ok:false} and letting the OTHER 13 render normally is strictly
// better than the mockup's all-or-nothing load.
function loadOne(id) {
  return api.load(id).catch(function (e) {
    console.error("[overview] " + id + " failed to load", e);
    return { ok: false, error: String((e && e.message) || e) };
  });
}

function loadAll() {
  return Promise.all(SNAPS.map(loadOne)).then(function (list) {
    const out = {};
    SNAPS.forEach(function (id, i) { out[id] = list[i]; });
    out.top10 = { ok: false, data: [] };
    return out;
  });
}

export async function mountOverview(root, ctx) {
  // Everything that registers an opener or a command runs BEFORE the first await:
  // the router clears the route registries as it navigates, so a registration made
  // after an await would attach to whichever route the user has moved to by then.
  // The openers close over `handles`, which the board fills in once the data is
  // there; until then they no-op and stay retryable.
  //
  // The teardown that DROPS those registrations again has to obey the same
  // rule, and used to be registered inside the render callback instead — so a
  // mount that ended on the XC-10 error card never registered one, and its two
  // ov:* palette commands followed the operator out of this area, where
  // running them does nothing at all. Registered here, next to what it
  // undoes, exactly like installTeardown() in investigate/alerting/automation.
  const handles = {};
  const state = { torn: false };
  installTeardown(state);

  const probe = el("div", { class: "ov-error-probe" });
  audit.register("overview-error-card", function () {
    if (probe.firstChild) return;                    // idempotent
    root.appendChild(probe);
    withErrorCard(probe, "__audit_unavailable__",
      function () { return api.load("__audit_unavailable__"); },
      function () { });
  });
  drawer.registerAudit("ov-posture-detail", function () {
    return handles.openPostureDetail ? handles.openPostureDetail() : null;
  });
  drawer.registerAudit("ov-query-new", function () {
    return handles.openQuery ? handles.openQuery(-1) : null;
  });
  drawer.registerAudit("ov-query-edit", function () {
    return handles.openQuery ? handles.openQuery(0) : null;
  });

  palette.registerFor(ROUTE, cmdSpec("ov:query-new", t("gui_add_query_widget"), function () {
    if (handles.openQuery) handles.openQuery(-1);
  }));
  palette.registerFor(ROUTE, cmdSpec("ov:posture", t("gui_ov_posture_score_label") + " · " + t("gui_ov_detail"), function () {
    if (handles.openPostureDetail) handles.openPostureDetail();
  }));

  root.appendChild(areaHead(t("gui_nav_overview"), ROUTE));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "overview (" + SNAPS.length + ")", loadAll, function (d) {
    if (ctx.stale()) return;
    state.queries = (d.dashboard_queries || []).slice();
    state.fields = fieldKeys(state.queries);
    const built = buildBoard(board, d, state);
    handles.openPostureDetail = built.openPostureDetail;
    handles.openQuery = built.openQuery;

    // Kick off the real top10 fetch now that the rest of the board has
    // already painted (see loadAll()'s comment above).
    built.refreshTop10();
  });
}

/** S2 teardown — self-unsubscribing: the first navigation away from
 *  #/overview destroys this mount's OV-05 chart handle(s) (a real
 *  ResizeObserver leak otherwise), closes any drawer/modal this area left open
 *  (drawer.mjs/modal.mjs are page-global singletons with no per-area scoping,
 *  so closeAll() is the only way to guarantee nothing this mount opened
 *  survives the navigation), and drops this route's palette commands.
 *
 *  Called from mountOverview BEFORE its first await, together with the
 *  registrations it undoes — the shape investigate/alerting/automation's own
 *  installTeardown() already had. It used to run inside the render callback,
 *  on the argument that a mount which lost the race to a fast navigation
 *  should not register a teardown at all; the price was that a mount ending on
 *  the error card registered none either, and leaked its palette commands into
 *  every other area. Nothing here needs board state to exist: chartHandles is
 *  read defensively, and closeAll()/setRoute() are safe on an empty area.
 *  state.torn also guards refreshTop10()'s background repaint (buildBoard)
 *  against firing after teardown. */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    (state.chartHandles || []).forEach(function (h) {
      try { h.destroy(); } catch (e) { console.error("[overview] chart teardown failed", e); }
    });
    drawer.closeAll();
    modal.closeAll();
    palette.setRoute(path);
  });
}

function cmdSpec(id, label, run) {
  const spec = {};
  spec.id = id;
  spec.label = label;
  spec.run = run;
  return spec;
}
