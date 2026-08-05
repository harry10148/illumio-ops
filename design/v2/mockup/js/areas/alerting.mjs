// alerting.mjs — #/alerting/{rules,ops}. Anchors AL-01…AL-14 (design/v2/coverage.yaml).
//
// The area answers two different questions and therefore has two sub-views:
//   rules — "what is allowed to page me, and under what condition"
//   ops   — "pull a lever now, and read what came back"
// The rules view is a register: one row per rule, the condition spelled out in
// the row rather than hidden behind an edit click. The ops view is a lever
// board plus one console, because every one of its actions is a POST whose only
// product output is a text blob (actions.js:88-146).
//
// FIELD CONTRACT (this file's reason to exist — previous-redesign failure #2):
// every key a rule of a given type carries in snapshots/rules.json is present in
// that type's drawer as an element with data-field="<key>". Editable fields are
// the ones the shipping save handlers actually send (rules.js:515-583); every
// other key is rendered read-only WITH its provenance, instead of being dropped
// on the floor — dropping is exactly how the last redesign lost fields.
// tests/design_v2/test_alert_rule_fields.py enforces the union over all rules of
// each type, so a backend field added later fails the guard until it is designed.
//
// HONESTY RULES followed here (Task 7 report §9.9):
//   * The mockup never calls an API. Rule edits, toggles and deletes change the
//     in-memory copy of the snapshot only, and say so.
//   * ops actions do not fabricate output. Each button records the request the
//     product would send; the console's own text says the run happens on a real
//     backend and this page is not one.
//   * The rule_test sandbox (AL-07) computes REAL hits: matcher.py:8-89 is
//     transcribed below and run against the raw events in events_viewer.json.
//     No number on this page is invented.
// Anything not transcribed from the product is marked DESIGN-ADDED at the point
// where it is decided.

import { el, clear, spacer } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { stamp } from "../core/fmt.mjs";
import { store } from "../core/store.mjs";
import { router } from "../core/router.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { areaHead } from "./placeholder.mjs";
import { createFilterBar, setFilterBarText, setFilterBarSnapshots } from "../components/filter-bar.mjs";
import { verifyPane } from "../components/verifypane.mjs";

const R_RULES = "#/alerting/rules";
const R_OPS = "#/alerting/ops";

// index.html:1266 (rules sub-tabs) — the product splits the same page into
// "rules" and "actions"; the v2 area keeps that split as two routes.
const SUB_ROUTES = [[R_RULES, "gui_tab_rules"], [R_OPS, "gui_actions"]];

const RULE_SNAPS = ["rules", "event_catalog", "events_viewer", "fb_suggest", "fb_browse"];
const OPS_SNAPS = ["status", "alert_plugins", "rules"];

// rules.js:85 — the unit suffix the condition column appends, by rule type.
const TYPE_UNITS = [["volume", " MB"], ["bandwidth", " Mbps"], ["traffic", " conns"]];

// index.html:2686-2694 (input[name=tr-pd]) / :2731-2739 (input[name=bw-pd]).
// rules.js:79's `pdm` prints these as bare English words; the v2 list reuses the
// modal's own catalogue keys instead so one vocabulary serves list and drawer.
const PD_OPTS = [["2", "gui_pd_blocked"], ["1", "gui_pd_potential"], ["0", "gui_pd_allowed"], ["-1", "gui_pd_all"]];

// index.html:2604-2609 (select#ev-status) / :2611-2616 (select#ev-severity)
const EV_STATUS = [["all", "gui_ev_status_all"], ["success", "gui_ev_status_success"], ["failure", "gui_ev_status_failure"]];
const EV_SEVERITY = [["all", "gui_ev_severity_all"], ["info", "gui_ev_severity_info"],
  ["error", "gui_ev_severity_error"], ["warning", "gui_ev_severity_warning"]];
// index.html:2628-2631 (input[name=ev-tt])
const EV_TT = [["immediate", "gui_tt_immediate"], ["count", "gui_tt_count"]];
// index.html:2724-2728 (input[name=bw-mt]) — the value is stored as the rule's `type`
const BW_METRICS = [["bandwidth", "gui_mt_bw"], ["volume", "gui_mt_vol"]];
// index.html:2657-2659 (select#sys-type, disabled) + rules.py:196-198 rejects anything else
const SYS_TYPES = [["pce_health", "gui_system_health_pce"]];
// index.html:1311-1315 (select#a-debug-pd). NOTE the numbering is NOT the rule
// `pd` numbering: analyzer.py:2527-2529 reads 1=blocked, 2=allowed, 3=all.
const DEBUG_PD = [["1", "gui_pd_blocked"], ["2", "gui_pd_allowed"], ["3", "gui_pd_all"]];

// Three rule keys are deliberately NOT drawer fields, and the guard test's
// INTERNAL set says the same thing:
//   id      — rules.py:161 gen_rule_id(), server-assigned
//   index   — rules.py:107 recomputed on every GET; the address PUT/DELETE
//             /api/rules/<idx> uses. (The brief's sketch called it `idx`.)
//   enabled — owned by the list's toggle (rules.js:130-147), not by the form
// Every other key of a type appears in that type's drawer.

// ── best-practice specs, transcribed from config.py:752-768 ─────────────────
// [name_key, filter_value, threshold_type, count, window, cooldown, status, severity, throttle]
const BP_EVENT_SPECS = [
  ["rule_agent_tampering", "agent.tampering", "immediate", 1, 10, 30, "all", "all", ""],
  ["rule_agent_suspend", "agent.suspend", "immediate", 1, 10, 30, "all", "all", ""],
  ["rule_agent_clone", "agent.clone_detected", "immediate", 1, 10, 30, "all", "all", ""],
  ["rule_agent_heartbeat", "system_task.agent_missed_heartbeats_check", "count", 3, 30, 60, "all", "all", "1/30m"],
  ["rule_agent_offline", "system_task.agent_offline_check", "count", 3, 30, 60, "all", "all", "1/30m"],
  ["rule_lost_agent", "lost_agent.found", "immediate", 1, 10, 60, "all", "all", ""],
  ["rule_login_failed", "user.sign_in,user.login", "count", 5, 10, 30, "failure", "all", "1/15m"],
  ["rule_api_auth_failed", "request.authentication_failed", "count", 5, 10, 30, "all", "all", "1/15m"],
  ["rule_policy_fail", "agent.refresh_policy", "immediate", 1, 10, 30, "failure", "all", ""],
  ["rule_ruleset_change", "rule_set.create,rule_set.update,rule_set.delete", "immediate", 1, 10, 60, "all", "all", ""],
  ["rule_policy_provision", "sec_policy.create", "immediate", 1, 10, 60, "all", "all", ""],
  ["rule_api_authz_failed", "request.authorization_failed", "count", 3, 10, 30, "all", "all", "1/15m"],
  ["rule_api_key_change", "api_key.create,api_key.delete", "immediate", 1, 10, 60, "all", "all", ""],
  ["rule_sec_rule_change", "sec_rule.create,sec_rule.update,sec_rule.delete", "immediate", 1, 10, 60, "all", "all", ""],
  ["rule_bulk_unpair", "workloads.unpair,agents.unpair", "immediate", 1, 10, 60, "all", "all", ""],
  ["rule_auth_settings_change", "authentication_settings.update", "immediate", 1, 10, 60, "all", "all", ""],
];

/* config.py:823-843 — the signature apply_best_practices() compares on in
 * append_missing mode. Transcribed so the impact summary can state the real
 * added/skipped split for THIS config instead of a guess. Encoded with
 * JSON.stringify (not a joined string) so free-text fields like src_label
 * that may contain a space can never blur the element boundary — a plain
 * separator such as " " would let ["a", "b c"] and ["a b", "c"] collide. */
function ruleSignature(rule) {
  const ty = rule.type;
  const s = function (v) { return String(v === null || v === undefined ? "" : v).trim(); };
  if (ty === "event") return JSON.stringify(["event", s(rule.filter_value), s(rule.filter_status || "all"), s(rule.filter_severity || "all")]);
  if (ty === "traffic") {
    return JSON.stringify(["traffic", String(parseInt(rule.pd, 10) || 0), String(rule.port === null || rule.port === undefined ? "None" : rule.port),
      String(rule.proto === null || rule.proto === undefined ? "None" : rule.proto),
      s(rule.src_label || rule.src_ip_in || ""), s(rule.dst_label || rule.dst_ip_in || "")]);
  }
  if (ty === "system") return JSON.stringify(["system", s(rule.filter_value)]);
  return JSON.stringify([String(ty), s(rule.name)]);
}

/** The 17 rules apply_best_practices() would build (16 event + the high-blocked
 *  traffic rule, config.py:798-819), reduced to what the signature needs. */
function bpSignatures() {
  const out = [];
  BP_EVENT_SPECS.forEach(function (spec) {
    const r = {};
    r.type = "event";
    r.filter_value = spec[1];
    r.filter_status = spec[6];
    r.filter_severity = spec[7];
    out.push(ruleSignature(r));
  });
  const hb = {};
  hb.type = "traffic";
  hb.pd = 2;
  hb.port = null;
  hb.proto = null;
  out.push(ruleSignature(hb));
  return out;
}

// ── matcher port: src/events/matcher.py:8-89 ────────────────────────────────
// Transcribed statement for statement so AL-07 can report REAL hits. The one
// unavoidable divergence: Python's `re` and JavaScript's RegExp are different
// engines, so an exotic pattern could disagree. Every rule in this snapshot uses
// plain event ids or comma lists, which both engines treat identically; the
// panel states the caveat rather than hiding it.
const RE_META = "*+?[](){}$\\".split("");

function looksLikeRegex(pattern) {
  if (pattern.charAt(0) === "^" || pattern.charAt(pattern.length - 1) === "$") return true;
  if (RE_META.some(function (c) { return pattern.indexOf(c) >= 0; })) return true;
  return [".*", ".+", ".?"].some(function (tok) { return pattern.indexOf(tok) >= 0; });
}

function valueMatches(pattern, value) {
  if (pattern === "*" || pattern === "any" || pattern === "all" || pattern === "") return true;
  const normalized = value === null || value === undefined ? "" : String(value);
  if (pattern.charAt(0) === "!") return !valueMatches(pattern.slice(1), value);
  if (pattern.indexOf("|") >= 0 && !looksLikeRegex(pattern)) return pattern.split("|").indexOf(normalized) >= 0;
  if (looksLikeRegex(pattern)) {
    try { return new RegExp("^" + pattern + "$").test(normalized); } catch (e) { return pattern === normalized; }
  }
  return pattern === normalized;
}

function extractNested(event, fieldPath) {
  let current = event;
  const parts = fieldPath.split(".");
  for (let i = 0; i < parts.length; i++) {
    if (current && typeof current === "object" && !Array.isArray(current) && parts[i] in current) current = current[parts[i]];
    else return null;
  }
  if (current === null || current === undefined) return null;
  return typeof current === "string" ? current : String(current);
}

function eventTypeMatches(pattern, eventType) {
  if (pattern === "*" || pattern === ".*" || pattern === "") return true;
  if (pattern.indexOf("|") >= 0 && !looksLikeRegex(pattern)) return pattern.split("|").indexOf(eventType) >= 0;
  if (looksLikeRegex(pattern)) {
    try {
      const src = pattern.charAt(0) === "^" ? pattern : "^" + pattern + "$";
      return new RegExp(src).test(eventType);
    } catch (e) { return pattern === eventType; }
  }
  return pattern === eventType;
}

/** matcher.py:59-89. Returns true when `rule` would fire on the RAW event. */
function matchesEventRule(rule, event) {
  const eventType = String(event.event_type || "");
  const patterns = String(rule.filter_value || "").split(",")
    .map(function (p) { return p.trim(); }).filter(function (p) { return p.length > 0; });
  if (!patterns.length) return false;
  if (!patterns.some(function (p) { return eventTypeMatches(p, eventType); })) return false;
  if (!valueMatches(String(rule.filter_status === undefined ? "all" : rule.filter_status), event.status)) return false;
  if (!valueMatches(String(rule.filter_severity === undefined ? "all" : rule.filter_severity), event.severity)) return false;
  const mf = rule.match_fields || rule.filter_match_fields || {};
  const paths = Object.keys(mf);
  for (let i = 0; i < paths.length; i++) {
    const path = paths[i];
    const pattern = String(mf[path]);
    if (path === "notification_type") {
      const list = Array.isArray(event.notifications) ? event.notifications : [];
      const values = list.filter(function (n) { return n && typeof n === "object"; })
        .map(function (n) { return String(n.notification_type || ""); });
      if (!values.some(function (v) { return valueMatches(pattern, v); })) return false;
      continue;
    }
    if (!valueMatches(pattern, extractNested(event, path))) return false;
  }
  return true;
}

// ── shared chrome (same vocabulary as investigate.mjs) ──────────────────────
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

function note(text) {
  return el("p", { class: "note", text: text });
}

function btn(cls, text, onClick) {
  return el("button", { class: cls, type: "button", text: text, onClick: onClick });
}

function badge(text, tn) {
  return el("span", { class: "badge", "data-tone": tn }, el("i", { class: "dot" }), el("span", { text: text }));
}

function areaTop(active) {
  const head = areaHead(t("v2_nav_alerting"), active);
  const nav = el("nav", { class: "subnav", "aria-label": t("v2_nav_alerting") });
  SUB_ROUTES.forEach(function (pair) {
    const a = el("a", { href: pair[0], text: t(pair[1]) });
    if (pair[0] === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  head.appendChild(nav);
  return head;
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

function numberField(value, onChange) {
  const input = el("input", { class: "field", type: "number", value: value === null || value === undefined ? "" : String(value) });
  if (onChange) input.addEventListener("input", function () { onChange(input.value); });
  return input;
}

function textField(value, onChange) {
  const input = el("input", { class: "field", type: "text", value: value === null || value === undefined ? "" : String(value) });
  if (onChange) input.addEventListener("input", function () { onChange(input.value); });
  return input;
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
function pickCell(headFn, cellFn) { const o = {}; o.width = 34; o.head = headFn; o.cell = cellFn; return o; }
function buildTable(columns, rows) { const spec = {}; spec.columns = columns; spec.rows = rows; return spec; }

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

/** A rule copy without the view-only keys this module adds (`_tone`). */
function jsonOf(rule) {
  const out = {};
  Object.keys(rule).sort().forEach(function (k) { if (k.charAt(0) !== "_") out[k] = rule[k]; });
  return out;
}

function isBlank(v) {
  if (v === null || v === undefined || v === "") return true;
  if (typeof v === "object" && !Array.isArray(v)) return Object.keys(v).length === 0;
  return false;
}

function showValue(v) {
  if (isBlank(v)) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ════════════════════════════════════════════════════ rules sub-view ════════

/* rules.js:84-89 — the condition column. `unit` and the "> n unit (Win:Xm CD:Ym)"
 * shape are transcribed; the cooldown falls back to the window exactly as the
 * product does. */
function conditionText(r) {
  if (r.threshold_count === null || r.threshold_count === undefined) return "—";
  const unit = lookup(TYPE_UNITS, r.type, "");
  return "> " + r.threshold_count + unit + " (Win:" + r.threshold_window + "m CD:" + (r.cooldown_minutes || r.threshold_window) + "m)";
}

/* rules.js:104-117 — the filters column, prefix by prefix, in the product's own
 * order. The one departure: `pd` prints the catalogue label (see PD_OPTS). */
function filtersText(r) {
  const f = [];
  if (r.type === "event") f.push(t("gui_rules_pfx_event") + r.filter_value);
  if (r.type === "system") {
    const health = r.filter_value === "pce_health" ? t("gui_system_health_pce") : (r.filter_value || "");
    f.push(t("gui_system_health_type") + ": " + health);
  }
  if (r.pd !== undefined && r.pd !== null) f.push(t("gui_rules_pfx_pd") + t(lookup(PD_OPTS, r.pd, "gui_pd_all")));
  if (r.port) f.push(t("gui_rules_pfx_port") + r.port);
  if (r.src_label) f.push(t("gui_rules_pfx_src") + r.src_label);
  if (r.dst_label) f.push(t("gui_rules_pfx_dst") + r.dst_label);
  if (r.src_ip_in) f.push(t("gui_rules_pfx_srcip") + r.src_ip_in);
  if (r.dst_ip_in) f.push(t("gui_rules_pfx_dstip") + r.dst_ip_in);
  const ts = r.throttle_state || {};
  const suppressed = (ts.cooldown_suppressed || 0) + (ts.throttle_suppressed || 0);
  if (suppressed > 0) f.push(t("gui_rules_pfx_suppressed") + suppressed);
  if (r.match_fields && Object.keys(r.match_fields).length) f.push(t("gui_rules_pfx_match") + Object.keys(r.match_fields).join(", "));
  return f.join(" | ");
}

/* rules.js:92-103 — cooldown badge. warn while cooling, ok when ready. */
function statusCell(r) {
  if (r.cooldown_remaining > 0) {
    return badge(t("gui_cooldown_active") + " · " + tf("gui_cooldown_remaining", { mins: r.cooldown_remaining }), "warn");
  }
  return badge(t("gui_cooldown_ready"), "ok");
}

/* The type cell. Direction B paints only exceptions, so the type is a neutral
 * chip: a colour per type would invent four severities the product does not
 * have (rules.js:83 prints the bare capitalised word). */
function typeCell(r) {
  return el("span", { class: "chips" }, el("span", null, el("b", { text: r.type })));
}

// ── drawer building blocks ──────────────────────────────────────────────────

/** An editable field: the control carries data-field so the guard sees it. */
function editField(key, labelText, control, hint) {
  control.dataset.field = key;
  const box = labelled(labelText, control, hint || null);
  box.lab.appendChild(el("code", { text: key }));
  return box;
}

/** A read-only backend field: value + why it is not editable here. */
function roField(key, value, noteText) {
  const li = el("li");
  li.appendChild(el("code", { class: "c", text: key }));
  const v = el("span", { class: "s", text: showValue(value) });
  v.dataset.field = key;
  li.appendChild(v);
  li.appendChild(el("span", { class: "r", text: noteText }));
  return li;
}

function roList(rows) {
  return el("ul", { class: "stack rofields" }, rows);
}

function sectionHead(text) {
  return el("h4", { class: "eyebrow", text: text });
}

/* AL-02 — event rule drawer. Form fields and their save mapping:
 *   ev-cat / ev-type  -> filter_value      (rules.js:519, index.html:2584-2591)
 *   ev-status         -> filter_status     (rules.js:531)
 *   ev-severity       -> filter_severity   (rules.js:532)
 *   ev-match-fields   -> match_fields      (rules.js:522-528, _parseMatchFields :387-407)
 *   ev-tt/cnt/win/cd  -> threshold_type, threshold_count, threshold_window,
 *                        cooldown_minutes (rules.js:534-537)
 *   name              -> derived from the catalogue entry (rules.js:520)
 * The category→event→filter-row chain is populateEvents/updateEventFilters
 * (rules.js:366-390, :445-457) driven by snapshots/event_catalog.json. */
function eventDrawer(rule, catalog) {
  const body = el("div", { "data-cov": "AL-02" });
  const r = rule || {};
  const state = {};
  state.filter_value = r.filter_value || "";
  state.filter_status = r.filter_status || "all";
  state.filter_severity = r.filter_severity || "all";
  state.threshold_type = r.threshold_type || "immediate";
  state.threshold_count = r.threshold_count === undefined ? 5 : r.threshold_count;
  state.threshold_window = r.threshold_window === undefined ? 10 : r.threshold_window;
  state.cooldown_minutes = r.cooldown_minutes === undefined ? 10 : r.cooldown_minutes;
  state.match_fields = r.match_fields || {};

  const categories = (catalog && catalog.categories) || [];
  const metaById = {};
  categories.forEach(function (cat) {
    (cat.events || []).forEach(function (ev) { metaById[ev.id] = el2meta(ev, cat); });
  });
  function el2meta(ev, cat) {
    const m = {};
    Object.keys(ev).forEach(function (k) { m[k] = ev[k]; });
    m.category_id = cat.id;
    m.category_label = cat.label;
    return m;
  }
  let category = "";
  categories.forEach(function (cat) {
    if ((cat.events || []).some(function (ev) { return ev.id === state.filter_value; })) category = cat.id;
  });

  const catSel = el("select", { class: "field" });
  const evSel = el("select", { class: "field" });
  const nameOut = el("span", { class: "field ro" });
  const infoBox = el("div", { class: "evinfo", "data-tone": "info", hidden: true });
  const statusSel = selectField(EV_STATUS, state.filter_status, function (v) { state.filter_status = v; repaintPayload(); });
  const sevSel = selectField(EV_SEVERITY, state.filter_severity, function (v) { state.filter_severity = v; repaintPayload(); });
  const filterRow = el("div", { class: "qrow" });
  const statusBox = editField("filter_status", t("gui_ev_status_filter"), statusSel);
  const sevBox = editField("filter_severity", t("gui_ev_severity_filter"), sevSel);
  filterRow.appendChild(statusBox);
  filterRow.appendChild(sevBox);

  const matchArea = el("textarea", { class: "field ta", rows: "4", placeholder: t("gui_ev_matchers_placeholder") });
  matchArea.value = Object.keys(state.match_fields).map(function (k) { return k + "=" + state.match_fields[k]; }).join("\n");
  matchArea.addEventListener("input", function () { repaintPayload(); });

  const cntInput = numberField(state.threshold_count, function (v) { state.threshold_count = v; repaintPayload(); });
  const winInput = numberField(state.threshold_window, function (v) { state.threshold_window = v; repaintPayload(); });
  const cdInput = numberField(state.cooldown_minutes, function (v) { state.cooldown_minutes = v; repaintPayload(); });
  const cntBox = editField("threshold_count", t("gui_count"), cntInput);
  const winBox = editField("threshold_window", t("gui_window_min"), winInput);
  const ttBox = editField("threshold_type", t("gui_type"),
    radioGroup("al-ev-tt", EV_TT, state.threshold_type, function (v) { state.threshold_type = v; onTtChange(); repaintPayload(); }));

  // rules.js:341-345 (onEvTtChange) — count/window only exist for cumulative.
  function onTtChange() {
    const isCount = state.threshold_type === "count";
    cntBox.hidden = !isCount;
    winBox.hidden = !isCount;
  }

  // rules.js:366-390 (populateEvents)
  function paintEvents() {
    clear(evSel);
    const cat = categories.filter(function (c) { return c.id === category; })[0];
    if (!cat) {
      evSel.appendChild(el("option", { value: "", text: t("gui_select_category_first") }));
      state.filter_value = "";
      paintInfo();
      return;
    }
    (cat.events || []).forEach(function (meta) {
      const text = meta.label && meta.label !== meta.id ? meta.id + " | " + meta.label : meta.id;
      const opt = el("option", { value: meta.id, text: text });
      if (meta.id === state.filter_value) opt.selected = true;
      evSel.appendChild(opt);
    });
    if (!metaById[state.filter_value] || metaById[state.filter_value].category_id !== category) {
      state.filter_value = evSel.value;
    }
    paintInfo();
  }

  // rules.js:392-441 (_renderEventInfo) + :445-457 (updateEventFilters)
  function paintInfo() {
    const meta = metaById[state.filter_value] || {};
    const showStatus = !!state.filter_value && !!meta.supports_status;
    const showSeverity = !!state.filter_value && !!meta.supports_severity;
    filterRow.hidden = !(showStatus || showSeverity);
    statusBox.hidden = !showStatus;
    sevBox.hidden = !showSeverity;
    if (!showStatus) { state.filter_status = "all"; statusSel.value = "all"; }
    if (!showSeverity) { state.filter_severity = "all"; sevSel.value = "all"; }

    clear(infoBox);
    infoBox.hidden = !state.filter_value;
    if (!state.filter_value) { nameOut.textContent = "—"; return; }
    const title = meta.label || state.filter_value;
    // rules.js:519-520 — the saved name is the catalogue label, never typed.
    nameOut.textContent = title;
    const head = el("div", { class: "evinfo-h" }, el("code", { text: state.filter_value }));
    if (meta.supports_status) head.appendChild(badge(t("gui_ev_status_filter_badge"), "info"));
    if (meta.supports_severity) head.appendChild(badge(t("gui_ev_severity_filter_badge"), "crit"));
    infoBox.appendChild(head);
    infoBox.appendChild(el("b", { text: title }));
    if (meta.description && meta.description !== title) infoBox.appendChild(el("p", { text: meta.description }));
    infoBox.appendChild(note(meta.tips || (meta.supports_status || meta.supports_severity
      ? t("gui_ev_capability_filters") : t("gui_ev_capability_basic"))));
    // rules.js:427-437 renders every related event; some catalogue entries carry
    // 30+, which pushes the form itself below the fold. The first eight are
    // shown and the rest are counted — the count is the honest way to say the
    // list is longer without burying the fields the drawer exists to edit.
    const related = meta.related_events || [];
    if (related.length) {
      const rel = el("div", { class: "chips" }, el("span", { text: t("gui_ev_see_also") }));
      related.slice(0, 8).forEach(function (e) { rel.appendChild(el("span", null, el("b", { text: e }))); });
      if (related.length > 8) rel.appendChild(el("span", { text: tf("v2_al_ev_related_more", { n: related.length - 8 }) }));
      infoBox.appendChild(rel);
    }
  }

  categories.forEach(function (cat) {
    const opt = el("option", { value: cat.id, text: cat.label });
    if (cat.id === category) opt.selected = true;
    catSel.appendChild(opt);
  });
  catSel.addEventListener("change", function () { category = catSel.value; paintEvents(); repaintPayload(); });
  evSel.addEventListener("change", function () { state.filter_value = evSel.value; paintInfo(); repaintPayload(); });

  const payload = el("pre", { class: "codepane" });
  function repaintPayload() {
    const d = {};
    d.name = nameOut.textContent === "—" ? "" : nameOut.textContent;
    d.filter_value = state.filter_value;
    d.filter_status = statusSel.value || "all";
    d.filter_severity = sevSel.value || "all";
    d.match_fields = parseMatchers(matchArea.value);
    d.threshold_type = state.threshold_type;
    d.threshold_count = state.threshold_count;
    d.threshold_window = state.threshold_window;
    d.cooldown_minutes = state.cooldown_minutes;
    payload.textContent = "POST /api/rules/event · PUT /api/rules/" + (r.index === undefined ? "<idx>" : r.index) + "\n"
      + JSON.stringify(d, null, 2);
  }

  body.appendChild(note(t("v2_al_src_event")));
  body.appendChild(sectionHead(t("v2_al_form_section")));
  body.appendChild(labelled(t("gui_category"), catSel));
  body.appendChild(editField("filter_value", t("gui_event_type"), evSel));
  body.appendChild(infoBox);
  body.appendChild(editField("name", t("gui_rule_name"), nameOut, t("v2_al_fn_name_event")));
  body.appendChild(filterRow);
  body.appendChild(editField("match_fields", t("gui_ev_field_matchers"), matchArea, t("gui_ev_field_matchers_hint")));
  body.appendChild(sectionHead(t("gui_threshold")));
  body.appendChild(ttBox);
  body.appendChild(cntBox);
  body.appendChild(winBox);
  body.appendChild(editField("cooldown_minutes", t("gui_cooldown"), cdInput));

  body.appendChild(sectionHead(t("v2_al_ro_section")));
  body.appendChild(roList([
    roField("type", r.type || "event", t("v2_al_fn_type")),
    roField("filter_key", r.filter_key || "event_type", t("v2_al_fn_filter_key")),
    roField("name_key", r.name_key, t("v2_al_fn_i18n_key")),
    roField("desc", r.desc, t("v2_al_fn_desc")),
    roField("desc_key", r.desc_key, t("v2_al_fn_i18n_key")),
    roField("rec", r.rec, t("v2_al_fn_rec")),
    roField("rec_key", r.rec_key, t("v2_al_fn_i18n_key")),
    roField("throttle", r.throttle, t("v2_al_fn_throttle")),
    roField("throttle_state", r.throttle_state, t("v2_al_fn_throttle_state")),
    roField("cooldown_remaining", r.cooldown_remaining, t("v2_al_fn_cooldown_remaining")),
  ]));

  body.appendChild(sectionHead(t("v2_al_payload")));
  body.appendChild(verifyPane(payload));
  body.appendChild(note(t("v2_al_mock_save")));

  paintEvents();
  onTtChange();
  repaintPayload();
  const title = r.index === undefined ? t("gui_add_event_rule") : t("gui_edit_event_rule");
  return drawerSpec(title, body, function () { toast.info(t("v2_al_mock_save")); return true; });
}

/* rules.js:387-407 (_parseMatchFields) — one `field.path=pattern` per line. The
 * product throws on a malformed line; here the offending line is reported and
 * skipped so the payload preview stays live while typing. */
function parseMatchers(text) {
  const out = {};
  String(text || "").split(/\r?\n/).forEach(function (raw) {
    const line = raw.trim();
    if (!line) return;
    const at = line.indexOf("=");
    if (at <= 0) return;
    const key = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    if (key && value) out[key] = value;
  });
  return out;
}

/* AL-03 — system health drawer. saveSystemRule (rules.js:545-560) sends exactly
 * three keys; rules.py:182-216 fills the rest and rejects any filter_value other
 * than pce_health, which is why the select is disabled (index.html:2657). */
function systemDrawer(rule) {
  const body = el("div", { "data-cov": "AL-03" });
  const r = rule || {};
  const nameInput = textField(r.name || t("rule_pce_health"), function () { repaint(); });
  const typeSel = selectField(SYS_TYPES, r.filter_value || "pce_health", function () { repaint(); });
  typeSel.disabled = true;
  const cdInput = numberField(r.cooldown_minutes === undefined ? 30 : r.cooldown_minutes, function () { repaint(); });
  const payload = el("pre", { class: "codepane" });

  function repaint() {
    const d = {};
    d.name = nameInput.value.trim() || t("rule_pce_health");
    d.filter_value = typeSel.value || "pce_health";
    d.cooldown_minutes = cdInput.value || 30;
    payload.textContent = "POST /api/rules/system · PUT /api/rules/" + (r.index === undefined ? "<idx>" : r.index) + "\n"
      + JSON.stringify(d, null, 2);
  }

  body.appendChild(note(t("v2_al_src_system")));
  body.appendChild(sectionHead(t("v2_al_form_section")));
  body.appendChild(editField("name", t("gui_rule_name"), nameInput));
  body.appendChild(editField("filter_value", t("gui_system_health_type"), typeSel, t("gui_system_health_desc")));
  body.appendChild(sectionHead(t("gui_threshold")));
  body.appendChild(note(t("gui_system_health_threshold_hint")));
  body.appendChild(editField("cooldown_minutes", t("gui_cooldown"), cdInput));

  body.appendChild(sectionHead(t("v2_al_ro_section")));
  body.appendChild(roList([
    roField("type", r.type || "system", t("v2_al_fn_type")),
    roField("threshold_type", r.threshold_type || "immediate", t("v2_al_fn_sys_threshold")),
    roField("threshold_count", r.threshold_count === undefined ? 1 : r.threshold_count, t("v2_al_fn_sys_threshold")),
    roField("threshold_window", r.threshold_window === undefined ? 10 : r.threshold_window, t("v2_al_fn_sys_threshold")),
    roField("desc", r.desc, t("v2_al_fn_desc_system")),
    roField("rec", r.rec, t("v2_al_fn_rec_system")),
    roField("match_fields", r.match_fields, t("v2_al_fn_match_system")),
    roField("throttle", r.throttle, t("v2_al_fn_throttle")),
    roField("throttle_state", r.throttle_state, t("v2_al_fn_throttle_state")),
    roField("cooldown_remaining", r.cooldown_remaining, t("v2_al_fn_cooldown_remaining")),
  ]));
  body.appendChild(sectionHead(t("v2_al_payload")));
  body.appendChild(verifyPane(payload));
  body.appendChild(note(t("v2_al_mock_save")));

  repaint();
  const title = r.index === undefined ? t("gui_add_system_health_rule") : t("gui_edit_system_health_rule");
  return drawerSpec(title, body, function () { toast.info(t("v2_al_mock_save")); return true; });
}

/* The filter fields a traffic/bandwidth rule can carry in storage. rules.py:41-47
 * calls these the "legacy scalar filter keys"; the FilterBar reads them
 * (filter-bar.mjs _objfbDeserialize :247-279) and writes the plural v2 keys back
 * (_objfbSerialize :179-212), which rules.py:66-77 whitelists. Both halves are
 * shown in the drawer because both halves exist in real stored rules. */
const TRAFFIC_FILTER_KEYS = ["src_label", "dst_label", "port", "proto"];
const BW_FILTER_KEYS = ["src_label", "dst_label", "src_ip_in", "dst_ip_in", "port", "proto",
  "ex_src_label", "ex_dst_label", "ex_src_ip", "ex_dst_ip", "ex_port"];

function filterFieldRows(keys, rule, noteText) {
  return keys.map(function (k) { return roField(k, rule[k], noteText); });
}

/* AL-04 / AL-05 — the two flow-rule drawers. They differ in four places only
 * (metric type, pd default, threshold label, stored filter key set), so one
 * builder serves both and the differences are parameters, not two copies.
 *   saveTraffic  rules.js:562-570  {name, pd, threshold_count, threshold_window,
 *                                   cooldown_minutes, filters}
 *   saveBW       rules.js:572-583  adds rule_type; the PUT path also sends
 *                                   type: rule_type (rules.js:578) */
function flowDrawer(kind, rule, snaps) {
  const isBw = kind === "bandwidth";
  const body = el("div", { "data-cov": isBw ? "AL-05" : "AL-04" });
  const r = rule || {};
  const metric = isBw ? (r.type === "volume" ? "volume" : "bandwidth") : "traffic";
  const state = {};
  state.metric = metric;
  state.pd = r.pd === undefined || r.pd === null ? (isBw ? "-1" : "2") : String(r.pd);

  const nameInput = textField(r.name || "", function () { repaint(); });
  const cntInput = numberField(r.threshold_count === undefined ? (isBw ? 100 : 10) : r.threshold_count, function () { repaint(); });
  const winInput = numberField(r.threshold_window === undefined ? 10 : r.threshold_window, function () { repaint(); });
  const cdInput = numberField(r.cooldown_minutes === undefined ? (isBw ? 30 : 10) : r.cooldown_minutes, function () { repaint(); });
  const cntBox = editField("threshold_count", isBw ? t("gui_bw_value_bandwidth") : t("gui_count"), cntInput);
  const cntHelp = el("small", { class: "hint", text: isBw ? t("gui_bw_help_bandwidth") : "" });
  if (isBw) cntBox.appendChild(cntHelp);

  const barHost = el("div");
  setFilterBarSnapshots(snaps.fb_suggest, snaps.fb_browse);
  const bar = createFilterBar(barHost, filterBarOpts(r));
  const serialized = el("ul", { class: "stack" });

  // rules.js:346-364 (onBwMetricTypeChange) — the threshold label/help swap with
  // the metric, and the metric IS the stored `type`.
  function onMetricChange() {
    if (!isBw) return;
    const volume = state.metric === "volume";
    cntBox.lab.firstChild.textContent = volume ? t("gui_bw_value_volume") : t("gui_bw_value_bandwidth");
    cntInput.placeholder = volume ? t("gui_bw_placeholder_volume") : t("gui_bw_placeholder_bandwidth");
    cntHelp.textContent = volume ? t("gui_bw_help_volume") : t("gui_bw_help_bandwidth");
  }

  const payload = el("pre", { class: "codepane" });
  function repaint() {
    const filters = bar.getFilters();
    clear(serialized);
    const keys = Object.keys(filters).sort();
    if (!keys.length) serialized.appendChild(el("li", null, el("span", { class: "s", text: t("v2_al_fb_none") })));
    keys.forEach(function (k) {
      const li = el("li");
      li.appendChild(el("code", { class: "c", text: k }));
      li.appendChild(el("span", { class: "s", text: JSON.stringify(filters[k]) }));
      serialized.appendChild(li);
    });

    const d = {};
    d.name = nameInput.value.trim();
    if (isBw) d.rule_type = state.metric;
    d.pd = state.pd;
    d.threshold_count = cntInput.value;
    d.threshold_window = winInput.value;
    d.cooldown_minutes = cdInput.value;
    d.filters = filters;
    const path = isBw ? "/api/rules/bandwidth" : "/api/rules/traffic";
    payload.textContent = "POST " + path + " · PUT /api/rules/" + (r.index === undefined ? "<idx>" : r.index) + "\n"
      + JSON.stringify(d, null, 2);
  }
  bar.onChange(repaint);

  body.appendChild(note(isBw ? t("gui_bw_rule_desc") : t("gui_traffic_rule_desc")));
  body.appendChild(note(isBw ? t("v2_al_src_bw") : t("v2_al_src_traffic")));
  body.appendChild(sectionHead(t("v2_al_form_section")));
  body.appendChild(editField("name", t("gui_rule_name"), nameInput));
  if (isBw) {
    body.appendChild(editField("type", t("gui_metric_type"),
      radioGroup("al-bw-mt", BW_METRICS, state.metric, function (v) { state.metric = v; onMetricChange(); repaint(); }),
      t("v2_al_fn_bw_metric")));
  }
  body.appendChild(editField("pd", t("gui_policy_dec"),
    radioGroup(isBw ? "al-bw-pd" : "al-tr-pd", PD_OPTS, state.pd, function (v) { state.pd = v; repaint(); })));
  body.appendChild(sectionHead(t("gui_col_filters")));
  body.appendChild(barHost);
  body.appendChild(sectionHead(t("v2_al_fb_serialized")));
  body.appendChild(serialized);
  body.appendChild(note(t("v2_al_fb_note")));
  body.appendChild(sectionHead(t("gui_threshold")));
  body.appendChild(cntBox);
  body.appendChild(editField("threshold_window", t("gui_window_min"), winInput));
  body.appendChild(editField("cooldown_minutes", t("gui_cooldown"), cdInput));

  const ro = [];
  if (!isBw) ro.push(roField("type", r.type || "traffic", t("v2_al_fn_type")));
  ro.push(roField("threshold_type", r.threshold_type || "count", t("v2_al_fn_flow_threshold")));
  ro.push(roField("desc", r.desc, t("v2_al_fn_desc_flow")));
  ro.push(roField("rec", r.rec, t("v2_al_fn_rec_flow")));
  ro.push(roField("throttle", r.throttle, t("v2_al_fn_throttle")));
  ro.push(roField("throttle_state", r.throttle_state, t("v2_al_fn_throttle_state")));
  ro.push(roField("cooldown_remaining", r.cooldown_remaining, t("v2_al_fn_cooldown_remaining")));
  body.appendChild(sectionHead(t("v2_al_ro_section")));
  body.appendChild(roList(ro));

  body.appendChild(sectionHead(t("v2_al_stored_filters")));
  const storedKeys = isBw ? BW_FILTER_KEYS : TRAFFIC_FILTER_KEYS;
  body.appendChild(roList(filterFieldRows(storedKeys, r, t("v2_al_fn_filter_scalar"))));
  if (isBw) body.appendChild(note(t("v2_al_fn_proto_bw")));

  body.appendChild(sectionHead(t("v2_al_payload")));
  body.appendChild(verifyPane(payload));
  body.appendChild(note(t("v2_al_mock_save")));

  onMetricChange();
  repaint();
  const addKey = isBw ? "gui_add_bw_rule" : "gui_add_traffic_rule";
  const editKey = isBw ? "gui_edit_bw_rule" : "gui_edit_traffic_rule";
  return drawerSpec(t(r.index === undefined ? addKey : editKey), body, function () {
    toast.info(t("v2_al_mock_save"));
    return true;
  });
}

// rules.js:370-378 / :380-385 — the rule FilterBar's category set. label_group
// is excluded because rules.py:36-40 rejects it with a 400, so offering it would
// build a filter the backend refuses.
const RULE_FB_CATS = ["label", "iplist", "workload", "ip", "service", "port", "process", "winservice", "transmission"];

function filterBarOpts(initial) {
  const o = {};
  o.cats = RULE_FB_CATS;
  if (initial) o.initial = initial;
  return o;
}

// ── rules sub-view mount ────────────────────────────────────────────────────

async function mountRules(root, ctx) {
  const handles = {};
  drawer.registerAudit("al-rule-event", function () { return handles.open ? handles.open("event") : null; });
  drawer.registerAudit("al-rule-system", function () { return handles.open ? handles.open("system") : null; });
  drawer.registerAudit("al-rule-traffic", function () { return handles.open ? handles.open("traffic") : null; });
  drawer.registerAudit("al-rule-bandwidth", function () { return handles.open ? handles.open("bandwidth") : null; });
  palette.registerFor(R_RULES, cmdSpec("al:add-event", t("gui_add_event"), function () { if (handles.open) handles.open("event", {}); }));
  palette.registerFor(R_RULES, cmdSpec("al:add-traffic", t("gui_add_traffic"), function () { if (handles.open) handles.open("traffic", {}); }));
  palette.registerFor(R_RULES, cmdSpec("al:test", t("v2_al_test_title"), function () { if (handles.focusTest) handles.focusTest(); }));

  root.appendChild(areaTop(R_RULES));
  const wrap = el("div", { class: "wb" });
  const main = el("div", { class: "wb-main" });
  const aside = el("aside", { class: "wb-aside" });
  wrap.appendChild(main);
  wrap.appendChild(aside);
  root.appendChild(wrap);

  // AL-06: #/alerting/rules?hl=<index|id>. GET /api/rules/<idx>/highlight
  // (rules.py:515-525) returns that one rule as syntax-highlighted JSON; the
  // hash parameter is the same address in a page that has no backend.
  const hl = ctx.query.get("hl");

  await withErrorCard(main, "rules (" + RULE_SNAPS.length + ")",
    function () { return loadAll(RULE_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      setFilterBarText(t);
      setFilterBarSnapshots(d.fb_suggest, d.fb_browse);

      // One in-memory copy of the snapshot: toggles and deletes below mutate
      // THIS, never the store's cached JSON, so leaving and returning to the
      // route resets the page — the honest behaviour for a mockup with no PUT.
      const state = {};
      state.rules = (Array.isArray(d.rules) ? d.rules : []).map(function (r) {
        const c = {};
        Object.keys(r).forEach(function (k) { c[k] = r[k]; });
        return c;
      });
      state.search = "";
      state.type = "";
      state.selected = [];
      state.hl = null;
      state.rules.forEach(function (r) {
        if (hl !== null && hl !== undefined && (String(r.index) === String(hl) || String(r.id) === String(hl))) state.hl = r.index;
      });

      const listPanel = panel("AL-01", t("gui_tab_rules"));
      const tableHost = el("div");
      const floatHost = el("div");
      const chipRow = el("div", { class: "qrow" });
      const meta = el("span", { class: "meta" });
      listPanel.head.appendChild(meta);
      main.appendChild(listPanel);
      main.appendChild(floatHost);

      const search = el("input", { class: "field", placeholder: t("gui_rules_search_placeholder") });
      search.addEventListener("input", function () { state.search = search.value.toLowerCase().trim(); paintTable(); });

      function typeCounts() {
        const counts = {};
        state.rules.forEach(function (r) { counts[r.type] = (counts[r.type] || 0) + 1; });
        return counts;
      }

      // index.html:1276-1279 — the four "+" buttons, one per rule type.
      function paintControls() {
        clear(chipRow);
        const counts = typeCounts();
        const searchBox = el("div", { class: "qf grow" }, el("label", { text: t("gui_search") }), search);
        chipRow.appendChild(searchBox);

        const chips = el("div", { class: "qf" }, el("label", { text: t("gui_col_type") }), el("div", { class: "typechips" }));
        const holder = chips.lastChild;
        const all = btn("btn ghost", t("v2_al_chip_all") + " " + state.rules.length, function () { state.type = ""; paintControls(); paintTable(); });
        all.setAttribute("aria-pressed", state.type === "" ? "true" : "false");
        holder.appendChild(all);
        ["event", "system", "traffic", "bandwidth", "volume"].forEach(function (ty) {
          if (!counts[ty]) return;
          const b = btn("btn ghost", ty + " " + counts[ty], function () {
            state.type = state.type === ty ? "" : ty;
            paintControls();
            paintTable();
          });
          b.setAttribute("aria-pressed", state.type === ty ? "true" : "false");
          holder.appendChild(b);
        });
        chipRow.appendChild(chips);
        chipRow.appendChild(spacer());
        const add = el("div", { class: "qf" }, el("label", { text: t("v2_al_add_rule") }), el("div", { class: "typechips" }));
        const addHolder = add.lastChild;
        addHolder.appendChild(btn("btn", t("gui_add_event"), function () { handles.open("event", {}); }));
        addHolder.appendChild(btn("btn", t("gui_add_system_health"), function () { handles.open("system", {}); }));
        addHolder.appendChild(btn("btn", t("gui_add_traffic"), function () { handles.open("traffic", {}); }));
        addHolder.appendChild(btn("btn", t("gui_add_bw"), function () { handles.open("bandwidth", {}); }));
        chipRow.appendChild(add);
      }

      // rules.js:225-241 (_doFilterRules): plain substring over the row's text.
      function visibleRules() {
        return state.rules.filter(function (r) {
          if (state.type && r.type !== state.type) return false;
          if (!state.search) return true;
          const hay = [r.type, r.name, conditionText(r), filtersText(r)].join(" ").toLowerCase();
          return hay.indexOf(state.search) >= 0;
        });
      }

      function isSelected(r) { return state.selected.indexOf(r.index) >= 0; }
      function toggleSel(r, on) {
        const at = state.selected.indexOf(r.index);
        if (on && at < 0) state.selected.push(r.index);
        if (!on && at >= 0) state.selected.splice(at, 1);
        paintFloat();
      }

      // rules.js:130-147 (_rulesToggleSwitchClick) — the product PUTs
      // {enabled} and reverts the switch when the call fails. There is no call
      // to make here, so the toast names the request instead of pretending.
      function toggleEnabled(r, on) {
        r.enabled = on;
        toast.info(tf("v2_al_toggle_note", { idx: r.index, enabled: String(on) }));
        paintTable();
      }

      function paintFloat() {
        clear(floatHost);
        if (!state.selected.length) return;
        const bar = el("div", { class: "floatbar", "data-tone": "crit" },
          el("span", { text: t("gui_selected") + " " }),
          el("b", { text: String(state.selected.length) }),
          btn("btn danger", t("v2_al_bulk_delete"), function () { openDelete(); }),
          btn("btn ghost", t("v2_al_sel_clear"), function () { state.selected = []; paintFloat(); paintTable(); })
        );
        floatHost.appendChild(bar);
      }

      // rules.js:163-175 (deleteSelected): descending index order, one DELETE
      // per rule, partial failures counted. The impact list says all of it.
      function openDelete() {
        const ids = state.selected.slice().sort(function (a, b) { return b - a; });
        const names = state.rules.filter(function (r) { return ids.indexOf(r.index) >= 0; })
          .map(function (r) { return r.type + " · " + r.name; });
        const impact = [tf("v2_al_del_count", { n: ids.length })].concat(names.slice(0, 6));
        if (names.length > 6) impact.push(tf("v2_al_del_more", { n: names.length - 6 }));
        impact.push(t("v2_al_del_order"));
        impact.push(t("v2_al_del_norecover"));
        return modal.confirm(confirmSpec(t("gui_msg_confirm_delete"), impact, function () {
          state.rules = state.rules.filter(function (r) { return ids.indexOf(r.index) < 0; });
          state.selected = [];
          toast.ok(t("v2_al_mock_delete"));
          paintFloat();
          paintTable();
          return true;
        }));
      }

      const jsonPanel = panel("AL-06", t("v2_al_hl_title"));
      const jsonBox = el("div");
      jsonPanel.body.appendChild(jsonBox);
      jsonPanel.body.appendChild(note(t("v2_al_hl_note")));

      function paintHighlight() {
        clear(jsonBox);
        const hit = state.rules.filter(function (r) { return r.index === state.hl; })[0];
        if (!hit) {
          jsonBox.appendChild(el("div", { class: "empty" },
            el("span", { class: "et", text: t("v2_al_hl_none") }),
            el("p", { text: t("v2_al_hl_empty") })));
          return;
        }
        jsonBox.appendChild(el("p", { class: "note", text: "GET /api/rules/" + hit.index + "/highlight" }));
        jsonBox.appendChild(el("pre", { class: "codepane tall", text: JSON.stringify(jsonOf(hit), null, 2) }));
        jsonBox.appendChild(btn("btn ghost", t("v2_al_hl_clear"), function () { router.go(R_RULES); }));
      }

      function paintTable() {
        const rows = visibleRules().map(function (r) {
          r._tone = r.index === state.hl ? "info" : null;
          return r;
        });
        meta.textContent = tf("v2_al_meta_counts", {
          total: state.rules.length,
          shown: rows.length,
          on: state.rules.filter(function (r) { return r.enabled !== false; }).length,
          cd: state.rules.filter(function (r) { return r.cooldown_remaining > 0; }).length,
        });

        const columns = [
          col("pick", "", pickCell(function () {
            const box = el("input", { type: "checkbox" });
            box.checked = rows.length > 0 && rows.every(isSelected);
            box.addEventListener("change", function () {
              rows.forEach(function (r) { toggleSel(r, box.checked); });
              paintTable();
            });
            return box;
          }, function (r) {
            const box = el("input", { type: "checkbox" });
            box.checked = isSelected(r);
            box.addEventListener("change", function () { toggleSel(r, box.checked); });
            return box;
          })),
          col("enabled", t("gui_enabled"), widthCell(72, function (r) {
            const on = r.enabled !== false;
            const b = btn("switch", on ? "ON" : "OFF", function () { toggleEnabled(r, !on); });
            b.setAttribute("aria-pressed", on ? "true" : "false");
            b.setAttribute("data-tone", on ? "ok" : "neutral");
            b.title = on ? t("gui_enabled") : t("gui_disabled");
            return b;
          })),
          col("type", t("gui_col_type"), widthCell(112, typeCell)),
          col("name", t("gui_col_name"), buildCell(function (r) {
            return el("span", { class: "idc" }, el("b", { text: r.name || "—" }), el("small", { text: "#" + r.index }));
          })),
          col("status", t("gui_col_status"), widthCell(150, statusCell)),
          col("cond", t("gui_col_condition"), widthCell(230, function (r) {
            return el("code", { class: "mono", text: conditionText(r) });
          })),
          col("filters", t("gui_col_filters"), buildCell(function (r) {
            return el("span", { title: filtersText(r), text: filtersText(r) || "—" });
          })),
          col("act", t("gui_col_edit"), widthCell(120, function (r) {
            const box = el("div", { class: "rowacts" });
            box.appendChild(btn("btn ghost", t("gui_edit_rule"), function () { handles.open(r.type, r); }));
            box.appendChild(btn("btn link", "JSON", function () { router.go(R_RULES + "?hl=" + r.index); }));
            return box;
          })),
        ];

        clear(tableHost);
        tableHost.appendChild(chipRow);
        const host = el("div");
        tableHost.appendChild(host);
        table.render(host, buildTable(columns, rows));
        paintHighlight();
        if (state.hl !== null) {
          // The row carries data-tone="info" so it exposes --mark/--fill, but the
          // visible treatment comes from .hl: a deep link is a selection, not a
          // severity, and the table's tone marks are reserved for warn/crit
          // (components.css:110-112, "only exceptions wear a mark").
          const tr = host.querySelector('tbody tr[data-tone="info"]');
          if (tr) {
            tr.classList.add("hl");
            if (tr.scrollIntoView) tr.scrollIntoView({ block: "center" });
          }
        }
      }

      listPanel.body.appendChild(tableHost);
      listPanel.body.appendChild(note(t("v2_al_list_note")));

      // ── AL-02…AL-05 openers ────────────────────────────────────────────
      // firstOf() is a seed for window.__openRuleDrawer(ty) only — the audit
      // hook (registerAudit above) and tests/design_v2/test_alert_rule_fields.py
      // call handles.open(ty) with no rule and need a populated form to check
      // field coverage against. Real "add" entry points (the four + buttons and
      // the palette add-* commands) must pass an explicit {} so the drawer opens
      // empty in add mode instead of silently seeding rule #0 — see finding #2.
      function firstOf(ty) {
        if (ty === "bandwidth") {
          return state.rules.filter(function (r) { return r.type === "bandwidth" || r.type === "volume"; })[0] || null;
        }
        return state.rules.filter(function (r) { return r.type === ty; })[0] || null;
      }
      handles.open = function (ty, rule) {
        const r = rule || firstOf(ty);
        if (ty === "event") return drawer.open(eventDrawer(r, d.event_catalog));
        if (ty === "system") return drawer.open(systemDrawer(r));
        // The flow drawers carry the FilterBar, whose three zones do not fit the
        // standard drawer width (investigate.mjs:982 widens it for the same bar).
        const h = drawer.open(flowDrawer(ty === "traffic" ? "traffic" : "bandwidth", r, d));
        h.el.classList.add("wide");
        return h;
      };
      // Contract used by tests/design_v2/test_alert_rule_fields.py and by
      // window.__openAllForAudit() (Task 7 report §7).
      window.__openRuleDrawer = function (ty) { return handles.open(ty); };

      // ── AL-07 rule_test sandbox ────────────────────────────────────────
      const testPanel = panel("AL-07", t("v2_al_test_title"));
      main.appendChild(testPanel);
      testPanel.body.appendChild(note(t("v2_al_test_desc")));

      const samples = ((d.events_viewer && d.events_viewer.items) || []).slice(0, 40);
      const sampleSel = el("select", { class: "field" });
      samples.forEach(function (item, i) {
        sampleSel.appendChild(el("option", { value: String(i), text: (item.event_type || "?") + " · " + stamp(item.timestamp) }));
      });
      const area = el("textarea", { class: "field ta", rows: "8", spellcheck: "false" });
      const resultHost = el("div");

      function loadSample() {
        const item = samples[Number(sampleSel.value) || 0];
        if (!item) return;
        area.value = JSON.stringify(item.raw || {}, null, 2);
      }

      function runTest() {
        clear(resultHost);
        let event = null;
        try { event = JSON.parse(area.value); } catch (e) {
          resultHost.appendChild(el("p", { class: "note", "data-tone": "crit", text: t("v2_al_test_bad_json") + " " + e.message }));
          return;
        }
        // analyzer.py:175-182 (rule_enabled) + :1040 — a disabled rule is skipped
        // before matching, so the sandbox skips it too. Toggling a rule off in the
        // list above and matching again shows exactly that.
        const eventRules = state.rules.filter(function (r) { return r.type === "event" && r.enabled !== false; });
        const hits = eventRules.filter(function (r) { return matchesEventRule(r, event); });
        const list = el("ul", { class: "stack" });
        hits.forEach(function (r) {
          const li = el("li");
          li.appendChild(el("span", { class: "dot", "data-tone": "ok" }));
          li.appendChild(el("span", { class: "s" }, el("b", { text: r.name }), el("code", { text: "#" + r.index })));
          li.appendChild(el("span", { class: "r", text: "filter_value=" + r.filter_value
            + " · filter_status=" + (r.filter_status || "all")
            + " · filter_severity=" + (r.filter_severity || "all")
            + " · match_fields=" + JSON.stringify(r.match_fields || {}) }));
          list.appendChild(li);
        });
        resultHost.appendChild(el("p", { class: "note", text: tf("v2_al_test_result", { hits: hits.length, total: eventRules.length }) }));
        if (hits.length) resultHost.appendChild(list);
        else resultHost.appendChild(el("div", { class: "empty" },
          el("span", { class: "et", text: t("v2_al_test_none") }),
          el("p", { text: t("v2_al_test_none_body") })));
      }

      const testRow = el("div", { class: "qrow" },
        el("div", { class: "qf grow" }, el("label", { text: t("v2_al_test_sample") }), sampleSel),
        el("div", { class: "qf" }, el("label", { text: " " }), btn("btn", t("v2_al_test_load"), loadSample)),
        el("div", { class: "qf" }, el("label", { text: " " }), btn("btn primary", t("v2_al_test_run"), runTest))
      );
      testPanel.body.appendChild(testRow);
      testPanel.body.appendChild(area);
      testPanel.body.appendChild(resultHost);
      testPanel.body.appendChild(note(t("v2_al_test_note")));
      handles.focusTest = function () { area.focus(); };

      aside.appendChild(jsonPanel);

      // The guide rail's second card explains what this page does NOT do, which
      // on a page full of switches is the most important thing on it.
      const scope = panel(null, t("v2_al_scope_title"));
      scope.body.appendChild(note(t("v2_al_scope_body")));
      scope.body.appendChild(note(t("v2_al_scope_ops")));
      scope.body.appendChild(btn("btn ghost", t("v2_health_goto") + " " + R_OPS, function () { router.go(R_OPS); }));
      aside.appendChild(scope);

      paintControls();
      paintTable();
      loadSample();
      withMeta(testPanel, tf("v2_al_test_meta", { n: samples.length }));
    });
}

// ══════════════════════════════════════════════════════ ops sub-view ════════

/* AL-13 — the console. actions.js:88-146 writes into #a-log: one bracketed
 * timestamp line per action, then the response `output`, then one line per
 * dispatch result. This mockup has no backend, so it logs the REQUEST each
 * button would send and says the run did not happen. It never prints a fake
 * `output` — a console that lies is worse than an empty one. */
function makeConsole() {
  const box = el("pre", { class: "console", "aria-live": "polite" });
  const lines = [];
  function paint() {
    box.textContent = lines.length ? lines.join("\n") : t("v2_al_console_empty");
    box.dataset.empty = lines.length ? "false" : "true";
    box.scrollTop = box.scrollHeight;
  }
  function clock() {
    const d = new Date();
    const p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
  }
  const api = {};
  api.el = box;
  api.request = function (method, path, body) {
    lines.push("[" + clock() + "] " + method + " " + path + (body ? " " + JSON.stringify(body) : ""));
    lines.push("          " + t("v2_al_console_not_run"));
    paint();
  };
  api.reset = function () { lines.length = 0; paint(); };
  paint();
  return api;
}

/* AL-14 — actions.js:1-8 (_alertChannelTone), digit for digit. The product's
 * CSS variables map onto the five-tone vocabulary: dim→neutral, warn→warn,
 * success→ok, failed→crit, skipped→warn, accent2→info. */
function channelTone(ch) {
  if (!ch.enabled) return "neutral";
  if (!ch.configured) return "warn";
  if (ch.last_status === "success") return "ok";
  if (ch.last_status === "failed") return "crit";
  if (ch.last_status === "skipped") return "warn";
  return "info";
}

/* actions.js:10-33 (_renderAlertChannelStatus) — the issue list, in order. The
 * one addition: a missing config key is named the way its settings form names it
 * ("Webhook URL (alerts.webhook_url)") instead of the bare dotted path, using
 * the labels alert_plugins.json already carries. */
function channelDetail(ch, labels) {
  const issues = [];
  if (!ch.enabled) issues.push(t("gui_action_plugin_disabled"));
  if (!ch.configured && ch.missing_required && ch.missing_required.length) {
    const named = ch.missing_required.map(function (k) { return labels[k] ? labels[k] + " (" + k + ")" : k; });
    issues.push(t("gui_action_plugin_missing_prefix") + " " + named.join(", "));
  }
  if (ch.last_status) issues.push(t("gui_action_plugin_last_prefix") + "=" + ch.last_status);
  if (ch.last_error) issues.push(ch.last_error);
  return issues.length ? issues.join(" | ") : t("gui_action_plugin_ready");
}

/** alert_plugins.json: plugin field key -> human label, so a missing_required
 *  entry can be named the way its settings form names it. */
function fieldLabels(plugins, name) {
  const out = {};
  const p = (plugins && plugins.plugins && plugins.plugins[name]) || null;
  ((p && p.fields) || []).forEach(function (f) { out[f.key] = f.label; });
  return out;
}

async function mountOps(root, ctx) {
  const handles = {};
  modal.registerAudit("al-ops-watermark", function () { return handles.watermark ? handles.watermark() : null; });
  modal.registerAudit("al-ops-bp", function () { return handles.bestPractices ? handles.bestPractices() : null; });
  palette.registerFor(R_OPS, cmdSpec("al:run", t("gui_run_once"), function () { if (handles.run) handles.run(); }));
  palette.registerFor(R_OPS, cmdSpec("al:test-alert", t("gui_test_alert"), function () { if (handles.testAll) handles.testAll(); }));

  root.appendChild(areaTop(R_OPS));
  const board = el("div", { class: "board" });
  root.appendChild(board);

  await withErrorCard(board, "ops (" + OPS_SNAPS.length + ")",
    function () { return loadAll(OPS_SNAPS); },
    function (d) {
      if (ctx.stale()) return;
      const consoleBox = makeConsole();
      const channels = (d.status && d.status.alert_channels) || [];
      const rules = Array.isArray(d.rules) ? d.rules : [];

      const row1 = el("div", { class: "brow c3" });
      const row2 = el("div", { class: "brow c2" });
      const row3 = el("div", { class: "brow" });
      board.appendChild(el("p", { class: "note", text: t("v2_al_ops_intro") }));
      board.appendChild(row1);
      board.appendChild(row2);
      board.appendChild(row3);

      // ── AL-08 run once (index.html:1300-1304, actions.py:506-531) ──────
      const runPanel = panel("AL-08", t("gui_run_once"));
      runPanel.body.appendChild(note(t("gui_run_once_desc")));
      runPanel.body.appendChild(note(t("v2_al_run_note")));
      handles.run = function () { consoleBox.request("POST", "/api/actions/run", null); };
      runPanel.body.appendChild(btn("btn primary", t("gui_run_btn"), handles.run));
      row1.appendChild(runPanel);

      // ── AL-09 debug (index.html:1306-1318, actions.py:533-566) ─────────
      const dbgPanel = panel("AL-09", t("gui_debug_mode"));
      dbgPanel.body.appendChild(note(t("gui_debug_desc")));
      const minsInput = numberField(30);
      const pdSel = selectField(DEBUG_PD, "3");
      const dbgRow = el("div", { class: "qrow" },
        el("div", { class: "qf" }, el("label", { text: t("gui_window_min") }), minsInput),
        el("div", { class: "qf" }, el("label", { text: t("gui_policy_dec") }), pdSel));
      dbgPanel.body.appendChild(dbgRow);
      dbgPanel.body.appendChild(note(t("v2_al_debug_note")));
      dbgPanel.body.appendChild(btn("btn primary", t("gui_run_debug"), function () {
        const body = {};
        body.mins = minsInput.value;
        body.pd_sel = pdSel.value;
        consoleBox.request("POST", "/api/actions/debug", body);
      }));
      row1.appendChild(dbgPanel);

      // ── AL-11 watermark (index.html:1318, actions.py:597-633) ──────────
      const wmPanel = panel("AL-11", t("gui_reset_watermark_label"));
      wmPanel.body.appendChild(note(t("gui_reset_watermark_confirm")));
      const wm = d.status && d.status.event_watermark;
      wmPanel.body.appendChild(el("ul", { class: "stack" },
        el("li", null, el("code", { class: "c", text: "event_watermark" }),
          el("span", { class: "s", text: showValue(wm) })),
        el("li", null, el("code", { class: "c", text: "alert_history" }),
          el("span", { class: "s", text: tf("v2_al_wm_cooldowns", { n: Object.keys((d.status && d.status.cooldowns) || {}).length }) })),
        el("li", null, el("code", { class: "c", text: "event_seen" }),
          el("span", { class: "s", text: t("v2_al_wm_seen") }))));
      handles.watermark = function () {
        return modal.confirm(confirmSpec(t("gui_reset_watermark_label"), [
          t("v2_al_wm_i1"), t("v2_al_wm_i2"), t("v2_al_wm_i3"), t("v2_al_wm_i4"),
        ], function () {
          consoleBox.request("POST", "/api/actions/reset-watermark", null);
          return true;
        }));
      };
      wmPanel.body.appendChild(btn("btn danger", t("gui_reset_watermark_label"), handles.watermark));
      row1.appendChild(wmPanel);

      // ── AL-10 test alert (index.html:1320-1327, actions.js:38-57) ──────
      const testPanel = panel("AL-10", t("gui_test_alert"));
      testPanel.body.appendChild(note(t("gui_test_alert_desc")));
      handles.testAll = function () { consoleBox.request("POST", "/api/actions/test-alert", null); };
      const btnRow = el("div", { class: "typechips" });
      btnRow.appendChild(btn("btn primary", t("gui_action_send_all"), handles.testAll));
      channels.forEach(function (ch) {
        const live = ch.enabled && ch.configured;
        const b = btn("btn", t("gui_action_test_prefix") + " " + (ch.display_name || ch.name), function () {
          const body = {};
          body.channel = ch.name;
          consoleBox.request("POST", "/api/actions/test-alert", body);
        });
        b.title = ch.description || "";
        if (!live) b.setAttribute("data-muted", "true");
        btnRow.appendChild(b);
      });
      testPanel.body.appendChild(btnRow);
      testPanel.body.appendChild(note(t("v2_al_test_alert_note")));
      row2.appendChild(testPanel);

      // ── AL-12 best practices (rules.js:584-608, config.py:845-896) ─────
      const bpPanel = panel("AL-12", t("gui_best_practices"));
      bpPanel.body.appendChild(note(t("gui_best_practices_desc")));
      const bpState = {};
      bpState.mode = "append_missing";
      const modes = [["append_missing", "v2_al_bp_append"], ["replace", "v2_al_bp_replace"]];
      bpPanel.body.appendChild(el("div", { class: "fld" },
        el("label", null, el("span", { text: t("v2_al_bp_mode") })),
        radioGroup("al-bp-mode", modes, bpState.mode, function (v) { bpState.mode = v; })));

      // The real added/skipped split for THIS config, computed with the
      // product's own signature (config.py:823-843) — not an estimate.
      const bpSigs = bpSignatures();
      const existing = {};
      rules.forEach(function (r) { existing[ruleSignature(r)] = true; });
      const added = bpSigs.filter(function (s) { return !existing[s]; }).length;
      const skipped = bpSigs.length - added;
      const bpSigSet = {};
      bpSigs.forEach(function (s) { bpSigSet[s] = true; });
      const lost = rules.filter(function (r) { return !bpSigSet[ruleSignature(r)]; });

      bpPanel.body.appendChild(el("ul", { class: "stack" },
        el("li", null, el("span", { class: "s", text: tf("v2_al_bp_stat_append", { added: added, skipped: skipped }) })),
        el("li", null, el("span", { class: "s", text: tf("v2_al_bp_stat_replace", { total: bpSigs.length, now: rules.length, lost: lost.length }) }))));

      handles.bestPractices = function () {
        const impact = [];
        if (bpState.mode === "replace") {
          impact.push(tf("v2_al_bp_i_replace", { total: bpSigs.length, now: rules.length }));
          lost.forEach(function (r) { impact.push(tf("v2_al_bp_i_lost", { type: r.type, name: r.name })); });
          impact.push(t("v2_al_bp_i_backup"));
        } else {
          impact.push(tf("v2_al_bp_i_append", { added: added, skipped: skipped }));
          impact.push(t("v2_al_bp_i_keep"));
          impact.push(t("v2_al_bp_i_backup"));
        }
        return modal.confirm(confirmSpec(t("gui_best_practices"), impact, function () {
          const body = {};
          body.mode = bpState.mode;
          consoleBox.request("POST", "/api/actions/best-practices", body);
          return true;
        }));
      };
      bpPanel.body.appendChild(btn("btn danger", t("gui_load"), handles.bestPractices));
      bpPanel.body.appendChild(note(t("v2_al_bp_note")));
      row2.appendChild(bpPanel);

      // ── AL-14 channel status, read-only (actions.js:10-33) ─────────────
      const chPanel = panel("AL-14", t("gui_alert_channels"));
      withMeta(chPanel, tf("v2_health_chan_live", {
        live: channels.filter(function (c) { return c.enabled && c.configured; }).length,
        total: channels.length,
      }));
      if (!channels.length) {
        chPanel.body.appendChild(el("div", { class: "empty" },
          el("span", { class: "et", text: t("gui_action_no_plugins") })));
      } else {
        const list = el("ul", { class: "stack" });
        channels.forEach(function (ch) {
          const li = el("li", { "data-tone": channelTone(ch) });
          li.appendChild(el("span", { class: "dot" }));
          const head = el("span", { class: "s" }, el("b", { text: ch.display_name || ch.name }), el("code", { text: ch.name }));
          li.appendChild(head);
          li.appendChild(el("span", { class: "c", text: ch.last_timestamp ? stamp(ch.last_timestamp) : "—" }));
          const detail = [channelDetail(ch, fieldLabels(d.alert_plugins, ch.name))];
          if (ch.last_target) detail.push("→ " + ch.last_target);
          li.appendChild(el("span", { class: "r", text: detail.join(" · ") }));
          list.appendChild(li);
        });
        chPanel.body.appendChild(list);
      }
      chPanel.body.appendChild(note(t("v2_al_ch_note")));
      row3.appendChild(chPanel);

      // ── AL-13 console ──────────────────────────────────────────────────
      const logPanel = panel("AL-13", t("gui_output"));
      logPanel.head.appendChild(spacer());
      logPanel.head.appendChild(btn("btn ghost", t("v2_al_console_clear"), function () { consoleBox.reset(); }));
      logPanel.body.appendChild(consoleBox.el);
      const fmt = el("details", { class: "guide" });
      fmt.appendChild(el("summary", { text: t("v2_al_fmt_title") }));
      const ul = el("ul");
      ["v2_al_fmt_run", "v2_al_fmt_debug", "v2_al_fmt_test", "v2_al_fmt_wm", "v2_al_fmt_bp", "v2_al_fmt_err"]
        .forEach(function (k) { ul.appendChild(el("li", { text: t(k) })); });
      fmt.appendChild(ul);
      logPanel.body.appendChild(fmt);
      row3.appendChild(logPanel);
    });
}

export { mountRules, mountOps };
