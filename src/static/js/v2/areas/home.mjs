// home.mjs — #/home. Anchors HM-01…HM-04, OV-02 (posture), XC-01 (rail),
// XC-10 (error card). v3 spec §2: the page answers five questions with five
// cards — what needs me, is the system healthy, what happens today, can the
// data be trusted, where is posture heading — and nothing else. Everything the
// v2 overview board also showed lives in its own area now (Top10 / saved
// queries on #/investigate/traffic; audit, snapshot and policy-usage summaries
// on #/reports; system / pipeline / TLS / channel detail on the system pages).
//
// Data: five GET snapshots, all already served by the backend — no new
// endpoint beyond 3A's /api/alerts (spec §4a).

import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { t, tf } from "../core/i18n.mjs";
import { el, clear, disclosure } from "../core/dom.mjs";
import { num, since, stamp, tone as toneOf } from "../core/fmt.mjs";
import { drawer } from "../components/drawer.mjs";
import { palette } from "../components/palette.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { computeLights, healthbar } from "../components/healthbar.mjs";
import { audit } from "../core/audit.mjs";
import {
  areaHead, panel, withMeta, withGoto, kv, badge, note, emptyState, brow,
  cardPosture, postureDetail, drawerSpec, cmdSpec, loadOne,
} from "./cards.mjs";

const ROUTE = "#/home";
const GO_INBOX = "#/investigate/inbox";
const GO_TRAFFIC = "#/investigate/traffic";
const GO_SCHEDULES = "#/policy/schedules";
const GO_REPORT_SCHEDULES = "#/reports/schedules";
const GO_JOBS = "#/system/jobs";
const GO_REPORTS = "#/reports";

const SNAPS = ["status", "dashboard_overview", "rs_schedules", "report_schedules"];
const ALERTS_PARAMS = { status: "new", page: 1, page_size: 4 };

// static keys so the i18n audit can see them (a concatenated key is invisible to it)
const STATUS_LABEL = { new: "gui_alert_status_new", ack: "gui_alert_status_ack", done: "gui_alert_status_done" };
const SEVERITY_RANK = { critical: 0, error: 1, warning: 2, warn: 2, info: 3 };
function severityTone(sev) {
  const s = String(sev || "").toLowerCase();
  if (s === "critical" || s === "error") return "crit";
  if (s === "warning" || s === "warn") return "warn";
  return "info";
}

function loadAll() {
  return Promise.all(SNAPS.map(loadOne).concat([
    api.load("alerts", ALERTS_PARAMS).catch(function (e) {
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

// ── HM-01 需要你處理 ──────────────────────────────────────────────────────
function cardNeedsYou(alerts) {
  const p = panel("HM-01", t("gui_home_needs_you"));
  if (!alerts || alerts.ok === false) {
    p.body.appendChild(note(tf("error_generic", { error: (alerts && alerts.error) || "—" })));
    p.setAttribute("data-tone", "warn");
    withGoto(p, GO_INBOX);
    return p;
  }
  const counts = alerts.counts || {};
  const items = (alerts.items || []).slice().sort(function (a, b) {
    return (SEVERITY_RANK[String(a.severity).toLowerCase()] ?? 9) - (SEVERITY_RANK[String(b.severity).toLowerCase()] ?? 9);
  });
  withMeta(p, tf("gui_home_needs_you_meta", { total: num(alerts.total || 0), open: num(counts.new || 0) }));
  if (!items.length) {
    p.body.appendChild(emptyState(t("gui_home_no_open_alerts"), GO_INBOX, t("gui_home_go_inbox")));
    p.setAttribute("data-tone", "ok");
    withGoto(p, GO_INBOX);
    return p;
  }
  const list = el("div", { class: "stack" });
  items.forEach(function (a) {
    const row = el("a", { class: "kv hm-alert", href: GO_INBOX + "?id=" + encodeURIComponent(a.id), "data-tone": severityTone(a.severity) },
      el("span", { class: "hm-alert-when mono", text: since(a.fired_at) }),
      el("span", { class: "hm-alert-body" },
        el("b", { text: a.rule_name || "—" }),
        el("small", { text: [a.type, a.summary].filter(Boolean).join(" · ") })),
      badge(STATUS_LABEL[a.status] ? t(STATUS_LABEL[a.status]) : t("gui_alert_status_new"), severityTone(a.severity))
    );
    list.appendChild(row);
  });
  p.body.appendChild(list);
  p.setAttribute("data-tone", items.some(function (a) { return severityTone(a.severity) === "crit"; }) ? "crit" : "warn");
  withGoto(p, GO_INBOX);
  return p;
}

// ── HM-02 系統健康 ────────────────────────────────────────────────────────
function cardHealth(st, ov) {
  const p = panel("HM-02", t("gui_home_health"));
  const lights = computeLights(st || {}, ov || {});
  const ven = (ov && ov.ven) || {};
  const venTone = ven.verdict === "ok" ? "ok" : (ven.verdict ? "warn" : "neutral");
  const rows = lights.map(function (l) { return { label: l.label, tone: l.tone, summary: l.summary || l.value, route: l.route }; });
  rows.push({
    label: t("gui_home_ven"), tone: venTone,
    summary: ven.total !== undefined ? tf("gui_home_ven_summary", { online: num(ven.online || 0), total: num(ven.total || 0) }) : "—",
    route: "#/system/pce",
  });
  const bad = rows.filter(function (r) { return r.tone === "crit" || r.tone === "warn"; });
  const lead = !bad.length
    ? t("gui_home_health_all_ok")
    : tf("gui_home_health_attention", { items: bad.map(function (r) { return r.label; }).join("、") });
  p.body.appendChild(el("p", { class: "lead", text: lead }));
  const grid = el("div", { class: "lamps" });
  rows.forEach(function (r) {
    grid.appendChild(el("a", { class: "lamp", href: r.route, "data-tone": r.tone },
      el("i", { class: "dot" }),
      el("span", null, el("b", { text: r.label }), el("small", { text: r.summary || "—" }))));
  });
  p.body.appendChild(grid);
  p.setAttribute("data-tone", bad.some(function (r) { return r.tone === "crit"; }) ? "crit" : (bad.length ? "warn" : "ok"));
  withGoto(p, "#/system/pce");
  return p;
}

// ── HM-03 今天會發生 ──────────────────────────────────────────────────────
function todayLocal(iso) {
  if (!iso) return false;
  const d = new Date(iso);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}
function hhmm(iso) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}
function cardToday(rs, reportSched, ov) {
  const p = panel("HM-03", t("gui_home_today"));
  const items = [];
  (Array.isArray(rs) ? rs : []).forEach(function (s) {
    if (!s || s.live_enabled === false) return;
    if (s.schedule_type === "one_time" || s.type === "one_time") {
      if (todayLocal(s.expire_at)) items.push({ when: hhmm(s.expire_at), sort: s.expire_at, text: tf("gui_home_today_rule_expire", { name: s.name || s.detail_name || "—" }), route: GO_SCHEDULES, tone: "info" });
      return;
    }
    if (s.start) items.push({ when: s.start, sort: "T" + s.start, text: tf("gui_home_today_rule_start", { name: s.name || "—", action: s.action || "" }), route: GO_SCHEDULES, tone: s.last_result === "error" ? "warn" : "info" });
    if (s.end) items.push({ when: s.end, sort: "T" + s.end, text: tf("gui_home_today_rule_end", { name: s.name || "—" }), route: GO_SCHEDULES, tone: "info" });
  });
  (Array.isArray(reportSched) ? reportSched : []).forEach(function (r) {
    if (!r || r.enabled === false || !r.next_run) return;
    if (todayLocal(r.next_run)) items.push({ when: hhmm(r.next_run), sort: r.next_run, text: tf("gui_home_today_report", { name: r.name || r.report_type || "—" }), route: GO_REPORT_SCHEDULES, tone: "info" });
  });
  const jobs = (ov && ov.job_health) || [];
  jobs.forEach(function (j) {
    if (!j || !/retention|archive/.test(String(j.job_id || ""))) return;
    if (!j.last_run || !j.interval_seconds) return;
    const next = new Date(new Date(j.last_run).getTime() + j.interval_seconds * 1000);
    if (todayLocal(next.toISOString())) items.push({ when: hhmm(next.toISOString()), sort: next.toISOString(), text: tf("gui_home_today_job", { job: j.job_id }), route: GO_JOBS, tone: j.level === "ok" ? "info" : "warn" });
  });
  items.sort(function (a, b) { return String(a.sort).localeCompare(String(b.sort)); });
  if (!items.length) {
    p.body.appendChild(emptyState(t("gui_home_today_empty"), GO_SCHEDULES, t("gui_home_go_schedules")));
  } else {
    const list = el("div", { class: "stack" });
    items.slice(0, 6).forEach(function (it) {
      list.appendChild(el("a", { class: "kv hm-today", href: it.route, "data-tone": it.tone },
        el("span", { class: "mono hm-when", text: it.when }),
        el("span", { text: it.text })));
    });
    p.body.appendChild(list);
  }
  withGoto(p, GO_SCHEDULES);
  return p;
}

// ── HM-04 7 天流量決策 ────────────────────────────────────────────────────
function cardDecisions(ov) {
  const b = (ov && ov.blocked) || {};
  const p = panel("HM-04", tf("gui_home_decisions", { days: num(b.window_days || 7) }));
  const allowed = Number(b.allowed || 0), potential = Number(b.potential || 0), unknown = Number(b.unknown || 0), blocked = Number(b.blocked || 0);
  const total = allowed + potential + unknown + blocked;
  if (!total) {
    p.body.appendChild(emptyState(t("gui_home_decisions_empty"), GO_TRAFFIC, t("gui_home_go_traffic")));
    withGoto(p, GO_TRAFFIC);
    return p;
  }
  if (b.vs_prev_pct !== undefined && b.vs_prev_pct !== null) {
    withMeta(p, tf("gui_home_decisions_vs_prev", { pct: (b.vs_prev_pct > 0 ? "+" : "") + num(b.vs_prev_pct) }));
  }
  const bar = el("div", { class: "decision-bar", role: "img", "aria-label": t("gui_home_decisions") });
  [["ok", allowed], ["warn", potential], ["neutral", unknown], ["crit", blocked]].forEach(function (pair) {
    if (!pair[1]) return;
    bar.appendChild(el("i", { "data-tone": pair[0], style: "flex-basis:" + (pair[1] / total * 100).toFixed(2) + "%" }));
  });
  p.body.appendChild(bar);
  const legend = el("div", { class: "legend" });
  [["ok", "gui_pd_allowed", allowed], ["warn", "gui_pd_potential", potential], ["neutral", "gui_siem_traffic_pd_unknown", unknown], ["crit", "gui_pd_blocked", blocked]].forEach(function (row) {
    legend.appendChild(el("span", { "data-tone": row[0] }, el("i", { class: "dot" }), el("span", { text: t(row[1]) + " " + num(row[2]) })));
  });
  p.body.appendChild(legend);
  p.body.appendChild(note(tf("gui_home_decisions_read", { n: num(potential) })));
  p.setAttribute("data-tone", blocked ? "crit" : (potential > allowed ? "warn" : "ok"));
  withGoto(p, GO_TRAFFIC);
  return p;
}

/** S2 — teardown is registered before the first await (tests/test_v2_teardown_registration.py). */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    drawer.closeAll();
    // v3.1: the health rail is this page's content now, not the shell's, so
    // its teardown contract is this area's to honour. An open light popover
    // holds two capture-phase document listeners and the TOPMOST entry on
    // core/dom.mjs's shared dismiss stack; leaving one behind on a detached
    // node means the next Escape anywhere in the app is eaten before any live
    // surface sees it. destroy() closes them and is idempotent.
    if (state.rail && typeof state.rail.destroy === "function") state.rail.destroy();
    palette.setRoute(path);
  });
}

export async function mountHome(root, ctx) {
  const handles = {};
  const state = { torn: false };
  installTeardown(state);
  const probe = el("div", { class: "ov-error-probe" });
  audit.register("home-error-card", function () {
    if (probe.firstChild) return;
    root.appendChild(probe);
    withErrorCard(probe, "__audit_unavailable__",
      function () { return api.load("__audit_unavailable__"); },
      function () { });
  });
  drawer.registerAudit("ov-posture-detail", function () {
    return handles.openPostureDetail ? handles.openPostureDetail() : null;
  });
  palette.registerFor(ROUTE, cmdSpec("home:inbox", t("gui_home_go_inbox"), function () { router.go(GO_INBOX); }));
  palette.registerFor(ROUTE, cmdSpec("ov:posture", t("gui_ov_posture_score_label") + " · " + t("gui_ov_detail"), function () {
    if (handles.openPostureDetail) handles.openPostureDetail();
  }));

  root.appendChild(areaHead(t("gui_nav_home"), ROUTE));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "home (" + (SNAPS.length + 1) + ")", loadAll, function (d) {
    if (ctx.stale() || state.torn) return;
    const st = d.status || {};
    const ov = d.dashboard_overview || {};
    const openCount = (d.alerts && d.alerts.counts && d.alerts.counts.new) || 0;
    const head = el("div", { class: "pagehead" },
      el("div", null,
        el("div", { class: "eyebrow", text: stamp(ov.as_of || st.timestamp || new Date().toISOString()) + (st.timezone ? " · " + st.timezone : "") }),
        el("h1", { class: "h1" },
          el("span", { text: t("gui_home_headline_prefix") }),
          el("b", { class: "hot", "data-cov": "HM-00", text: " " + tf("gui_home_headline_count", { n: num(openCount) }) + " " }),
          el("span", { text: t("gui_home_headline_suffix") }))),
      el("button", { class: "btn primary", type: "button", text: t("gui_home_go_inbox"), onClick: function () { router.go(GO_INBOX); } })
    );
    board.appendChild(head);
    // XC-01. Until 3B's five-light rail becomes the spec §2 side card (Task 4)
    // it keeps its own markup, moved verbatim out of the shell — so it is on
    // #/home and nowhere else, which is the ruling it always had.
    state.rail = healthbar.render(st, ov);
    board.appendChild(state.rail);
    function openPostureDetail() {
      return drawer.open(drawerSpec(t("gui_ov_posture_score_label"), postureDetail(ov.posture || {})));
    }
    handles.openPostureDetail = openPostureDetail;
    board.appendChild(brow("c75", [cardNeedsYou(d.alerts), cardHealth(st, ov)]));
    board.appendChild(brow("c3", [cardToday(d.rs_schedules, d.report_schedules, ov), cardDecisions(ov), cardPosture(ov, openPostureDetail)]));
  });
}
