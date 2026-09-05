// home.mjs — #/home. Anchors HM-00..HM-03, HM-05, XC-10 (error card).
//
// Spec v3.1 §2: the home page answers one question — "is there anything I
// need to do right now" — so the RECENT ALERTS are the page and everything
// else is background. 3B answered five questions with five equal panels in a
// board; this is one list with three quiet cards beside it.
//
// What v3.1 removed, and why each is not a loss:
//   · the five-light health rail (XC-01). It was chrome on one route; its six
//     lamps and their reasons are the first side card now.
//   · the 7-day traffic-decision band (HM-04). It belongs on the page that
//     can act on it — traffic search — not on a page nobody queries from.
//   · the posture DETAIL drawer (OV-02). The score survives as one line in
//     the policy card; the breakdown lives in the reports area.
//
// Data: four GET snapshots plus /api/alerts, all already served — no new
// endpoint (spec §4).

import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { t, tf } from "../core/i18n.mjs";
import { el, clear } from "../core/dom.mjs";
import { num, tone } from "../core/fmt.mjs";
import { drawer } from "../components/drawer.mjs";
import { palette } from "../components/palette.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { computeLights } from "../components/healthbar.mjs";
import { audit } from "../core/audit.mjs";
import { pageHead, sideCard, listRow, listFoot, chip } from "../components/page.mjs";
import { note, emptyState, loadOne } from "./cards.mjs";

const ROUTE = "#/home";
const GO_ALERTS = "#/investigate/alerts";
const GO_TRAFFIC = "#/investigate/traffic";
const GO_SCHEDULES = "#/policy/schedules";
const GO_REPORT_SCHEDULES = "#/reports/schedules";
const GO_JOBS = "#/system/jobs";
const GO_REPORTS = "#/reports";
const GO_ALERT_RULES = "#/policy/alert-rules";
const GO_PCE = "#/system/pce";
const GO_CACHE = "#/system/cache";

const SNAPS = ["status", "dashboard_overview", "rs_schedules", "report_schedules"];
// spec §2: the list shows the ten most recent, with an unhandled/all switch.
const LIST_SIZE = 10;

// static keys so the i18n audit can see them (a concatenated key is invisible to it)
const STATUS_LABEL = { new: "gui_alert_status_new", ack: "gui_alert_status_ack", done: "gui_alert_status_done" };
const SEVERITY_RANK = { critical: 0, error: 1, warning: 2, warn: 2, info: 3 };

function severityTone(sev) {
  const s = String(sev || "").toLowerCase();
  if (s === "critical" || s === "error") return "crit";
  if (s === "warning" || s === "warn") return "warn";
  return "info";
}
function statusTone(status) { return status === "done" ? "ok" : status === "ack" ? "info" : "warn"; }
function statusText(status) { return t(STATUS_LABEL[status] || "gui_alert_status_new"); }

function hhmm(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "—";
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}
function day(iso) {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}
/** The summary minus the rule name it opens with — the row already has it. */
function summaryTail(a) {
  const summary = String(a.summary || "");
  const rule = String(a.rule_name || "");
  if (rule && summary.indexOf(rule) === 0) {
    return summary.slice(rule.length).replace(/^\s*[·|,-]\s*/, "");
  }
  return summary;
}

function loadAll(status) {
  return Promise.all(SNAPS.map(loadOne).concat([
    api.load("alerts", { status: status, page: 1, page_size: LIST_SIZE }).catch(function (e) {
      console.error("[home] alerts failed to load", e);
      return { ok: false, error: String((e && e.message) || e) };
    }),
  ])).then(function (list) {
    const out = {};
    SNAPS.forEach(function (id, i) { out[id] = list[i]; });
    out.alerts = list[SNAPS.length];
    return out;
  });
}

// ── HM-06 the four instruments ──────────────────────────────────────────────

/* The dashboard strip the operator asked for. Every figure comes from the
 * `dashboard_overview` snapshot the page already loads for its health lights,
 * so this adds no request — the endpoint has been answering all along and
 * nothing in the v3 GUI was reading these four branches of it.
 *
 * A cell is an <a>, not a <div>: a number with no way through to the page that
 * explains it is a dead end, and each of these four has an obvious owner.
 *
 * "Flagged" and not "Blocked": the figure is blocked + potentially-blocked,
 * and `Blocked` is a glossary term with a fixed meaning, so naming this one
 * after it would be wrong twice over.
 */
function kpiCell(labelText, value, detailText, tn, route) {
  return el("a", { class: "kpicell", href: route, "data-tone": tn || "neutral" },
    el("span", { class: "k", text: labelText }),
    el("span", { class: "v", text: value }),
    el("span", { class: "d", title: detailText, text: detailText }));
}

/** ok / warn / error from the API, plus the two "cannot say" branches it
 *  returns when the cache is off or a panel threw. */
function verdictText(verdict) {
  const v = String(verdict || "");
  if (v === "no_cache") return t("gui_home_kpi_no_cache");
  if (v === "ok") return t("gui_home_verdict_ok");
  if (v === "warn") return t("gui_home_verdict_warn");
  if (v === "error") return t("gui_home_verdict_error");
  return t("gui_home_verdict_unknown");
}

/** True when the panel could not be computed at all — then the cell shows a
 *  dash and says why, rather than a zero that reads like a measurement. */
function unavailable(panel) {
  const v = String((panel || {}).verdict || "");
  return v === "no_cache" || v === "unknown" || !Object.keys(panel || {}).length;
}

function kpiStrip(ov) {
  const ven = (ov && ov.ven) || {};
  const flagged = (ov && ov.blocked) || {};
  const pipe = (ov && ov.pipeline) || {};
  const alerts = (ov && ov.alerts) || {};

  const venOff = Number(ven.offline || 0);
  const venCell = kpiCell(
    t("gui_home_kpi_ven"),
    ven.total === undefined ? "—" : num(ven.online || 0) + "/" + num(ven.total || 0),
    ven.total === undefined ? verdictText(ven.verdict) : tf("gui_home_kpi_ven_d", { n: num(venOff) }),
    ven.total === undefined ? "neutral" : tone(ven.verdict),
    GO_PCE);

  const flagCell = kpiCell(
    t("gui_home_kpi_flagged"),
    unavailable(flagged) ? "—" : num(flagged.flagged || 0),
    unavailable(flagged)
      ? verdictText(flagged.verdict)
      : tf("gui_home_kpi_flagged_d", { days: num(flagged.window_days || 7), pct: num(flagged.vs_prev_pct || 0) }),
    unavailable(flagged) ? "neutral" : tone(flagged.verdict),
    GO_TRAFFIC);

  const pipeCell = kpiCell(
    t("gui_home_kpi_pipeline"),
    verdictText(pipe.verdict),
    unavailable(pipe)
      ? t("gui_home_kpi_pipeline_off")
      : tf("gui_home_kpi_pipeline_d", { pct: String(pipe.siem_success_1h === undefined ? 0 : pipe.siem_success_1h), dlq: num(pipe.dlq || 0) }),
    unavailable(pipe) ? "neutral" : tone(pipe.verdict),
    GO_CACHE);

  const alertCell = kpiCell(
    t("gui_home_kpi_alerts"),
    num(alerts.fired_24h || 0),
    tf("gui_home_kpi_alerts_d", { failed: num(alerts.failed || 0), suppressed: num(alerts.suppressed || 0) }),
    tone(alerts.verdict),
    GO_ALERTS);

  return el("div", { class: "kpirow", "data-cov": "HM-06" }, venCell, flagCell, pipeCell, alertCell);
}

// ── HM-01 the recent alerts ─────────────────────────────────────────────────

function alertList(alerts, state, repaint) {
  const wrap = el("section", { class: "sect", "data-cov": "HM-01" });
  const head = el("div", { class: "sect-head" },
    el("h3", { text: t("gui_home_recent") }));

  const filters = el("div", { class: "seg" });
  [["new", "gui_home_filter_open"], ["", "gui_home_filter_all"]].forEach(function (pair) {
    filters.appendChild(el("button", {
      type: "button", text: t(pair[1]), "data-status": pair[0] || "all",
      "aria-pressed": state.status === pair[0] ? "true" : "false",
      onClick: function () { state.status = pair[0]; repaint(); },
    }));
  });
  head.appendChild(filters);
  head.appendChild(el("a", { class: "seeall", href: GO_ALERTS, text: t("gui_home_see_all") }));
  wrap.appendChild(head);

  if (!alerts || alerts.ok === false) {
    wrap.setAttribute("data-tone", "warn");
    wrap.appendChild(note(tf("error_generic", { error: (alerts && alerts.error) || "—" })));
    return wrap;
  }
  const items = (alerts.items || []).slice().sort(function (a, b) {
    return (SEVERITY_RANK[String(a.severity).toLowerCase()] ?? 9) - (SEVERITY_RANK[String(b.severity).toLowerCase()] ?? 9);
  });
  if (!items.length) {
    wrap.setAttribute("data-tone", "ok");
    wrap.appendChild(emptyState(t("gui_home_no_open_alerts"), GO_ALERTS, t("gui_home_go_alerts")));
    return wrap;
  }
  const list = el("div", { class: "list" });
  items.forEach(function (a) {
    list.appendChild(listRow({
      href: GO_ALERTS + "?id=" + encodeURIComponent(a.id),
      tone: severityTone(a.severity),
      when: { main: hhmm(a.fired_at), sub: day(a.fired_at) },
      title: a.rule_name || "—",
      sub: summaryTail(a),
      status: chip(statusText(a.status), statusTone(a.status)),
    }));
  });
  wrap.appendChild(list);
  const counts = alerts.counts || {};
  wrap.appendChild(listFoot(
    tf("gui_home_recent_foot", { total: num(alerts.total || items.length), done: num(counts.done || 0) }),
    el("a", { href: GO_ALERT_RULES, text: t("gui_al_manage_rules") })
  ));
  wrap.setAttribute("data-tone", items.some(function (a) { return severityTone(a.severity) === "crit"; }) ? "crit" : "warn");
  return wrap;
}

// ── HM-02 system health ─────────────────────────────────────────────────────

/**
 * Six lamps, a sentence each, and the reasons one click away.
 *
 * The rail this replaces put its reasons in a popover, and four e2e tests
 * read them: an authentication failure has to be distinguishable from an
 * unreachable PCE, and the probe chain has to be visible. "六燈＋每燈一句"
 * (spec §2) is the resting state, not a decision to throw the diagnosis away,
 * so each lamp is a <details> whose summary is the sentence.
 */
function healthCard(st, ov) {
  const lights = computeLights(st || {}, ov || {});
  const ven = (ov && ov.ven) || {};
  const rows = lights.map(function (l) {
    return { label: l.label, tone: l.tone, line: l.summary || l.value, reasons: l.reasons || [], route: l.route };
  });
  rows.push({
    label: t("gui_home_ven"),
    tone: ven.verdict === "ok" ? "ok" : (ven.verdict ? "warn" : "neutral"),
    line: ven.total !== undefined ? tf("gui_home_ven_summary", { online: num(ven.online || 0), total: num(ven.total || 0) }) : "—",
    reasons: [],
    route: GO_PCE,
  });

  const box = el("div", { class: "lamps" });
  rows.forEach(function (r) {
    const body = el("div", { class: "lamp-why" });
    r.reasons.forEach(function (reason) { body.appendChild(el("p", { text: reason })); });
    body.appendChild(el("a", { href: r.route, text: t("gui_home_health_open") }));
    box.appendChild(el("details", { class: "lamp", "data-tone": r.tone },
      el("summary", null,
        el("i", { class: "dot", "aria-hidden": "true" }),
        el("span", null, el("b", { text: r.label }), el("small", { text: r.line || "—" }))),
      body));
  });

  const bad = rows.filter(function (r) { return r.tone === "crit" || r.tone === "warn"; });
  const card = sideCard(t("gui_home_health"), box);
  card.setAttribute("data-cov", "HM-02");
  card.setAttribute("data-tone", bad.some(function (r) { return r.tone === "crit"; }) ? "crit" : (bad.length ? "warn" : "ok"));
  return { el: card, bad: bad };
}

// ── HM-03 today's schedule ──────────────────────────────────────────────────

function todayLocal(iso) {
  if (!iso) return false;
  const d = new Date(iso);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

function todayCard(rs, reportSched, ov) {
  const items = [];
  (Array.isArray(rs) ? rs : []).forEach(function (s) {
    if (!s || s.live_enabled === false) return;
    if (s.schedule_type === "one_time" || s.type === "one_time") {
      if (todayLocal(s.expire_at)) items.push({ when: hhmm(s.expire_at), sort: s.expire_at, text: tf("gui_home_today_rule_expire", { name: s.name || s.detail_name || "—" }), route: GO_SCHEDULES, tone: "info" });
      return;
    }
    /* 3B marked a schedule whose last run errored; the v3.1 rewrite of this
     * card dropped the mark, so a failed schedule read exactly like a healthy
     * one on the page an operator looks at first. Restored with the mapping 3B
     * used — and with a WORD, because §5.2 does not let a colour carry a
     * status on its own. */
    if (s.start) items.push({ when: s.start, sort: "T" + s.start, text: tf("gui_home_today_rule_start", { name: s.name || "—", action: s.action || "" }), route: GO_SCHEDULES, tone: s.last_result === "error" ? "warn" : "info" });
    if (s.end) items.push({ when: s.end, sort: "T" + s.end, text: tf("gui_home_today_rule_end", { name: s.name || "—" }), route: GO_SCHEDULES, tone: "info" });
  });
  (Array.isArray(reportSched) ? reportSched : []).forEach(function (r) {
    if (!r || r.enabled === false || !r.next_run) return;
    if (todayLocal(r.next_run)) items.push({ when: hhmm(r.next_run), sort: r.next_run, text: tf("gui_home_today_report", { name: r.name || r.report_type || "—" }), route: GO_REPORT_SCHEDULES, tone: "info" });
  });
  ((ov && ov.job_health) || []).forEach(function (j) {
    if (!j || !/retention|archive/.test(String(j.job_id || ""))) return;
    if (!j.last_run || !j.interval_seconds) return;
    const next = new Date(new Date(j.last_run).getTime() + j.interval_seconds * 1000);
    if (todayLocal(next.toISOString())) items.push({ when: hhmm(next.toISOString()), sort: next.toISOString(), text: tf("gui_home_today_job", { job: j.job_id }), route: GO_JOBS, tone: j.level === "error" ? "warn" : "info" });
  });
  items.sort(function (a, b) { return String(a.sort).localeCompare(String(b.sort)); });

  const body = items.length
    ? el("ul", { class: "sched" }, items.slice(0, 6).map(function (it) {
      return el("li", { "data-tone": it.tone || "info" },
        el("b", { text: it.when }),
        el("a", { href: it.route, text: it.text }),
        it.tone === "warn" ? el("small", { text: t("gui_home_today_last_failed") }) : null);
    }))
    : el("p", { class: "note" }, el("span", { text: t("gui_home_today_empty") }));
  const card = sideCard(t("gui_home_today"), body);
  card.setAttribute("data-cov", "HM-03");
  return card;
}

// ── HM-05 policy, right now ─────────────────────────────────────────────────

/**
 * What the policy looks like today, in three lines.
 *
 * Spec §2 asked for provision COUNT and ruleset DELTA over seven days. The
 * backend serves neither, and §4 rules out adding an endpoint in this
 * revision — so this shows the three policy figures the appliance really has
 * (posture score, how many rulesets there are, how many workloads are being
 * enforced) rather than inventing a movement nobody measured.
 */
function policyCard(ov) {
  const posture = (ov && ov.posture) || {};
  const enforcement = (ov && ov.enforcement) || {};
  const modes = enforcement.by_mode || {};
  const enforced = Number(modes.full || 0) + Number(modes.selective || 0);
  const rulesets = el("b", { text: "—" });
  const box = el("div", { class: "kv-list" },
    el("div", { class: "kv" },
      el("span", { text: t("gui_ov_posture_score_label") }),
      el("b", { text: posture.available && posture.score !== undefined ? num(posture.score) + "/100" : "—" })),
    el("div", { class: "kv" },
      el("span", { text: t("gui_home_policy_enforced") }),
      el("b", { text: enforcement.total ? tf("gui_home_policy_enforced_n", { n: num(enforced), total: num(enforcement.total) }) : "—" })),
    el("div", { class: "kv" }, el("span", { text: t("gui_home_policy_rulesets") }), rulesets),
    el("a", { class: "cardlink", href: GO_REPORTS, text: t("gui_home_policy_reports") }));
  const card = sideCard(t("gui_home_policy_week"), box);
  card.setAttribute("data-cov", "HM-05");
  card.rulesets = rulesets;
  return card;
}

/** Ruleset count comes from its own endpoint, so it lands after the card. */
function fillRulesets(card, state) {
  // size: 1 — this needs `total`, not the rulesets, and the server does a
  // per-ruleset schedule lookup for every item it serialises.
  api.load("rs_rulesets", { page: 1, size: 1 }).then(function (d) {
    if (state.torn || !card.rulesets) return;
    const total = d && d.total;
    card.rulesets.textContent = total === undefined || total === null ? "—" : num(total);
  }).catch(function (e) {
    if (state.torn) return;
    console.error("[home] ruleset count failed to load", e);
  });
}

// ── mount ───────────────────────────────────────────────────────────────────

/** S2 — teardown is registered before the first await (tests/test_v2_teardown_registration.py). */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    drawer.closeAll();
    palette.setRoute(path);
  });
}

export async function mountHome(root, ctx) {
  const state = { torn: false, status: "new" };
  installTeardown(state);
  const probe = el("div", { class: "ov-error-probe" });
  audit.register("home-error-card", function () {
    if (probe.firstChild) return;
    root.appendChild(probe);
    withErrorCard(probe, "__audit_unavailable__",
      function () { return api.load("__audit_unavailable__"); },
      function () { });
  });
  audit.register("home-health-why", function () {
    root.querySelectorAll("details.lamp").forEach(function (d) { d.open = true; });
  });
  palette.registerFor(ROUTE, {
    id: "home:alerts", label: t("gui_home_go_alerts"), group: t("gui_cmd_group_area"),
    run: function () { router.go(GO_ALERTS); },
  });
  palette.registerFor(ROUTE, {
    id: "home:traffic", label: t("gui_home_go_traffic"), group: t("gui_cmd_group_area"),
    run: function () { router.go(GO_TRAFFIC); },
  });

  const head = pageHead({
    route: ROUTE,
    title: t("gui_home_loading"),
    actions: [
      el("button", { class: "btn", type: "button", text: t("gui_home_go_traffic"), onClick: function () { router.go(GO_TRAFFIC); } }),
      el("button", { class: "btn primary", type: "button", text: t("gui_home_go_reports"), onClick: function () { router.go(GO_REPORTS); } }),
    ],
  });
  root.appendChild(head);
  const body = el("div", { class: "home" });
  root.appendChild(body);

  async function paint() {
    if (state.torn) return;
    clear(body);
    await withErrorCard(body, "home (" + (SNAPS.length + 1) + ")", function () { return loadAll(state.status); }, function (d) {
      if (ctx.stale() || state.torn) return;
      const st = d.status || {};
      const ov = d.dashboard_overview || {};
      const counts = (d.alerts && d.alerts.counts) || {};
      const open = counts.new || 0;
      const health = healthCard(st, ov);

      // spec §2: the title is the page's whole answer — how many alerts are
      // still open, and how many lights are not green.
      const h2 = head.querySelector("h2");
      if (h2) {
        clear(h2);
        // spec §2's own example sentence: "{n} 件告警還沒處理，系統有 {m}
        // 項要看一下". The count is its own node so HM-00 has something to
        // anchor to and the number can carry the accent on its own.
        h2.appendChild(el("b", { class: "hot", "data-cov": "HM-00", text: tf("gui_home_headline_count", { n: num(open) }) }));
        h2.appendChild(el("span", { text: " " + tf("gui_home_headline_health", { m: num(health.bad.length) }) }));
      }
      const text = head.querySelector(".phead-text");
      const oldSub = text.querySelector("p");
      const sub = el("p", { text: t("gui_home_sub") });
      if (oldSub) text.replaceChild(sub, oldSub); else text.appendChild(sub);

      const policy = policyCard(ov);
      const main = el("div", { class: "home-main" }, alertList(d.alerts, state, paint));
      body.appendChild(kpiStrip(ov));
      const side = el("aside", { class: "home-side" },
        health.el,
        todayCard(d.rs_schedules, d.report_schedules, ov),
        policy);
      body.appendChild(main);
      body.appendChild(side);
      fillRulesets(policy, state);
    });
  }
  await paint();
}
