// automation.mjs — #/automation/{rules,reports,jobs}. Anchors AU-01…AU-13.
//
// The area answers one question in three tenses: WHAT ACTS WITHOUT A HUMAN?
//   rules   — schedules that flip PCE policy on and off (the sharp one)
//   reports — schedules that produce files and mail them
//   jobs    — the appliance's own heartbeat, the machinery under both
//
// ── THE DUAL-TARGET MODEL (previous-redesign failure #1) ────────────────────
// A rule schedule targets EITHER a whole ruleset OR one single rule inside a
// ruleset. Two independent carriers of that fact live in every stored entry:
//   · href      — "/orgs/1/sec_policy/draft/rule_sets/619"            ruleset
//                 "/orgs/1/sec_policy/draft/rule_sets/624/sec_rules/1724"  rule
//                 (a rule href may also carry /rules/ or /deny_rules/ — see
//                  RULE_HREF below; matching only sec_rules loses deny rules)
//   · is_ruleset — the boolean the create form sends (rule-scheduler.js:449),
//                  which api_client.py:1325 uses to choose the PROVISION scope
// The last redesign collapsed the two into one "schedule" row and lost the rule
// level entirely. Here every row of AU-08 carries data-sched-target-kind, the
// two carriers are cross-checked in the row builder (a disagreement is shown,
// never silently resolved), and tests/design_v2/test_rule_scheduler_model.py
// asserts row count and target kinds against snapshots/rs_schedules.json.
// The drawer exists twice for the same reason: AU-05 is opened from the ruleset
// header, AU-06 from a rule row, and each one states its own target.
//
// ── HONESTY RULES (Task 7 report §9.9) ─────────────────────────────────────
//   * No API call is made anywhere. Saves, toggles, deletes and run-now edit an
//     in-memory copy of the snapshot and say so in a toast.
//   * AU-09 "立即檢查" does not fabricate a run. It states what the real POST
//     does (rule_scheduler.py:432-445) and, separately, renders a decision
//     preview computed by transcribing the engine (rule_scheduler.py:302-399)
//     against the browser's clock — labelled as a computation, not as a result.
//   * Empty snapshots stay empty. rs_status.timeline_24h is [] and
//     report_sched_history.history is [] on this appliance; both render their
//     product empty-state plus the reason the data is absent.
// Anything not transcribed from the product is marked DESIGN-ADDED where it is
// decided.

import { el, clear, spacer } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { num, dur, stamp, since, tone } from "../core/fmt.mjs";
import { store } from "../core/store.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { verifyPane } from "../components/verifypane.mjs";
import { areaHead } from "./placeholder.mjs";

const R_RULES = "#/automation/rules";
const R_REPORTS = "#/automation/reports";
const R_JOBS = "#/automation/jobs";

const SUB_ROUTES = [
  [R_RULES, "gui_rs_tab"],
  [R_REPORTS, "gui_tab_report_schedules"],
  [R_JOBS, "gui_ov_job_health"],
];

const RULE_SNAPS = ["rs_status", "rs_schedules", "rs_rulesets", "rs_ruleset_detail", "rs_logs"];
const REPORT_SNAPS = ["report_schedules", "report_sched_history"];
const JOB_SNAPS = ["dashboard_overview"];

// rule-scheduler.js:527 — the day map the timing column uses. Order is the
// engine's own (rule_scheduler.py normalize_day compares lowercase English).
const DAYS = [
  ["Monday", "gui_rs_mon"],
  ["Tuesday", "gui_rs_tue"],
  ["Wednesday", "gui_rs_wed"],
  ["Thursday", "gui_rs_thu"],
  ["Friday", "gui_rs_fri"],
  ["Saturday", "gui_rs_sat"],
  ["Sunday", "gui_rs_sun"],
];

// rule-scheduler.js:110 (select#rs-search-scope) — only the two rule scopes are
// served by /api/rule_scheduler/rules/search; the ruleset scopes filter the list.
const SEARCH_SCOPES = [["id", "gui_rs_scope_rule_id"], ["desc", "gui_rs_scope_rule_desc"]];

// rule-scheduler.js:421-422 (input[name=rs-sch-type]) — the two stored shapes.
// rule_scheduler.py:323-325 rejects anything else with gui_err_invalid_rule_sched_type.
const SCH_TYPES = [["recurring", "gui_rs_recurring"], ["one_time", "gui_rs_one_time"]];

// rule-scheduler.js:422 (input[name=rs-sch-action]) — recurring only.
// rule_scheduler.py:394 (engine): target = in_window for allow, NOT in_window for disable.
const SCH_ACTIONS = [["allow", "gui_rs_on_during"], ["disable", "gui_rs_off_during"]];

/* dashboard.js:317-329 (typeLabels) + index.html:1591-1603 (select#sched-report-type)
 * — the same eleven types in both places, and the list column prints the RAW
 * value for anything else (`typeLabels[s.report_type] || s.report_type`).
 * This snapshot's one schedule stores report_type "audit_summary", which is NOT
 * one of the eleven: the product's list therefore shows the bare string, and its
 * form select has no such option. dashboard.js:401 sets select.value to it
 * anyway on open; a <select> given a value with no matching <option> reports
 * selectedIndex=-1 and value="" (it does NOT fall back to the first option).
 * dashboard.js:450 then reads that "" at save time and PUTs report_type="" —
 * opening and saving CLEARS the type, it does not rewrite it to another one.
 * The mockup keeps the stored value as an option and flags it (see
 * v2_au_rep_type_unknown). */
const REPORT_TYPES = [
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

// dashboard.js:332-336 (freqBaseMap) + index.html select#sched-freq
const FREQS = [["daily", "gui_sched_freq_daily"], ["weekly", "gui_sched_freq_weekly"], ["monthly", "gui_sched_freq_monthly"]];
// index.html:1638-1645 (select#sched-dow) + config_models.py:124 — the
// product's day_of_week values are the full lowercase English day names, NOT
// three-letter codes. report_scheduler.py:259 matches with
// now.strftime("%A").lower(), which only ever produces these seven strings;
// a stored value outside this set (this snapshot has "mon") can never match,
// so that schedule silently never fires on its intended day (see
// knownDayOfWeek / v2_au_dow_unknown below — a real product bug, not
// normalized away here).
const DOW = [["monday", "gui_rs_mon"], ["tuesday", "gui_rs_tue"], ["wednesday", "gui_rs_wed"],
  ["thursday", "gui_rs_thu"], ["friday", "gui_rs_fri"], ["saturday", "gui_rs_sat"], ["sunday", "gui_rs_sun"]];

function knownDayOfWeek(v) {
  return !!lookup(DOW, v, "");
}
// dashboard.js:412 — the form stores one value; "all" expands to three formats
// on save (dashboard.js:443-444).
const FORMATS = [["html", "gui_sched_fmt_html"], ["csv", "gui_sched_fmt_csv"],
  ["xlsx", "gui_sched_fmt_xlsx"], ["all", "gui_sched_fmt_all"]];

// dashboard.js:384 TRAFFIC_PROFILE_TYPES — the filter section only exists for
// these; audit_summary (this snapshot's type) is not one of them.
const TRAFFIC_PROFILE_TYPES = ["traffic", "security_risk", "network_inventory", "rule_hit_count"];

// ── shared chrome (same vocabulary as investigate.mjs / alerting.mjs) ───────
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

function withTone(p, tn) {
  p.setAttribute("data-tone", tn);
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

function kv(label, value, tn) {
  const b = el("b", { class: "mono", "data-tone": tn || null, title: String(value) });
  if (tn) b.appendChild(el("i", { class: "dot" }));
  b.appendChild(el("span", { text: value }));
  return el("div", { class: "kv" }, el("span", { text: label }), b);
}

function emptyState(title, body) {
  return el("div", { class: "empty" },
    el("span", { class: "et", text: title }),
    body ? el("p", { text: body }) : null);
}

function kpiCell(labelText, value, unit, detail) {
  return el("div", { class: "kpicell" },
    el("span", { class: "k", title: labelText, text: labelText }),
    el("span", { class: "v", title: String(value) }, el("span", { text: String(value) }),
      unit ? el("s", { text: unit }) : null),
    el("span", { class: "d", title: detail || "", text: detail || "" })
  );
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

/** An editable field: the control carries data-field so a reviewer can map it. */
function editField(key, labelText, control, hint) {
  control.dataset.field = key;
  const box = labelled(labelText, control, hint || null);
  box.lab.appendChild(el("code", { text: key }));
  return box;
}

/** A backend field this form does not own: value + why it is read-only here. */
function roField(key, value, why) {
  const li = el("li");
  li.appendChild(el("code", { class: "c", text: key }));
  const v = el("span", { class: "s", text: showValue(value) });
  v.dataset.field = key;
  li.appendChild(v);
  li.appendChild(el("span", { class: "r", text: why }));
  return li;
}

function roList(rows) {
  return el("ul", { class: "stack rofields" }, rows);
}

function sectionHead(text) {
  return el("h4", { class: "eyebrow", text: text });
}

function selectField(pairs, value, onChange) {
  const sel = el("select", { class: "field" });
  pairs.forEach(function (pair) {
    const opt = el("option", { value: pair[0], text: t(pair[1]) });
    if (String(value) === String(pair[0])) opt.selected = true;
    sel.appendChild(opt);
  });
  if (onChange) sel.addEventListener("change", function () { onChange(sel.value); });
  return sel;
}

/** Same control, but the pairs carry literal labels (already resolved). */
function selectLiteral(pairs, value, onChange) {
  const sel = el("select", { class: "field" });
  pairs.forEach(function (pair) {
    const opt = el("option", { value: pair[0], text: pair[1] });
    if (String(value) === String(pair[0])) opt.selected = true;
    sel.appendChild(opt);
  });
  if (onChange) sel.addEventListener("change", function () { onChange(sel.value); });
  return sel;
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

function textField(value, onChange, type) {
  const input = el("input", { class: "field", type: type || "text", value: value === null || value === undefined ? "" : String(value) });
  if (onChange) input.addEventListener("input", function () { onChange(input.value); });
  return input;
}

function checkField(checkedOn, onChange) {
  const input = el("input", { type: "checkbox" });
  input.checked = !!checkedOn;
  if (onChange) input.addEventListener("change", function () { onChange(input.checked); });
  return el("label", { class: "chk" }, input, el("span", { text: "" }));
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

function buildCell(fn) { const o = {}; o.cell = fn; return o; }
function widthCell(width, fn) { const o = {}; o.width = width; if (fn) o.cell = fn; return o; }
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

function loadAll(ids) {
  return Promise.all(ids.map(function (id) { return store.load(id); })).then(function (list) {
    const out = {};
    ids.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

function lookup(pairs, key, fallback) {
  let hit = fallback;
  pairs.forEach(function (pair) { if (pair[0] === String(key)) hit = pair[1]; });
  return hit;
}

/** dashboard.js:331 — a type outside the catalogue prints as its raw value. */
function reportTypeLabel(v) {
  const key = lookup(REPORT_TYPES, v, "");
  return key ? t(key) : String(v === null || v === undefined ? "" : v);
}

function knownReportType(v) {
  return !!lookup(REPORT_TYPES, v, "");
}

function showValue(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function areaTop(active) {
  const head = areaHead(t("v2_nav_automation"), active);
  const nav = el("nav", { class: "subnav", "aria-label": t("v2_nav_automation") });
  SUB_ROUTES.forEach(function (pair) {
    const a = el("a", { href: pair[0], text: t(pair[1]) });
    if (pair[0] === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  head.appendChild(nav);
  return head;
}

/** Shallow copy — every mutation in this area happens on a copy, never on the
 *  store's cached JSON (leaving and returning resets the page). */
function copyOf(obj) {
  const out = {};
  Object.keys(obj || {}).forEach(function (k) { out[k] = obj[k]; });
  return out;
}

// ════════════════════════════════════════════════ the dual-target model ═════

/* A rule href is a ruleset href with one more pair of segments, and the PCE has
 * THREE rule collections: sec_rules (allow), rules (the legacy allow list) and
 * deny_rules (deny / override_deny) — rule_scheduler.py:160-166 reads all three
 * when it builds a ruleset's rule list. Matching only "/sec_rules/" would file
 * every deny-rule schedule under "ruleset", which is exactly the collapse this
 * area exists to prevent (found by screenshot: rule 293 of the captured ruleset
 * is a deny rule).
 *
 * Both carriers matter, and that is why a disagreement is shown instead of
 * resolved: api_client.py:1311-1326 (toggle_and_provision) PUTs to the href but
 * picks what to PROVISION from is_ruleset —
 *     rs_href = draft_href if is_ruleset else "/".join(draft_href.split("/")[:7])
 * so a wrong is_ruleset provisions the wrong scope even though the toggle landed
 * on the right object. targetKind() answers with the href (the address that is
 * actually written), targetMismatch() reports the disagreement. */
const RULE_HREF = /\/rule_sets\/[^/]+\/(sec_rules|rules|deny_rules)\//;

function targetKind(s) {
  return RULE_HREF.test(String(s.href || "")) ? "rule" : "ruleset";
}

function targetMismatch(s) {
  const claimed = s.is_ruleset ? "ruleset" : "rule";
  return claimed !== targetKind(s);
}

function targetLabel(s) {
  return targetKind(s) === "rule" ? t("gui_rs_type_rule") : t("gui_rs_type_ruleset");
}

// ════════════════════════════════════════════════════ rules sub-view ════════

/* rule-scheduler.js:783-795 — "today" is the browser's local midnight, and each
 * entry's `timestamp` is parsed with new Date(). Transcribed exactly: a run is
 * an entry, a hit is a log line containing [ACTION] (rule_scheduler.py:403), an
 * error entry is one with [FAILED] or [ERROR] (rule_scheduler.py:409, :423, :427). */
function logStats(history, sinceMs) {
  const out = {};
  out.runs = 0;
  out.hits = 0;
  out.errors = 0;
  out.last = null;
  (history || []).forEach(function (entry) {
    if (!entry.timestamp) return;
    const ts = new Date(entry.timestamp).getTime();
    if (!isFinite(ts) || ts < sinceMs) return;
    out.runs += 1;
    const lines = entry.logs || [];
    out.hits += lines.filter(function (l) { return String(l).indexOf("[ACTION]") >= 0; }).length;
    if (lines.some(function (l) { return /\[FAILED\]|\[ERROR\]/.test(String(l)); })) out.errors += 1;
    if (out.last === null || ts > out.last) out.last = ts;
  });
  return out;
}

function hhmm(ms) {
  const d = new Date(ms);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}

/** The captured log history's own last day, so the KPI row can state a figure
 *  that is not zero-by-construction. DESIGN-ADDED (see the sub-line note). */
function lastLogDay(history) {
  let day = "";
  (history || []).forEach(function (e) {
    const d = String(e.timestamp || "").slice(0, 10);
    if (d && d > day) day = d;
  });
  return day;
}

function dayStats(history, day) {
  const out = {};
  out.runs = 0;
  out.hits = 0;
  out.errors = 0;
  (history || []).forEach(function (e) {
    if (String(e.timestamp || "").slice(0, 10) !== day) return;
    out.runs += 1;
    const lines = e.logs || [];
    out.hits += lines.filter(function (l) { return String(l).indexOf("[ACTION]") >= 0; }).length;
    if (lines.some(function (l) { return /\[FAILED\]|\[ERROR\]/.test(String(l)); })) out.errors += 1;
  });
  return out;
}

/* AU-01 — the status line and the four KPIs.
 * rule-scheduler.js:758-851 (rsRenderKpi):
 *   總排程   :772-780  status.schedule_count; sub = 已啟用 / 今日無記錄
 *   今日已執行 :798-810  count of today's log entries; sub = 上次 HH:MM
 *   命中規則  :812-827  [ACTION] lines today; sub = n 錯誤 (warn) / 正常 / 今日無記錄
 *   下次觸發  :830-848  status.next_trigger_at, parsed by its own regex so the
 *                      browser timezone never re-interprets the wall clock;
 *                      sub = MM-DD when the trigger is not today
 * The status strip above them is this design's: check_interval_seconds and the
 * snapshot instant are in the payload but the product prints neither. */
function rulesStatus(d) {
  const st = d.rs_status || {};
  const history = (d.rs_logs && d.rs_logs.history) || [];
  const schedules = Array.isArray(d.rs_schedules) ? d.rs_schedules : [];

  const p = panel("AU-01", t("gui_rs_tab"));
  const count = st.schedule_count === undefined || st.schedule_count === null ? 0 : st.schedule_count;
  withMeta(p, tf("v2_au_status_meta", {
    every: dur(st.check_interval_seconds), rows: num(schedules.length),
  }));

  const strip = el("div", { class: "strip", "data-tone": "info" });
  strip.appendChild(el("span", null, el("span", { text: t("gui_rs_run_check") + " " }),
    el("b", { text: dur(st.check_interval_seconds) })));
  strip.appendChild(el("span", null, el("span", { text: t("gui_rs_kpi_next") + " " }),
    el("b", { text: String(st.next_trigger_at || "—").replace("T", " ") })));
  strip.appendChild(el("span", null, el("span", { text: t("gui_rs_schedules") + " " }),
    el("b", { text: num(count) })));
  strip.appendChild(spacer());
  strip.appendChild(el("span", { class: "mono", text: "GET /api/rule_scheduler/status" }));
  p.body.appendChild(strip);

  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const today = logStats(history, midnight.getTime());
  const snapDay = lastLogDay(history);
  const onSnapDay = dayStats(history, snapDay);

  const row = el("div", { class: "kpirow" });
  row.appendChild(kpiCell(t("gui_rs_kpi_total"), num(count), null,
    count > 0 ? t("gui_rs_kpi_enabled") : t("gui_rs_kpi_none_today")));
  row.appendChild(kpiCell(t("gui_rs_kpi_today"), num(today.runs), null,
    today.last ? (t("gui_rs_kpi_last") + " " + hhmm(today.last)) : t("gui_rs_kpi_none_today")));
  row.appendChild(kpiCell(t("gui_rs_kpi_hits"), num(today.hits), null,
    today.errors > 0 ? (num(today.errors) + " " + t("gui_rs_kpi_errors"))
      : (today.hits > 0 ? t("gui_rs_kpi_ok") : t("gui_rs_kpi_none_today"))));

  // :830-848 — the ISO string is read with a regex, not Date(), so a browser in
  // another timezone still shows the wall clock the scheduler computed.
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(st.next_trigger_at || ""));
  const now = new Date();
  const sameDay = m && Number(m[1]) === now.getFullYear() && Number(m[2]) === now.getMonth() + 1
    && Number(m[3]) === now.getDate();
  row.appendChild(kpiCell(t("gui_rs_kpi_next"), m ? (m[4] + ":" + m[5]) : "—", null,
    m ? (sameDay ? "" : m[2] + "-" + m[3]) : t("gui_rs_kpi_none_today")));
  p.body.appendChild(row);

  // DESIGN-ADDED: the product's "today" is the browser's today, which on a
  // static snapshot is always a day with no runs. The captured history's own
  // last day is stated beside it so the zero above reads as a date problem
  // rather than as a dead scheduler.
  p.body.appendChild(note(tf("v2_au_kpi_snapday", {
    day: snapDay || "—", runs: num(onSnapDay.runs), hits: num(onSnapDay.hits), errors: num(onSnapDay.errors),
  })));
  return p;
}

// ── AU-02 timeline ─────────────────────────────────────────────────────────

function toMinutes(hm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hm || ""));
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

function pct(minutes) {
  return (minutes / 1440 * 100) + "%";
}

/* The transcribed half: rule-scheduler.js:704-757 (rsRenderTimeline).
 * 24 buckets, one per hour, filled from status.timeline_24h [{hour,count}];
 * a bucket's level is its share of the busiest bucket (>0.66 lvl-3, >0.33
 * lvl-2, else lvl-1) and a payload with no buckets renders every cell empty
 * with gui_rs_timeline_empty as the meta. This appliance's payload IS empty. */
function bucketRow(buckets) {
  const counts = new Array(24).fill(0);
  let total = 0;
  (buckets || []).forEach(function (b) {
    const hour = b.hour;
    const c = Number(b.count) || 0;
    if (hour === null || hour === undefined || hour < 0 || hour > 23 || c <= 0) return;
    counts[hour] += c;
    total += c;
  });
  const has = (buckets || []).length > 0;
  const max = Math.max.apply(null, counts.concat([1]));

  const track = el("div", { class: "tl-track tl-buckets" });
  for (let h = 0; h < 24; h++) {
    const c = counts[h];
    let lvl = "0";
    if (has && c > 0) lvl = c / max > 0.66 ? "3" : (c / max > 0.33 ? "2" : "1");
    const label = String(h).padStart(2, "0") + ":00";
    const tip = c > 0 ? (label + "  " + c + " " + t("gui_rs_tl_action_unit"))
      : (label + "  " + t("gui_rs_tl_no_toggles"));
    track.appendChild(el("i", { "data-lvl": lvl, title: tip }));
  }
  const out = {};
  out.track = track;
  out.total = total;
  out.has = has;
  return out;
}

/* The DESIGN-ADDED half: the product's timeline can only show toggles that have
 * already happened, so on a quiet appliance it is 24 empty cells and tells the
 * operator nothing about what is ARMED. The lanes below plot each stored
 * schedule's window on the same 24-hour ruler, straight from rs_schedules —
 * recurring windows as a band (with the midnight wraparound the engine
 * implements, rule_scheduler.py:346-353), one-time schedules as a bar that runs
 * to their expiry. No number here is invented; the lane is a second view of the
 * same three rows AU-08 lists. */
function scheduleLane(s) {
  const lane = el("div", { class: "tl-lane" });
  const kind = targetKind(s);
  const tn = s.type === "one_time" ? "info" : (s.action === "allow" ? "ok" : "crit");
  const track = el("div", { class: "tl-track tl-rel", "data-tone": tn });

  if (s.type === "recurring") {
    const a = toMinutes(s.start);
    const b = toMinutes(s.end);
    if (a !== null && b !== null) {
      if (a <= b) {
        track.appendChild(el("i", { class: "tl-band", style: "left:" + pct(a) + ";width:" + pct(b - a) }));
      } else {
        // rule_scheduler.py:350-353 — a window that crosses midnight is two
        // spans of the same day on this ruler.
        track.appendChild(el("i", { class: "tl-band", style: "left:" + pct(a) + ";width:" + pct(1440 - a) }));
        track.appendChild(el("i", { class: "tl-band", style: "left:0;width:" + pct(b) }));
      }
    }
  } else {
    track.appendChild(el("i", { class: "tl-band tl-band-open", style: "left:0;width:100%" }));
  }

  // The lane's right column is the reading, not the full day list: the full
  // list (in the product's own wording) is the AU-08 timing column, and it is
  // the tooltip here.
  const dayList = (s.days || []).length === 7 ? t("gui_rs_everyday")
    : (s.days || []).map(function (d) { return t(lookup(DAYS, d, "")) || d; }).join(", ");
  const when = s.type === "recurring"
    ? tf("v2_au_tl_days_fmt", { n: (s.days || []).length, range: (s.start || "") + "-" + (s.end || "") })
    : tf("v2_au_tl_until_fmt", { when: String(s.expire_at || "").replace("T", " ") });
  const tip = s.type === "recurring" ? (dayList + " " + (s.start || "") + "-" + (s.end || "")) : when;

  lane.appendChild(el("span", { class: "tl-name" },
    el("b", { title: s.detail_name || s.name || "", text: s.detail_name || s.name || "" }),
    el("small", { text: targetLabel(s) + " · " + (s.detail_rs || "—") })));
  lane.appendChild(track);
  lane.appendChild(el("span", { class: "tl-when", title: tip, text: when }));
  lane.dataset.schedKind = kind;
  return lane;
}

function timelinePanel(d) {
  const st = d.rs_status || {};
  const schedules = Array.isArray(d.rs_schedules) ? d.rs_schedules : [];
  const p = panel("AU-02", t("gui_rs_tl_title"));

  const b = bucketRow(st.timeline_24h);
  withMeta(p, b.has ? (num(b.total) + " " + t("gui_rs_tl_action_unit")) : t("gui_rs_timeline_empty"));

  const wrap = el("div", { class: "tl" });
  const ruler = el("div", { class: "tl-lane tl-ruler" });
  ruler.appendChild(el("span", { class: "tl-name" }));
  const ticks = el("div", { class: "tl-track tl-ticks" });
  for (let h = 0; h < 24; h += 3) {
    ticks.appendChild(el("span", { style: "left:" + pct(h * 60), text: String(h).padStart(2, "0") }));
  }
  ruler.appendChild(ticks);
  ruler.appendChild(el("span", { class: "tl-when", text: "" }));
  wrap.appendChild(ruler);

  const toggles = el("div", { class: "tl-lane" });
  toggles.appendChild(el("span", { class: "tl-name" },
    el("b", { text: t("v2_au_tl_toggle_row") }),
    el("small", { text: "timeline_24h" })));
  toggles.appendChild(b.track);
  toggles.appendChild(el("span", { class: "tl-when", text: b.has ? num(b.total) : "0" }));
  wrap.appendChild(toggles);

  schedules.forEach(function (s) { wrap.appendChild(scheduleLane(s)); });
  p.body.appendChild(wrap);

  if (!b.has) p.body.appendChild(note(t("v2_au_tl_empty_why")));
  p.body.appendChild(note(t("v2_au_tl_lane_note")));
  return p;
}

// ── AU-05 / AU-06 / AU-07 the two schedule drawers ─────────────────────────

/* Pre-flight, transcribed from rule_scheduler.py:302-330. The POST refuses in
 * three ways BEFORE anything is stored, and every one of them is fail-closed:
 *   has_draft_changes(href)            -> 400 rs_sch_draft_block
 *   get_provision_state(href)=='unknown' -> 502 rs_sch_pce_unreachable  (the PCE
 *       did not answer; the comment at :313-318 insists this must NOT be
 *       reported as a draft problem, or the operator hunts a draft that does
 *       not exist)
 *   provision state != 'active'        -> 400 rs_sch_draft_block
 * A mockup cannot call the PCE. The nearest fact in the snapshot is the ruleset
 * list's own provision_state ("DRAFT" when the ruleset carries update_type,
 * rule_scheduler.py:140), so that is what the banner reads — and it says which
 * of the two it is standing in for. */
function preflight(provState) {
  const out = {};
  if (provState === "DRAFT") {
    out.tone = "crit";
    out.blocked = true;
    out.text = t("v2_au_pf_draft");
  } else if (!provState) {
    out.tone = "warn";
    out.blocked = false;
    out.text = t("v2_au_pf_unknown");
  } else {
    out.tone = "ok";
    out.blocked = false;
    out.text = t("v2_au_pf_ok");
  }
  return out;
}

/* rule_scheduler.py:355-372 — the annotation written into the PCE object's own
 * description. It is built in ENGLISH on purpose (comment at :357-360: the note
 * is opaque data that later report runs surface verbatim, so Chinese would leak
 * into EN-mode audit reports). Transcribed so the drawer can show exactly what
 * the PCE will carry. */
function noteText(state) {
  if (state.type === "recurring") {
    const days = state.days.length < 7
      ? state.days.map(function (d) { return d.slice(0, 3); }).join(",")
      : "Every day";
    const act = state.action === "allow" ? "Enable during window" : "Disable during window";
    const tz = state.timezone !== "local" ? state.timezone : "Local";
    return "[📅 Recurring: " + days + " " + state.start + "-" + state.end + " (" + tz + ") " + act + "]";
  }
  return "[⏰ Expire: " + String(state.expire_at || "").replace("T", " ") + "]";
}

/* Save-time validation, both layers:
 *   client — rule-scheduler.js:447-462: recurring needs days AND start AND end
 *            (gui_rs_fill_days_time); one_time needs a non-empty expire
 *            (gui_rs_set_expire) and sends it with the T replaced by a space.
 *   server — rule_scheduler.py:323-343: type must be one of the two; recurring
 *            parses start/end with %H:%M; one_time re-inserts the T and parses
 *            with fromisoformat.
 * AU-07 lives on the expire field because that is where the two layers meet. */
function validate(state) {
  if (state.type !== "recurring" && state.type !== "one_time") return t("gui_err_invalid_rule_sched_type");
  if (state.type === "recurring") {
    if (!state.days.length || !state.start || !state.end) return t("gui_rs_fill_days_time");
    if (toMinutes(state.start) === null || toMinutes(state.end) === null) return t("gui_err_invalid_time_hhmm");
    return null;
  }
  if (!state.expire_at) return t("gui_rs_set_expire");
  if (isNaN(Date.parse(String(state.expire_at).replace(" ", "T")))) return t("gui_err_invalid_expire_fmt");
  return null;
}

/**
 * scheduleDrawerBody(target, cov) — one builder, two anchors.
 *   target: {href, name, is_ruleset, detail_rs, detail_src, detail_dst,
 *            detail_svc, provision_state, existing}
 *   cov:    "AU-05" (ruleset level) or "AU-06" (rule level)
 * The two levels differ in exactly two ways, and both are stated in the body:
 * the href shape, and whether the source/destination/service detail belongs to
 * one rule or is inherited "全部" for the whole ruleset (rule-scheduler.js:411-418).
 */
function scheduleDrawerBody(target, cov, onSaved) {
  const body = el("div", { "data-cov": cov });
  const prev = target.existing || {};
  const state = {};
  state.type = prev.type || "recurring";
  state.action = prev.action || "allow";
  state.days = prev.days ? prev.days.slice() : ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
  state.start = prev.start || "08:00";
  state.end = prev.end || "18:00";
  state.expire_at = String(prev.expire_at || "").replace(" ", "T");
  state.timezone = prev.timezone || "local";
  state.name = prev.detail_name || prev.name || target.name || "";

  const isRule = RULE_HREF.test(String(target.href || ""));

  // ── target identity: the half of the model the last redesign dropped ──
  const idBox = el("div", { class: "evinfo", "data-tone": isRule ? "info" : "neutral" });
  idBox.appendChild(el("div", { class: "evinfo-h" },
    badge(isRule ? t("gui_rs_type_rule") : t("gui_rs_type_ruleset"), isRule ? "info" : "neutral"),
    el("code", { text: target.href || "" })));
  idBox.appendChild(el("b", { text: target.name || "" }));
  idBox.appendChild(el("p", { text: t("v2_au_target_note_" + (isRule ? "rule" : "ruleset")) }));
  body.appendChild(idBox);

  // ── pre-flight ──
  const pf = preflight(target.provision_state);
  const pfBox = el("div", { class: "strip", "data-tone": pf.tone });
  pfBox.appendChild(el("span", { text: t("v2_au_preflight") }));
  pfBox.appendChild(el("b", { text: pf.text }));
  body.appendChild(pfBox);
  body.appendChild(note(t("v2_au_pf_note")));

  // ── form ──
  body.appendChild(sectionHead(t("gui_rs_schedule_title")));
  body.appendChild(editField("detail_name", t("gui_rs_col_name"),
    textField(state.name, function (v) { state.name = v; }), t("v2_au_name_hint")));

  const recurBox = el("div");
  const onceBox = el("div", { "data-cov": "AU-07" });

  function syncType() {
    // rule-scheduler.js:436-440 (rsSchTypeChanged) — the two field groups are
    // mutually exclusive. style.display, not [hidden]: a [hidden] element with a
    // flex/grid display rule in CSS stays visible (a real bug from the last round).
    recurBox.style.display = state.type === "recurring" ? "" : "none";
    onceBox.style.display = state.type === "one_time" ? "" : "none";
    paintNote();
  }

  const typeCtl = radioGroup("au-sch-type-" + cov, SCH_TYPES, state.type, function (v) {
    state.type = v;
    syncType();
  });
  typeCtl.dataset.field = "type";
  body.appendChild(labelled(t("gui_rs_sch_type"), typeCtl));

  // recurring group
  const actionCtl = radioGroup("au-sch-action-" + cov, SCH_ACTIONS, state.action, function (v) {
    state.action = v;
    paintNote();
  });
  actionCtl.dataset.field = "action";
  recurBox.appendChild(labelled(t("gui_rs_action_label"), actionCtl, t("v2_au_action_hint")));

  const dayBox = el("div", { class: "daychips" });
  dayBox.dataset.field = "days";
  DAYS.forEach(function (pair) {
    const input = el("input", { type: "checkbox", value: pair[0] });
    input.checked = state.days.indexOf(pair[0]) >= 0;
    input.addEventListener("change", function () {
      state.days = state.days.filter(function (x) { return x !== pair[0]; });
      if (input.checked) state.days.push(pair[0]);
      state.days = DAYS.map(function (p) { return p[0]; }).filter(function (x) { return state.days.indexOf(x) >= 0; });
      paintNote();
    });
    dayBox.appendChild(el("label", null, input, el("span", { text: t(pair[1]) })));
  });
  recurBox.appendChild(labelled(t("gui_rs_active_days"), dayBox));

  const startCtl = textField(state.start, function (v) { state.start = v; paintNote(); }, "time");
  const endCtl = textField(state.end, function (v) { state.end = v; paintNote(); }, "time");
  recurBox.appendChild(editField("start", t("gui_rs_start_time"), startCtl));
  recurBox.appendChild(editField("end", t("gui_rs_end_time"), endCtl, t("v2_au_wrap_hint")));
  recurBox.appendChild(editField("timezone", t("gui_rs_timezone"),
    textField(state.timezone, function (v) { state.timezone = v; paintNote(); }), t("v2_au_tz_hint")));
  body.appendChild(recurBox);

  // one_time group — AU-07. index.html:2362-2372 (#rs-sch-onetime-fields) gives
  // one_time its OWN timezone control (#rs-sch-timezone-ot), independent of the
  // recurring group's (#rs-sch-timezone); rsSaveSchedule (rule-scheduler.js:466)
  // sends that field's value as `timezone`, and the engine compares expire_at
  // against it per-schedule (rule_scheduler.py:333-337). Dropping this control
  // silently pins every one_time schedule to whatever `state.timezone` last
  // held from the recurring group (or "local"), which the operator never chose.
  onceBox.appendChild(editField("expire_at", t("gui_rs_expire_at"),
    textField(state.expire_at, function (v) { state.expire_at = v; paintNote(); }, "datetime-local"),
    t("gui_rs_expire_note")));
  onceBox.appendChild(editField("timezone", t("gui_rs_timezone"),
    textField(state.timezone, function (v) { state.timezone = v; paintNote(); }), t("v2_au_tz_hint")));
  onceBox.appendChild(note(t("v2_au_expire_engine")));
  body.appendChild(onceBox);

  // ── what the PCE will carry ──
  body.appendChild(sectionHead(t("v2_au_note_preview")));
  const notePane = el("pre", { class: "codepane" });
  body.appendChild(verifyPane(notePane));
  body.appendChild(note(t("v2_au_note_en")));

  function paintNote() { notePane.textContent = noteText(state); }
  syncType();

  // ── the fields the form sends but never shows, and the stored-only ones ──
  body.appendChild(sectionHead(t("v2_au_stored_fields")));
  body.appendChild(roList([
    roField("href", target.href, t("v2_au_ro_href")),
    roField("is_ruleset", String(!isRule), t("v2_au_ro_is_ruleset")),
    roField("detail_rs", target.detail_rs, t("v2_au_ro_detail")),
    roField("detail_src", target.detail_src, t("v2_au_ro_detail")),
    roField("detail_dst", target.detail_dst, t("v2_au_ro_detail")),
    roField("detail_svc", target.detail_svc, t("v2_au_ro_detail")),
    roField("id", prev.id, t("v2_au_ro_id")),
    roField("last_checked", prev.last_checked, t("v2_au_ro_state")),
    roField("last_action", prev.last_action, t("v2_au_ro_state")),
    roField("last_result", prev.last_result, t("v2_au_ro_state")),
    roField("last_error", prev.last_error, t("v2_au_ro_state")),
    roField("pce_status", prev.pce_status, t("v2_au_ro_recon")),
    roField("live_enabled", prev.live_enabled, t("v2_au_ro_recon")),
    roField("live_name", prev.live_name, t("v2_au_ro_recon")),
  ]));

  const errLine = el("p", { class: "note", "data-tone": "crit" });
  body.appendChild(errLine);

  const spec = drawerSpec(
    (target.existing ? t("gui_rs_col_edit") : t("gui_rs_schedule_title")) + " · " + (target.name || ""),
    body,
    function () {
      // A refusal the operator cannot see is a refusal they will repeat: the
      // message is placed where the form is, and scrolled to.
      const err = validate(state) || (pf.blocked ? pf.text : null);
      if (err) {
        errLine.textContent = err;
        errLine.scrollIntoView({ block: "center" });
        return false;
      }
      errLine.textContent = "";
      if (onSaved) onSaved(state);
      toast.info(t("v2_au_mock_save"));
      return true;
    }
  );
  return spec;
}

// ── AU-03 / AU-04 ruleset browser ──────────────────────────────────────────

/* rule-scheduler.js:196-201 — the schedule mark column. 1 = this ruleset itself
 * carries a schedule, 2 = one of its rules does (rule_scheduler.py:104-128
 * computes it), 0 = neither. */
function schedMark(kind) {
  if (kind !== 1 && kind !== 2) return el("span", { class: "mono", text: "—" });
  const label = kind === 1 ? t("gui_rs_legend_rs") : t("gui_rs_legend_child");
  const mark = badge(label, kind === 1 ? "info" : "neutral");
  mark.title = label;   // the column is narrow at compact density
  return mark;
}

function provBadge(stateStr) {
  return badge(stateStr === "DRAFT" ? "DRAFT" : "ACTIVE", stateStr === "DRAFT" ? "warn" : "ok");
}

function onOffBadge(on) {
  return badge(on ? "ON" : "OFF", on ? "ok" : "neutral");
}

/* rule_scheduler.py:144-190 (rs_rules_search) — scope 'id' is an EXACT match on
 * the extracted rule id, scope 'desc' is a case-insensitive substring of the
 * rule's description. Transcribed exactly.
 * DESIGN-ADDED, and stated on the panel: the real endpoint runs this predicate
 * over api.get_all_rulesets() — every ruleset, every rule — and returns hits
 * across the whole policy. The mockup has one captured ruleset detail, so the
 * same predicate runs over that one ruleset's rules. */
function ruleMatches(rule, q, scope) {
  if (!q) return true;
  const id = String(rule.id === undefined ? "" : rule.id);
  if (scope === "id") return q === id;
  return String(rule.description || "").toLowerCase().indexOf(q.toLowerCase()) >= 0;
}

// ── AU-08 schedule list ────────────────────────────────────────────────────

/* rule_scheduler.py:258-300 — the reconciliation. One fetch of every ruleset
 * builds a map of live hrefs; then per stored schedule:
 *   live_map is None (the fetch failed) -> live_enabled null, pce_status LEFT
 *       ALONE. Unknown is not deleted.
 *   href found  -> live_enabled/live_name from the PCE, and a previous
 *       'deleted' flag is cleared.
 *   href absent -> live_enabled null and the entry is marked pce_status
 *       'deleted' in the DB.
 * rule-scheduler.js:499-506 renders that as one badge; this column keeps the
 * three states apart because "unknown" and "deleted" are different problems. */
function reconCell(s) {
  if (s.pce_status === "deleted") return badge(t("gui_rs_status_deleted"), "crit");
  if (s.live_enabled === true) return badge("ON", "ok");
  if (s.live_enabled === false) return badge("OFF", "neutral");
  return badge(t("v2_au_recon_unknown"), "warn");
}

/* rule-scheduler.js:508-534 — the action and timing columns. */
function actionCell(s) {
  if (s.type !== "recurring") return badge(t("gui_rs_expire"), "info");
  return s.action === "allow" ? badge(t("gui_rs_enable_label"), "ok") : badge(t("gui_rs_disable_label"), "crit");
}

function timingText(s) {
  const tz = s.timezone && s.timezone !== "local" ? s.timezone : t("gui_rs_local_tz");
  if (s.type === "recurring") {
    const days = (s.days || []).length === 7 ? t("gui_rs_everyday")
      : (s.days || []).map(function (d) { return t(lookup(DAYS, d, "")) || String(d).slice(0, 3); }).join(", ");
    return days + " " + (s.start || "") + " - " + (s.end || "") + " (" + tz + ")";
  }
  return t("gui_rs_until") + " " + String(s.expire_at || "").replace("T", " ") + " (" + tz + ")";
}

/* rule-scheduler.js:556-566 — the last-run cell. last_checked, then the action
 * with a "!" when the result was an error; an error tints the cell and puts the
 * recorded text in the tooltip. */
function lastRunCell(s) {
  if (!s.last_checked) return el("span", { class: "mono", text: t("gui_jh_never_ran") });
  const suffix = s.last_action ? (" (" + s.last_action + (s.last_result === "error" ? " !" : "") + ")") : "";
  const bad = s.last_result === "error";
  const span = el("span", { class: "mono", "data-tone": bad ? "crit" : null, title: bad ? (s.last_error || "") : "" });
  if (bad) span.appendChild(el("i", { class: "dot" }));
  span.appendChild(el("span", { text: stamp(s.last_checked) + suffix }));
  return span;
}

// ── AU-09 decision preview ─────────────────────────────────────────────────

/* Transcribed from rule_scheduler.py:302-399 (RuleScheduler.check), which is the
 * body the real POST runs. For each stored schedule the engine computes, in this
 * order:
 *   one_time : now > expire_at -> [EXPIRED], disable + provision, and the entry
 *              is removed only if that succeeded (:355-378, the fail-closed fix
 *              from the 2026-07-24 review). Otherwise target = enabled.
 *   recurring: in_window from the day list and start/end (with the midnight
 *              wraparound at :346-353); target = in_window for action 'allow',
 *              its negation for 'disable' (:355).
 *   both     : has_draft_changes(href) -> [略過] skip, no toggle (:381-385).
 * This preview runs that arithmetic on the browser's clock and says so. It is a
 * computation over the snapshot, NOT a run: nothing is toggled, nothing is
 * logged, and the appliance never hears about it. */
function decide(s, nowDate, draftBlocked) {
  const out = {};
  out.name = s.detail_name || s.name || "";
  out.kind = targetKind(s);
  if (draftBlocked) {
    out.tone = "warn";
    out.verdict = t("v2_au_dec_skip_draft");
    return out;
  }
  if (s.type === "one_time") {
    const exp = Date.parse(String(s.expire_at || "").replace(" ", "T"));
    if (isFinite(exp) && nowDate.getTime() > exp) {
      out.tone = "crit";
      out.verdict = t("v2_au_dec_expired");
    } else {
      out.tone = "ok";
      out.verdict = t("v2_au_dec_keep_enabled");
    }
    return out;
  }
  const dayName = DAYS[(nowDate.getDay() + 6) % 7][0];
  const inDays = (s.days || []).indexOf(dayName) >= 0;
  const prevName = DAYS[(nowDate.getDay() + 5) % 7][0];
  const inPrevDays = (s.days || []).indexOf(prevName) >= 0;
  const cur = String(nowDate.getHours()).padStart(2, "0") + ":" + String(nowDate.getMinutes()).padStart(2, "0");
  const a = String(s.start || "");
  const b = String(s.end || "");
  const inWindow = a <= b
    ? (inDays && a <= cur && cur < b)
    : ((inDays && cur >= a) || (inPrevDays && cur < b));
  const target = s.action === "allow" ? inWindow : !inWindow;
  out.tone = target ? "ok" : "neutral";
  out.verdict = (inWindow ? t("v2_au_dec_in_window") : t("v2_au_dec_out_window"))
    + " → " + (target ? t("gui_rs_enable_label") : t("gui_rs_disable_label"));
  return out;
}

// ── rules sub-view mount ───────────────────────────────────────────────────

async function mountRules(root, ctx) {
  const handles = {};
  // Registered synchronously, before the first await (Task 7 report §9.6).
  drawer.registerAudit("au-sched-ruleset", function () { return handles.openRuleset ? handles.openRuleset() : null; });
  drawer.registerAudit("au-sched-rule", function () { return handles.openRule ? handles.openRule() : null; });
  modal.registerAudit("au-sched-delete", function () { return handles.confirmDelete ? handles.confirmDelete() : null; });
  palette.registerFor(R_RULES, cmdSpec("au:check", t("gui_rs_run_check"), function () { if (handles.check) handles.check(); }));
  palette.registerFor(R_RULES, cmdSpec("au:sched-rs", t("gui_rs_schedule_rs_btn"), function () { if (handles.openRuleset) handles.openRuleset(); }));
  palette.registerFor(R_RULES, cmdSpec("au:clear-log", t("gui_rs_clear"), function () { if (handles.clearLog) handles.clearLog(); }));

  root.appendChild(areaTop(R_RULES));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "rule scheduler (" + RULE_SNAPS.length + ")",
    function () { return loadAll(RULE_SNAPS); },
    function (d) {
      if (ctx.stale()) return;

      const state = {};
      state.schedules = (Array.isArray(d.rs_schedules) ? d.rs_schedules : []).map(copyOf);
      state.rulesets = ((d.rs_rulesets && d.rs_rulesets.items) || []).map(copyOf);
      state.detail = d.rs_ruleset_detail || null;
      state.selected = state.detail && state.detail.ruleset ? String(state.detail.ruleset.id) : "";
      state.search = "";
      state.scope = "id";
      state.page = 0;
      state.picked = [];
      state.logShown = 20;

      const detailId = state.detail && state.detail.ruleset ? String(state.detail.ruleset.id) : "";

      board.appendChild(el("p", { class: "note", text: t("v2_au_rules_intro") }));

      const row1 = el("div", { class: "brow c75" });
      const row2 = el("div", { class: "brow" });
      const row3 = el("div", { class: "brow" });
      const row4 = el("div", { class: "brow c2" });
      board.appendChild(row1);
      board.appendChild(row2);
      board.appendChild(row3);
      board.appendChild(row4);

      row1.appendChild(rulesStatus(d));
      row1.appendChild(timelinePanel(d));

      // ── AU-03 list -> detail ────────────────────────────────────────────
      const split = el("div", { class: "rsplit" });
      const listHost = el("div");
      const detailHost = el("div");
      split.appendChild(listHost);
      split.appendChild(detailHost);
      row2.appendChild(split);

      function rulesetById(id) {
        let hit = null;
        state.rulesets.forEach(function (r) { if (String(r.id) === String(id)) hit = r; });
        return hit;
      }

      function paintList() {
        clear(listHost);
        const p = panel("AU-03", t("gui_rs_browse_add"));
        const total = (d.rs_rulesets && d.rs_rulesets.total) || state.rulesets.length;
        const size = (d.rs_rulesets && d.rs_rulesets.size) || 50;
        withMeta(p, tf("v2_au_rs_meta", { total: num(total), size: num(size) }));
        p.body.classList.add("flush");

        const rows = state.rulesets.map(function (rs) {
          const r = {};
          r.mark = rs.schedule_type;
          r.id = rs.id;
          r.name = rs.name;
          r.rules = rs.rules_count;
          r.prov = rs.provision_state;
          r.on = rs.enabled;
          r._tone = rs.provision_state === "DRAFT" ? "warn" : null;
          return r;
        });
        const cols = [
          col("mark", t("gui_rs_col_sch"), widthCell(96, function (r) { return schedMark(r.mark); })),
          col("id", t("gui_rs_col_id"), widthCell(56, function (r) {
            return el("span", { class: "mono", text: String(r.id) });
          })),
          col("name", t("gui_rs_col_name"), buildCell(function (r) {
            return el("span", { class: "idc" }, el("b", { text: r.name }),
              el("small", { text: r.prov + " · " + (r.on ? "ON" : "OFF") }));
          })),
          col("rules", t("gui_rs_col_rules"), widthCell(64, function (r) {
            return el("span", { class: "mono", text: String(r.rules) });
          })),
        ];
        const handle = table.render(p.body, pagedTable(cols, rows, pageSpec(state.page, size, total),
          function (next) { state.page = next; paintList(); }));
        handle.el.querySelectorAll("tbody tr").forEach(function (tr, i) {
          tr.style.cursor = "pointer";
          tr.addEventListener("click", function () {
            state.selected = String(rows[i].id);
            paintDetail();
          });
          if (String(rows[i].id) === String(state.selected)) tr.classList.add("hl");
        });
        p.body.appendChild(el("div", { class: "panel-b" }, note(t("v2_au_rs_page_note"))));
        listHost.appendChild(p);
      }

      function paintDetail() {
        clear(detailHost);
        const rs = rulesetById(state.selected);
        const p = panel(null, rs ? rs.name : t("gui_rs_loading"));
        if (!rs) {
          p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), t("v2_au_pick_ruleset")));
          detailHost.appendChild(p);
          paintList();
          return;
        }

        withMeta(p, "ID " + rs.id);
        withAction(p, t("gui_rs_schedule_rs_btn"), function () { return handles.openRuleset(); });

        const flags = el("div", { class: "chips" });
        flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_prov") + " " }), el("b", { text: rs.provision_state })));
        flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_status") + " " }), el("b", { text: rs.enabled ? "ON" : "OFF" })));
        flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_sch") + " " }),
          el("b", { text: rs.schedule_type === 1 ? t("gui_rs_legend_rs") : (rs.schedule_type === 2 ? t("gui_rs_legend_child") : "—") })));
        flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_rules") + " " }), el("b", { text: String(rs.rules_count) })));
        p.body.appendChild(flags);

        if (String(rs.id) !== detailId) {
          // The capture list pins rs_ruleset_detail to rs_rulesets.items[0].id
          // (tests/design_v2/test_capture_snapshots.py:91-101), so exactly one
          // ruleset has a captured rule list. Saying so beats faking rules.
          p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"),
            tf("v2_au_detail_only", { id: detailId })));
          p.body.appendChild(btn("btn", tf("v2_au_open_captured", { id: detailId }), function () {
            state.selected = detailId;
            paintDetail();
          }));
          detailHost.appendChild(p);
          paintList();
          return;
        }

        // ── AU-04 rule search ──────────────────────────────────────────
        const searchPanel = el("div", { "data-cov": "AU-04" });
        const qrow = el("div", { class: "qrow" });
        const scopeSel = selectField(SEARCH_SCOPES, state.scope, function (v) { state.scope = v; paintRules(); });
        const searchIn = textField(state.search, function (v) { state.search = v.trim(); paintRules(); });
        searchIn.setAttribute("placeholder", t("gui_rs_placeholder"));
        const scopeField = el("div", { class: "qf" }, el("label", { text: t("v2_au_search_scope") }), scopeSel);
        const searchField = el("div", { class: "qf grow" }, el("label", { text: t("gui_search") }), searchIn);
        qrow.appendChild(scopeField);
        qrow.appendChild(searchField);
        qrow.appendChild(btn("btn ghost", t("gui_rs_clear"), function () {
          state.search = "";
          searchIn.value = "";
          paintRules();
        }));
        searchPanel.appendChild(qrow);
        const hits = el("p", { class: "note" });
        searchPanel.appendChild(hits);
        searchPanel.appendChild(note(t("v2_au_search_note")));
        p.body.appendChild(searchPanel);

        const rulesHost = el("div");
        p.body.appendChild(rulesHost);

        function paintRules() {
          clear(rulesHost);
          const all = (state.detail && state.detail.rules) || [];
          const shown = all.filter(function (r) { return ruleMatches(r, state.search, state.scope); });
          hits.textContent = tf("v2_au_search_hits", { hits: num(shown.length), total: num(all.length) });

          const rows = shown.map(function (r) {
            const o = copyOf(r);
            o._tone = r.provision_state === "DRAFT" ? "warn" : null;
            return o;
          });
          const cols = [
            col("no", t("gui_rs_col_no"), widthCell(48, function (r) {
              return el("span", { class: "mono", text: String(r.no || "") });
            })),
            col("id", t("gui_rs_col_id"), widthCell(64, function (r) {
              return el("span", { class: "mono", text: String(r.id) });
            })),
            col("provision_state", t("gui_rs_col_prov"), widthCell(78, function (r) { return provBadge(r.provision_state); })),
            col("enabled", t("gui_rs_col_status"), widthCell(64, function (r) { return onOffBadge(r.enabled); })),
            col("is_scheduled", t("gui_rs_col_sch"), widthCell(88, function (r) {
              return r.is_scheduled ? badge(t("gui_rs_sch_badge_child"), "info") : el("span", { class: "mono", text: "—" });
            })),
            col("rule_type", t("gui_rs_col_rule_type"), widthCell(124, function (r) {
              return badge(t("gui_rs_rule_type_" + (r.rule_type || "allow")), r.rule_type === "allow" ? "ok" : "crit");
            })),
            col("description", t("gui_rs_col_desc"), buildCell(function (r) {
              return el("span", { class: "idc" },
                el("b", { text: r.description || t("gui_rs_no_desc") }),
                el("small", { title: r.source + " → " + r.dest, text: r.source + " → " + r.dest }));
            })),
            col("service", t("gui_rs_col_service"), widthCell(150, function (r) { return r.service || t("gui_rs_all"); })),
            col("act", t("gui_rs_col_action"), widthCell(84, function (r) {
              return btn("btn", t("gui_rs_schedule_btn"), function () { openRuleDrawer(r); });
            })),
          ];
          const box = el("div", { class: "tblbox" });
          rulesHost.appendChild(box);
          table.render(box, buildTable(cols, rows));
          if (!rows.length) rulesHost.appendChild(note(t("gui_rs_no_results")));
        }

        paintRules();
        detailHost.appendChild(p);
        paintList();
      }

      // ── the two drawers ────────────────────────────────────────────────
      function targetSpec(href, name, detailRs, provState) {
        const o = {};
        o.href = href;
        o.name = name;
        o.detail_rs = detailRs;
        o.provision_state = provState;
        return o;
      }

      function openRulesetDrawer() {
        const rs = rulesetById(state.selected) || state.rulesets[0] || {};
        const target = targetSpec(rs.href || "", rs.name || "", rs.name || "", rs.provision_state);
        target.detail_src = t("gui_rs_all");
        target.detail_dst = t("gui_rs_all");
        target.detail_svc = t("gui_rs_all");
        target.existing = existingFor(rs.href);
        return drawer.open(scheduleDrawerBody(target, "AU-05", function () { paintSchedules(); }));
      }

      function openRuleDrawer(rule) {
        const rs = (state.detail && state.detail.ruleset) || {};
        const r = rule || ((state.detail && state.detail.rules) || [])[0] || {};
        const target = targetSpec(r.href || "", r.description || (t("gui_rs_type_rule") + " " + r.id),
          rs.name || "", r.provision_state);
        target.detail_src = r.source || t("gui_rs_all");
        target.detail_dst = r.dest || t("gui_rs_all");
        target.detail_svc = r.service || t("gui_rs_all");
        target.existing = existingFor(r.href);
        return drawer.open(scheduleDrawerBody(target, "AU-06", function () { paintSchedules(); }));
      }

      function existingFor(href) {
        let hit = null;
        state.schedules.forEach(function (s) { if (href && s.href === href) hit = s; });
        return hit;
      }

      handles.openRuleset = openRulesetDrawer;
      handles.openRule = function () {
        // The audit opener needs the rule-level drawer even before a row is
        // clicked: it opens it on the one_time schedule's own target when that
        // rule is in the captured detail, else on the first captured rule.
        const rules = (state.detail && state.detail.rules) || [];
        let pick = rules[0] || null;
        state.schedules.forEach(function (s) {
          if (targetKind(s) !== "rule") return;
          rules.forEach(function (r) { if (r.href === s.href) pick = r; });
        });
        return openRuleDrawer(pick);
      };

      // ── AU-08 schedule list ────────────────────────────────────────────
      const schedHost = el("div");
      row3.appendChild(schedHost);

      function paintSchedules() {
        clear(schedHost);
        const p = panel("AU-08", t("gui_rs_schedules"));
        const kinds = state.schedules.map(targetKind);
        withMeta(p, tf("v2_au_sched_meta", {
          total: num(state.schedules.length),
          rulesets: num(kinds.filter(function (k) { return k === "ruleset"; }).length),
          rules: num(kinds.filter(function (k) { return k === "rule"; }).length),
        }));
        withAction(p, t("gui_rs_delete_selected"), function () { return handles.confirmDelete(); });
        p.body.classList.add("flush");

        const rows = state.schedules.map(function (s) { return copyOf(s); });
        const cols = [
          col("pick", "", widthCell(34, function (r) {
            const box = el("input", { type: "checkbox" });
            box.checked = state.picked.indexOf(r.href) >= 0;
            box.addEventListener("change", function () {
              state.picked = state.picked.filter(function (h) { return h !== r.href; });
              if (box.checked) state.picked.push(r.href);
            });
            return box;
          })),
          col("target", t("gui_rs_target"), widthCell(230, function (r) {
            // The guard binds each rendered row back to its own snapshot entry
            // by data-sched-id (== href) before it asserts data-sched-target-kind
            // — a same-size kind swap must not be able to hide behind a set
            // comparison (tests/design_v2/test_rule_scheduler_model.py).
            const kind = targetKind(r);
            const cell = el("span", {
              class: "idc", "data-sched-target-kind": kind,
              "data-sched-id": r.href || "", title: r.href || "",
            });
            cell.appendChild(el("b", { text: r.detail_name || r.name || "" }));
            // A rule target names its parent ruleset here; a ruleset target's
            // name is already the line above, so it names only its id.
            cell.appendChild(el("small", {
              text: kind === "rule"
                ? (targetLabel(r) + " · " + (r.detail_rs || "—") + " · #" + (r.id || ""))
                : (targetLabel(r) + " · #" + (r.id || "")),
            }));
            if (targetMismatch(r)) cell.appendChild(el("small", { "data-tone": "crit", text: t("v2_au_kind_mismatch") }));
            return cell;
          })),
          col("recon", t("v2_au_recon"), widthCell(96, function (r) { return reconCell(r); })),
          col("action", t("gui_rs_col_action"), widthCell(84, function (r) { return actionCell(r); })),
          col("timing", t("gui_rs_col_timing"), widthCell(240, function (r) {
            return el("span", { class: "mono", title: timingText(r), text: timingText(r) });
          })),
          col("scope", t("gui_rs_col_source"), buildCell(function (r) {
            return el("span", { class: "idc" },
              el("b", { title: r.detail_src + " → " + r.detail_dst, text: r.detail_src + " → " + r.detail_dst }),
              el("small", { title: r.detail_svc || "", text: r.detail_svc || "" }));
          })),
          col("last", t("gui_rs_th_last_run"), widthCell(190, function (r) { return lastRunCell(r); })),
          col("edit", t("gui_rs_col_edit"), widthCell(70, function (r) {
            return btn("btn", t("gui_rs_col_edit"), function () {
              const target = targetSpec(r.href, r.detail_name || r.name || "", r.detail_rs || "", null);
              target.detail_src = r.detail_src;
              target.detail_dst = r.detail_dst;
              target.detail_svc = r.detail_svc;
              target.existing = r;
              drawer.open(scheduleDrawerBody(target, targetKind(r) === "rule" ? "AU-06" : "AU-05", function () { paintSchedules(); }));
            });
          })),
        ];
        rows.forEach(function (r) {
          r._tone = r.pce_status === "deleted" ? "crit" : (r.last_result === "error" ? "warn" : null);
        });
        table.render(p.body, buildTable(cols, rows));
        const foot = el("div", { class: "panel-b" });
        foot.appendChild(note(t("v2_au_recon_note")));
        foot.appendChild(note(t("v2_au_kind_note")));
        p.body.appendChild(foot);
        schedHost.appendChild(p);
      }

      handles.confirmDelete = function () {
        const picked = state.picked.length ? state.picked : state.schedules.map(function (s) { return s.href; });
        const impact = [tf("v2_au_del_i_count", { n: num(picked.length) })];
        picked.slice(0, 4).forEach(function (href) {
          const s = existingFor(href) || {};
          impact.push(targetLabel(s) + " · " + (s.detail_name || s.name || href));
        });
        impact.push(t("v2_au_del_i_note"));
        impact.push(t("v2_au_del_i_fail"));
        return modal.confirm(confirmSpec(t("gui_rs_delete_selected"), impact, function () {
          state.schedules = state.schedules.filter(function (s) { return picked.indexOf(s.href) < 0; });
          state.picked = [];
          paintSchedules();
          toast.ok(tf("gui_rs_deleted", { count: picked.length }));
          return true;
        }));
      };

      // ── AU-09 立即檢查 + AU-10 執行紀錄 ────────────────────────────────
      const checkPanel = panel("AU-09", t("gui_rs_run_check"));
      const previewHost = el("div");
      checkPanel.body.appendChild(note(t("v2_au_check_real")));
      checkPanel.body.appendChild(verifyPane(el("pre", { class: "codepane", text: t("v2_au_check_flow") })));
      checkPanel.body.appendChild(previewHost);

      function paintPreview(show) {
        clear(previewHost);
        if (!show) {
          previewHost.appendChild(el("div", { class: "empty" },
            el("span", { class: "et", text: t("gui_rs_log_ready") }),
            el("p", { text: t("v2_au_check_empty") })));
          return;
        }
        const now = new Date();
        previewHost.appendChild(sectionHead(t("v2_au_dec_title")));
        previewHost.appendChild(note(tf("v2_au_dec_clock", { now: stamp(now.toISOString()) })));
        const list = el("ul", { class: "stack" });
        state.schedules.forEach(function (s) {
          const rs = rulesetById(s.id);
          const draft = !!(rs && rs.provision_state === "DRAFT");
          const v = decide(s, now, draft);
          const li = el("li", { "data-tone": v.tone });
          li.appendChild(el("span", { class: "dot" }));
          li.appendChild(el("span", { class: "s" }, el("b", { text: v.name }),
            el("code", { text: v.kind })));
          li.appendChild(el("span", { class: "c", text: v.verdict }));
          list.appendChild(li);
        });
        previewHost.appendChild(list);
        previewHost.appendChild(note(t("v2_au_dec_note")));
      }
      paintPreview(false);
      handles.check = function () {
        paintPreview(true);
        toast.info(t("v2_au_check_toast"));
      };
      withAction(checkPanel, t("gui_rs_run_check"), handles.check);
      row4.appendChild(checkPanel);

      const logPanel = panel("AU-10", t("gui_rs_logs"));
      const logPane = el("pre", { class: "console" });
      const history = (d.rs_logs && d.rs_logs.history) || [];
      withMeta(logPanel, tf("v2_au_log_meta", { n: num(history.length) }));

      function paintLog() {
        // rule-scheduler.js:651-676 (rsLoadLogHistory) — newest first, each entry
        // headed by "═══ timestamp ═══" then its own lines.
        if (!history.length) {
          logPane.textContent = t("gui_rs_execution_history_empty");
          logPane.dataset.empty = "true";
          return;
        }
        const lines = [];
        const start = Math.max(0, history.length - state.logShown);
        for (let i = history.length - 1; i >= start; i--) {
          lines.push("═══ " + history[i].timestamp + " ═══");
          (history[i].logs || []).forEach(function (l) { lines.push(l); });
          lines.push("");
        }
        logPane.dataset.empty = "false";
        logPane.textContent = lines.join("\n");
      }
      paintLog();
      handles.clearLog = function () {
        // rule-scheduler.js:640-643 (rsClearLog) — this empties the pane only.
        logPane.textContent = "";
        logPane.dataset.empty = "true";
        toast.info(t("v2_au_log_clear_note"));
      };
      withAction(logPanel, t("gui_rs_clear"), handles.clearLog);
      logPanel.body.appendChild(logPane);
      const logFoot = el("div", { class: "qrow" });
      logFoot.appendChild(btn("btn ghost", t("gui_load_more"), function () {
        state.logShown += 20;
        paintLog();
      }));
      logFoot.appendChild(spacer());
      logFoot.appendChild(el("span", { class: "mono", text: "GET /api/rule_scheduler/logs" }));
      logPanel.body.appendChild(logFoot);
      logPanel.body.appendChild(note(t("v2_au_log_cap")));
      row4.appendChild(logPanel);

      paintDetail();
      paintSchedules();
    });
}

// ═══════════════════════════════════════════════════ reports sub-view ═══════

/** dashboard.js:331 pattern applied to day_of_week: the translated label for a
 * known value, the raw stored value for an outlier (an unrecognised day stays
 * visible instead of rendering blank). */
function dowLabel(v) {
  const key = lookup(DOW, v, "");
  return key ? t(key) : String(v || "");
}

/* dashboard.js:330-370 (renderSchedules) — the frequency column is one string:
 * the base word, then the weekday for weekly / the day number for monthly, then
 * HH:MM and the timezone label. Transcribed. */
function freqText(s) {
  let out = t(lookup(FREQS, s.schedule_type, "gui_sched_freq_weekly"));
  if (s.schedule_type === "weekly") out += " (" + dowLabel(s.day_of_week) + ")";
  else if (s.schedule_type === "monthly") out += " (" + t("gui_sched_day_of_month") + " " + (s.day_of_month || 1) + ")";
  const tz = s.timezone && s.timezone !== "local" ? s.timezone : t("gui_rs_local_tz");
  out += " " + String(s.hour || 0).padStart(2, "0") + ":" + String(s.minute || 0).padStart(2, "0") + " (" + tz + ")";
  return out;
}

/* dashboard.js:347-351 — the status column. `running` is a state the GUI writes
 * itself before it starts the thread (reports.py:1203). */
function schedStatus(s) {
  if (s.last_status === "success") return badge(t("gui_sched_status_success"), "ok");
  if (s.last_status === "failed") return badge(t("gui_sched_status_failed"), "crit");
  if (s.last_status === "running") return badge(t("sched_running"), "info");
  return badge(t("gui_sched_status_never"), "neutral");
}

/* AU-11 — the CRUD drawer. Every key report_schedules.json carries appears here
 * with data-field. Editable = what saveSchedule() actually sends
 * (dashboard.js:441-475); everything else is listed read-only with its origin,
 * because a field dropped from the form is a field the operator can no longer
 * see. */
function reportDrawerBody(sched, onSaved) {
  const body = el("div", { "data-cov": "AU-11" });
  const s = copyOf(sched || {});
  const state = {};
  state.name = s.name || "";
  state.report_type = s.report_type || "traffic";
  state.schedule_type = s.schedule_type || "weekly";
  state.day_of_week = s.day_of_week || "monday";
  state.day_of_month = s.day_of_month === undefined ? 1 : s.day_of_month;
  state.hour = s.hour === undefined ? 8 : s.hour;
  state.minute = s.minute === undefined ? 0 : s.minute;
  state.timezone = s.timezone || "local";
  state.lookback_days = s.lookback_days === undefined ? 7 : s.lookback_days;
  state.max_reports = s.max_reports === undefined ? 30 : s.max_reports;
  state.format = (s.format && s.format.length > 1) ? "all" : ((s.format && s.format[0]) || "html");
  state.email_report = !!s.email_report;
  state.email_recipients = (s.email_recipients || []).join("\n");
  state.cron_expr = s.cron_expr || "";
  state.enabled = s.enabled !== false;

  body.appendChild(editField("name", t("gui_sched_name"),
    textField(state.name, function (v) { state.name = v; }), t("gui_sched_name_placeholder")));
  // The stored type stays selectable even when the product's own option list
  // does not contain it — dropping it here is how a saved schedule silently
  // changes what it reports.
  const typePairs = REPORT_TYPES.map(function (pair) { return [pair[0], t(pair[1])]; });
  if (!knownReportType(state.report_type)) {
    typePairs.unshift([state.report_type, state.report_type + " ⚠"]);
  }
  body.appendChild(editField("report_type", t("gui_sched_report_type"),
    selectLiteral(typePairs, state.report_type, function (v) {
      state.report_type = v;
      syncType();
    })));
  // Only a STORED type can be off-list; a new schedule has none yet.
  if (s.report_type && !knownReportType(s.report_type)) {
    body.appendChild(note(tf("v2_au_rep_type_unknown", { type: s.report_type })));
  }

  const filterNote = el("p", { class: "note" });
  body.appendChild(filterNote);

  body.appendChild(editField("schedule_type", t("gui_sched_freq"),
    selectField(FREQS, state.schedule_type, function (v) {
      state.schedule_type = v;
      syncFreq();
    })));

  // Same keep-and-flag treatment as report_type above: a stored day_of_week
  // outside the product's seven values stays selectable and marked ⚠ instead
  // of being silently normalized into one of them.
  const dowPairs = DOW.map(function (pair) { return [pair[0], t(pair[1])]; });
  if (!knownDayOfWeek(state.day_of_week)) {
    dowPairs.unshift([state.day_of_week, state.day_of_week + " ⚠"]);
  }
  const dowBox = editField("day_of_week", t("gui_sched_day_of_week"),
    selectLiteral(dowPairs, state.day_of_week, function (v) { state.day_of_week = v; }));
  const domBox = editField("day_of_month", t("gui_sched_day_of_month"),
    textField(state.day_of_month, function (v) { state.day_of_month = v; }, "number"));
  body.appendChild(dowBox);
  if (s.day_of_week && !knownDayOfWeek(s.day_of_week)) {
    body.appendChild(note(tf("v2_au_dow_unknown", { value: s.day_of_week })));
  }
  body.appendChild(domBox);

  body.appendChild(editField("hour", t("gui_sched_hour_prefix"),
    textField(state.hour, function (v) { state.hour = v; }, "number")));
  body.appendChild(editField("minute", t("gui_sched_minute"),
    textField(state.minute, function (v) { state.minute = v; }, "number")));
  body.appendChild(editField("timezone", t("gui_rs_timezone"),
    textField(state.timezone, function (v) { state.timezone = v; })));
  body.appendChild(editField("lookback_days", t("gui_sched_lookback"),
    textField(state.lookback_days, function (v) { state.lookback_days = v; }, "number")));
  body.appendChild(editField("max_reports", t("gui_sched_max_reports"),
    textField(state.max_reports, function (v) { state.max_reports = v; }, "number"),
    t("gui_sched_max_reports_hint")));
  body.appendChild(editField("format", t("gui_sched_format"),
    selectField(FORMATS, state.format, function (v) { state.format = v; }), t("v2_au_fmt_hint")));

  const mailCtl = checkField(state.email_report, function (on) {
    state.email_report = on;
    syncMail();
  });
  mailCtl.dataset.field = "email_report";
  body.appendChild(labelled(t("gui_sched_email"), mailCtl));
  const recips = el("textarea", { class: "field ta", rows: "3" });
  recips.value = state.email_recipients;
  recips.dataset.field = "email_recipients";
  recips.addEventListener("input", function () { state.email_recipients = recips.value; });
  const recipBox = labelled(t("gui_sched_recipients"), recips, t("gui_sched_recipients_hint"));
  body.appendChild(recipBox);

  body.appendChild(editField("cron_expr", t("gui_sched_cron_expr"),
    textField(state.cron_expr, function (v) { state.cron_expr = v; }), t("gui_sched_cron_expr_hint")));

  body.appendChild(sectionHead(t("v2_au_stored_fields")));
  body.appendChild(roList([
    roField("id", s.id, t("v2_au_ro_sched_id")),
    roField("enabled", String(state.enabled), t("v2_au_ro_enabled")),
    roField("last_run", s.last_run, t("v2_au_ro_state")),
    roField("last_status", s.last_status, t("v2_au_ro_state")),
    roField("last_error", s.last_error, t("v2_au_ro_state")),
  ]));

  function syncFreq() {
    // dashboard.js:374-381 (onSchedFreqChange) — weekly shows the weekday row,
    // monthly the day-of-month row, daily neither.
    dowBox.style.display = state.schedule_type === "weekly" ? "" : "none";
    domBox.style.display = state.schedule_type === "monthly" ? "" : "none";
  }
  function syncMail() {
    // dashboard.js:391-393 (onSchedEmailChange)
    recipBox.style.display = state.email_report ? "" : "none";
  }
  function syncType() {
    // dashboard.js:383-389 (onSchedReportTypeChange) — the traffic filter block
    // and the app/env row only exist for some report types. The mockup states
    // the rule instead of porting the FilterBar into this drawer a second time.
    filterNote.textContent = TRAFFIC_PROFILE_TYPES.indexOf(state.report_type) >= 0
      ? t("v2_au_rep_filters_on")
      : (state.report_type === "app_summary" ? t("v2_au_rep_app_on") : t("v2_au_rep_filters_off"));
  }
  syncFreq();
  syncMail();
  syncType();

  const errLine = el("p", { class: "note", "data-tone": "crit" });
  body.appendChild(errLine);

  return drawerSpec(
    sched ? t("gui_sched_modal_edit") : t("gui_sched_modal_add"),
    body,
    function () {
      // dashboard.js:441-443 — the only client-side check the product makes.
      if (!String(state.name).trim()) {
        errLine.textContent = t("gui_msg_name_required");
        errLine.scrollIntoView({ block: "center" });
        return false;
      }
      errLine.textContent = "";
      if (onSaved) onSaved(state);
      toast.info(t("v2_au_mock_save"));
      return true;
    }
  );
}

async function mountReports(root, ctx) {
  const handles = {};
  drawer.registerAudit("au-report-sched", function () { return handles.open ? handles.open() : null; });
  modal.registerAudit("au-report-delete", function () { return handles.confirmDelete ? handles.confirmDelete() : null; });
  palette.registerFor(R_REPORTS, cmdSpec("au:add-sched", t("gui_sched_add"), function () { if (handles.open) handles.open(null); }));

  root.appendChild(areaTop(R_REPORTS));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "report schedules (" + REPORT_SNAPS.length + ")",
    function () { return loadAll(REPORT_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      const state = {};
      state.schedules = ((d.report_schedules && d.report_schedules.schedules) || []).map(copyOf);
      state.selected = state.schedules.length ? state.schedules[0].id : null;

      board.appendChild(el("p", { class: "note", text: t("v2_au_reports_intro") }));
      const row1 = el("div", { class: "brow" });
      const row2 = el("div", { class: "brow c2" });
      board.appendChild(row1);
      board.appendChild(row2);

      const listHost = el("div");
      row1.appendChild(listHost);

      function selected() {
        let hit = null;
        state.schedules.forEach(function (s) { if (s.id === state.selected) hit = s; });
        return hit;
      }

      handles.open = function (sched) {
        const target = sched === undefined ? selected() : sched;
        return drawer.open(reportDrawerBody(target, function (form) {
          if (!target) {
            const created = copyOf(form);
            created.id = Date.now();
            created.enabled = true;
            state.schedules.push(created);
          } else {
            Object.keys(form).forEach(function (k) { target[k] = form[k]; });
          }
          paintList();
        }));
      };

      handles.confirmDelete = function () {
        const s = selected();
        if (!s) return null;
        return modal.confirm(confirmSpec(tf("gui_sched_confirm_delete", { name: s.name || "" }),
          [t("v2_au_rep_del_i1"), t("v2_au_rep_del_i2"), t("v2_au_mock_delete")], function () {
            state.schedules = state.schedules.filter(function (x) { return x.id !== s.id; });
            state.selected = state.schedules.length ? state.schedules[0].id : null;
            paintList();
            toast.ok(t("gui_sched_deleted"));
            return true;
          }));
      };

      function paintList() {
        clear(listHost);
        const p = panel("AU-11", t("gui_tab_report_schedules"));
        withMeta(p, tf("v2_au_rep_meta", {
          total: num(state.schedules.length),
          on: num(state.schedules.filter(function (s) { return s.enabled; }).length),
        }));
        withAction(p, t("gui_sched_add"), function () { handles.open(null); });
        p.body.classList.add("flush");

        if (!state.schedules.length) {
          p.body.classList.remove("flush");
          p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), t("gui_sched_empty")));
          listHost.appendChild(p);
          return;
        }

        const rows = state.schedules.map(function (s) {
          const r = copyOf(s);
          r._tone = s.last_status === "failed" ? "crit" : null;
          return r;
        });
        const cols = [
          col("name", t("gui_sched_col_name"), buildCell(function (r) {
            return el("span", { class: "idc" }, el("b", { text: r.name || "" }),
              el("small", { text: "#" + r.id }));
          })),
          col("report_type", t("gui_sched_col_type"), widthCell(160, function (r) {
            const box = el("span", { class: "idc" });
            box.appendChild(el("b", { text: reportTypeLabel(r.report_type) }));
            if (!knownReportType(r.report_type)) {
              box.appendChild(el("small", { "data-tone": "warn", text: t("v2_au_rep_type_off_list") }));
            }
            return box;
          })),
          col("freq", t("gui_sched_col_freq"), widthCell(230, function (r) {
            const box = el("span", { class: "idc" });
            box.appendChild(el("span", { class: "mono", title: freqText(r), text: freqText(r) }));
            // Same off-list flag as the report_type column: an outlier
            // day_of_week is exactly the kind of value the product's own
            // strftime match (report_scheduler.py:259) can never satisfy.
            if (r.schedule_type === "weekly" && !knownDayOfWeek(r.day_of_week)) {
              box.appendChild(el("small", { "data-tone": "warn", text: t("v2_au_dow_off_list") }));
            }
            return box;
          })),
          col("last_run", t("gui_sched_col_last"), widthCell(130, function (r) {
            return el("span", { class: "mono", text: r.last_run ? stamp(r.last_run) : t("gui_sched_status_never") });
          })),
          col("last_status", t("gui_sched_col_status"), widthCell(96, function (r) { return schedStatus(r); })),
          col("enabled", t("gui_sched_col_enabled"), widthCell(74, function (r) {
            return badge(r.enabled ? t("sched_enabled_short") : t("sched_disabled_short"), r.enabled ? "ok" : "neutral");
          })),
          col("act", t("gui_sched_col_actions"), widthCell(230, function (r) {
            const box = el("div", { class: "rowacts", "data-cov": "AU-12" });
            box.appendChild(btn("btn", t("gui_sched_edit"), function () {
              state.selected = r.id;
              handles.open(selected());
            }));
            box.appendChild(btn("btn", r.enabled ? t("gui_sched_disable") : t("gui_sched_enable"), function () {
              // dashboard.js:499-505 — POST /toggle then reload the list.
              const live = selectedById(r.id);
              if (live) live.enabled = !live.enabled;
              paintList();
              toast.info(t("gui_sched_toggled") + " · " + t("v2_au_mock_toggle"));
            }));
            box.appendChild(btn("btn primary", t("gui_sched_run"), function () {
              state.selected = r.id;
              runNow(r.id);
            }));
            box.appendChild(btn("btn danger", t("gui_delete"), function () {
              state.selected = r.id;
              handles.confirmDelete();
            }));
            return box;
          })),
        ];
        const handle = table.render(p.body, buildTable(cols, rows));
        handle.el.querySelectorAll("tbody tr").forEach(function (tr, i) {
          tr.addEventListener("click", function () {
            state.selected = rows[i].id;
            paintHistory();
            paintList();
          });
          if (rows[i].id === state.selected) tr.classList.add("hl");
        });
        listHost.appendChild(p);
      }

      function selectedById(id) {
        let hit = null;
        state.schedules.forEach(function (s) { if (s.id === id) hit = s; });
        return hit;
      }

      function runNow(id) {
        // dashboard.js:517-525 — POST /run answers immediately; the run itself is
        // a daemon thread (reports.py:1204-1217) which writes running -> success
        // / failed into the state file, so the product just reloads 3s later.
        const s = selectedById(id);
        if (!s) return;
        s.last_status = "running";
        paintList();
        paintHistory();
        toast.info(t("gui_sched_run_ok") + " · " + t("v2_au_mock_run"));
      }

      // ── AU-12 history ─────────────────────────────────────────────────
      const histHost = el("div");
      row2.appendChild(histHost);

      function paintHistory() {
        clear(histHost);
        const p = panel(null, t("v2_au_rep_history"));
        const s = selected();
        const entries = (d.report_sched_history && d.report_sched_history.history) || [];
        withMeta(p, tf("v2_au_rep_hist_meta", { n: num(entries.length) }));
        if (s) {
          p.body.appendChild(kv(t("gui_sched_col_name"), s.name || "—"));
          p.body.appendChild(kv(t("gui_sched_col_last"), s.last_run ? stamp(s.last_run) : t("gui_sched_status_never")));
          p.body.appendChild(kv(t("gui_sched_col_status"), s.last_status || t("gui_sched_status_never")));
          p.body.appendChild(kv("last_error", s.last_error || "—"));
        }
        if (!entries.length) {
          p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), t("v2_au_rep_hist_empty")));
        } else {
          const list = el("ul", { class: "stack" });
          entries.forEach(function (e) {
            const li = el("li", { "data-tone": tone(e.status) });
            li.appendChild(el("span", { class: "dot" }));
            li.appendChild(el("span", { class: "s", text: stamp(e.last_run || e.timestamp || "") }));
            li.appendChild(el("span", { class: "c", text: e.status || "" }));
            list.appendChild(li);
          });
          p.body.appendChild(list);
        }
        p.body.appendChild(note(t("v2_au_rep_hist_note")));
        histHost.appendChild(p);
      }

      // the schedule tick job, so the reader can see what drives this page
      const tickPanel = panel(null, t("v2_au_rep_tick"));
      tickPanel.body.appendChild(note(t("v2_au_rep_tick_note")));
      tickPanel.body.appendChild(kv("tick_report_schedules", "60s"));
      const tickRow = el("div", { class: "qrow" });
      tickRow.appendChild(btn("btn", t("v2_health_goto") + " " + R_JOBS, function () { router.go(R_JOBS); }));
      tickPanel.body.appendChild(tickRow);
      row2.appendChild(tickPanel);

      paintList();
      paintHistory();
    });
}

// ══════════════════════════════════════════════════════ jobs sub-view ═══════

/* AU-13 — integrations.js:1504-1541 (_buildOvJobHealth) is the whole product
 * view: five columns and a coloured dot, with the backend's `level` as the
 * verdict (comment at :1502-1503 — error = last run failed, warn = never ran or
 * overdue, ok = healthy) and gui_jh_overdue appended only when a warn job HAS a
 * last_run (:1513-1515). The interval is printed h / m / s (:1517-1521).
 *
 * This view is the operational one: the same 14 rows, plus a beat meter and a
 * projected next run. Both extras are DESIGN-ADDED and both are arithmetic on
 * fields already in the payload — age = as_of - last_run, next = last_run +
 * interval_seconds. Nothing here re-judges `level`; the meter only shows the
 * distance the backend's verdict was computed from. */
function jobAge(job, asOf) {
  const a = Date.parse(job.last_run);
  const b = Date.parse(asOf);
  if (!isFinite(a) || !isFinite(b)) return null;
  return (b - a) / 1000;
}

function beatMeter(ratio) {
  const box = el("div", { class: "beat" });
  const clamped = Math.max(0, Math.min(ratio === null ? 0 : ratio, 1.6));
  box.appendChild(el("i", { style: "width:" + (clamped / 1.6 * 100) + "%" }));
  box.appendChild(el("u", { style: "left:" + (1 / 1.6 * 100) + "%" }));
  return box;
}

async function mountJobs(root, ctx) {
  const handles = {};
  palette.registerFor(R_JOBS, cmdSpec("au:jobs-bad", t("v2_au_job_only_bad"), function () { if (handles.onlyBad) handles.onlyBad(); }));

  root.appendChild(areaTop(R_JOBS));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "job health (" + JOB_SNAPS.length + ")",
    function () { return loadAll(JOB_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      const ov = d.dashboard_overview || {};
      const jobs = (ov.job_health || []).map(copyOf);
      const state = {};
      state.onlyBad = false;

      board.appendChild(el("p", { class: "note", text: t("v2_au_jobs_intro") }));
      const row1 = el("div", { class: "brow" });
      const row2 = el("div", { class: "brow" });
      board.appendChild(row1);
      board.appendChild(row2);

      const okCount = jobs.filter(function (j) { return j.level === "ok"; }).length;
      const warnCount = jobs.filter(function (j) { return j.level === "warn"; }).length;
      const errCount = jobs.filter(function (j) { return j.level === "error"; }).length;

      const head = panel("AU-13", t("gui_ov_job_health"));
      withMeta(head, tf("v2_health_jobs_ok", { ok: okCount, total: jobs.length }));
      withTone(head, errCount ? "crit" : (warnCount ? "warn" : "ok"));

      const kpi = el("div", { class: "kpirow" });
      kpi.appendChild(kpiCell(t("v2_au_job_total"), num(jobs.length), null, t("v2_au_job_total_note")));
      kpi.appendChild(kpiCell(t("gui_status_ok"), num(okCount), "/" + jobs.length, t("v2_au_job_ok_note")));
      kpi.appendChild(kpiCell(t("gui_jh_overdue"), num(warnCount), null, t("v2_au_job_warn_note")));
      kpi.appendChild(kpiCell(t("gui_rs_error_prefix"), num(errCount), null, t("v2_au_job_err_note")));
      head.body.appendChild(kpi);
      head.body.appendChild(note(tf("v2_au_job_asof", { at: stamp(ov.as_of) })));
      head.body.appendChild(note(t("v2_au_job_level_note")));

      const filterRow = el("div", { class: "qrow" });
      const toggleBtn = btn("btn", t("v2_au_job_only_bad"), function () {
        state.onlyBad = !state.onlyBad;
        toggleBtn.setAttribute("aria-pressed", state.onlyBad ? "true" : "false");
        toggleBtn.textContent = state.onlyBad ? t("v2_au_job_all") : t("v2_au_job_only_bad");
        paintJobs();
      });
      toggleBtn.setAttribute("aria-pressed", "false");
      filterRow.appendChild(toggleBtn);
      filterRow.appendChild(spacer());
      filterRow.appendChild(el("span", { class: "mono", text: "GET /api/dashboard/overview → job_health[]" }));
      head.body.appendChild(filterRow);
      row1.appendChild(head);
      handles.onlyBad = function () { toggleBtn.click(); };

      const tableHost = el("div");
      row2.appendChild(tableHost);

      function paintJobs() {
        clear(tableHost);
        const p = panel(null, t("gui_jh_th_job"));
        p.body.classList.add("flush");
        const shown = state.onlyBad ? jobs.filter(function (j) { return j.level !== "ok"; }) : jobs;
        withMeta(p, tf("v2_table_rows", { total: num(shown.length) }));

        const rows = shown.map(function (j) {
          const r = copyOf(j);
          r._age = jobAge(j, ov.as_of);
          r._ratio = (r._age === null || !Number(j.interval_seconds)) ? null : r._age / Number(j.interval_seconds);
          r._tone = tone(j.level);
          return r;
        });
        const cols = [
          col("job_id", t("gui_jh_th_job"), widthCell(220, function (r) {
            const box = el("span", { class: "idc", "data-tone": r._tone });
            box.appendChild(el("b", { text: r.job_id }));
            box.appendChild(el("small", { text: r.detail || "" }));
            return box;
          })),
          col("last_run", t("gui_jh_th_last_run"), widthCell(190, function (r) {
            if (!r.last_run) return el("span", { class: "mono", text: t("gui_jh_never_ran") });
            return el("span", { class: "idc" }, el("b", { class: "mono", text: stamp(r.last_run) }),
              el("small", { text: since(r.last_run, ov.as_of) + " " + t("v2_au_job_ago") }));
          })),
          col("last_status", t("gui_jh_th_status"), widthCell(140, function (r) {
            const txt = (r.level === "warn" && r.last_run)
              ? ((r.last_status || "") + " · " + t("gui_jh_overdue"))
              : (r.last_status || "");
            return badge(txt || "—", r._tone);
          })),
          col("interval_seconds", t("gui_jh_th_interval"), widthCell(80, function (r) {
            return el("span", { class: "mono", text: Number(r.interval_seconds) ? dur(r.interval_seconds) : "—" });
          })),
          col("beat", t("v2_au_job_beat"), buildCell(function (r) {
            const box = el("div", { "data-tone": r._tone });
            box.appendChild(beatMeter(r._ratio));
            box.appendChild(el("small", { class: "beat-cap", text: r._ratio === null ? "—"
              : (Math.round(r._ratio * 100) + "% · " + t("v2_au_job_next") + " "
                + (r._age === null ? "—" : dur(Math.max(0, Number(r.interval_seconds) - r._age)))) }));
            return box;
          })),
        ];
        table.render(p.body, buildTable(cols, rows));
        const foot = el("div", { class: "panel-b" });
        foot.appendChild(note(t("v2_au_job_beat_note")));
        foot.appendChild(note(t("v2_au_job_hist_note")));
        p.body.appendChild(foot);
        tableHost.appendChild(p);
      }

      paintJobs();
    });
}

export { mountRules as mountAutoRules, mountReports as mountAutoReports, mountJobs as mountAutoJobs };
