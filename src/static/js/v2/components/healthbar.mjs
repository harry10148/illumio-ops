// healthbar.mjs — XC-01. Five lights across the instrument rail.
//
// Scope: the overview only (spec §1.1, amended at Gate 2 — it used to sit in
// the chrome on every route). The area that mounts this owns the
// attach/detach (app.mjs's syncRail pattern, T2); this module just renders
// the rail and keeps its audit opener quiet while detached.
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
//  2 PCE          src/static/js/dashboard.js:1338-1346 — event_poll_status:
//                 'ok' -> ok, 'warn'|'degraded' -> warn, any other non-empty and
//                 non-'unknown' -> err, else unknown. One escalation, also
//                 source-backed: pce_stats.consecutive_failures > 0 is the
//                 watchdog's failure counter (src/analyzer.py:602, 1137) -> crit.
//                 pce_stats.last_error must NOT drive the tone: src/events/stats.py
//                 record_pce_success (65-88) never clears it, so it is a sticky
//                 field with no timestamp — a probe that succeeded a second ago
//                 still carries last week's error. It is shown as a reason, and
//                 labelled as sticky, so nobody reads it as "now".
//  3 Cache lag    integrations.js:1391-1398 (_pipelineReasons) — cache_lag rows
//                 with level 'error'|'warning' produce gui_pl_reason_lag, hours =
//                 round(lag_s/3600). Worst row wins.
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

import { el, spacer, dismissible } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { dur, since, stamp, tone, worst, atLeast, firstLine } from "../core/fmt.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";

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
  const light = new Light("jobs", t("gui_ov_job_health"), "#/automation/jobs");
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
function pceLight(st, ov) {
  const light = new Light("pce", t("gui_dashboard_pce_health"), "#/system/pce");
  const p = (st && st.pce_stats) || {};
  const polled = String(p.event_poll_status || "unknown").toLowerCase();
  const failures = Number(p.consecutive_failures) || 0;

  let tn = "neutral";
  if (polled === "ok") tn = "ok";
  else if (polled === "warn" || polled === "degraded") tn = "warn";
  else if (polled && polled !== "unknown") tn = "crit";
  if (failures > 0) tn = "crit";

  // The readout must state whatever drove the LED. A health-stage failure leaves
  // event_poll_status at "ok" while raising consecutive_failures (stats.py
  // record_pce_error, 113-126), so showing "OK" next to a red LED would be a lie:
  // the failure count takes the readout whenever it is what escalated the tone.
  const readout = failures > 0 ? "×" + failures : polled.toUpperCase();
  let summary = t("gui_jh_th_last_run") + " " + since(p.last_success, ov && ov.as_of);

  if (failures > 0) {
    const line = tf("gui_health_pce_failures", { n: failures, stage: p.last_error_stage || "—" });
    light.reasons.push(line);
    summary = line;
  }
  if (p.last_success) {
    light.reasons.push(tf("gui_health_pce_last_success", { age: since(p.last_success, ov && ov.as_of) }));
  }
  if (p.last_error) {
    light.reasons.push(tf("gui_health_pce_last_error", {
      stage: p.last_error_stage || "—",
      message: firstLine(p.last_error, 120),
    }));
    light.reasons.push(t("gui_health_pce_sticky"));
  }
  if (!light.reasons.length) light.reasons.push(t("gui_health_clear"));

  return light.set(tn, readout, summary);
}

// ── 3 · Cache lag ───────────────────────────────────────────────────────────
function lagLight(ov) {
  const light = new Light("lag", t("gui_ov_cache_lag_label"), "#/system/cache");
  const lags = (ov && ov.pipeline && ov.pipeline.cache_lag) || [];
  const maxLag = lags.reduce(function (m, l) { return Math.max(m, Number(l.lag_s) || 0); }, 0);

  lags.forEach(function (l) {
    if (l.level === "error" || l.level === "warning") {
      light.reasons.push(tf("gui_pl_reason_lag", { source: l.source, hours: Math.round((Number(l.lag_s) || 0) / 3600) }));
    } else {
      light.reasons.push(tf("gui_health_lag_line", { source: l.source, age: dur(l.lag_s) }));
    }
  });
  if (!lags.length) light.reasons.push(t("gui_health_clear"));

  return light.set(lags.length ? worst(lags.map(function (l) { return l.level; })) : "neutral",
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

// ── rendering ───────────────────────────────────────────────────────────────
function buildPopover(light, close) {
  const pop = el("div", { class: "popover rail-pop", "data-tone": light.tone, role: "dialog" },
    el("h4", { text: light.label + " · " + t("gui_health_reasons") }),
    el("ul", null, light.reasons.map(function (r) {
      return el("li", null, el("span", { class: "dot" }), el("span", { text: r }));
    })),
    el("div", { class: "pop-foot" },
      el("button", {
        class: "btn link",
        type: "button",
        text: t("gui_health_goto") + " " + light.route,
        onClick: function () { close(); router.go(light.route); },
      }),
      spacer(),
      el("button", { class: "btn ghost", type: "button", text: t("gui_close"), onClick: close })
    )
  );
  return pop;
}

function buildSlot(light, closeOthers) {
  const slot = el("div", { class: "rail-slot" });
  const cell = el("button", {
    class: "rail-cell",
    type: "button",
    "data-tone": light.tone,
    "aria-expanded": "false",
  },
    el("span", { class: "k" }, el("span", { class: "led" }), el("span", { text: light.label })),
    el("span", { class: "v", text: light.value }),
    el("span", { class: "d", title: light.summary, text: light.summary }),
    el("span", { class: "ul" })
  );
  slot.appendChild(cell);

  let pop = null;
  let dispose = null;

  function close() {
    if (!pop) return;
    dispose();
    dispose = null;
    slot.removeChild(pop);
    pop = null;
    cell.setAttribute("aria-expanded", "false");
  }

  function open(exclusive) {
    if (pop) return;                 // idempotent — __openAllForAudit may re-enter
    if (exclusive) closeOthers(close);
    pop = buildPopover(light, close);
    slot.appendChild(pop);
    cell.setAttribute("aria-expanded", "true");
    dispose = dismissible(pop, close);
  }

  cell.addEventListener("click", function () { if (pop) close(); else open(true); });
  return { slot: slot, open: open, close: close };
}

export const healthbar = {
  /** render(statusSnap, overviewSnap) -> HTMLElement (the whole rail, XC-01), with a .destroy() attached (see header note 2). */
  render(statusSnap, overviewSnap) {
    const lights = computeLights(statusSnap, overviewSnap);
    const rail = el("div", { class: "rail", "data-cov": "XC-01", role: "group", "aria-label": t("gui_ov_pipeline_health") });
    const handles = [];

    lights.forEach(function (light) {
      const h = buildSlot(light, function (keep) {
        handles.forEach(function (other) { if (other.close !== keep) other.close(); });
      });
      handles.push(h);
      rail.appendChild(h.slot);
    });

    const asOf = (overviewSnap && overviewSnap.as_of) || "";
    rail.appendChild(el("div", { class: "railmeta" },
      el("span", null, t("gui_ov_as_of") + " ", el("b", { class: "mono", text: stamp(asOf) })),
      el("span", { class: "mono", text: (statusSnap && statusSnap.timezone) || "" })
    ));

    // Every light's popover carries reasons the gate must be able to see.
    // The opener stays global (the rail outlives any single mount) but no-ops
    // while the rail is detached — the area only attaches this on #/overview,
    // and opening popovers in a detached tree would inflate the audit's
    // "opened" count on every other route for surfaces nobody can see.
    audit.registerGlobal("healthbar", function () {
      if (!rail.isConnected) return;
      handles.forEach(function (h) { h.open(false); });
    });

    // Teardown contract: destroy() closes any open popover. It deliberately
    // does not unregister the audit opener above — see header note 2.
    rail.destroy = function () {
      handles.forEach(function (h) { h.close(); });
    };

    return rail;
  },

  /** mount(host, statusSnap, overviewSnap) — replaces host's contents. Returns the rail (see render()). */
  mount(host, statusSnap, overviewSnap) {
    const rail = this.render(statusSnap, overviewSnap);
    while (host.firstChild) host.removeChild(host.firstChild);
    host.appendChild(rail);
    return rail;
  },
};
