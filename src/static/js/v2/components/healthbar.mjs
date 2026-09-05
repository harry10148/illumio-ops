// healthbar.mjs — how many system lights there are, what tone each one is,
// and why. RENDERING LIVES ELSEWHERE: v3.1 (spec §2) replaced the instrument
// rail this file used to draw with the home page's health card, so this is
// now a pure computation over the two health snapshots and `computeLights` is
// its only export. areas/home.mjs is the one consumer.
//
// PORT OF design/v2/mockup/js/components/healthbar.mjs. Differences from the
// mockup:
//   1. i18n keys renamed v2_health_* -> gui_health_* (this task's global
//      rename; v2_ never ships in the product catalogue).
//   2. Teardown: render()/mount() still return the rail HTMLElement, same as
//      the mockup (this is the one component whose consumers may want the
//      bare node for direct DOM composition, so the return type is
//      preserved) — but a `.destroy()` method is attached to that element.
//      It closes any open popover (the mockup's popovers already have their
//      own close(), tracked in the `handles` array below; destroy() just
//      calls every one of them, same as a route change would want). It does
//      NOT unregister the audit.registerGlobal("healthbar", ...) opener:
//      audit.mjs has no unregisterGlobal, and per this file's own original
//      comment healthbar is meant to be a session-lived global surface (like
//      palette) — the opener already no-ops on a detached rail
//      (`if (!rail.isConnected) return;`), so a stale registration after
//      destroy() is harmless, not a leak.
//   3. SIEM light comment (item 4 below): the mockup called the <95%
//      escalation "DESIGN-ADDED (no source backing)" — a note for reviewers
//      comparing the mockup against production. In v2 this is no longer a
//      mockup annotation to justify; it is a shipped product decision. The
//      escalation itself is UNCHANGED (still <95% -> at least warn) — only
//      the comment's framing changed, from "here is where the mockup
//      diverges from the source" to "here is why v2 alerts on this".
//
// The tone of every light other than #4 is transcribed from the shipping GUI
// so the mockup/v2 cannot invent a nicer reality than the product shows:
//
//  1 Daemon/排程  src/static/js/integrations.js:1502-1539 (_buildOvJobHealth)
//                 comment 1502-1503: level error = 上次失敗, warn = 從未跑或逾期,
//                 ok = 正常; 1508-1510 maps level -> danger/warning/success;
//                 1513-1515 appends "overdue" for warn rows that did run.
//  2 PCE          pce_stats.health_status/health_category are the control-plane
//                 signal. event_poll_status and ingestion failures belong to the
//                 pipeline lights below, so a successful /noop remains green when
//                 a fresh events/traffic watermark reports last_status=error.
//                 Raw/sticky last_error text is deliberately not rendered; the
//                 normalized category supplies the operator-facing reason.
//  3 Cache lag    cache_lag rows use both time-based level and the latest ingest
//                 status. last_status=error wins even when the failure just bumped
//                 the watermark and the measured lag is still small.
//  4 SIEM         integrations.js:1406-1410 (_buildOvPipelineHealth) — verdict
//                 ok/warn/error -> card-ok/card-warn/card-err; 1427-1428
//                 (_buildOvCards) — dlq > 0 renders card-warn. v2 PRODUCT
//                 DECISION: siem_success_1h < 95 also escalates the rail's
//                 tone to at least warn. The source data only carries this
//                 threshold as a reason string (_pipelineReasons, 1399-1401)
//                 and colours the shipping card by verdict alone — v2 lets it
//                 move the LED deliberately, because a light that stays green
//                 while one dispatch in twenty fails is not doing its job.
//  5 告警管道      integrations.js:1650/1660/1667/1671 (_buildAlertChannelCards) —
//                 configured -> 'ok' chip, otherwise 'muted'; 1474
//                 (_buildOvRecentTable) — a dispatch with failures is danger.
//
// Data in: store.load("status") + store.load("dashboard_overview").

import { t, tf } from "../core/i18n.mjs";
import { dur, since, tone, worst, atLeast } from "../core/fmt.mjs";

class Light {
  constructor(id, label, route) {
    this.id = id;
    this.label = label;
    this.route = route;
    this.tone = "neutral";
    this.value = "—";
    this.summary = "";
    this.reasons = [];
  }
  set(tn, value, summary) {
    this.tone = tn;
    this.value = value;
    this.summary = summary;
    return this;
  }
}

// ── 1 · Daemon / 排程 ────────────────────────────────────────────────────────
function jobsLight(ov) {
  const light = new Light("jobs", t("gui_ov_job_health"), "#/system/jobs");
  const jobs = (ov && ov.job_health) || [];
  const bad = jobs.filter(function (j) { return j.level !== "ok"; });
  const okCount = jobs.length - bad.length;
  const tn = bad.length ? worst(bad.map(function (j) { return j.level; })) : (jobs.length ? "ok" : "neutral");

  bad.forEach(function (j) {
    const status = j.level === "warn" && j.last_run
      ? (j.last_status || "") + " · " + t("gui_jh_overdue")
      : (j.last_status || t("gui_jh_never_ran"));
    light.reasons.push(tf("gui_health_job_line", {
      job: j.job_id,
      status: status,
      interval: dur(j.interval_seconds),
      age: j.last_run ? since(j.last_run, ov.as_of) : "—",
    }));
  });
  if (!bad.length) light.reasons.push(tf("gui_health_jobs_ok", { ok: okCount, total: jobs.length }));

  return light.set(tn, okCount + "/" + jobs.length,
    t("gui_jh_overdue") + " " + bad.length + " · " + t("gui_jh_th_last_run") + " "
    + (jobs.length ? since(jobs[0].last_run, ov.as_of) : "—"));
}

// ── 2 · PCE ─────────────────────────────────────────────────────────────────
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

function pceCategoryReason(p) {
  const category = String((p && p.health_category) || "unknown").toLowerCase();
  if (category === "auth_failed") return t("gui_health_pce_auth_failed");
  if (category === "authorization_failed") return t("gui_health_pce_authorization_failed");
  if (category === "transport_error") return t("gui_health_pce_unreachable");
  if (category === "rate_limited") return t("gui_health_pce_rate_limited");
  if (category === "server_error") return t("gui_health_pce_server_error");
  if (["warning", "degraded", "error", "critical"].indexOf(category) >= 0) {
    return tf("gui_health_pce_reported_status", { status: category });
  }
  if (category !== "ok" && category !== "unknown") {
    return tf("gui_health_pce_http_error", { status: p.last_error_status || "—" });
  }
  return "";
}

function pceControlTone(p) {
  const category = String((p && p.health_category) || "unknown").toLowerCase();
  const health = String((p && p.health_status) || "unknown").toLowerCase();
  if (["auth_failed", "authorization_failed", "transport_error", "server_error"].indexOf(category) >= 0) return "crit";
  if (["rate_limited", "http_error"].indexOf(category) >= 0) return "warn";
  if (["error", "critical"].indexOf(category) >= 0) return "crit";
  if (["warning", "degraded"].indexOf(category) >= 0) return "warn";
  if (health === "error" || health === "critical") return "crit";
  if (health === "warning" || health === "degraded") return "warn";
  if (category === "ok" || health === "ok") return "ok";
  return "neutral";
}

function pceLight(st, ov) {
  const light = new Light("pce", t("gui_dashboard_pce_health"), "#/system/pce");
  const p = (st && st.pce_stats) || {};
  const health = String(p.health_status || "unknown").toLowerCase();
  const failures = Number(p.consecutive_failures) || 0;
  const healthFailure = failures > 0 && (p.last_error_stage === "health" || health !== "ok");
  const deployment = (st && st.deployment_type) || p.deployment_type || "on_prem";
  const probe = healthProbeLabel((st && st.health_probe) || p.health_probe);
  const probeLine = tf("gui_health_pce_probe", {
    deployment: deploymentLabel(deployment),
    probe: probe,
  });
  const categoryLine = pceCategoryReason(p);
  const tn = pceControlTone(p);
  const readout = healthFailure ? "×" + failures : health.toUpperCase();
  let summary = probeLine;

  light.reasons.push(probeLine);
  if (categoryLine) {
    light.reasons.push(categoryLine);
    summary = categoryLine;
  }
  if (healthFailure) {
    const line = tf("gui_health_pce_failures", { n: failures, stage: p.last_error_stage || "—" });
    light.reasons.push(line);
    summary = line;
  }
  if (p.last_success) {
    light.reasons.push(tf("gui_health_pce_last_success", { age: since(p.last_success, ov && ov.as_of) }));
  }
  return light.set(tn, readout, summary);
}

// ── 3 · Cache lag ───────────────────────────────────────────────────────────
function lagLight(ov) {
  const light = new Light("lag", t("gui_ov_cache_lag_label"), "#/system/cache");
  const lags = (ov && ov.pipeline && ov.pipeline.cache_lag) || [];
  const maxLag = lags.reduce(function (m, l) { return Math.max(m, Number(l.lag_s) || 0); }, 0);

  lags.forEach(function (l) {
    if (l.last_status === "error") {
      light.reasons.push(tf("gui_health_source_failed", { source: l.source }));
    } else if (l.level === "error" || l.level === "warning") {
      light.reasons.push(tf("gui_pl_reason_lag", { source: l.source, hours: Math.round((Number(l.lag_s) || 0) / 3600) }));
    } else {
      light.reasons.push(tf("gui_health_source_freshness", {
        source: l.source, status: l.last_status || "—", age: dur(l.lag_s),
      }));
    }
  });
  if (!lags.length) light.reasons.push(t("gui_health_clear"));

  const lagTones = lags.map(function (l) { return l.last_status === "error" ? "crit" : l.level; });
  return light.set(lags.length ? worst(lagTones) : "neutral",
    dur(maxLag),
    lags.map(function (l) { return l.source + " " + dur(l.lag_s); }).join(" · "));
}

// ── 4 · SIEM / pipeline ─────────────────────────────────────────────────────
function siemLight(ov) {
  const light = new Light("siem", t("gui_ov_pipeline_title"), "#/system/siem");
  const p = (ov && ov.pipeline) || {};
  let tn = p.verdict === undefined ? "neutral" : tone(p.verdict);
  const pct = p.siem_success_1h;

  // v2 product decision (see the header note) — the source only reports this
  // threshold as text; the rail lets it move the LED.
  if (pct !== null && pct !== undefined && Number(pct) < 95) {
    tn = atLeast(tn, "warn");
    light.reasons.push(tf("gui_pl_reason_siem", { pct: pct }));
  }
  // Source-backed: _buildOvCards renders card-warn for a non-empty DLQ.
  if (Number(p.dlq) > 0) {
    tn = atLeast(tn, "warn");
    light.reasons.push(tf("gui_pl_reason_dlq", { n: p.dlq }));
  }
  light.reasons.push(tf("gui_health_siem_queue", {
    state: p.siem_idle ? t("gui_health_queue_idle") : t("gui_health_queue_active"),
  }));

  return light.set(tn,
    (pct === null || pct === undefined ? "—" : pct + "%"),
    t("gui_ov_dlq") + " " + (Number(p.dlq) || 0) + " · " + (p.siem_idle ? t("gui_health_queue_idle") : t("gui_health_queue_active")));
}

// ── 5 · 告警管道 ─────────────────────────────────────────────────────────────
function channelsLight(st) {
  const light = new Light("channels", t("gui_ov_alert_channels"), "#/system/channels");
  const chans = (st && st.alert_channels) || [];
  const live = chans.filter(function (c) { return c.enabled && c.configured; });
  const failed = live.filter(function (c) { return c.last_status && c.last_status !== "success"; });

  failed.forEach(function (c) {
    light.reasons.push(tf("gui_health_chan_fail", { name: c.display_name || c.name, status: c.last_status }));
  });
  light.reasons.push(tf("gui_health_chan_live", { live: live.length, total: chans.length }));

  return light.set(failed.length ? "crit" : (live.length ? "ok" : "neutral"),
    live.length + "/" + chans.length,
    live.map(function (c) { return c.display_name || c.name; }).join(" · ") || t("gui_health_clear"));
}

export function computeLights(statusSnap, overviewSnap) {
  return [
    jobsLight(overviewSnap),
    pceLight(statusSnap, overviewSnap),
    lagLight(overviewSnap),
    siemLight(overviewSnap),
    channelsLight(statusSnap),
  ];
}

// v3.1 (spec §2) deleted this module's rendering half. The five-light rail
// it drew was chrome that only ever belonged on one route, and its popover
// printed a route as link text (§5.2). areas/home.mjs now renders the same
// lights — plus VEN — as the home page's first side card, with each light's
// reasons behind its own disclosure. What is left here is the computation:
// which lights exist, what tone each one is, and why.
