// reports.mjs — #/reports. Anchors RP-01…RP-09 + XC-07 (design/v2/coverage.yaml).
//
// The product's report page is a wall of eleven identical buttons
// (src/templates/index.html:1351-1495) over one shared generate modal
// (:2771-2868) whose sections are shown and hidden per type
// (dashboard.js:660-727). Two things are invisible there and are the reason
// this area is shaped the way it is:
//
//   1. WHEN a type last produced anything. loadRcardMeta (dashboard.js:223-298)
//      already computes it and prints it in 8px grey; here it is the card's
//      second line, in the mono readout face. A report shelf with dates tells
//      an operator which report is stale — a wall of buttons tells them nothing.
//   2. WHICH parameters a type actually takes. One shared modal means the form
//      is only knowable by opening it. Each card names its parameter sections
//      before you click, and the drawer prints the exact request body.
//
// FIELD CONTRACT (same rule as alerting.mjs): every key a type's _doGenerate*
// puts in its request body exists in that type's drawer as an element carrying
// data-field="<key>", and the payload pane is generated FROM those controls, so
// the two can never drift.
//
// HONESTY RULES (Task 7 report §9.9):
//   * Nothing here generates a report. "產生" runs the transcribed progress
//     sequence and stops at a step that says so; it never claims a file.
//   * The output list, delete and bulk delete mutate an in-memory copy of
//     reports_list.json only.
//   * RP-05's enablement card reads snapshots/rhc_enablement.json. The product
//     never calls that endpoint (it discovers the state reactively from a failed
//     generate, dashboard.js:1295-1306) — reading it up front is DESIGN-ADDED
//     and marked as such on the card.

import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { stamp } from "../core/fmt.mjs";
import { store } from "../core/store.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { progress } from "../components/progress.mjs";
import { areaHead } from "./placeholder.mjs";
import { createFilterBar, setFilterBarText, setFilterBarSnapshots } from "../components/filter-bar.mjs";
import { verifyPane } from "../components/verifypane.mjs";

const ROUTE = "#/reports";

const SNAPS = ["reports_list", "report_schedules", "rhc_enablement", "labels", "status", "fb_suggest", "fb_browse"];

// index.html:2844-2852 (select#m-gen-format) — always visible, even for the two
// types that ignore it (see FORMAT_NOTE below).
const FORMATS = [["html", "gui_fmt_html"], ["csv", "gui_fmt_csv"], ["xlsx", "gui_fmt_xlsx"], ["all", "gui_fmt_all"]];
// index.html:2853-2859 (select#m-gen-lang); syncReportLangToUi dashboard.js:646-654.
const LANGS = [["en", "gui_report_lang_en"], ["zh_TW", "gui_report_lang_zh_tw"]];
// index.html:2774-2780 (input[name=traffic-source]); toggleTrafficSource dashboard.js:744-756.
const SOURCES = [["api", "gui_gen_source_api"], ["csv", "gui_gen_source_csv"]];
// index.html:2835-2843 (select#m-gen-data-source); reports.py:64-78 maps it server-side.
const DATA_SOURCES = [["hybrid", "gui_rpt_ds_hybrid"], ["live", "gui_rpt_ds_live"], ["cache-only", "gui_rpt_ds_cache_only"]];
// index.html:2823-2825 — the three policy-decision checkboxes of the report filter block.
const PDS = [["blocked", "rpt_pd_blocked"], ["potentially_blocked", "rpt_pd_potential"], ["allowed", "rpt_pd_allowed"]];
// index.html:2807-2813 (data-action="setDateRange") — utils.js:228-238 sets end=today, start=today-n.
const QUICK_DAYS = [1, 7, 30, 60];

/* One report type. `sections` is the visibility set openReportGenModal
 * (dashboard.js:679-716) computes for that type:
 *   source  — API/CSV radio (and, when CSV, the file input)
 *   dates   — start/end + quick ranges
 *   filters — the pd checkboxes AND the FilterBar (_ensureRptFilterBar :790-795)
 *   app     — app/env selects (_populateAppLabelSelects :729-742)
 *   ds      — the data_source select, itself gated on _CACHE_AVAILABLE
 *   snapshot— no dates; the "reads current data" note instead (:716)
 * `dateFmt` is the real divergence between the generators: "iso" sends
 * <date>T00:00:00Z / T23:59:59Z, "raw" sends the bare YYYY-MM-DD string. */
class RType {
  constructor(id, titleKey, descKey, endpoint, sections) {
    this.id = id;
    this.titleKey = titleKey;
    this.descKey = descKey;
    this.endpoint = endpoint;
    this.sections = sections;
    this.genKey = "gui_gen_fallback_title";
    this.dateFmt = "raw";
    this.srcNote = null;
    this.async = false;
    this.formatNote = null;
  }
  has(s) { return this.sections.indexOf(s) >= 0; }
  meta(genKey, dateFmt, srcNote) {
    this.genKey = genKey;
    this.dateFmt = dateFmt;
    this.srcNote = srcNote;
    return this;
  }
  flags(isAsync, formatNote) {
    this.async = isAsync;
    this.formatNote = formatNote;
    return this;
  }
}

/* The eleven cards, in the product's own grid order (index.html:1352-1494).
 * `data-rtype` is the card attribute; note it is NOT the report-SCHEDULE type
 * vocabulary — a schedule calls #5 "ven_status" (index.html:1591-1603, see
 * automation.mjs REPORT_TYPES) while the card calls it "ven". Both are kept as
 * they are; normalising one into the other would invent an id neither API uses. */
const TRAFFIC_PROFILE = ["source", "dates", "filters", "ds"];

const RTYPES = [
  new RType("traffic", "gui_btn_traffic_report", "gui_rcard_traffic_desc", "/api/reports/generate", TRAFFIC_PROFILE)
    .meta("gui_gen_traffic_title", "iso", "v2_rp_src_traffic").flags(true, null),
  new RType("security_risk", "gui_rcard_security_title", "gui_rcard_security_desc", "/api/reports/generate", TRAFFIC_PROFILE)
    .meta("gui_gen_security_title", "iso", "v2_rp_src_traffic").flags(true, null),
  new RType("network_inventory", "gui_rcard_inventory_title", "gui_rcard_inventory_desc", "/api/reports/generate", TRAFFIC_PROFILE)
    .meta("gui_gen_inventory_title", "iso", "v2_rp_src_traffic").flags(true, null),
  new RType("audit", "gui_btn_audit_report", "gui_rcard_audit_desc", "/api/audit_report/generate", ["dates"])
    .meta("gui_gen_audit_title", "iso", "v2_rp_src_audit").flags(false, null),
  new RType("ven", "gui_btn_ven_report", "gui_rcard_ven_desc", "/api/ven_status_report/generate", ["snapshot"])
    .meta("gui_gen_ven_title", "raw", "v2_rp_src_ven").flags(false, null),
  new RType("policy_usage", "gui_btn_pu_report", "gui_rcard_pu_desc", "/api/policy_usage_report/generate", ["source", "dates"])
    .meta("gui_gen_pu_title", "raw", "v2_rp_src_pu").flags(false, null),
  new RType("rule_hit_count", "gui_btn_rhc_report", "gui_rcard_rhc_desc", "/api/rule_hit_count_report/generate", ["source", "dates"])
    .meta("gui_gen_rhc_title", "raw", "v2_rp_src_rhc").flags(false, null),
  new RType("readiness", "gui_rcard_readiness_title", "gui_rcard_readiness_desc", "/api/readiness_report/generate", ["dates", "ds"])
    .meta("gui_gen_readiness_title", "raw", "v2_rp_src_readiness").flags(false, null),
  new RType("policy_diff", "gui_rcard_policy_diff_title", "gui_rcard_policy_diff_desc", "/api/policy_diff_report/generate", ["snapshot"])
    .meta("gui_gen_policy_diff_title", "raw", "v2_rp_src_pd").flags(false, "v2_rp_fmt_pd"),
  new RType("policy_resolver", "gui_rcard_policy_resolver_title", "gui_rcard_policy_resolver_desc", "/api/policy_resolver_report/generate", ["snapshot"])
    .meta("gui_gen_policy_resolver_title", "raw", "v2_rp_src_pr").flags(false, "v2_rp_fmt_pr"),
  new RType("app_summary", "gui_rcard_app_title", "gui_rcard_app_desc", "/api/app_report/generate", ["dates", "app", "ds"])
    .meta("gui_gen_app_title", "raw", "v2_rp_src_app").flags(true, null),
];

// The card meta strip's schedule chip (dashboard.js:264-271).
const SCHED_CHIPS = [["daily", "gui_rcard_sched_daily"], ["weekly", "gui_rcard_sched_weekly"], ["month", "gui_rcard_sched_monthly"]];

// ── shared chrome (same vocabulary as the other areas) ──────────────────────
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

function note(text) { return el("p", { class: "note", text: text }); }
function btn(cls, text, onClick) { return el("button", { class: cls, type: "button", text: text, onClick: onClick }); }
function sectionHead(text) { return el("h4", { class: "eyebrow", text: text }); }

/** A body key the form does not let you edit, with the reason. Same device as
 *  alerting.mjs: a key that reaches the backend is never invisible here. */
function roField(key, value, noteText) {
  const li = el("li");
  li.appendChild(el("code", { class: "c", text: key }));
  const v = el("span", { class: "s", text: value === null || value === undefined || value === "" ? "\u2014" : String(value) });
  v.dataset.field = key;
  li.appendChild(v);
  li.appendChild(el("span", { class: "r", text: noteText }));
  return li;
}

function roList(rows) { return el("ul", { class: "stack rofields" }, rows); }

function labelled(labelText, control, hint) {
  const box = el("div", { class: "fld" });
  const lab = el("label", null, el("span", { text: labelText }));
  box.appendChild(lab);
  box.appendChild(control);
  if (hint) box.appendChild(el("small", { class: "hint", text: hint }));
  box.lab = lab;
  return box;
}

/** An editable field whose control carries the request-body key it feeds. */
function editField(key, labelText, control, hint) {
  control.dataset.field = key;
  const box = labelled(labelText, control, hint || null);
  box.lab.appendChild(el("code", { text: key }));
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

function dateField(value, onChange) {
  const input = el("input", { class: "field", type: "date", value: value || "" });
  if (onChange) input.addEventListener("change", function () { onChange(input.value); });
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

function tableSpec(columns, rows, page, onPage) {
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

function rtypeOf(id) {
  let hit = null;
  RTYPES.forEach(function (rt) { if (rt.id === id) hit = rt; });
  return hit;
}

// ── report_type derivation ──────────────────────────────────────────────────
/* dashboard.js:239-255, prefix rule for prefix rule. The traffic-family sidecar
 * always writes report_type "traffic" (report_generator.py hardcodes it), so
 * the three traffic profiles are only separable by filename — and the specific
 * SecurityRisk / NetworkInventory prefixes must be tested BEFORE the bare dated
 * traffic pattern, because "Illumio_Traffic_Report_" is a strict prefix of both.
 * 36 of this snapshot's 69 files have no sidecar at all; this prefix rule
 * recovers 25 of those, so only 11 stay genuinely untyped. */
function derivedType(rp) {
  const name = String(rp.filename || "");
  let ty = rp.report_type || "";
  if (name.indexOf("Illumio_Traffic_Report_SecurityRisk_") === 0) ty = "security_risk";
  else if (name.indexOf("Illumio_Traffic_Report_NetworkInventory_") === 0) ty = "network_inventory";
  else if (/^Illumio_Traffic_Report_\d{4}-/.test(name)) ty = "traffic";
  if (!ty && name.indexOf("Illumio_Policy_Diff_Report_") === 0) ty = "policy_diff";
  if (!ty && name.indexOf("Illumio_Policy_Resolver_") === 0) ty = "policy_resolver";
  if (!ty && name.indexOf("Illumio_App_Summary_") === 0) ty = "app_summary";
  return ty;
}

/** dashboard.js:264-271 — the schedule chip, matched on interval/frequency. */
function schedChip(s) {
  if (!s || !s.enabled) return t("gui_rcard_sched_manual");
  const iv = String(s.interval || s.frequency || "").toLowerCase();
  let hit = null;
  SCHED_CHIPS.forEach(function (pair) { if (!hit && iv.indexOf(pair[0]) >= 0) hit = pair[1]; });
  return t(hit || "gui_rcard_sched_scheduled");
}

/** dashboard.js:282 — the card's "last produced" stamp, mtime is epoch seconds. */
function lastStamp(mtime) {
  if (!mtime) return "—";
  return stamp(new Date(mtime * 1000).toISOString()).slice(0, 16);
}

function sizeText(bytes) {
  return (Number(bytes || 0) / 1024).toFixed(1) + " KB";
}

/* dashboard.js:718-724 — start defaults to today-7, end to today, and both are
 * only written when the input is EMPTY, which is why the modal keeps whatever
 * the previous type left behind. The mockup has one drawer per open, so the
 * default is applied every time; the note on the field says what the product does. */
function isoDay(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() - (offsetDays || 0));
  return d.toISOString().slice(0, 10);
}

// ══════════════════════════════════════════════ RP-02 the generate drawer ════

/* Every _doGenerate* body key, per type, with its source line:
 *   traffic profiles CSV  dashboard.js:922-928   source/format/traffic_report_profile/lang/file
 *   traffic profiles API  dashboard.js:962-967   source/format/start_date/end_date/
 *                                                traffic_report_profile/lang/data_source/filters
 *   audit                 dashboard.js:993-999   start_date/end_date/format/lang
 *   ven                   dashboard.js:1022-1026 format/lang
 *   policy_usage CSV      dashboard.js:1216-1219 source/format/lang/file
 *   policy_usage API      dashboard.js:1224      source/start_date/end_date/format/lang
 *   rule_hit_count CSV    dashboard.js:1277-1280 source/format/lang/file
 *   rule_hit_count native dashboard.js:1285-1286 source/start_date/end_date/format/lang
 *   readiness             dashboard.js:1051-1058 format/lang/start_date/end_date/[data_source]
 *   policy_diff           dashboard.js:1084-1088 format(html|csv only)/lang
 *   policy_resolver       dashboard.js:1109      format:'all' hardcoded/lang
 *   app_summary           dashboard.js:1134-1151 app/env/lang/start_date/end_date/data_source
 * The pane below is built FROM the controls, so a control that is missing shows
 * up as a missing key rather than as a silently correct-looking payload. */
function genDrawer(rt, d, lang) {
  const body = el("div", { "data-cov": "RP-02" });
  const state = {};
  state.source = "api";
  state.pds = [];

  const fmtSel = selectField(FORMATS, "html");
  const langSel = selectField(LANGS, lang);
  const startInput = dateField(isoDay(7));
  const endInput = dateField(isoDay(0));
  const dsSel = selectField(DATA_SOURCES, "hybrid");
  const fileInput = el("input", { class: "field", type: "file", accept: ".csv" });
  const appSel = el("select", { class: "field" });
  const envSel = el("select", { class: "field" });
  const payload = el("pre", { class: "codepane tall" });

  const srcBox = editField("source", t("gui_gen_data_source"),
    radioGroup("rp-src-" + rt.id, SOURCES, state.source, function (v) { state.source = v; onSource(); repaint(); }));
  const fileBox = editField("file", t("gui_gen_select_csv_file"), fileInput, t("v2_rp_file_hint"));
  const dateRow = el("div", { class: "qrow" },
    el("div", { class: "qf" }, el("label", { text: t("gui_gen_start_date") }), startInput),
    el("div", { class: "qf" }, el("label", { text: t("gui_gen_end_date") }), endInput));
  const quickRow = el("div", { class: "typechips" });
  QUICK_DAYS.forEach(function (n) {
    quickRow.appendChild(btn("btn ghost", tf("v2_rp_quick_days", { n: n }), function () {
      startInput.value = isoDay(n);
      endInput.value = isoDay(0);
      repaint();
    }));
  });
  const dateBox = el("div", null,
    sectionHead(t("gui_quick_range")), quickRow, dateRow,
    note(t(rt.dateFmt === "iso" ? "v2_rp_date_iso" : "v2_rp_date_raw")),
    note(t("v2_rp_date_sticky")));
  startInput.dataset.field = "start_date";
  endInput.dataset.field = "end_date";

  // RP-09's other half: the two selects the product fills from /api/labels.
  // The captured snapshot is one unkeyed list (endpoints.yaml:56 calls
  // /api/labels with no key), so BOTH selects are fed from it and the drawer
  // says so rather than pretending it captured key=app and key=env separately.
  const labels = (d.labels && d.labels.labels) || [];
  labels.forEach(function (v) { appSel.appendChild(el("option", { value: v, text: v })); });
  envSel.appendChild(el("option", { value: "", text: t("gui_env_any") }));
  labels.forEach(function (v) { envSel.appendChild(el("option", { value: v, text: v })); });
  appSel.addEventListener("change", repaint);
  envSel.addEventListener("change", repaint);
  const appBox = el("div", null,
    editField("app", t("gui_app_label_field"), appSel, t("v2_rp_app_required")),
    editField("env", t("gui_env_label_field"), envSel),
    note(t("v2_rp_labels_src")));

  // RP-02's filter block: three pd checkboxes + the shared FilterBar.
  const pdRow = el("div", { class: "typechips" });
  PDS.forEach(function (pair) {
    const box = el("input", { type: "checkbox", value: pair[0] });
    box.addEventListener("change", function () {
      const at = state.pds.indexOf(pair[0]);
      if (box.checked && at < 0) state.pds.push(pair[0]);
      if (!box.checked && at >= 0) state.pds.splice(at, 1);
      repaint();
    });
    pdRow.appendChild(el("label", { class: "chk" }, box, el("span", { text: t(pair[1]) })));
  });
  const barHost = el("div");
  const filterBox = el("div", null,
    sectionHead(t("rpt_filter_toggle")),
    labelled(t("rpt_filter_pd"), pdRow),
    el("div", { class: "fld" }, el("label", null, el("span", { text: t("rpt_filter_objects") }), el("code", { text: "filters" })), barHost));
  pdRow.dataset.field = "policy_decisions";
  barHost.dataset.field = "filters";

  let bar = null;
  if (rt.has("filters")) {
    setFilterBarText(t);
    setFilterBarSnapshots(d.fb_suggest, d.fb_browse);
    bar = createFilterBar(barHost, {});
    bar.onChange(repaint);
  }

  const dsBox = editField("data_source", t("gui_rpt_data_source"), dsSel, t("gui_rpt_ds_hint"));

  function onSource() {
    const csv = state.source === "csv";
    fileBox.hidden = !csv;
    dateBox.hidden = csv || !rt.has("dates");
    // toggleTrafficSource dashboard.js:744-756 — the data-source row only ever
    // shows for API mode, and only for the types that support the cache.
    dsBox.hidden = csv || !rt.has("ds");
  }

  /* _collectReportFilters dashboard.js:797-815 — returns null when neither the
   * pd boxes nor the FilterBar have anything, so `filters` is then omitted from
   * the body entirely (dashboard.js:967 sends it only when non-null). */
  function collectFilters() {
    const objFilters = bar ? bar.getFilters() : {};
    const pds = state.pds.length ? state.pds.slice() : null;
    if (!pds && !Object.keys(objFilters).length) return null;
    const out = {};
    out.policy_decisions = pds;
    Object.keys(objFilters).forEach(function (k) { out[k] = objFilters[k]; });
    return out;
  }

  function dateValue(input, endOfDay) {
    const raw = input.value || "";
    if (rt.dateFmt !== "iso" || !raw) return raw;
    return new Date(raw + (endOfDay ? "T23:59:59Z" : "T00:00:00Z")).toISOString();
  }

  function repaint() {
    const csv = state.source === "csv";
    const b = {};
    if (rt.has("source")) b.source = csv ? "csv" : (rt.id === "rule_hit_count" ? "native" : "api");
    // policy_resolver ignores the select and hardcodes 'all' (dashboard.js:1109);
    // policy_diff coerces anything that is not csv to html (dashboard.js:1084).
    if (rt.id === "policy_resolver") b.format = "all";
    else if (rt.id === "policy_diff") b.format = fmtSel.value === "csv" ? "csv" : "html";
    else b.format = fmtSel.value;
    if (rt.id === "app_summary") {
      b.app = appSel.value;
      b.env = envSel.value;
    }
    if (rt.has("filters")) b.traffic_report_profile = rt.id;
    if (!csv && rt.has("dates")) {
      b.start_date = dateValue(startInput, false);
      b.end_date = dateValue(endInput, true);
    }
    b.lang = langSel.value;
    if (!csv && rt.has("ds")) b.data_source = dsSel.value;
    if (csv) b.file = t("v2_rp_file_placeholder");
    if (rt.has("filters") && !csv) {
      const f = collectFilters();
      if (f) b.filters = f;
    }
    const verb = csv ? "POST (multipart/form-data) " : "POST ";
    payload.textContent = verb + rt.endpoint + "\n" + JSON.stringify(b, null, 2);
    return b;
  }

  fmtSel.addEventListener("change", repaint);
  langSel.addEventListener("change", repaint);
  startInput.addEventListener("change", repaint);
  endInput.addEventListener("change", repaint);
  dsSel.addEventListener("change", repaint);
  fileInput.addEventListener("change", repaint);

  body.appendChild(note(t(rt.descKey)));
  body.appendChild(note(t(rt.srcNote)));
  body.appendChild(sectionHead(t("v2_rp_form_section")));
  if (rt.has("source")) {
    body.appendChild(srcBox);
    body.appendChild(fileBox);
    if (rt.id === "rule_hit_count") body.appendChild(note(t("v2_rp_rhc_native")));
  }
  if (rt.has("snapshot")) body.appendChild(note(t("gui_gen_snapshot_note")));
  if (rt.has("dates")) body.appendChild(dateBox);
  if (rt.has("app")) body.appendChild(appBox);
  if (rt.has("filters")) body.appendChild(filterBox);
  if (rt.has("ds")) {
    body.appendChild(dsBox);
    body.appendChild(note(t("v2_rp_ds_gate")));
  }
  body.appendChild(sectionHead(t("v2_rp_out_section")));
  body.appendChild(editField("format", t("gui_sched_format"), fmtSel, rt.formatNote ? t(rt.formatNote) : null));
  body.appendChild(editField("lang", t("gui_report_lang_label"), langSel, t("v2_rp_lang_field_hint")));
  // Body keys the form does not expose as controls. traffic_report_profile is
  // the card's own identity (dashboard.js:962-967 reads it from the button that
  // opened the modal, never from an input) — it still reaches the backend, so it
  // is stated rather than left to be discovered in the payload pane.
  if (rt.has("filters")) {
    body.appendChild(sectionHead(t("v2_rp_ro_section")));
    body.appendChild(roList([roField("traffic_report_profile", rt.id, t("v2_rp_fn_profile"))]));
  }
  body.appendChild(sectionHead(t("v2_rp_payload")));
  body.appendChild(verifyPane(payload));
  body.appendChild(note(t("v2_rp_mock_gen")));

  onSource();
  repaint();
  return drawerSpec(t(rt.genKey), body, function () {
    runProgress(rt, state.source);
    return true;
  });
}

// ══════════════════════════ RP-03 / XC-07 the unified progress component ═════

/* _showGenProgress / _updateGenStep (dashboard.js:529-558) is ONE status line,
 * not a stepper — the product overwrites the same <div> five times. The v2
 * component keeps every step visible so the operator can see where a long run
 * is, and can collapse the card and keep working (progress.mjs).
 *
 * The sequence below is the real one, per path:
 *   CSV            gui_gen_step_parsing -> gui_gen_step_running_bg (dashboard.js:920, 930)
 *   API sync       gui_gen_step_fetching -> gui_gen_done            (:955, :1029 …)
 *   API + audit    adds gui_gen_step_analysing after 3000 ms        (:998, cleared :1000)
 *   API async job  gui_gen_step_fetching -> gui_gen_step_running_bg (_pollReportJob :870)
 * The final step is this mockup's own: the run stops there because there is no
 * backend to finish it, and saying so is the whole point. */
let liveProgress = null;

function stepsFor(rt, source) {
  const steps = [];
  if (source === "csv") steps.push(t("gui_gen_step_parsing"));
  else steps.push(t("gui_gen_step_fetching"));
  if (rt.id === "audit") steps.push(t("gui_gen_step_analysing"));
  if (rt.async || source === "csv") steps.push(t("gui_gen_step_running_bg"));
  steps.push(t("v2_rp_step_mock"));
  return steps;
}

function runProgress(rt, source) {
  if (liveProgress) liveProgress.close();
  const steps = stepsFor(rt, source);
  const p = progress.start(t(rt.genKey), steps);
  p.el.dataset.cov = "XC-07";
  liveProgress = p;
  let at = 0;
  function tick() {
    if (liveProgress !== p) return;
    at += 1;
    p.step(at);
    if (at < steps.length - 1) window.setTimeout(tick, 700);
  }
  window.setTimeout(tick, 350);
  return p;
}

function stopProgress() {
  if (!liveProgress) return;
  liveProgress.close();
  liveProgress = null;
}

// The progress card is docked to <body>, not to the area root, so leaving the
// route would strand it over another page. Registered once at module load —
// a per-mount listener would leak one subscription per visit.
router.onChange(function (path) { if (path !== ROUTE) stopProgress(); });

// ══════════════════════════════════════════════════════════ mount ════════════

async function mountReports(root, ctx) {
  const handles = {};
  // Registered synchronously, before the first await (Task 7 report §9.6).
  drawer.registerAudit("rp-gen", function () { return handles.open ? handles.open("traffic") : null; });
  // Seeds a selection first: the bulk bar and its confirm only exist when rows
  // are picked, so an opener that skipped the selection would show the gate an
  // empty dialog that no operator could ever reach.
  modal.registerAudit("rp-bulk-delete", function () { return handles.auditBulk ? handles.auditBulk() : null; });
  modal.registerAudit("rp-rhc-enable", function () { return handles.enableRhc ? handles.enableRhc() : null; });
  audit.register("rp-progress", function () {
    if (liveProgress) return;
    runProgress(RTYPES[0], "api");
  });
  palette.registerFor(ROUTE, cmdSpec("rp:gen-traffic", t("gui_gen_traffic_title"), function () { if (handles.open) handles.open("traffic"); }));
  palette.registerFor(ROUTE, cmdSpec("rp:gen-audit", t("gui_gen_audit_title"), function () { if (handles.open) handles.open("audit"); }));
  palette.registerFor(ROUTE, cmdSpec("rp:outputs", t("gui_report_output"), function () { if (handles.focusOutputs) handles.focusOutputs(); }));

  root.appendChild(areaHead(t("v2_nav_reports"), ROUTE));
  const wrap = el("div", { class: "wb" });
  const main = el("div", { class: "wb-main" });
  const aside = el("aside", { class: "wb-aside" });
  wrap.appendChild(main);
  wrap.appendChild(aside);
  root.appendChild(wrap);

  await withErrorCard(main, "reports (" + SNAPS.length + ")",
    function () { return loadAll(SNAPS); },
    function (d) {
      if (ctx.stale()) return;

      const state = {};
      state.reports = ((d.reports_list && d.reports_list.reports) || []).map(function (r) {
        const c = {};
        Object.keys(r).forEach(function (k) { c[k] = r[k]; });
        c._type = derivedType(r);
        return c;
      });
      state.reports.sort(function (a, b) { return b.mtime - a.mtime; });
      state.search = "";
      state.selected = [];
      state.page = 0;
      // syncReportLangToUi dashboard.js:646-654 — the report language starts as
      // the UI language, and anything that is not zh_TW becomes en.
      state.lang = (d.status && d.status.language) === "zh_TW" ? "zh_TW" : "en";

      const schedules = (d.report_schedules && d.report_schedules.schedules) || [];
      const schedByType = {};
      schedules.forEach(function (s) {
        const ty = s.report_type || "";
        if (ty && !schedByType[ty]) schedByType[ty] = s;
      });
      const latestByType = {};
      const countByType = {};
      state.reports.forEach(function (r) {
        if (!r._type) return;
        countByType[r._type] = (countByType[r._type] || 0) + 1;
        if (!latestByType[r._type] || r.mtime > latestByType[r._type]) latestByType[r._type] = r.mtime;
      });

      handles.open = function (id) {
        const rt = rtypeOf(id) || RTYPES[0];
        const h = drawer.open(genDrawer(rt, d, state.lang));
        // The action keeps its name across the flow: the card says 產生, so the
        // drawer's primary must too. drawer.mjs labels it gui_save by default
        // because every other caller is an edit form.
        const go = h.el.querySelector(".drawer-f .btn.primary");
        if (go) go.textContent = t("gui_gen_generate");
        // The three traffic profiles carry the FilterBar, whose three zones do
        // not fit the default drawer width (investigate.mjs:982 does the same).
        if (rt.has("filters")) h.el.classList.add("wide");
        return h;
      };

      // ── RP-01 the catalogue ────────────────────────────────────────────
      const catPanel = panel("RP-01", t("v2_rp_catalogue"));
      withMeta(catPanel, tf("v2_rp_cat_meta", { types: RTYPES.length, files: state.reports.length }));
      const grid = el("div", { class: "rpgrid" });
      RTYPES.forEach(function (rt) {
        const card = el("article", { class: "rpcard", "data-rtype": rt.id });
        card.appendChild(el("div", { class: "rpcard-h" },
          el("code", { text: rt.id }),
          el("span", { class: "rpcard-sched", text: schedChip(schedByType[rt.id]) })));
        card.appendChild(el("b", { text: t(rt.titleKey) }));
        card.appendChild(el("p", { text: t(rt.descKey) }));
        const secs = el("div", { class: "chips" });
        rt.sections.forEach(function (s) { secs.appendChild(el("span", null, el("b", { text: t("v2_rp_sec_" + s) }))); });
        card.appendChild(secs);
        const last = el("div", { class: "rpcard-last" },
          el("span", { class: "k", text: t("v2_rp_last") }),
          el("span", { class: "v mono", text: lastStamp(latestByType[rt.id]) }),
          el("span", { class: "n mono", text: tf("v2_rp_files_n", { n: countByType[rt.id] || 0 }) }));
        card.appendChild(last);
        card.appendChild(btn("btn primary", t("gui_gen_generate"), function () { handles.open(rt.id); }));
        grid.appendChild(card);
      });
      catPanel.body.appendChild(grid);
      catPanel.body.appendChild(note(t("v2_rp_cat_note")));
      // The note must not hardcode these three numbers: rawEmpty (no sidecar at
      // all) splits into recovered (saved by the filename-prefix rule above) and
      // stillUntyped (genuinely unlabeled) — recomputed from the live snapshot so
      // a future fixture swap can't silently drift the copy out of sync again.
      const rawEmpty = state.reports.filter(function (r) { return !(r.report_type || ""); });
      const recovered = rawEmpty.filter(function (r) { return !!r._type; });
      const stillUntyped = state.reports.filter(function (r) { return !r._type; });
      catPanel.body.appendChild(note(tf("v2_rp_untyped_note", {
        total: state.reports.length,
        rawEmpty: rawEmpty.length,
        recovered: recovered.length,
        stillUntyped: stillUntyped.length
      })));
      main.appendChild(catPanel);

      // ── RP-06 / RP-07 the output list ──────────────────────────────────
      const outPanel = panel("RP-06", t("gui_report_output"));
      const outMeta = el("span", { class: "meta" });
      outPanel.head.appendChild(outMeta);
      const outHost = el("div");
      const floatHost = el("div", { "data-cov": "RP-07" });
      const search = el("input", { class: "field", placeholder: t("gui_col_filename") });
      search.addEventListener("input", function () {
        state.search = search.value.toLowerCase().trim();
        state.page = 0;
        paintOut();
      });
      outPanel.body.appendChild(el("div", { class: "qrow" },
        el("div", { class: "qf grow" }, el("label", { text: t("gui_search") }), search)));
      outPanel.body.appendChild(outHost);
      outPanel.body.appendChild(note(t("v2_rp_out_note")));
      main.appendChild(outPanel);
      main.appendChild(floatHost);
      handles.focusOutputs = function () { search.focus(); };

      function visibleReports() {
        if (!state.search) return state.reports;
        return state.reports.filter(function (r) {
          return String(r.filename).toLowerCase().indexOf(state.search) >= 0
            || String(r._type).toLowerCase().indexOf(state.search) >= 0;
        });
      }

      function isSelected(r) { return state.selected.indexOf(r.filename) >= 0; }
      function toggleSel(r, on) {
        const at = state.selected.indexOf(r.filename);
        if (on && at < 0) state.selected.push(r.filename);
        if (!on && at >= 0) state.selected.splice(at, 1);
        paintFloat();
      }

      /* dashboard.js:209-220 — one DELETE per file, then a reload. There is no
       * request to make here, so the row leaves the in-memory copy and the toast
       * names what the product would have sent. */
      function deleteOne(r) {
        return modal.confirm(confirmSpec(tf("gui_delete_confirm", { filename: r.filename }),
          [tf("v2_rp_del_one", { filename: r.filename }), t("v2_rp_del_norecover")],
          function () {
            state.reports = state.reports.filter(function (x) { return x.filename !== r.filename; });
            toggleSel(r, false);
            toast.ok(tf("gui_deleted_ok", { filename: r.filename }));
            paintOut();
            return true;
          }));
      }

      /* dashboard.js:159-181 — one POST /api/reports/bulk-delete carrying every
       * filename; the response splits into `deleted` and `errors`, and a partial
       * failure is reported as a second, warning toast (:174-176). */
      handles.bulkDelete = function () {
        const names = state.selected.slice();
        const impact = [tf("gui_delete_selected_confirm", { count: names.length })].concat(names.slice(0, 6));
        if (names.length > 6) impact.push(tf("v2_rp_del_more", { n: names.length - 6 }));
        impact.push(t("v2_rp_del_bulk_partial"));
        impact.push(t("v2_rp_del_norecover"));
        return modal.confirm(confirmSpec(t("gui_delete_selected"), impact, function () {
          state.reports = state.reports.filter(function (x) { return names.indexOf(x.filename) < 0; });
          state.selected = [];
          toast.ok(tf("gui_deleted_count", { count: names.length }));
          paintFloat();
          paintOut();
          return true;
        }));
      };

      function paintFloat() {
        clear(floatHost);
        if (!state.selected.length) return;
        floatHost.appendChild(el("div", { class: "floatbar", "data-tone": "crit" },
          el("span", { text: t("gui_selected") + " " }),
          el("b", { text: String(state.selected.length) }),
          btn("btn danger", t("gui_delete_selected"), function () { handles.bulkDelete(); }),
          btn("btn ghost", t("v2_rp_sel_clear"), function () { state.selected = []; paintFloat(); paintOut(); })));
      }

      function typeCell(r) {
        if (!r._type) return el("span", { class: "chips" }, el("span", { class: "off", text: t("v2_rp_untyped") }));
        const rt = rtypeOf(r._type);
        return el("span", { class: "chips" }, el("span", null, el("b", { text: rt ? t(rt.titleKey) : r._type })));
      }

      function paintOut() {
        const rows = visibleReports();
        const size = 15;
        const pages = Math.max(1, Math.ceil(rows.length / size));
        if (state.page >= pages) state.page = pages - 1;
        const slice = rows.slice(state.page * size, state.page * size + size);
        outMeta.textContent = tf("v2_rp_out_meta", { shown: rows.length, total: state.reports.length });

        const columns = [
          col("pick", "", pickCell(function () {
            const box = el("input", { type: "checkbox" });
            box.checked = slice.length > 0 && slice.every(isSelected);
            box.addEventListener("change", function () {
              slice.forEach(function (r) { toggleSel(r, box.checked); });
              paintOut();
            });
            return box;
          }, function (r) {
            const box = el("input", { type: "checkbox" });
            box.checked = isSelected(r);
            box.addEventListener("change", function () { toggleSel(r, box.checked); });
            return box;
          })),
          col("filename", t("gui_col_filename"), buildCell(function (r) {
            return el("span", { class: "idc", title: r.filename },
              el("b", { text: r.filename }),
              el("small", { text: r.summary || t("v2_rp_no_summary") }));
          })),
          col("type", t("gui_col_type"), widthCell(170, typeCell)),
          col("mtime", t("gui_col_date_created"), widthCell(150, function (r) {
            return el("code", { class: "mono", text: lastStamp(r.mtime) });
          })),
          col("size", t("gui_col_size"), widthCell(90, function (r) { return sizeText(r.size); })),
          col("act", t("gui_actions"), widthCell(190, function (r) {
            const box = el("div", { class: "rowacts" });
            const isHtml = /\.html?$/i.test(String(r.filename));
            if (isHtml) box.appendChild(btn("btn ghost", t("gui_btn_view"), function () { toast.info(tf("v2_rp_view_note", { filename: r.filename })); }));
            box.appendChild(btn("btn ghost", t("gui_btn_download"), function () { toast.info(tf("v2_rp_dl_note", { filename: r.filename })); }));
            box.appendChild(btn("btn danger", t("gui_btn_delete"), function () { deleteOne(r); }));
            return box;
          })),
        ];

        table.render(outHost, tableSpec(columns, slice, pageSpec(state.page, size, rows.length), function (next) {
          state.page = Math.max(0, Math.min(next, pages - 1));
          paintOut();
        }));
      }

      handles.auditBulk = function () {
        if (!state.selected.length) {
          state.reports.slice(0, 2).forEach(function (r) { toggleSel(r, true); });
          paintOut();
        }
        return handles.bulkDelete();
      };

      paintOut();
      paintFloat();

      // ── RP-05 RHC enablement ───────────────────────────────────────────
      const rhc = d.rhc_enablement || {};
      const rhcOn = rhc.state === "enabled";
      const rhcPanel = panel("RP-05", t("gui_btn_rhc_report"));
      rhcPanel.dataset.tone = rhcOn ? "ok" : "warn";
      withMeta(rhcPanel, String(rhc.state || "—"));
      rhcPanel.body.appendChild(el("ul", { class: "stack" },
        el("li", { "data-tone": rhcOn ? "ok" : "warn" },
          el("span", { class: "dot" }),
          el("span", { class: "s", text: t("v2_rp_rhc_state") }),
          el("span", { class: "c", text: String(rhc.state || "—") })),
        el("li", { "data-tone": rhc.pce_report_enabled ? "ok" : "warn" },
          el("span", { class: "dot" }),
          el("span", { class: "s", text: t("v2_rp_rhc_pce") }),
          el("span", { class: "c", text: String(!!rhc.pce_report_enabled) })),
        el("li", { "data-tone": rhc.ven_scopes_enabled ? "ok" : "warn" },
          el("span", { class: "dot" }),
          el("span", { class: "s", text: t("v2_rp_rhc_ven") }),
          el("span", { class: "c", text: String(!!rhc.ven_scopes_enabled) }))));
      rhcPanel.body.appendChild(note(String(rhc.detail || "")));
      /* dashboard.js:1295-1306 — the confirm is a window.confirm carrying the
       * whole warning; here the same sentence becomes the modal's impact list so
       * "writes draft firewall_settings" and "provisions to production policy"
       * are two separate consequences instead of one paragraph. */
      handles.enableRhc = function () {
        return modal.confirm(confirmSpec(t("gui_btn_rhc_report"), [
          tf("gui_rhc_needs_enable_confirm", { state: rhc.state || "" }),
          t("v2_rp_rhc_i_draft"),
          t("v2_rp_rhc_i_all"),
          t("v2_rp_rhc_i_cli"),
        ], function () {
          toast.info(t("v2_rp_rhc_mock"));
          return true;
        }));
      };
      rhcPanel.body.appendChild(btn(rhcOn ? "btn ghost" : "btn danger", t("v2_rp_rhc_enable"), handles.enableRhc));
      if (rhcOn) rhcPanel.body.appendChild(note(t("gui_rhc_enabled_ok")));
      else rhcPanel.body.appendChild(note(t("gui_rhc_use_pu_hint")));
      rhcPanel.body.appendChild(note(t("v2_rp_rhc_reactive")));
      aside.appendChild(rhcPanel);

      // ── RP-08 report language ──────────────────────────────────────────
      const langPanel = panel("RP-08", t("gui_report_lang_label"));
      const uiLang = (d.status && d.status.language) || "—";
      langPanel.body.appendChild(el("div", { class: "kv" },
        el("span", { text: t("v2_rp_lang_ui") }), el("b", { class: "mono", text: uiLang })));
      const langSel = selectField(LANGS, state.lang, function (v) {
        state.lang = v;
        toast.info(tf("v2_rp_lang_set", { lang: v }));
      });
      langSel.dataset.field = "lang";
      langPanel.body.appendChild(labelled(t("gui_report_lang_label"), langSel));
      langPanel.body.appendChild(note(t("v2_rp_lang_note")));
      aside.appendChild(langPanel);

      // ── RP-09 label lookup ─────────────────────────────────────────────
      const labels = (d.labels && d.labels.labels) || [];
      const labelPanel = panel("RP-09", t("gui_app_label_field"));
      withMeta(labelPanel, tf("v2_rp_labels_n", { n: labels.length }));
      const labelSearch = el("input", { class: "field", placeholder: t("gui_search") });
      const labelChips = el("div", { class: "chips" });
      function paintLabels() {
        clear(labelChips);
        const q = labelSearch.value.toLowerCase().trim();
        const hits = labels.filter(function (v) { return !q || String(v).toLowerCase().indexOf(q) >= 0; });
        if (!hits.length) {
          labelChips.appendChild(el("span", { class: "off", text: t("gui_empty_state_no_data_title") }));
          return;
        }
        hits.forEach(function (v) {
          const chip = btn("btn ghost", v, function () {
            handles.open("app_summary");
            toast.info(tf("v2_rp_label_pick", { label: v }));
          });
          labelChips.appendChild(chip);
        });
      }
      labelSearch.addEventListener("input", paintLabels);
      labelPanel.body.appendChild(labelSearch);
      labelPanel.body.appendChild(labelChips);
      labelPanel.body.appendChild(note(t("v2_rp_labels_note")));
      aside.appendChild(labelPanel);

      // ── RP-03 progress + async polling ─────────────────────────────────
      const progPanel = panel("RP-03", t("v2_rp_progress_title"));
      progPanel.body.appendChild(note(t("v2_rp_progress_body")));
      const stepList = el("ol", { class: "steplist" });
      [["v2_rp_path_api", "gui_gen_step_fetching"], ["v2_rp_path_csv", "gui_gen_step_parsing"],
        ["v2_rp_path_audit", "gui_gen_step_analysing"], ["v2_rp_path_async", "gui_gen_step_running_bg"],
        ["v2_rp_path_done", "gui_gen_done"]].forEach(function (pair) {
          stepList.appendChild(el("li", null,
            el("span", { class: "s", text: t(pair[1]) }),
            el("span", { class: "r", text: t(pair[0]) })));
        });
      progPanel.body.appendChild(stepList);
      progPanel.body.appendChild(el("div", { class: "typechips" },
        btn("btn", t("v2_rp_demo_run"), function () { runProgress(RTYPES[0], "api"); }),
        btn("btn ghost", t("v2_rp_demo_stop"), stopProgress)));
      progPanel.body.appendChild(note(tf("v2_rp_poll_note", { interval: 2, deadline: 30 })));
      progPanel.body.appendChild(note(t("v2_rp_async_types")));
      aside.appendChild(progPanel);

      // ── RP-04 partial results ──────────────────────────────────────────
      const partPanel = panel("RP-04", t("v2_rp_partial_title"));
      partPanel.dataset.tone = "warn";
      partPanel.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
        el("span", { text: tf("gui_toast_report_partial", { formats: "csv, xlsx" }) })));
      partPanel.body.appendChild(note(t("v2_rp_partial_body")));
      partPanel.body.appendChild(el("ul", { class: "stack" },
        el("li", null, el("code", { class: "c", text: "partial" }), el("span", { class: "s", text: t("v2_rp_partial_k1") })),
        el("li", null, el("code", { class: "c", text: "failed_formats" }), el("span", { class: "s", text: t("v2_rp_partial_k2") })),
        el("li", null, el("code", { class: "c", text: "files" }), el("span", { class: "s", text: t("v2_rp_partial_k3") }))));
      partPanel.body.appendChild(note(t("v2_rp_partial_where")));
      aside.appendChild(partPanel);
    });
}

export { mountReports };
