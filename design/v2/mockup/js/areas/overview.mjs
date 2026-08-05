// overview.mjs — #/overview. Anchors OV-01…OV-16 (design/v2/coverage.yaml).
//
// Reading order of the board is the operator's, not the API's:
//   band 1  is the appliance alive?          OV-01 OV-16 OV-10 OV-14
//   band 2  how exposed am I?                OV-02 OV-03
//   band 3  what is moving right now?        OV-05 OV-04
//   band 4  what did the last reports say?   OV-06 OV-08 OV-07
//   band 5  is the machinery keeping up?     OV-11 OV-13 OV-12
//   band 6  what came out, and who is told?  OV-09 OV-15
//
// Every read-only card carries one affordance in its header — "前往 <route>" —
// because a summary card's job is to report and hand off, never to pretend it is
// the control surface. The only cards that act are OV-02 (its own breakdown) and
// OV-04 (the saved queries, which this area owns).
//
// Field semantics are transcribed from the shipping GUI; the source line is cited
// above each builder. Anything this design added on top of the source is marked
// DESIGN-ADDED, per Task 7 report §9.9.

import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { num, dur, stamp, since, tone, atLeast, firstLine } from "../core/fmt.mjs";
import { store } from "../core/store.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { chart } from "../components/chart.mjs";
import { areaHead } from "./placeholder.mjs";

const ROUTE = "#/overview";

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

const SNAPS = [
  "status", "dashboard_overview", "dashboard_queries", "top10",
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

// dashboard_queries stores a FLAT query_def (dashboard.py:539-546); these are the
// labels for the keys the snapshot actually carries. The field SET comes from the
// snapshot at runtime — only the display ORDER and the labels are authored here.
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
const LIST_FIELDS = ["src_labels", "dst_labels", "ports"];

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
    text: t("v2_health_goto") + " " + route,
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
      text: label || (t("v2_health_goto") + " " + route),
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
function cardSystem(st, ov) {
  const pce = st.pce_stats || {};
  const poll = String(pce.event_poll_status || "");
  const fails = Number(pce.consecutive_failures) || 0;
  let tn = tone(poll);
  if (st.health_check === false) tn = atLeast(tn, "crit");
  if (fails > 0) tn = "crit";

  const p = panel("OV-01", t("v2_ov_system_status"));
  withMeta(p, String(st.api_url || "").replace(/^https?:\/\//, ""));
  withGoto(p, GO_PCE);
  withTone(p, tn);

  const ok = st.health_check !== false;
  p.body.appendChild(lead(poll ? poll.toUpperCase() : "—", t("gui_card_event_poll"),
    badge(ok ? t("gui_status_ok") : t("gui_status_fail"), ok ? "ok" : "crit")));
  p.body.appendChild(kv(t("v2_ov_pce_failures"), String(fails), fails > 0 ? "crit" : null));
  p.body.appendChild(kv(t("v2_ov_last_poll"), since(pce.last_event_poll, ov.as_of)));
  p.body.appendChild(kv(t("v2_ov_last_batch"),
    tf("v2_ov_last_batch_fmt", { total: num(pce.last_batch_total), unknown: num(pce.last_batch_unknown) })));
  p.body.appendChild(kv(t("gui_dashboard_rules"), num(st.rules_count)));
  p.body.appendChild(kv(t("v2_user_version"), "v" + (st.version || "—")));
  p.body.appendChild(kv(t("v2_ov_watermark"), stamp(st.event_watermark) || "—"));
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
    if (l.level === "error" || l.level === "warning") {
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
    badge(pipe.siem_idle ? t("v2_health_queue_idle") : t("v2_health_queue_active"), "neutral")));
  const lag = (pipe.cache_lag || []).map(function (c) { return c.source + " " + dur(c.lag_s); }).join(" · ");
  p.body.appendChild(kv(t("gui_ov_cache_lag_label"), lag || "—"));
  p.body.appendChild(kv(t("gui_ov_siem_success_1h"),
    pipe.siem_success_1h === null || pipe.siem_success_1h === undefined ? "—" : pipe.siem_success_1h + "%"));
  p.body.appendChild(kv(t("gui_ov_dlq_label"), num(pipe.dlq)));
  p.body.appendChild(note(reasons.length ? reasons.join(" · ") : t("v2_health_clear")));
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
  p.body.appendChild(kv(t("v2_ov_cert_subject"), info.subject || "—"));
  p.body.appendChild(kv(t("v2_ov_cert_valid_until"), info.not_after || "—"));
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
// a frozen snapshot must measure against its own as_of or every mockup viewed
// tomorrow would report a fresh figure as stale.
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
      el("span", { class: "r", text: t("v2_ov_current") + " " + r.current + " → " + t("gui_target") + " " + r.target })
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
  if (po.available) withAction(p, t("v2_ov_detail"), openDetail);
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
// attack_summary.action_matrix ranked, limit 3 — so the mockup reads
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
  p.body.appendChild(note(t("v2_ov_dead_panel")));
  return p;
}

// dashboard.py:684-729 (api_dashboard_top10) never echoes which rank_by produced
// the payload, and for rank_by=volume every row's val_fmt is independently scaled
// to whichever of B/KB/MB/GB/TB fits its magnitude (764-777) -- e.g. "1.20 GB" and
// "980.00 MB" would compare as 1.20 vs 980.00 under a bare parseFloat, which is
// wrong on both axes (bar length AND the "· 最大頻寬" title, which was hardcoded
// regardless of what was actually ranked). This reads the unit off each row's own
// val_fmt: Mbps -> bandwidth (already comparable as-is), a byte unit -> volume
// (normalised to bytes so every row shares one basis), no unit -> count.
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

// ── OV-05 Top10 圖表 ← top10.json ──────────────────────────────────────────
function cardTop10(top) {
  const data = top.data || [];
  const parsed = data.map(function (r) { return parseTopValue(r.val_fmt); });
  // rank_by is not in the response, so the label is read off the data actually
  // observed (first row's detected unit), not assumed to be bandwidth.
  const rankBy = parsed.length ? parsed[0].rankBy : "bandwidth";
  const rankLabel = lookup(RANK_KEYS, rankBy, "gui_rank_bw");
  const p = panel("OV-05", t("gui_top10_title") + " · " + t(rankLabel));
  withMeta(p, tf("v2_ov_top10_meta_fmt", {
    source: top.source || "—", cap: top.cap, rows: tf("v2_table_rows", { total: num(top.total) }),
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
  chart.rankedBars(host, rows, tip);

  // Two rows can carry the same source/destination/service and different values:
  // the analyzer derives per-window traffic from successive cache observations,
  // so one flow yields one row per observation window (first_seen → last_seen).
  // Rows 0 and 1 of this very snapshot are that case. Say so rather than let the
  // chart look like it double-counted.
  const seen = [];
  let repeated = false;
  data.forEach(function (r) {
    const key = r.s_href + "|" + r.d_href + "|" + r.svc;
    if (seen.indexOf(key) >= 0) repeated = true;
    else seen.push(key);
  });
  if (repeated) p.body.appendChild(note(t("v2_ov_top10_windows")));
  if (top.truncated) p.body.appendChild(note(tf("gui_top10_truncated", { cap: top.cap })));
  return p;
}

// ── OV-04 自訂查詢卡＋新增/編輯 drawer ← dashboard_queries.json ─────────────
// The stored shape is FLAT (dashboard.py:539-546 flattens the FilterBar dict into
// query_def at save time), so the drawer edits flat keys — that is what the next
// GET returns and what /api/dashboard/top10 reads (dashboard.py:684-729).
function fieldKeys(queries) {
  const seen = [];
  const first = queries[0] || {};
  Object.keys(first).forEach(function (k) { if (seen.indexOf(k) < 0) seen.push(k); });
  const ordered = [];
  FIELD_ORDER.forEach(function (k) { if (seen.indexOf(k) >= 0) ordered.push(k); });
  seen.forEach(function (k) { if (ordered.indexOf(k) < 0) ordered.push(k); });
  return ordered;
}

function fieldLabel(key) {
  if (key === "src_labels") return t("gui_fb_dir_src") + " " + t("gui_fb_cat_label");
  if (key === "dst_labels") return t("gui_fb_dir_dst") + " " + t("gui_fb_cat_label");
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
    if (isList) wrap.appendChild(el("span", { class: "hint", text: t("v2_ov_list_hint") }));
    form.appendChild(wrap);
  });

  form.appendChild(note(t("v2_ov_query_local")));
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
  return parts.length ? parts.join("  " + t("v2_ov_cond_and") + "  ") : t("v2_ov_cond_none");
}

function cardQueries(state, onEdit, onNew) {
  const p = panel("OV-04", t("gui_top10_widgets"));
  withMeta(p, tf("v2_table_rows", { total: state.queries.length }));
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
// snapshot.hero.score/score_grade are NOT used: dashboard_hero.py:44-46 matches
// the English word "maturity" against kpi["label"], which /api/dashboard/snapshot
// has already localised (_retranslate_kpi_labels), so a zh appliance always falls
// through to 0.0/"?" — visible in this very snapshot (hero.score 0.0 while
// maturity_score is 25.6/F). The card reads maturity_score/maturity_grade, the
// authoritative fields on the same payload, and says so.
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
  p.body.appendChild(note(t("v2_ov_hero_recomputed")));
  return p;
}

// ── OV-07 policy usage 摘要 ← dashboard_pu.json ────────────────────────────
// The captured payload is {ok:false, error:"…"} — the appliance has never produced
// a Policy Usage report. The card renders that verdict and the product's own
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
// warn = never ran or overdue, ok = healthy); 1513-1515 appends gui_jh_overdue
// only when the job is warn AND has actually run before.
function cardJobs(ov) {
  const jobs = ov.job_health || [];
  const okCount = jobs.filter(function (j) { return j.level === "ok"; }).length;
  const p = panel("OV-11", t("gui_ov_job_health"));
  withMeta(p, tf("v2_health_jobs_ok", { ok: okCount, total: jobs.length }));
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
    // status is null on events where the notion does not apply (30 of the 67
    // captured items, e.g. user.pce_session_terminated) — null is not a failure.
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
    note(tf("v2_ov_events_window", { since: stamp(su.query_since), until: stamp(su.query_until) }))));
  return p;
}

// ── OV-12 資料完整性卡 ← integrations.js:1562-1583 (_buildOvDataIntegrity) ──
// Source semantics (comment at 1562-1563): collections whose GET was truncated and
// whose fallback did not recover, over the last 7 days; every entry is warn because
// truncation means report data is incomplete. The product returns '' for an empty
// list — the card vanishes. Here it stays and states the negative result, because a
// coverage anchor that only exists during an incident cannot be reviewed.
function cardIntegrity(ov) {
  const items = ov.data_integrity || [];
  const p = panel("OV-12", t("gui_ov_data_integrity"));
  withMeta(p, tf("v2_table_rows", { total: items.length }));
  withGoto(p, GO_PCE);
  withTone(p, items.length ? "warn" : "ok");

  if (!items.length) {
    p.body.appendChild(emptyState(t("v2_ov_no_truncation"), GO_PCE));
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

// ── OV-09 報表最近產出 meta ← reports_list.json ────────────────────────────
// One row per report_type, newest first. report_type is "" whenever the file has
// no .metadata.json sidecar (reports.py:215) — 36 of the 69 captured files, mostly
// VEN status / policy diff / policy resolver output. Those are shown as one
// "untyped" row rather than dropped.
function cardReports(rl, ov) {
  const reports = (rl.reports || []).slice().sort(function (a, b) { return b.mtime - a.mtime; });
  const byType = new Map();
  reports.forEach(function (r) {
    const key = r.report_type || "";
    if (!byType.has(key)) byType.set(key, []);
    byType.get(key).push(r);
  });

  const p = panel("OV-09", t("gui_tab_reports"));
  withMeta(p, t("v2_ov_latest_per_type"));
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
    r.type = key ? t(lookup(REPORT_TYPE_KEYS, key, key)) : t("v2_ov_report_untyped");
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
        el("span", { class: "mono", text: tf("v2_ov_report_count", { n: r.count }) }));
    })),
    col("file", t("gui_col_filename"), buildCell(function (r) { return el("span", { class: "mono", title: r.file, text: r.file }); })),
    col("size", t("gui_col_size"), numCell(function (r) { return r.size; })),
    // Age, not a wall-clock stamp: mtime is epoch seconds and the filenames carry
    // appliance-local time (UTC+8), so rendering a UTC stamp beside a filename
    // that says 1532 would read as a contradiction. Age is timezone-free.
    col("age", t("v2_col_age"), numCell(function (r) { return r.age; })),
  ];
  table.render(p.body, buildTable(cols, rows));
  return p;
}

// ── OV-15 告警管道卡（唯讀）← status.alert_channels + alert_plugins.json ────
// integrations.js:1650/1660/1667/1671 — a channel wears the "ok" chip when it is
// configured, "muted" otherwise; status.alert_channels already carries the
// authoritative configured/enabled pair plus the last dispatch outcome.
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
      ? t("v2_ov_last_dispatch") + " " + (c.last_status || "—")
        + (c.last_timestamp ? " · " + stamp(c.last_timestamp) : "")
        + (c.last_target ? " · " + firstLine(c.last_target, 42) : "")
      : tf("v2_ov_missing_fields", { fields: (c.missing_required || []).join(", ") || "—" });
    list.appendChild(el("li", { "data-tone": tn },
      badge(ready ? t("gui_ov_ch_verified") : t("gui_ov_ch_not_configured"), tn),
      el("span", { class: "s", text: c.display_name || c.name }),
      el("span", { class: "c", text: tf("v2_ov_plugin_fields", { n: (plugin.fields || []).length }) }),
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

  function openPostureDetail() {
    return drawer.open(drawerSpec(t("gui_ov_posture_score_label"), postureDetail(ov.posture || {})));
  }

  function openQuery(index) {
    const isNew = index < 0;
    if (!isNew && !state.queries[index]) return null;
    const source = isNew ? {} : state.queries[index];
    const keys = isNew ? state.fields : fieldKeys([source]).concat(
      state.fields.filter(function (k) { return Object.keys(source).indexOf(k) < 0; }));
    const form = buildQueryForm(source, keys);
    const spec = drawerSpec(isNew ? t("gui_add_query_widget") : t("gui_edit_query_widget"), form);
    spec.onSave = function () {
      const next = form.read();
      if (isNew) state.queries.push(next);
      else state.queries[index] = next;
      state.repaint();
      toast.ok(tf(isNew ? "v2_ov_query_added" : "v2_ov_query_saved", { name: next.name || "—" }));
      return true;
    };
    if (!isNew) {
      const handle = drawer.open(spec);
      const del = el("button", { class: "btn danger", type: "button", text: t("gui_delete") });
      del.addEventListener("click", function () {
        modal.confirm(confirmSpec(t("gui_confirm_delete_widget"), [source.name || "—"], function () {
          state.queries.splice(index, 1);
          handle.close();
          state.repaint();
          toast.warn(tf("v2_ov_query_deleted", { name: source.name || "—" }));
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
  host.appendChild(brow("c4", [
    cardSystem(st, ov),
    cardIntegrations(d),
    cardPipeline(ov),
    cardTls(d.tls_status || {}, ov.tls),
  ]));
  host.appendChild(brow("c75", [
    cardPosture(ov, openPostureDetail),
    cardTopActions((d.dashboard_snapshot && d.dashboard_snapshot.snapshot) || {}),
  ]));
  host.appendChild(brow("c75", [
    cardTop10(d.top10 || {}),
    cardQueries(state, openQuery, function () { openQuery(-1); }),
  ]));
  host.appendChild(brow("c3", [
    cardAudit(d.dashboard_audit || {}),
    cardSnapshot(d.dashboard_snapshot || {}),
    cardPolicyUsage(d.dashboard_pu || {}),
  ]));
  // Both of these are four-column tables; three to a row squeezed job names and
  // event targets to ellipses, so they get half the board each.
  host.appendChild(brow("c2", [
    cardJobs(ov),
    cardEvents(d.events_viewer || {}),
  ]));
  host.appendChild(brow("c543", [
    cardReports(d.reports_list || {}, ov),
    cardChannels(st, d.alert_plugins || {}),
    cardIntegrity(ov),
  ]));

  return { openPostureDetail: openPostureDetail, openQuery: openQuery };
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

function loadAll() {
  return Promise.all(SNAPS.map(function (id) { return store.load(id); })).then(function (list) {
    const out = {};
    SNAPS.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

export async function mountOverview(root, ctx) {
  // Everything that registers an opener or a command runs BEFORE the first await:
  // the router clears the route registries as it navigates, so a registration made
  // after an await would attach to whichever route the user has moved to by then
  // (Task 7 report §9.6). The openers close over `handles`, which the board fills
  // in once the data is there; until then they no-op and stay retryable.
  const handles = {};

  const probe = el("div", { class: "ov-error-probe" });
  audit.register("overview-error-card", function () {
    if (probe.firstChild) return;                    // idempotent
    root.appendChild(probe);
    withErrorCard(probe, "__audit_unavailable__",
      function () { return store.load("__audit_unavailable__"); },
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
  palette.registerFor(ROUTE, cmdSpec("ov:posture", t("gui_ov_posture_score_label") + " · " + t("v2_ov_detail"), function () {
    if (handles.openPostureDetail) handles.openPostureDetail();
  }));

  root.appendChild(areaHead(t("v2_nav_overview"), ROUTE));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "overview (" + SNAPS.length + ")", loadAll, function (d) {
    if (ctx.stale()) return;
    const state = {};
    state.queries = (d.dashboard_queries || []).slice();
    state.fields = fieldKeys(state.queries);
    const built = buildBoard(board, d, state);
    handles.openPostureDetail = built.openPostureDetail;
    handles.openQuery = built.openQuery;
  });
}

function cmdSpec(id, label, run) {
  const spec = {};
  spec.id = id;
  spec.label = label;
  spec.run = run;
  return spec;
}
