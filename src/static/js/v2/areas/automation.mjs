// automation.mjs — #/automation/{rules,reports,jobs}. Anchors AU-01…AU-13
// (design/v2/coverage.yaml).
//
// PORT OF design/v2/mockup/js/areas/automation.mjs (2039 lines, frozen) against
// the live backend. Deliberate deviations from the mockup, recorded at their
// call sites below and summarised here:
//
//   1. store.load(id) -> api.load(id, params?); loadOne/loadAll isolate a
//      failed source into a `{ok:false,error}` sentinel (same convention as
//      alerting.mjs) so one dead endpoint does not blank the whole board —
//      every reader below already does safe property access with a fallback,
//      matching the mockup's own `d.rs_status || {}` style.
//   2. AU-03's `rs_ruleset_detail` is no longer fetched eagerly for only the
//      one ruleset the frozen snapshot happened to capture. It is a
//      parameterised GET_MAP entry (store-map.mjs) fetched lazily, per row
//      click, via `api.load("rs_ruleset_detail", {rs_id})` — so EVERY
//      ruleset's real rule list is reachable, not just the first page's
//      first row. The mockup's `v2_au_detail_only` / `v2_au_open_captured`
//      honesty notes existed only to explain that single-snapshot limit and
//      are dropped as obsolete.
//   3. AU-05/06/07: the mockup's client-computed `preflight()` banner
//      (pf_draft/pf_ok/pf_unknown, fabricated from a snapshot's captured
//      provision_state because a mockup cannot call the PCE) is dropped.
//      Save POSTs the real body to POST /api/rule_scheduler/schedules — the
//      one real endpoint that serves BOTH add and edit (rule_scheduler.py's
//      `db.put(href, ...)` is an upsert keyed by href) — and on failure shows
//      the REAL backend's fail-closed error text (400 href-required, 400
//      draft-block, 502 PCE-unreachable) inline in the drawer, scrolled into
//      view. That is this area's "two-level drawer's pre-check message comes
//      from the real backend response" key flow.
//   4. AU-08 bulk delete POSTs the real /api/rule_scheduler/schedules/delete
//      with the picked hrefs, then reloads rs_status + rs_schedules and
//      rebuilds the whole rules board from the fresh response — the
//      "reconcile against the list" flow.
//   5. AU-09 "立即檢查": the mockup's local decision-preview arithmetic
//      (`decide()`, transcribing rule_scheduler.py's engine so a PCE-less
//      mockup could show *something*) is dropped now that the real engine is
//      one click away. The button POSTs the real /api/rule_scheduler/check,
//      prints the returned log lines, and reloads rs_logs so AU-10 shows the
//      same run. See "Destructive-operation discipline" in the test file for
//      why this is safe to click for real.
//   6. AU-11/12 report-schedule CRUD is real POST/PUT/DELETE/toggle against
//      /api/report-schedules*; run-now stays wired to the real POST .../run
//      (AU-12 coverage requires the button to exist and call the real
//      endpoint) but this area's own e2e never clicks it.
//      report_sched_history is fetched lazily per selected schedule via
//      GET_MAP's `report_sched_history({schedule_id})`.
//   7. AU-03's ruleset-browser pager calls `api.get()` directly with a
//      page/size query string rather than being added to GET_MAP — the
//      brief's documented escape hatch for a dynamic query on an id the
//      transcribed yaml only lists as a bare path (store-map.mjs's own
//      header note already establishes this exact pattern for
//      events_viewer/workload_search).
//   8. verifyPane (design/v2/mockup/js/components/verifypane.mjs) is
//      dropped, per investigate.mjs's established precedent: a live Save
//      really is a save, so the note-preview pane above it is labelled a
//      preview in its own text, not wrapped in a mockup disclaimer.
//   9. Every repaintable region (status/timeline/ruleset browser/schedule
//      list/log pane, and the report-schedule list/history) is rebuilt from
//      scratch on every repaint (clear + fresh panel), never patched in
//      place — this is the mockup's OWN pattern for paintList/paintDetail/
//      paintSchedules, just applied uniformly so a post-CRUD reload cannot
//      grow a duplicate `.meta` span the way an in-place `withMeta()` call
//      would.
//  10. i18n: v2_au_* -> gui_au_* renamed. Keys that existed only to narrate
//      the mockup's absence of a backend (mock_save/mock_delete/mock_toggle/
//      mock_run, pf_draft/pf_ok/pf_unknown/pf_note/preflight, the dec_*
//      decision-preview set, check_flow/check_empty/check_toast,
//      kpi_snapday, detail_only/open_captured, rs_page_note) are dropped as
//      no longer true. New: gui_au_schedule_saved, gui_au_check_result,
//      gui_au_precheck_note. gui_au_tl_empty_why and gui_au_del_i_count keep
//      their key names but drop the "mockup only changes memory" / "this
//      exact snapshot" framing, since both are real now.
//  11. Each mount registers its audit openers and a synchronous,
//      self-unsubscribing router teardown (installTeardown, below): it
//      destroys every table this area created, closes drawers/modals, and
//      clears this route's palette commands — same shape as alerting.mjs's
//      installTeardown. This area has no FilterBar instances to release.
//
// FIELD CONTRACT: every backend schedule key (rule-scheduler AND
// report-scheduler) is represented in its drawer with data-field="<key>".
// Editable fields follow the real route handlers; derived/server-owned
// fields remain read-only with their provenance in the "stored fields" list,
// so a new backend key cannot be silently dropped by this port.

import { el, clear, disclosure } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { num, dur, stamp, since, tone } from "../core/fmt.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { audit } from "../core/audit.mjs";

const R_RULES = "#/automation/rules";
const R_REPORTS = "#/automation/reports";
const R_JOBS = "#/automation/jobs";

const SUB_ROUTES = [
  [R_RULES, "gui_rs_tab"],
  [R_REPORTS, "gui_tab_report_schedules"],
  [R_JOBS, "gui_ov_job_health"],
];

// The eager batch for #/automation/rules. rs_ruleset_detail is deliberately
// NOT here — see deviation #2 above; it is fetched per selected row.
const RULE_SNAPS = ["rs_status", "rs_schedules", "rs_rulesets", "rs_logs"];
const REPORT_SNAPS = ["report_schedules"];
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

// The mockup builds this key by string concatenation ("gui_rs_rule_type_" +
// r.rule_type), which scripts/audit_i18n_usage.py's static scanner cannot
// resolve to a real key (it flags the bare prefix as an undefined key,
// findings A/B/G) — same reason rule-scheduler.js:156-159 spells out all
// three literal calls instead of concatenating. lookup() here matches the
// TYPE_UNITS/PD_OPTS pattern already used by alerting.mjs for the same
// audit-visibility reason.
const RULE_TYPE_OPTS = [["allow", "gui_rs_rule_type_allow"], ["deny", "gui_rs_rule_type_deny"],
  ["override_deny", "gui_rs_rule_type_override_deny"]];

// rule-scheduler.js:421-422 (input[name=rs-sch-type]) — the two stored shapes.
// rule_scheduler.py:323-325 rejects anything else with gui_err_invalid_rule_sched_type.
const SCH_TYPES = [["recurring", "gui_rs_recurring"], ["one_time", "gui_rs_one_time"]];

// rule-scheduler.js:422 (input[name=rs-sch-action]) — recurring only.
// rule_scheduler.py:394 (engine): target = in_window for allow, NOT in_window for disable.
const SCH_ACTIONS = [["allow", "gui_rs_on_during"], ["disable", "gui_rs_off_during"]];

/* dashboard.js:317-329 (typeLabels) + index.html:1591-1603 (select#sched-report-type)
 * — the same eleven types in both places, and the list column prints the RAW
 * value for anything else (`typeLabels[s.report_type] || s.report_type`). */
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
// product's day_of_week values are the full lowercase English day names.
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
// these; this port does not re-embed a FilterBar in this drawer (see AU-11).
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

function loadOne(id, params) {
  return api.load(id, params).catch(function (e) {
    console.error("[automation] " + id + " failed to load", e);
    return { ok: false, error: String((e && e.message) || e) };
  });
}

function loadAll(ids) {
  return Promise.all(ids.map(function (id) { return loadOne(id); })).then(function (list) {
    const out = {};
    ids.forEach(function (id, i) { out[id] = list[i]; });
    return out;
  });
}

function errText(value) {
  const message = value && (value.error || value.message);
  return message ? String(message) : t("gui_err_generic");
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

/* Route as a data attribute, not visible chrome — see overview.mjs's areaHead. */
function areaHead(title, route) {
  return el("div", { class: "area-head", "data-route": route },
    el("h1", { text: title })
  );
}

function areaTop(active) {
  const head = areaHead(t("gui_nav_automation"), active);
  const nav = el("nav", { class: "subnav", "aria-label": t("gui_nav_automation") });
  SUB_ROUTES.forEach(function (pair) {
    const a = el("a", { href: pair[0], text: t(pair[1]) });
    if (pair[0] === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  head.appendChild(nav);
  return head;
}

/** Shallow copy — every mutation in this area happens on a copy, never on the
 *  cached response (a reload always starts clean). */
function copyOf(obj) {
  const out = {};
  Object.keys(obj || {}).forEach(function (k) { out[k] = obj[k]; });
  return out;
}

/** S2 — teardown is registered before the first await for every sub-route. */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    Object.keys(state.tableHandles || {}).forEach(function (k) {
      try { state.tableHandles[k].destroy(); } catch (e) { console.error("[automation] table teardown failed", e); }
    });
    state.tableHandles = {};
    drawer.closeAll();
    modal.closeAll();
    palette.setRoute(path);
  });
}

// ════════════════════════════════════════════════ the dual-target model ═════

/* A rule href is a ruleset href with one more pair of segments, and the PCE has
 * THREE rule collections: sec_rules (allow), rules (the legacy allow list) and
 * deny_rules (deny / override_deny) — rule_scheduler.py:160-166 reads all three
 * when it builds a ruleset's rule list. Matching only "/sec_rules/" would file
 * every deny-rule schedule under "ruleset". Both carriers matter, and that is
 * why a disagreement is shown instead of resolved: api_client.py:1311-1326
 * (toggle_and_provision) PUTs to the href but picks what to PROVISION from
 * is_ruleset — targetKind() answers with the href (the address that is
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

/* AU-01 — the status line and the four KPIs. rule-scheduler.js:758-851 (rsRenderKpi). */
function rulesStatus(rsStatus, history, schedules) {
  const st = rsStatus || {};

  const p = panel("AU-01", t("gui_rs_tab"));
  const count = st.schedule_count === undefined || st.schedule_count === null ? 0 : st.schedule_count;
  withMeta(p, tf("gui_au_status_meta", {
    every: dur(st.check_interval_seconds), rows: num(schedules.length),
  }));

  const strip = el("div", { class: "strip", "data-tone": "info" });
  strip.appendChild(el("span", null, el("span", { text: t("gui_rs_run_check") + " " }),
    el("b", { text: dur(st.check_interval_seconds) })));
  strip.appendChild(el("span", null, el("span", { text: t("gui_rs_kpi_next") + " " }),
    el("b", { text: String(st.next_trigger_at || "—").replace("T", " ") })));
  strip.appendChild(el("span", null, el("span", { text: t("gui_rs_schedules") + " " }),
    el("b", { text: num(count) })));
  // Density spec R4: the "GET /api/rule_scheduler/status" endpoint label that
  // used to close this strip is gone — the three real values above it are
  // the content, and this page's disclosure covers where they come from.
  p.body.appendChild(strip);

  const midnight = new Date();
  midnight.setHours(0, 0, 0, 0);
  const today = logStats(history, midnight.getTime());

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

/* rule-scheduler.js:704-757 (rsRenderTimeline). 24 buckets, one per hour, filled
 * from status.timeline_24h [{hour,count}]; a bucket's level is its share of the
 * busiest bucket and a payload with no buckets renders every cell empty. */
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

/* DESIGN-ADDED lanes: the product's own timeline can only show toggles that
 * already happened, so it says nothing about what is ARMED. Each lane plots
 * one REAL stored schedule's window on the same 24-hour ruler, straight from
 * the live rs_schedules rows — recurring windows as a band (with the midnight
 * wraparound the engine implements, rule_scheduler.py:346-353), one-time
 * schedules as a bar that runs to their expiry. */
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
        track.appendChild(el("i", { class: "tl-band", style: "left:" + pct(a) + ";width:" + pct(1440 - a) }));
        track.appendChild(el("i", { class: "tl-band", style: "left:0;width:" + pct(b) }));
      }
    }
  } else {
    track.appendChild(el("i", { class: "tl-band tl-band-open", style: "left:0;width:100%" }));
  }

  const when = s.type === "recurring"
    ? tf("gui_au_tl_days_fmt", { n: (s.days || []).length, range: (s.start || "") + "-" + (s.end || "") })
    : tf("gui_au_tl_until_fmt", { when: String(s.expire_at || "").replace("T", " ") });
  const dayList = (s.days || []).length === 7 ? t("gui_rs_everyday")
    : (s.days || []).map(function (d) { return t(lookup(DAYS, d, "")) || d; }).join(", ");
  const tip = s.type === "recurring" ? (dayList + " " + (s.start || "") + "-" + (s.end || "")) : when;

  lane.appendChild(el("span", { class: "tl-name" },
    el("b", { title: s.detail_name || s.name || "", text: s.detail_name || s.name || "" }),
    el("small", { text: targetLabel(s) + " · " + (s.detail_rs || "—") })));
  lane.appendChild(track);
  lane.appendChild(el("span", { class: "tl-when", title: tip, text: when }));
  lane.dataset.schedKind = kind;
  return lane;
}

function timelinePanel(rsStatus, schedules) {
  const st = rsStatus || {};
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
  // Density spec R4: this lane's name used to carry "timeline_24h" as a
  // sub-label — the backend field, not anything an operator reads for.
  toggles.appendChild(el("span", { class: "tl-name" },
    el("b", { text: t("gui_au_tl_toggle_row") })));
  toggles.appendChild(b.track);
  toggles.appendChild(el("span", { class: "tl-when", text: b.has ? num(b.total) : "0" }));
  wrap.appendChild(toggles);

  schedules.forEach(function (s) { wrap.appendChild(scheduleLane(s)); });
  p.body.appendChild(wrap);

  // Density spec R5: an empty ruler's "why" (when it applies) and how the
  // armed-schedule lanes read fold into one explanation instead of one or
  // two standing paragraphs under the ruler.
  p.body.appendChild(disclosure(t("gui_gen_explain"),
    b.has ? null : note(t("gui_au_tl_empty_why")),
    note(t("gui_au_tl_lane_note"))));
  return p;
}

// ── AU-05 / AU-06 / AU-07 the two schedule drawers ─────────────────────────

/* rule_scheduler.py:355-372 — the annotation written into the PCE object's own
 * description. Built in ENGLISH on purpose (:357-360: later report runs surface
 * it verbatim, so Chinese would leak into EN-mode audit reports). */
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

/** The real POST body rule_scheduler.py's create route accepts — see
 *  rule_scheduler.py:302-393. The same endpoint serves add AND edit
 *  (db.put(href, ...) upserts by href), so there is exactly one body shape. */
function scheduleBody(target, isRule, state) {
  const body = {};
  body.href = target.href;
  body.type = state.type;
  body.name = state.name;
  body.detail_name = state.name;
  body.is_ruleset = !isRule;
  body.detail_rs = target.detail_rs;
  body.detail_src = target.detail_src;
  body.detail_dst = target.detail_dst;
  body.detail_svc = target.detail_svc;
  if (state.type === "recurring") {
    body.action = state.action;
    body.days = state.days;
    body.start = state.start;
    body.end = state.end;
    body.timezone = state.timezone;
  } else {
    body.expire_at = state.expire_at;
    body.timezone = state.timezone;
  }
  return body;
}

/**
 * scheduleDrawerBody(target, cov, onSaved) — one builder, two anchors.
 *   target: {href, name, is_ruleset, detail_rs, detail_src, detail_dst,
 *            detail_svc, provision_state, existing}
 *   cov:    "AU-05" (ruleset level) or "AU-06" (rule level)
 *   onSaved(): called after a REAL save succeeds, so the caller can reload
 *              rs_status/rs_schedules and rebuild the board.
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
    target.provision_state ? badge(target.provision_state, target.provision_state === "DRAFT" ? "warn" : "ok") : null,
    el("code", { text: target.href || "" })));
  idBox.appendChild(el("b", { text: target.name || "" }));
  idBox.appendChild(el("p", { text: isRule ? t("gui_au_target_note_rule") : t("gui_au_target_note_ruleset") }));
  body.appendChild(idBox);
  body.appendChild(note(t("gui_au_precheck_note")));

  // ── form ──
  body.appendChild(sectionHead(t("gui_rs_schedule_title")));
  body.appendChild(editField("detail_name", t("gui_rs_col_name"),
    textField(state.name, function (v) { state.name = v; }), t("gui_au_name_hint")));

  const recurBox = el("div");
  const onceBox = el("div", { "data-cov": "AU-07" });

  function syncType() {
    // rule-scheduler.js:436-440 (rsSchTypeChanged) — the two field groups are
    // mutually exclusive. style.display, not [hidden]: a [hidden] element with
    // a flex/grid display rule in CSS stays visible.
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

  const actionCtl = radioGroup("au-sch-action-" + cov, SCH_ACTIONS, state.action, function (v) {
    state.action = v;
    paintNote();
  });
  actionCtl.dataset.field = "action";
  recurBox.appendChild(labelled(t("gui_rs_action_label"), actionCtl, t("gui_au_action_hint")));

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
  recurBox.appendChild(editField("end", t("gui_rs_end_time"), endCtl, t("gui_au_wrap_hint")));
  recurBox.appendChild(editField("timezone", t("gui_rs_timezone"),
    textField(state.timezone, function (v) { state.timezone = v; paintNote(); }), t("gui_au_tz_hint")));
  body.appendChild(recurBox);

  // one_time group — AU-07. index.html:2362-2372 gives one_time its OWN
  // timezone control, independent of the recurring group's.
  onceBox.appendChild(editField("expire_at", t("gui_rs_expire_at"),
    textField(state.expire_at, function (v) { state.expire_at = v; paintNote(); }, "datetime-local"),
    t("gui_rs_expire_note")));
  onceBox.appendChild(editField("timezone", t("gui_rs_timezone"),
    textField(state.timezone, function (v) { state.timezone = v; paintNote(); }), t("gui_au_tz_hint")));
  onceBox.appendChild(note(t("gui_au_expire_engine")));
  body.appendChild(onceBox);

  // ── what the PCE will carry ──
  body.appendChild(sectionHead(t("gui_au_note_preview")));
  const notePane = el("pre", { class: "codepane" });
  body.appendChild(notePane);
  body.appendChild(note(t("gui_au_note_en")));

  function paintNote() { notePane.textContent = noteText(state); }
  syncType();

  // ── the fields the form sends but never shows, and the stored-only ones ──
  body.appendChild(sectionHead(t("gui_au_stored_fields")));
  body.appendChild(roList([
    roField("href", target.href, t("gui_au_ro_href")),
    roField("is_ruleset", String(!isRule), t("gui_au_ro_is_ruleset")),
    roField("detail_rs", target.detail_rs, t("gui_au_ro_detail")),
    roField("detail_src", target.detail_src, t("gui_au_ro_detail")),
    roField("detail_dst", target.detail_dst, t("gui_au_ro_detail")),
    roField("detail_svc", target.detail_svc, t("gui_au_ro_detail")),
    roField("id", prev.id, t("gui_au_ro_id")),
    roField("last_checked", prev.last_checked, t("gui_au_ro_state")),
    roField("last_action", prev.last_action, t("gui_au_ro_state")),
    roField("last_result", prev.last_result, t("gui_au_ro_state")),
    roField("last_error", prev.last_error, t("gui_au_ro_state")),
    roField("pce_status", prev.pce_status, t("gui_au_ro_recon")),
    roField("live_enabled", prev.live_enabled, t("gui_au_ro_recon")),
    roField("live_name", prev.live_name, t("gui_au_ro_recon")),
  ]));

  const errLine = el("p", { class: "note", "data-tone": "crit" });
  body.appendChild(errLine);

  const spec = drawerSpec(
    (target.existing ? t("gui_rs_col_edit") : t("gui_rs_schedule_title")) + " · " + (target.name || ""),
    body,
    function () {
      const err = validate(state);
      if (err) {
        errLine.textContent = err;
        errLine.scrollIntoView({ block: "center" });
        return false;
      }
      errLine.textContent = "";
      const payload = scheduleBody(target, isRule, state);
      return api.post("/api/rule_scheduler/schedules", payload).then(function (result) {
        // The two-level drawer's pre-check message: a rejection here is the
        // REAL backend's fail-closed gate (href required / draft-block /
        // PCE-unreachable), not a client-side guess — see deviation #3.
        if (!result || result.ok !== true) {
          errLine.textContent = errText(result);
          errLine.scrollIntoView({ block: "center" });
          return false;
        }
        toast.ok(t("gui_au_schedule_saved"));
        if (onSaved) onSaved();
        return true;
      });
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
  mark.title = label;
  return mark;
}

function provBadge(stateStr) {
  return badge(stateStr === "DRAFT" ? "DRAFT" : "ACTIVE", stateStr === "DRAFT" ? "warn" : "ok");
}

function onOffBadge(on) {
  return badge(on ? "ON" : "OFF", on ? "ok" : "neutral");
}

/* rule_scheduler.py:144-190 (rs_rules_search) — scope 'id' is an EXACT match on
 * the extracted rule id, scope 'desc' is a case-insensitive substring. */
function ruleMatches(rule, q, scope) {
  if (!q) return true;
  const id = String(rule.id === undefined ? "" : rule.id);
  if (scope === "id") return q === id;
  return String(rule.description || "").toLowerCase().indexOf(q.toLowerCase()) >= 0;
}

// ── AU-08 schedule list ────────────────────────────────────────────────────

/* rule_scheduler.py:258-300 — the reconciliation. rule-scheduler.js:499-506
 * renders that as one badge; this column keeps the three states apart because
 * "unknown" and "deleted" are different problems. */
function reconCell(s) {
  if (s.pce_status === "deleted") return badge(t("gui_rs_status_deleted"), "crit");
  if (s.live_enabled === true) return badge("ON", "ok");
  if (s.live_enabled === false) return badge("OFF", "neutral");
  return badge(t("gui_au_recon_unknown"), "warn");
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

/* rule-scheduler.js:556-566 — the last-run cell. */
function lastRunCell(s) {
  if (!s.last_checked) return el("span", { class: "mono", text: t("gui_jh_never_ran") });
  const suffix = s.last_action ? (" (" + s.last_action + (s.last_result === "error" ? " !" : "") + ")") : "";
  const bad = s.last_result === "error";
  const span = el("span", { class: "mono", "data-tone": bad ? "crit" : null, title: bad ? (s.last_error || "") : "" });
  if (bad) span.appendChild(el("i", { class: "dot" }));
  span.appendChild(el("span", { text: stamp(s.last_checked) + suffix }));
  return span;
}

// ── rules sub-view mount ───────────────────────────────────────────────────

async function mountRules(root, ctx) {
  const handles = {};
  const state = {
    torn: false, tableHandles: {}, rsStatus: {}, rsLogHistory: [], schedules: [], rulesets: [],
    total: 0, size: 50, page: 0, detail: null, detailError: null, selected: "",
    search: "", scope: "id", picked: [], logShown: 20,
  };
  installTeardown(state);
  // AU-04 (the per-rule search panel) is plain page content, not a drawer —
  // but it only renders once a ruleset row has been SELECTED, so a DOM sweep
  // never sees it either. audit.mjs's contract is "every anchor is reachable
  // after __openAllForAudit()", and Task 11's live coverage gate
  // (tools/gate_coverage_live.py) is what found this one not honouring it.
  // Idempotent, per that contract: no-op once something is selected, and a
  // no-op when the browser is empty (no PCE, no rulesets).
  audit.register("au-rule-search", function () {
    if (state.selected || !state.rulesets.length) return;
    selectRuleset(state.rulesets[0].id);
  });
  drawer.registerAudit("au-sched-ruleset", function () { return handles.openRuleset ? handles.openRuleset() : null; });
  drawer.registerAudit("au-sched-rule", function () { return handles.openRule ? handles.openRule() : null; });
  modal.registerAudit("au-sched-delete", function () { return handles.confirmDelete ? handles.confirmDelete() : null; });
  palette.registerFor(R_RULES, cmdSpec("au:check", t("gui_rs_run_check"), function () { if (handles.check) handles.check(); }));
  palette.registerFor(R_RULES, cmdSpec("au:sched-rs", t("gui_rs_schedule_rs_btn"), function () { if (handles.openRuleset) handles.openRuleset(); }));
  palette.registerFor(R_RULES, cmdSpec("au:clear-log", t("gui_rs_clear"), function () { if (handles.clearLog) handles.clearLog(); }));

  root.appendChild(areaTop(R_RULES));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  function destroyTables() {
    Object.keys(state.tableHandles).forEach(function (k) {
      try { state.tableHandles[k].destroy(); } catch (e) { console.error("[automation] table teardown failed", e); }
    });
    state.tableHandles = {};
  }

  function rulesetById(id) {
    let hit = null;
    state.rulesets.forEach(function (r) { if (String(r.id) === String(id)) hit = r; });
    return hit;
  }

  function existingFor(href) {
    let hit = null;
    state.schedules.forEach(function (s) { if (href && s.href === href) hit = s; });
    return hit;
  }

  // ── AU-09 決定 / AU-10 log repaint targets (populated by renderBoard) ────
  let logPane = null;
  let logPanel = null;

  function paintLog() {
    if (!logPane) return;
    const history = state.rsLogHistory || [];
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
    if (logPanel) withMeta(logPanel, tf("gui_au_log_meta", { n: num(history.length) }));
  }

  function renderBoard() {
    if (state.torn) return;
    destroyTables();
    clear(board);
    // Density spec R5: the two-sentence framing note (this page acts for
    // real; the target column below states ruleset vs. rule for that reason)
    // collapses instead of standing open on every visit.
    board.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_au_rules_intro"))));

    const row1 = el("div", { class: "brow c75" });
    const row2 = el("div", { class: "brow" });
    const row3 = el("div", { class: "brow" });
    const row4 = el("div", { class: "brow c2" });
    board.appendChild(row1);
    board.appendChild(row2);
    board.appendChild(row3);
    board.appendChild(row4);

    row1.appendChild(rulesStatus(state.rsStatus, state.rsLogHistory, state.schedules));
    row1.appendChild(timelinePanel(state.rsStatus, state.schedules));

    // ── AU-03 list -> detail ────────────────────────────────────────────
    const split = el("div", { class: "rsplit" });
    const listHost = el("div");
    const detailHost = el("div");
    split.appendChild(listHost);
    split.appendChild(detailHost);
    row2.appendChild(split);

    function paintList() {
      clear(listHost);
      const p = panel("AU-03", t("gui_rs_browse_add"));
      withMeta(p, tf("gui_au_rs_meta", { total: num(state.total), size: num(state.size) }));
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
      if (!rows.length) {
        p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), null));
      }
      state.tableHandles.rulesetList = table.render(p.body,
        pagedTable(cols, rows, pageSpec(state.page, state.size, state.total), function (next) {
          // AU-03 pager — a direct api.get() call with a page/size query string;
          // see deviation #7. rule_scheduler.py:142 (rs_rulesets) is the same
          // endpoint GET_MAP's `rs_rulesets` maps, one page later.
          state.page = next;
          api.get("/api/rule_scheduler/rulesets?page=" + (next + 1) + "&size=" + state.size)
            .then(function (fresh) {
              if (state.torn) return;
              state.rulesets = ((fresh && fresh.items) || []).map(copyOf);
              state.total = (fresh && fresh.total) || state.total;
              renderBoard();
            })
            .catch(function (e) { toast.crit(errText(e && e.data ? e.data : e)); });
        }));
      state.tableHandles.rulesetList.el.querySelectorAll("tbody tr").forEach(function (tr, i) {
        tr.style.cursor = "pointer";
        tr.addEventListener("click", function () { selectRuleset(rows[i].id); });
        if (String(rows[i].id) === String(state.selected)) tr.classList.add("hl");
      });
      listHost.appendChild(p);
    }

    function paintDetail() {
      clear(detailHost);
      const rs = rulesetById(state.selected);
      const p = panel(null, rs ? rs.name : t("gui_rs_loading"));
      if (!state.selected) {
        p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), t("gui_au_pick_ruleset")));
        detailHost.appendChild(p);
        return;
      }
      if (state.detailError) {
        p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), state.detailError));
        detailHost.appendChild(p);
        return;
      }
      if (!state.detail) {
        p.body.appendChild(note(t("gui_rs_loading")));
        detailHost.appendChild(p);
        return;
      }
      const detailRs = state.detail.ruleset || {};
      withMeta(p, "ID " + detailRs.id);
      withAction(p, t("gui_rs_schedule_rs_btn"), function () { return handles.openRuleset(); });

      const flags = el("div", { class: "chips" });
      flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_prov") + " " }), el("b", { text: detailRs.provision_state })));
      flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_status") + " " }), el("b", { text: detailRs.enabled ? "ON" : "OFF" })));
      flags.appendChild(el("span", null, el("span", { text: t("gui_rs_col_rules") + " " }), el("b", { text: String((state.detail.rules || []).length) })));
      p.body.appendChild(flags);

      // ── AU-04 rule search ──────────────────────────────────────────
      const searchPanel = el("div", { "data-cov": "AU-04" });
      const qrow = el("div", { class: "qrow" });
      const scopeSel = selectField(SEARCH_SCOPES, state.scope, function (v) { state.scope = v; paintRules(); });
      const searchIn = textField(state.search, function (v) { state.search = v.trim(); paintRules(); });
      searchIn.setAttribute("placeholder", t("gui_rs_placeholder"));
      const scopeField = el("div", { class: "qf" }, el("label", { text: t("gui_au_search_scope") }), scopeSel);
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
      searchPanel.appendChild(note(t("gui_au_search_note")));
      p.body.appendChild(searchPanel);

      const rulesHost = el("div");
      p.body.appendChild(rulesHost);

      function paintRules() {
        clear(rulesHost);
        const all = state.detail.rules || [];
        const shown = all.filter(function (r) { return ruleMatches(r, state.search, state.scope); });
        hits.textContent = tf("gui_au_search_hits", { hits: num(shown.length), total: num(all.length) });

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
            return badge(t(lookup(RULE_TYPE_OPTS, r.rule_type || "allow", "gui_rs_rule_type_allow")), r.rule_type === "allow" ? "ok" : "crit");
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
        if (state.tableHandles.ruleSearch) { try { state.tableHandles.ruleSearch.destroy(); } catch (e) { /* already gone */ } }
        state.tableHandles.ruleSearch = table.render(box, buildTable(cols, rows));
        if (!rows.length) rulesHost.appendChild(note(t("gui_rs_no_results")));
      }

      paintRules();
      detailHost.appendChild(p);
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
      return drawer.open(scheduleDrawerBody(target, "AU-05", function () { reloadSchedulesAndDetail(); }));
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
      return drawer.open(scheduleDrawerBody(target, "AU-06", function () { reloadSchedulesAndDetail(); }));
    }

    handles.openRuleset = openRulesetDrawer;
    handles.openRule = function () {
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
      withMeta(p, tf("gui_au_sched_meta", {
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
          const kind = targetKind(r);
          const cell = el("span", {
            class: "idc", "data-sched-target-kind": kind,
            "data-sched-id": r.href || "", title: r.href || "",
          });
          cell.appendChild(el("b", { text: r.detail_name || r.name || "" }));
          cell.appendChild(el("small", {
            text: kind === "rule"
              ? (targetLabel(r) + " · " + (r.detail_rs || "—") + " · #" + (r.id || ""))
              : (targetLabel(r) + " · #" + (r.id || "")),
          }));
          if (targetMismatch(r)) cell.appendChild(el("small", { "data-tone": "crit", text: t("gui_au_kind_mismatch") }));
          return cell;
        })),
        col("recon", t("gui_au_recon"), widthCell(96, function (r) { return reconCell(r); })),
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
            drawer.open(scheduleDrawerBody(target, targetKind(r) === "rule" ? "AU-06" : "AU-05",
              function () { reloadSchedulesAndDetail(); }));
          });
        })),
      ];
      rows.forEach(function (r) {
        r._tone = r.pce_status === "deleted" ? "crit" : (r.last_result === "error" ? "warn" : null);
      });
      if (!rows.length) p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), null));
      state.tableHandles.scheduleList = table.render(p.body, buildTable(cols, rows));
      // Density spec R5: the two standing paragraphs that used to sit under
      // this table (the three reconciliation states, and how a rule href is
      // told apart from a ruleset href) merge into one explanation.
      p.body.appendChild(disclosure(t("gui_gen_explain"),
        note(t("gui_au_recon_note")), note(t("gui_au_kind_note"))));
      schedHost.appendChild(p);
    }

    handles.confirmDelete = function () {
      const picked = state.picked.length ? state.picked : state.schedules.map(function (s) { return s.href; });
      if (!picked.length) return null;
      const impact = [tf("gui_au_del_i_count", { n: num(picked.length) })];
      picked.slice(0, 4).forEach(function (href) {
        const s = existingFor(href) || {};
        impact.push(targetLabel(s) + " · " + (s.detail_name || s.name || href));
      });
      impact.push(t("gui_au_del_i_note"));
      impact.push(t("gui_au_del_i_fail"));
      return modal.confirm(confirmSpec(t("gui_rs_delete_selected"), impact, function () {
        return api.post("/api/rule_scheduler/schedules/delete", { hrefs: picked }).then(function (result) {
          if (!result || result.ok !== true) {
            toast.crit(errText(result));
            return false;
          }
          state.picked = [];
          toast.ok(tf("gui_deleted_count", { count: (result.deleted || []).length }));
          return reloadSchedulesAndDetail();
        });
      }));
    };

    // ── AU-09 立即檢查 + AU-10 執行紀錄 ────────────────────────────────
    const checkPanel = panel("AU-09", t("gui_rs_run_check"));
    // Density spec R4/R5: the raw "POST /api/rule_scheduler/check" label is
    // gone, and what the button really does (lock, engine.check, log append)
    // is several sentences — it now lives in the shared explanation instead
    // of standing open above the button on every visit.
    checkPanel.body.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_au_check_real"))));
    const checkResultHost = el("div");
    checkPanel.body.appendChild(checkResultHost);

    handles.check = async function () {
      clear(checkResultHost);
      checkResultHost.appendChild(note(t("gui_rs_loading")));
      let result;
      try {
        result = await api.post("/api/rule_scheduler/check", {});
      } catch (e) {
        result = { ok: false, error: errText(e && e.data ? e.data : e) };
      }
      if (state.torn) return;
      clear(checkResultHost);
      if (!result || result.ok !== true) {
        checkResultHost.appendChild(el("p", { class: "note", "data-tone": "crit", text: errText(result) }));
        toast.crit(errText(result));
        return;
      }
      const logs = Array.isArray(result.logs) ? result.logs : [];
      checkResultHost.appendChild(el("pre", { class: "codepane", text: logs.length ? logs.join("\n") : t("gui_rs_log_ready") }));
      toast.ok(tf("gui_au_check_result", { n: num(logs.length) }));
      try {
        const fresh = await api.reload("rs_logs");
        if (!state.torn) { state.rsLogHistory = (fresh && fresh.history) || []; paintLog(); }
      } catch (e) { /* log refresh is best-effort */ }
    };
    withAction(checkPanel, t("gui_rs_run_check"), handles.check);
    row4.appendChild(checkPanel);

    logPanel = panel("AU-10", t("gui_rs_logs"));
    logPane = el("pre", { class: "console" });
    handles.clearLog = function () {
      // rule-scheduler.js:640-643 (rsClearLog) — this empties the pane only;
      // the server's ring buffer is untouched.
      logPane.textContent = "";
      logPane.dataset.empty = "true";
      toast.info(t("gui_au_log_clear_note"));
    };
    withAction(logPanel, t("gui_rs_clear"), handles.clearLog);
    logPanel.body.appendChild(logPane);
    const logFoot = el("div", { class: "qrow" });
    logFoot.appendChild(btn("btn ghost", t("gui_load_more"), function () {
      state.logShown += 20;
      paintLog();
    }));
    logPanel.body.appendChild(logFoot);
    // Density spec R4/R5: the raw "GET /api/rule_scheduler/logs" label is
    // gone; the ring-buffer cap and what Clear does/does not touch fold into
    // the shared explanation.
    logPanel.body.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_au_log_cap"))));
    row4.appendChild(logPanel);
    paintLog();

    paintList();
    paintDetail();
    paintSchedules();
  }

  /** selectRuleset(id) — the real fetch behind AU-03/04's row click. */
  async function selectRuleset(id) {
    state.selected = String(id);
    state.detail = null;
    state.detailError = null;
    renderBoard();
    try {
      const detail = await api.load("rs_ruleset_detail", { rs_id: state.selected });
      if (state.torn || state.selected !== String(id)) return;
      state.detail = detail;
    } catch (e) {
      if (state.torn || state.selected !== String(id)) return;
      state.detailError = errText(e && e.data ? e.data : e);
    }
    renderBoard();
  }

  /** After a real create/edit/delete: reload status+schedules (and the
   *  selected ruleset's detail, whose is_scheduled flags depend on them),
   *  then rebuild the whole board — this area's "reconcile against the
   *  list" flow. */
  async function reloadSchedulesAndDetail() {
    if (state.torn) return true;
    try {
      const [st, sc] = await Promise.all([api.reload("rs_status"), api.reload("rs_schedules")]);
      if (state.torn) return true;
      state.rsStatus = st && st.ok !== false ? st : {};
      state.schedules = Array.isArray(sc) ? sc.map(copyOf) : [];
    } catch (e) {
      toast.crit(errText(e && e.data ? e.data : e));
      return false;
    }
    if (state.selected) {
      try {
        state.detail = await api.reload("rs_ruleset_detail", { rs_id: state.selected });
      } catch (e) {
        state.detailError = errText(e && e.data ? e.data : e);
      }
    }
    if (state.torn) return true;
    renderBoard();
    return true;
  }

  await withErrorCard(board, "rule scheduler (" + RULE_SNAPS.length + ")",
    function () { return loadAll(RULE_SNAPS); },
    function (d) {
      if (ctx.stale() || state.torn) return;
      state.rsStatus = d.rs_status && d.rs_status.ok !== false ? d.rs_status : {};
      state.rsLogHistory = (d.rs_logs && d.rs_logs.history) || [];
      state.schedules = Array.isArray(d.rs_schedules) ? d.rs_schedules.map(copyOf) : [];
      state.rulesets = ((d.rs_rulesets && d.rs_rulesets.items) || []).map(copyOf);
      state.total = (d.rs_rulesets && d.rs_rulesets.total) || state.rulesets.length;
      state.size = (d.rs_rulesets && d.rs_rulesets.size) || 50;
      renderBoard();
    });
}

// ═══════════════════════════════════════════════════ reports sub-view ═══════

/** dashboard.js:331 pattern applied to day_of_week: the translated label for a
 * known value, the raw stored value for an outlier. */
function dowLabel(v) {
  const key = lookup(DOW, v, "");
  return key ? t(key) : String(v || "");
}

/* dashboard.js:330-370 (renderSchedules) — the frequency column is one string. */
function freqText(s) {
  let out = t(lookup(FREQS, s.schedule_type, "gui_sched_freq_weekly"));
  if (s.schedule_type === "weekly") out += " (" + dowLabel(s.day_of_week) + ")";
  else if (s.schedule_type === "monthly") out += " (" + t("gui_sched_day_of_month") + " " + (s.day_of_month || 1) + ")";
  const tz = s.timezone && s.timezone !== "local" ? s.timezone : t("gui_rs_local_tz");
  out += " " + String(s.hour || 0).padStart(2, "0") + ":" + String(s.minute || 0).padStart(2, "0") + " (" + tz + ")";
  return out;
}

/* dashboard.js:347-351 — the status column. */
function schedStatus(s) {
  if (s.last_status === "success") return badge(t("gui_sched_status_success"), "ok");
  if (s.last_status === "failed") return badge(t("gui_sched_status_failed"), "crit");
  if (s.last_status === "running") return badge(t("sched_running"), "info");
  return badge(t("gui_sched_status_never"), "neutral");
}

/** The real PUT/POST body reports.py's route accepts — see
 *  reports.py:1092-1233 and dashboard.js:441-475 (the fields the form owns). */
function reportBody(state) {
  const body = {};
  body.name = state.name.trim();
  body.report_type = state.report_type;
  body.schedule_type = state.schedule_type;
  body.day_of_week = state.day_of_week;
  body.day_of_month = Number(state.day_of_month) || 1;
  body.hour = Number(state.hour) || 0;
  body.minute = Number(state.minute) || 0;
  body.timezone = state.timezone;
  body.lookback_days = Number(state.lookback_days) || 0;
  body.max_reports = Number(state.max_reports) || 0;
  body.format = state.format === "all" ? ["html", "csv", "xlsx"] : [state.format];
  body.email_report = state.email_report;
  body.email_recipients = String(state.email_recipients || "").split(/\r?\n/)
    .map(function (s) { return s.trim(); }).filter(Boolean);
  body.cron_expr = state.cron_expr;
  return body;
}

/* AU-11 — the CRUD drawer. Every key report_schedules.json carries appears
 * here with data-field. */
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
  const typePairs = REPORT_TYPES.map(function (pair) { return [pair[0], t(pair[1])]; });
  if (!knownReportType(state.report_type)) {
    typePairs.unshift([state.report_type, state.report_type + " ⚠"]);
  }
  body.appendChild(editField("report_type", t("gui_sched_report_type"),
    selectLiteral(typePairs, state.report_type, function (v) {
      state.report_type = v;
      syncType();
    })));
  if (s.report_type && !knownReportType(s.report_type)) {
    body.appendChild(note(tf("gui_au_rep_type_unknown", { type: s.report_type })));
  }

  const filterNote = el("p", { class: "note" });
  body.appendChild(filterNote);

  body.appendChild(editField("schedule_type", t("gui_sched_freq"),
    selectField(FREQS, state.schedule_type, function (v) {
      state.schedule_type = v;
      syncFreq();
    })));

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
    body.appendChild(note(tf("gui_au_dow_unknown", { value: s.day_of_week })));
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
    selectField(FORMATS, state.format, function (v) { state.format = v; }), t("gui_au_fmt_hint")));

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

  body.appendChild(sectionHead(t("gui_au_stored_fields")));
  body.appendChild(roList([
    roField("id", s.id, t("gui_au_ro_sched_id")),
    roField("enabled", String(state.enabled), t("gui_au_ro_enabled")),
    roField("last_run", s.last_run, t("gui_au_ro_state")),
    roField("last_status", s.last_status, t("gui_au_ro_state")),
    roField("last_error", s.last_error, t("gui_au_ro_state")),
  ]));

  function syncFreq() {
    dowBox.style.display = state.schedule_type === "weekly" ? "" : "none";
    domBox.style.display = state.schedule_type === "monthly" ? "" : "none";
  }
  function syncMail() {
    recipBox.style.display = state.email_report ? "" : "none";
  }
  function syncType() {
    filterNote.textContent = TRAFFIC_PROFILE_TYPES.indexOf(state.report_type) >= 0
      ? t("gui_au_rep_filters_on")
      : (state.report_type === "app_summary" ? t("gui_au_rep_app_on") : t("gui_au_rep_filters_off"));
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
      const payload = reportBody(state);
      // v2_au_ro_enabled (gui_au_ro_enabled): "owned by the list's toggle,
      // not a form field; creation always sends true." Only CREATE sets it —
      // an edit PUT must never carry a stale `enabled` that could clobber
      // what the toggle button set since this drawer was opened.
      if (!sched) payload.enabled = true;
      const req = sched ? api.put("/api/report-schedules/" + sched.id, payload) : api.post("/api/report-schedules", payload);
      return req.then(function (result) {
        if (!result || result.ok !== true) {
          errLine.textContent = errText(result);
          errLine.scrollIntoView({ block: "center" });
          return false;
        }
        toast.ok(t("gui_au_schedule_saved"));
        if (onSaved) onSaved();
        return true;
      });
    }
  );
}

async function mountReports(root, ctx) {
  const handles = {};
  const state = { torn: false, tableHandles: {}, schedules: [], selected: null, history: [] };
  installTeardown(state);
  drawer.registerAudit("au-report-sched", function () { return handles.open ? handles.open() : null; });
  modal.registerAudit("au-report-delete", function () { return handles.confirmDelete ? handles.confirmDelete() : null; });
  palette.registerFor(R_REPORTS, cmdSpec("au:add-sched", t("gui_sched_add"), function () { if (handles.open) handles.open(null); }));

  root.appendChild(areaTop(R_REPORTS));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  function destroyTables() {
    Object.keys(state.tableHandles).forEach(function (k) {
      try { state.tableHandles[k].destroy(); } catch (e) { console.error("[automation] table teardown failed", e); }
    });
    state.tableHandles = {};
  }

  function selected() {
    let hit = null;
    state.schedules.forEach(function (s) { if (s.id === state.selected) hit = s; });
    return hit;
  }
  function selectedById(id) {
    let hit = null;
    state.schedules.forEach(function (s) { if (s.id === id) hit = s; });
    return hit;
  }

  async function reloadList() {
    if (state.torn) return true;
    try {
      const fresh = await api.reload("report_schedules");
      if (state.torn) return true;
      state.schedules = ((fresh && fresh.schedules) || []).map(copyOf);
      if (!state.schedules.some(function (s) { return s.id === state.selected; })) {
        state.selected = state.schedules.length ? state.schedules[0].id : null;
      }
    } catch (e) {
      toast.crit(errText(e && e.data ? e.data : e));
      return false;
    }
    if (state.torn) return true;
    renderBoard();
    if (state.selected) await loadHistory(state.selected);
    return true;
  }

  async function loadHistory(id) {
    state.history = [];
    try {
      const h = await api.load("report_sched_history", { schedule_id: id });
      if (state.torn || state.selected !== id) return;
      state.history = (h && h.history) || [];
    } catch (e) {
      if (state.torn || state.selected !== id) return;
      state.history = [];
    }
    paintHistory();
  }

  let listHost = null;
  let histHost = null;

  function paintList() {
    if (!listHost) return;
    clear(listHost);
    const p = panel("AU-11", t("gui_tab_report_schedules"));
    withMeta(p, tf("gui_au_rep_meta", {
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
          box.appendChild(el("small", { "data-tone": "warn", text: t("gui_au_rep_type_off_list") }));
        }
        return box;
      })),
      col("freq", t("gui_sched_col_freq"), widthCell(230, function (r) {
        const box = el("span", { class: "idc" });
        box.appendChild(el("span", { class: "mono", title: freqText(r), text: freqText(r) }));
        if (r.schedule_type === "weekly" && !knownDayOfWeek(r.day_of_week)) {
          box.appendChild(el("small", { "data-tone": "warn", text: t("gui_au_dow_off_list") }));
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
          // dashboard.js:499-505 — real POST /toggle then reload the list.
          api.post("/api/report-schedules/" + r.id + "/toggle", {}).then(function (result) {
            if (!result || result.ok !== true) { toast.crit(errText(result)); return; }
            toast.ok(t("gui_sched_toggled"));
            reloadList();
          });
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
    if (state.tableHandles.reportList) { try { state.tableHandles.reportList.destroy(); } catch (e) { /* already gone */ } }
    state.tableHandles.reportList = table.render(p.body, buildTable(cols, rows));
    state.tableHandles.reportList.el.querySelectorAll("tbody tr").forEach(function (tr, i) {
      tr.addEventListener("click", function () {
        state.selected = rows[i].id;
        loadHistory(state.selected);
        paintList();
      });
      if (rows[i].id === state.selected) tr.classList.add("hl");
    });
    listHost.appendChild(p);
  }

  // real /run — AU-12. This button is wired to the actual endpoint (it fires
  // a real background report generation, reports.py:1181-1219); the area's
  // own e2e never clicks it — see the test file's destructive-operation note.
  function runNow(id) {
    const s = selectedById(id);
    if (!s) return;
    api.post("/api/report-schedules/" + id + "/run", {}).then(function (result) {
      if (!result || result.ok !== true) { toast.crit(errText(result)); return; }
      toast.info(t("gui_sched_run_ok"));
      reloadList();
    });
  }

  function paintHistory() {
    if (!histHost) return;
    clear(histHost);
    const p = panel(null, t("gui_au_rep_history"));
    const s = selected();
    const entries = state.history;
    withMeta(p, tf("gui_au_rep_hist_meta", { n: num(entries.length) }));
    if (s) {
      p.body.appendChild(kv(t("gui_sched_col_name"), s.name || "—"));
      p.body.appendChild(kv(t("gui_sched_col_last"), s.last_run ? stamp(s.last_run) : t("gui_sched_status_never")));
      p.body.appendChild(kv(t("gui_sched_col_status"), s.last_status || t("gui_sched_status_never")));
      // Density spec R4/R6: this row used to be labelled with the raw
      // "last_error" field name. gui_rs_error_prefix is the same "Error"
      // label the rule-scheduler side of this file already carries.
      p.body.appendChild(kv(t("gui_rs_error_prefix"), s.last_error || "—"));
    }
    if (!entries.length) {
      p.body.appendChild(emptyState(t("gui_empty_state_no_data_title"), t("gui_au_rep_hist_empty")));
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
    // Density spec R4/R5: the raw "GET /api/report-schedules/<id>/history"
    // endpoint and what it actually returns (one state row, not per-run
    // history) fold into the shared explanation.
    p.body.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_au_rep_hist_note"))));
    histHost.appendChild(p);
  }

  function renderBoard() {
    if (state.torn) return;
    destroyTables();
    clear(board);
    // Density spec R5: the two-sentence "this changes no policy, every field
    // below is either yours or backend-written" framing collapses instead of
    // standing open on every visit.
    board.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_au_reports_intro"))));
    const row1 = el("div", { class: "brow" });
    const row2 = el("div", { class: "brow c2" });
    board.appendChild(row1);
    board.appendChild(row2);

    listHost = el("div");
    row1.appendChild(listHost);
    histHost = el("div");
    row2.appendChild(histHost);

    const tickPanel = panel(null, t("gui_au_rep_tick"));
    // Density spec R4/R5: the raw "tick_report_schedules" / "60s" row is
    // gone as a standing kv — the note already names the job and its
    // interval in prose, and now lives in the shared explanation.
    tickPanel.body.appendChild(disclosure(t("gui_gen_explain"), note(t("gui_au_rep_tick_note"))));
    const tickRow = el("div", { class: "qrow" });
    tickRow.appendChild(btn("btn", t("gui_health_goto") + " " + R_JOBS, function () { router.go(R_JOBS); }));
    tickPanel.body.appendChild(tickRow);
    row2.appendChild(tickPanel);

    paintList();
    paintHistory();
  }

  handles.open = function (sched) {
    const target = sched === undefined ? selected() : sched;
    return drawer.open(reportDrawerBody(target, function () { reloadList(); }));
  };

  handles.confirmDelete = function () {
    const s = selected();
    if (!s) return null;
    return modal.confirm(confirmSpec(tf("gui_sched_confirm_delete", { name: s.name || "" }),
      [t("gui_au_rep_del_i1"), t("gui_au_rep_del_i2")], function () {
        return api.del("/api/report-schedules/" + s.id).then(function (result) {
          if (!result || result.ok !== true) { toast.crit(errText(result)); return false; }
          toast.ok(t("gui_sched_deleted"));
          return reloadList();
        });
      }));
  };

  await withErrorCard(board, "report schedules (" + REPORT_SNAPS.length + ")",
    function () { return loadAll(REPORT_SNAPS); },
    function (d) {
      if (ctx.stale() || state.torn) return;
      state.schedules = ((d.report_schedules && d.report_schedules.schedules) || []).map(copyOf);
      state.selected = state.schedules.length ? state.schedules[0].id : null;
      renderBoard();
      if (state.selected) loadHistory(state.selected);
    });
}

// ══════════════════════════════════════════════════════ jobs sub-view ═══════

/* AU-13 — integrations.js:1504-1541 (_buildOvJobHealth). The interval printed
 * h / m / s (:1517-1521). The beat meter and projected next run are
 * DESIGN-ADDED arithmetic on fields already in the payload — nothing here
 * re-judges `level`. */
function jobAge(job, asOf) {
  const a = Date.parse(job.last_run);
  const b = Date.parse(asOf);
  if (!isFinite(a) || !isFinite(b)) return null;
  return (b - a) / 1000;
}

/* One line saying what is actually wrong with a job, for the page's headline.
 * `level` is the backend's own verdict (dashboard.py's _overview_job_health):
 * error = the last run failed, warn = never ran or is past
 * max(2 x interval, 600s). This only has to name that verdict in words — it
 * must not re-derive it, or the page and the API would drift apart. */
function jobReason(job) {
  if (job.level === "error") return t("gui_au_job_reason_failed");
  if (!job.last_run) return t("gui_au_job_reason_never");
  return Number(job.interval_seconds)
    ? tf("gui_au_job_reason_overdue", { interval: dur(job.interval_seconds) })
    : t("gui_jh_overdue");
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
  const state = { torn: false, tableHandles: {} };
  installTeardown(state);
  palette.registerFor(R_JOBS, cmdSpec("au:jobs-bad", t("gui_au_job_only_bad"), function () { if (handles.onlyBad) handles.onlyBad(); }));

  root.appendChild(areaTop(R_JOBS));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "job health (" + JOB_SNAPS.length + ")",
    function () { return loadAll(JOB_SNAPS); },
    function (d) {
      if (ctx.stale() || state.torn) return;
      const ov = d.dashboard_overview || {};
      const jobs = (ov.job_health || []).map(copyOf);
      const localState = {};
      localState.onlyBad = false;

      const row1 = el("div", { class: "brow" });
      board.appendChild(row1);

      const okCount = jobs.filter(function (j) { return j.level === "ok"; }).length;
      const bad = jobs.filter(function (j) { return j.level !== "ok"; });
      const errCount = jobs.filter(function (j) { return j.level === "error"; }).length;

      const head = panel("AU-13", t("gui_ov_job_health"));
      withTone(head, errCount ? "crit" : (bad.length ? "warn" : "ok"));
      withMeta(head, bad.length
        ? tf("gui_au_jobs_attention", { n: num(bad.length) })
        : tf("gui_health_jobs_ok", { ok: okCount, total: jobs.length }));

      /* Density spec R1/R3 — this page answers "is anything wrong with the
       * schedules". When nothing is, that answer is one line; the four KPI
       * cells it replaces spent a whole screen restating "14, 14, 0, 0".
       * When something IS wrong, the answer is the offending jobs themselves,
       * so they lead instead of being one filter click away inside a 14-row
       * table. */
      if (!bad.length) {
        head.body.appendChild(note(t("gui_au_jobs_all_ok")));
      } else {
        /* Cap the headline. With 10 of 11 jobs unhealthy the "conclusion"
         * grows back into the table it replaced, which defeats the point; the
         * overflow line hands off to the full list right below. */
        const HEADLINE_MAX = 5;
        const list = el("div", { class: "badlist" });
        bad.slice(0, HEADLINE_MAX).forEach(function (j) {
          const line = el("div", { class: "idc", "data-tone": tone(j.level) });
          line.appendChild(el("b", { text: j.job_id }));
          line.appendChild(el("small", { text: jobReason(j) }));
          if (j.last_run) {
            line.appendChild(el("small", {
              class: "mono", text: since(j.last_run, ov.as_of) + " " + t("gui_au_job_ago"),
            }));
          }
          list.appendChild(line);
        });
        head.body.appendChild(list);
        if (bad.length > HEADLINE_MAX) {
          head.body.appendChild(note(tf("gui_au_jobs_more", { n: num(bad.length - HEADLINE_MAX) })));
        }
      }
      head.body.appendChild(note(tf("gui_au_job_asof", { at: stamp(ov.as_of) })));

      /* R2's third layer: the full table is evidence, not the headline, so it
       * ships collapsed. The only-failures filter moves in here with it — it
       * has nothing to do once the failures are what the page opens with. */
      const filterRow = el("div", { class: "qrow" });
      const toggleBtn = btn("btn", t("gui_au_job_only_bad"), function () {
        localState.onlyBad = !localState.onlyBad;
        toggleBtn.setAttribute("aria-pressed", localState.onlyBad ? "true" : "false");
        toggleBtn.textContent = localState.onlyBad ? t("gui_au_job_all") : t("gui_au_job_only_bad");
        paintJobs();
      });
      toggleBtn.setAttribute("aria-pressed", "false");
      filterRow.appendChild(toggleBtn);
      const tableHost = el("div");
      const allWrap = disclosure(
        tf("gui_au_jobs_show_all", { n: num(jobs.length) }), filterRow, tableHost);
      head.body.appendChild(allWrap);

      /* R5 — the three explanations are kept, not deleted. They answer real
       * questions (what makes a job "warn", what the beat bar measures, why
       * there is no run history); they just stop being the first thing on the
       * page. */
      head.body.appendChild(disclosure(t("gui_gen_explain"),
        note(t("gui_au_job_level_note")),
        note(t("gui_au_job_beat_note")),
        note(t("gui_au_job_hist_note"))));

      row1.appendChild(head);
      /* The palette command opens the disclosure it now lives inside, so
       * "show only failures" still reaches a visible control. */
      handles.onlyBad = function () { allWrap.open = true; toggleBtn.click(); };

      function paintJobs() {
        clear(tableHost);
        /* No inner panel: the table sits inside a disclosure whose summary
         * already names it and counts it ("show all 14 jobs"), so a nested
         * header repeating "Job / 14 rows" is chrome about chrome — and it put
         * a second .meta inside AU-13, which is how it was noticed. */
        const shown = localState.onlyBad ? jobs.filter(function (j) { return j.level !== "ok"; }) : jobs;

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
              el("small", { text: since(r.last_run, ov.as_of) + " " + t("gui_au_job_ago") }));
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
          col("beat", t("gui_au_job_beat"), buildCell(function (r) {
            const box = el("div", { "data-tone": r._tone });
            box.appendChild(beatMeter(r._ratio));
            box.appendChild(el("small", {
              class: "beat-cap", text: r._ratio === null ? "—"
                : (Math.round(r._ratio * 100) + "% · " + t("gui_au_job_next") + " "
                  + (r._age === null ? "—" : dur(Math.max(0, Number(r.interval_seconds) - r._age)))),
            }));
            return box;
          })),
        ];
        if (state.tableHandles.jobs) { try { state.tableHandles.jobs.destroy(); } catch (e) { /* already gone */ } }
        /* The beat-meter and run-history notes that used to sit under this
         * table now live in the page's one "說明" disclosure (R5) rather than
         * being repeated at the foot of the evidence. */
        state.tableHandles.jobs = table.render(tableHost, buildTable(cols, rows));
      }

      paintJobs();
    });
}

export { mountRules as mountAutoRules, mountReports as mountAutoReports, mountJobs as mountAutoJobs };
