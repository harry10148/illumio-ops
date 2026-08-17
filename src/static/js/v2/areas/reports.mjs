// reports.mjs — #/reports. Anchors RP-01…RP-09 + XC-07 (design/v2/coverage.yaml).
//
// PORT OF design/v2/mockup/js/areas/reports.mjs. That file's own header
// explains the product's report page (a wall of eleven buttons over one
// shared modal) and the two things the mockup adds that the product does
// not show: WHEN a type last produced anything, and WHICH parameters a type
// actually takes. Both stand unchanged here — this port only replaces the
// mockup's "nothing here is real" plumbing with the real backend, per the
// task brief's T8 row. Deviations from the mockup, each at its precise
// location below:
//
//   1. Every `store.load(id)` -> `api.load(id)`. All seven ids — reports_list,
//      report_schedules, rhc_enablement, labels, status, fb_suggest, fb_browse
//      — are already exact entries in store-map.mjs's GET_MAP (nothing needed
//      api.get()), but SNAPS itself now carries only five: rhc_enablement and
//      fb_browse are loaded separately — see point 12.
//   2. RP-02's eleven generate drawers now issue a REAL POST to their real
//      endpoint (read from src/gui/routes/reports.py for every one of them).
//      traffic/security_risk/network_inventory and app_summary always answer
//      `{ok:true, job_id}` (a background thread, regardless of csv/api
//      source); the other seven answer synchronously with the final result.
//      RType.async already encoded this split correctly — no change there.
//   3. RP-03/XC-07's docked progress card now drives off the real response
//      instead of a fake 700ms ticker: synchronous types call
//      progress.done()/fail() straight from the POST's response; the async
//      types poll GET /api/reports/jobs/<job_id> every 2s for up to a real
//      30-minute ceiling — the exact figure dashboard.js:868 uses in
//      `_pollReportJob`, transcribed in runGenerate/pollReportJob below. The
//      mockup's honesty step ("v2_rp_step_mock", "此處沒有後端，產出不會發生")
//      and its drawer note ("v2_rp_mock_gen") are gone — dropped, not
//      replaced, because they are no longer true.
//   4. verifyPane() is dropped — same call investigate.mjs and automation.mjs
//      already made (components/verifypane.mjs's own header says it is a
//      mockup-only device, "Phase 2 will NOT build them into the product").
//      The payload `<pre>` stays, unbadged: it is now the operator's real
//      preview of the request about to be sent, built from the same
//      `repaint()` that constructs the body runGenerate actually POSTs.
//   5. RP-05's "Enable for all VENs" button now really POSTs
//      /api/rule_hit_count/enable (dropping the mock toast "v2_rp_rhc_mock").
//      The identical confirm+POST path also fires when a rule_hit_count
//      generate answers `needs_enablement` — dashboard.js:1265-1300 does
//      this with a bare `window.confirm`; here it goes through
//      modal.confirm/XC-08 like every other destructive action in v2.
//   6. RP-06/07's delete, bulk-delete, view and download are real: DELETE
//      /api/reports/<filename>, POST /api/reports/bulk-delete (its `errors`
//      array is inspected, not just `ok` — A3: a bulk delete that fails half
//      its files still answers ok:true), and the row's 瀏覽/下載 actions are
//      real `<a href="/reports/<filename>[?download=1]">` links to the real
//      `GET /reports/<filename>` route (reports.py:286) — replacing toast
//      stubs that quoted a `/api/reports/download/...` / `/view/...` path
//      the backend has never had (those were the mockup's own invention,
//      per v2_rp_dl_note/v2_rp_view_note, now dropped). "v2_rp_out_note"'s
//      claim that delete only touches an in-memory copy is no longer true;
//      rewritten as gui_rp_out_note.
//   7. i18n: v2_* -> gui_*. rpt_filter_pd / rpt_filter_toggle /
//      rpt_filter_objects / rpt_pd_blocked / rpt_pd_potential /
//      rpt_pd_allowed are dropped even though the mockup used them verbatim
//      from the shipping catalogue: /api/ui_translations only serves keys
//      matching gui_/sched_/status_/error_/pd_ (src/gui/_helpers.py
//      _ui_translation_dict), so t() would mark them permanently missing.
//      Replaced with catalogue keys that ARE served: gui_policy_dec,
//      gui_pd_blocked/potential/allowed, gui_qt_object_filters (already
//      shipped, investigate.mjs's own FilterBar description) — only
//      gui_rp_filter_toggle is a genuinely new key, for the one string with
//      no existing gui_ equivalent. Every toast/step string reuses the
//      product's own existing per-type keys (gui_toast_<type>_done/fail/
//      error, gui_gen_step_*, gui_rhc_*, gui_toast_events_count/
//      flows_count/report_partial) rather than minting new ones — reports.py's
//      real responses already match the shape those keys were written for.
//   8. RP-03's aside panel drops the mockup's "Run demo" / "End demo"
//      buttons (v2_rp_demo_run/stop): they ran the same fake ticker being
//      removed everywhere else, and a button that fires a real POST on every
//      click would breach this area's destructive-operation discipline. The
//      panel is documentation-only now.
//   9. audit.register("rp-progress", …) no longer starts a fake run either —
//      it is exactly the callback window.__openAllForAudit() fires from
//      every area's coverage-anchor e2e test (see tests/v2_e2e_utils.py's
//      sibling test files), so wiring it to a real POST would fire an
//      uncontrolled /api/reports/generate every time that sweep runs
//      anywhere in the suite. It now shows the docked card in its real idle
//      first-step state (progress.start(), no .step()/.done()/.fail() ever
//      called) — enough for the coverage gate to see XC-07's anchor, with no
//      network call and nothing that could read as a fabricated result.
//  10. genDrawer's FilterBar instance is exposed on the returned spec's body
//      (`spec.body._filterBar`) so handles.open can register
//      `h.onClose(() => …destroy())` — the drawer.mjs teardown contract
//      Tasks 4-9 all follow. The mockup never needed this: closing its
//      drawer never freed a live component.
//  11. state.torn + a router.onChange teardown (same shape as overview.mjs /
//      investigate.mjs) is new. The mockup's render callback had nothing
//      async left running after paint; this port polls jobs and refreshes
//      the report list from the real backend, so it needs one. It destroys
//      the output table handle, closes any drawer/modal, and drops this
//      route's palette commands; the poll timer/progress card are cancelled
//      by the pre-existing module-level stopProgress(), reachable from
//      either teardown path. Registered at the top of mountReports, before
//      its first await (Task 12d): it used to run inside the render callback,
//      so a mount that ended on the XC-10 error card registered none at all
//      and leaked its three rp:* palette commands into every other area.
//  12. rhc_enablement and fb_browse are real GETs that reach the live PCE
//      (rule_hit_count_enablement.check_enablement's two `_api_get` calls;
//      filter_object_cache's module-level TTL cache, which raises on a cold
//      miss against an unreachable PCE) and can genuinely fail — something
//      store.load() never did. Both are now loaded OUTSIDE loadAll(SNAPS)'s
//      strict Promise.all (whose contract, same as overview.mjs/
//      investigate.mjs, is "any failure here error-cards the whole area"),
//      each with its own fallback: a failed rhc_enablement renders RP-05 as
//      a real error with a real retry button (loadRhc()); a failed fb_browse
//      just leaves the FilterBar's browse tab empty until a retry succeeds
//      (same degrade investigate.mjs's prefetchFilterCorpus already ships).
//      Neither failure can hide report generation, the output list, or any
//      of the other seven RP-* panels.
//  13. CSV-source generation (toFormData/runGenerate) sends its
//      multipart/form-data body through `api.postForm()` — post()'s sibling
//      for the one request shape it cannot express, added to core/api.mjs
//      alongside this task. First cut here duplicated api.mjs's fetch+CSRF
//      logic by hand with no refresh-and-retry on a stale token (Task 8
//      review, Important finding: every other write in the app recovers
//      from that automatically, this one silently failed instead). Fixed by
//      moving the shared logic into api.mjs's own rawRequest() once, not by
//      re-copying it here.


import { el, clear } from "../core/dom.mjs";
import { t, tf } from "../core/i18n.mjs";
import { stamp } from "../core/fmt.mjs";
import { api } from "../core/api.mjs";
import { router } from "../core/router.mjs";
import { audit } from "../core/audit.mjs";
import { toast } from "../core/toast.mjs";
import { withErrorCard } from "../components/errorcard.mjs";
import { drawer } from "../components/drawer.mjs";
import { modal } from "../components/modal.mjs";
import { table, col } from "../components/table.mjs";
import { palette } from "../components/palette.mjs";
import { progress } from "../components/progress.mjs";
import { createFilterBar, setFilterBarText, setFilterBarSnapshots } from "../components/filter-bar.mjs";

const ROUTE = "#/reports";

/* rhc_enablement and fb_browse are deliberately NOT in this list — see
 * header point 12. Both are real GETs that reach the live PCE
 * (rule_hit_count_enablement.check_enablement / filter_object_cache's cold
 * module cache) and can genuinely fail with a real PCE outage; loadAll()
 * below feeds withErrorCard's Promise.all, whose contract is "any failure
 * here error-cards the WHOLE area" (overview.mjs/investigate.mjs keep the
 * same PCE-touching ids out of their own strict lists for the same reason).
 * Both are still loaded for real — just individually, with their own
 * fallback, so one optional panel's outage never hides report generation or
 * the output list. */
const SNAPS = ["reports_list", "report_schedules", "labels", "status", "fb_suggest"];

/** Minimal area-head: title + route breadcrumb. Same local copy every
 * single-route area keeps (overview.mjs's own comment explains why: small
 * enough that duplicating it beats pulling in a shell.mjs that does not
 * exist in this app). */
/* Route as a data attribute, not visible chrome — see overview.mjs's areaHead. */
function areaHead(title, route) {
  return el("div", { class: "area-head", "data-route": route },
    el("h1", { text: title })
  );
}

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
// gui_pd_* (not rpt_pd_*): the shipping rpt_pd_blocked/potential/allowed keys are real, but
// /api/ui_translations only serves gui_/sched_/status_/error_/pd_-prefixed keys
// (src/gui/_helpers.py:_ui_translation_dict) — see this file's header, point 7.
const PDS = [["blocked", "gui_pd_blocked"], ["potentially_blocked", "gui_pd_potential"], ["allowed", "gui_pd_allowed"]];
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
    this.async = false;
    this.formatNote = null;
  }
  has(s) { return this.sections.indexOf(s) >= 0; }
  meta(genKey, dateFmt) {
    this.genKey = genKey;
    this.dateFmt = dateFmt;
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
    .meta("gui_gen_traffic_title", "iso").flags(true, null),
  new RType("security_risk", "gui_rcard_security_title", "gui_rcard_security_desc", "/api/reports/generate", TRAFFIC_PROFILE)
    .meta("gui_gen_security_title", "iso").flags(true, null),
  new RType("network_inventory", "gui_rcard_inventory_title", "gui_rcard_inventory_desc", "/api/reports/generate", TRAFFIC_PROFILE)
    .meta("gui_gen_inventory_title", "iso").flags(true, null),
  new RType("audit", "gui_btn_audit_report", "gui_rcard_audit_desc", "/api/audit_report/generate", ["dates"])
    .meta("gui_gen_audit_title", "iso").flags(false, null),
  new RType("ven", "gui_btn_ven_report", "gui_rcard_ven_desc", "/api/ven_status_report/generate", ["snapshot"])
    .meta("gui_gen_ven_title", "raw").flags(false, null),
  new RType("policy_usage", "gui_btn_pu_report", "gui_rcard_pu_desc", "/api/policy_usage_report/generate", ["source", "dates"])
    .meta("gui_gen_pu_title", "raw").flags(false, null),
  new RType("rule_hit_count", "gui_btn_rhc_report", "gui_rcard_rhc_desc", "/api/rule_hit_count_report/generate", ["source", "dates"])
    .meta("gui_gen_rhc_title", "raw").flags(false, null),
  new RType("readiness", "gui_rcard_readiness_title", "gui_rcard_readiness_desc", "/api/readiness_report/generate", ["dates", "ds"])
    .meta("gui_gen_readiness_title", "raw").flags(false, null),
  new RType("policy_diff", "gui_rcard_policy_diff_title", "gui_rcard_policy_diff_desc", "/api/policy_diff_report/generate", ["snapshot"])
    .meta("gui_gen_policy_diff_title", "raw").flags(false, "gui_rp_fmt_pd"),
  new RType("policy_resolver", "gui_rcard_policy_resolver_title", "gui_rcard_policy_resolver_desc", "/api/policy_resolver_report/generate", ["snapshot"])
    .meta("gui_gen_policy_resolver_title", "raw").flags(false, "gui_rp_fmt_pr"),
  new RType("app_summary", "gui_rcard_app_title", "gui_rcard_app_desc", "/api/app_report/generate", ["dates", "app", "ds"])
    .meta("gui_gen_app_title", "raw").flags(true, null),
];

// The card meta strip's schedule chip (dashboard.js:264-271).
const SCHED_CHIPS = [["daily", "gui_rcard_sched_daily"], ["weekly", "gui_rcard_sched_weekly"], ["month", "gui_rcard_sched_monthly"]];

// A section id -> its chip key, spelled out as a literal map (not built by
// string concatenation) so scripts/audit_i18n_usage.py's static scanner can
// resolve every key — same reason automation.mjs's RULE_TYPE_OPTS exists
// (its own comment explains the scanner limitation in full).
const SECTION_LABELS = {
  source: "gui_rp_sec_source",
  dates: "gui_rp_sec_dates",
  filters: "gui_rp_sec_filters",
  app: "gui_rp_sec_app",
  ds: "gui_rp_sec_ds",
  snapshot: "gui_rp_sec_snapshot",
};

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
  const v = el("span", { class: "s", text: value === null || value === undefined || value === "" ? "—" : String(value) });
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
  return Promise.all(ids.map(function (id) { return api.load(id); })).then(function (list) {
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

function errText(value) {
  const message = value && (value.error || value.message);
  return message ? String(message) : t("gui_err_generic");
}

/** Real GET /api/rule_hit_count/enablement (header, point 12), loaded/reloaded
 * outside loadAll()'s strict Promise.all so a real PCE outage answers with
 * `{_error}` instead of error-carding the whole area. */
function loadRhc() {
  return api.reload("rhc_enablement").catch(function (e) {
    return { _error: errText(e && e.data ? e.data : e) };
  });
}

// ── report_type derivation ──────────────────────────────────────────────────
/* dashboard.js:239-255, prefix rule for prefix rule. The traffic-family sidecar
 * always writes report_type "traffic" (report_generator.py hardcodes it), so
 * the three traffic profiles are only separable by filename — and the specific
 * SecurityRisk / NetworkInventory prefixes must be tested BEFORE the bare dated
 * traffic pattern, because "Illumio_Traffic_Report_" is a strict prefix of both. */
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
 * the previous type left behind. This port opens a fresh drawer each time, so
 * the default is applied every time; the note on the field says what the
 * product does. */
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
 *   readiness              dashboard.js:1051-1058 format/lang/start_date/end_date/[data_source]
 *   policy_diff            dashboard.js:1084-1088 format(html|csv only)/lang
 *   policy_resolver        dashboard.js:1109      format:'all' hardcoded/lang
 *   app_summary            dashboard.js:1134-1151 app/env/lang/start_date/end_date/data_source
 * The pane below is built FROM the controls, so a control that is missing shows
 * up as a missing key rather than as a silently correct-looking payload — and,
 * unlike the mockup, this pane is exactly what runGenerate() sends (see
 * onSave below), because it calls the very same repaint(). */
function genDrawer(rt, d, lang, hooks) {
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
  const fileBox = editField("file", t("gui_gen_select_csv_file"), fileInput, t("gui_rp_file_hint"));
  const dateRow = el("div", { class: "qrow" },
    el("div", { class: "qf" }, el("label", { text: t("gui_gen_start_date") }), startInput),
    el("div", { class: "qf" }, el("label", { text: t("gui_gen_end_date") }), endInput));
  const quickRow = el("div", { class: "typechips" });
  QUICK_DAYS.forEach(function (n) {
    quickRow.appendChild(btn("btn ghost", tf("gui_rp_quick_days", { n: n }), function () {
      startInput.value = isoDay(n);
      endInput.value = isoDay(0);
      repaint();
    }));
  });
  const dateBox = el("div", null,
    sectionHead(t("gui_quick_range")), quickRow, dateRow,
    note(t(rt.dateFmt === "iso" ? "gui_rp_date_iso" : "gui_rp_date_raw")),
    note(t("gui_rp_date_sticky")));
  startInput.dataset.field = "start_date";
  endInput.dataset.field = "end_date";

  // RP-09's other half: the two selects the product fills from /api/labels.
  // The initial load is one unkeyed list (endpoints.yaml:56 calls
  // /api/labels with no key), so BOTH selects are fed from it and the drawer
  // says so rather than pretending it fetched key=app and key=env separately.
  const labels = (d.labels && d.labels.labels) || [];
  labels.forEach(function (v) { appSel.appendChild(el("option", { value: v, text: v })); });
  envSel.appendChild(el("option", { value: "", text: t("gui_env_any") }));
  labels.forEach(function (v) { envSel.appendChild(el("option", { value: v, text: v })); });
  appSel.addEventListener("change", repaint);
  envSel.addEventListener("change", repaint);
  const appBox = el("div", null,
    editField("app", t("gui_app_label_field"), appSel, t("gui_rp_app_required")),
    editField("env", t("gui_env_label_field"), envSel),
    note(t("gui_rp_labels_src")));

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
    sectionHead(t("gui_rp_filter_toggle")),
    labelled(t("gui_policy_dec"), pdRow),
    el("div", { class: "fld" }, el("label", null, el("span", { text: t("gui_qt_object_filters") }), el("code", { text: "filters" })), barHost));
  pdRow.dataset.field = "policy_decisions";
  barHost.dataset.field = "filters";

  let bar = null;
  if (rt.has("filters")) {
    setFilterBarText(t);
    setFilterBarSnapshots(d.fb_suggest, d.fb_browse);
    bar = createFilterBar(barHost, {});
    bar.onChange(repaint);
  }
  // Teardown handle for handles.open (drawer.mjs contract) — see header, point 10.
  body._filterBar = bar;

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
   * the body entirely (dashboard.js:967 sends it only when non-null; reports.py
   * :460-461 treats an absent key and `{}` identically, `raw_filters or {}`). */
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

  /** Builds the body AND refreshes the payload preview. runGenerate() calls
   * this same function to get the real request body (see onSave below) — the
   * preview can never drift from what is actually sent. */
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
    if (csv) b.file = t("gui_rp_file_placeholder");
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
  body.appendChild(sectionHead(t("gui_rp_form_section")));
  if (rt.has("source")) {
    body.appendChild(srcBox);
    body.appendChild(fileBox);
    if (rt.id === "rule_hit_count") body.appendChild(note(t("gui_rp_rhc_native")));
  }
  if (rt.has("snapshot")) body.appendChild(note(t("gui_gen_snapshot_note")));
  if (rt.has("dates")) body.appendChild(dateBox);
  if (rt.has("app")) body.appendChild(appBox);
  if (rt.has("filters")) body.appendChild(filterBox);
  if (rt.has("ds")) {
    body.appendChild(dsBox);
    body.appendChild(note(t("gui_rp_ds_gate")));
  }
  body.appendChild(sectionHead(t("gui_rp_out_section")));
  body.appendChild(editField("format", t("gui_sched_format"), fmtSel, rt.formatNote ? t(rt.formatNote) : null));
  body.appendChild(editField("lang", t("gui_report_lang_label"), langSel, t("gui_rp_lang_field_hint")));
  // Body keys the form does not expose as controls. traffic_report_profile is
  // the card's own identity (dashboard.js:962-967 reads it from the button that
  // opened the modal, never from an input) — it still reaches the backend, so it
  // is stated rather than left to be discovered in the payload pane.
  if (rt.has("filters")) {
    body.appendChild(sectionHead(t("gui_rp_ro_section")));
    body.appendChild(roList([roField("traffic_report_profile", rt.id, t("gui_rp_fn_profile"))]));
  }
  body.appendChild(sectionHead(t("gui_rp_payload")));
  body.appendChild(payload);

  onSource();
  repaint();
  return drawerSpec(t(rt.genKey), body, function () {
    const b = repaint();
    const isCsv = state.source === "csv";
    if (isCsv && (!fileInput.files || !fileInput.files[0])) {
      toast.crit(t("gui_err_no_csv"));
      return false;
    }
    runGenerate(rt, state.source, b, isCsv ? fileInput.files[0] : null, hooks);
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
 *   API sync       gui_gen_step_fetching -> done                   (:955, :1029 …)
 *   API + audit    adds gui_gen_step_analysing after 3000 ms        (:998, cleared :1000)
 *   API async job  gui_gen_step_fetching -> gui_gen_step_running_bg (_pollReportJob :870)
 * progress.start() already paints the first step as "active" with no call
 * needed (progress.mjs's own `at = 0` default) — runGenerate only ever calls
 * .step() to advance PAST a completed step, and .done()/.fail() at the end. */
let liveProgress = null;
let livePollTimer = null;

function stepsFor(rt, source) {
  const steps = [];
  if (source === "csv") steps.push(t("gui_gen_step_parsing"));
  else steps.push(t("gui_gen_step_fetching"));
  if (rt.id === "audit") steps.push(t("gui_gen_step_analysing"));
  if (rt.async || source === "csv") steps.push(t("gui_gen_step_running_bg"));
  return steps;
}

function stopProgress() {
  if (livePollTimer) { window.clearTimeout(livePollTimer); livePollTimer = null; }
  if (!liveProgress) return;
  liveProgress.close();
  liveProgress = null;
}

// The progress card is docked to <body>, not to the area root, so leaving the
// route would strand it over another page. Registered once at module load —
// a per-mount listener would leak one subscription per visit. Also cancels
// the poll timer, so no job poll survives a navigation away from #/reports.
router.onChange(function (path) { if (path !== ROUTE) stopProgress(); });

const POLL_MS = 2000;
// dashboard.js:868 — 30-minute ceiling ("App Summary on large estates can
// take ~15-20 min"). Transcribed exactly; see header point 3.
const POLL_DEADLINE_MS = 30 * 60 * 1000;

const TOAST_FAIL = {
  traffic: "gui_toast_traffic_fail", security_risk: "gui_toast_traffic_fail", network_inventory: "gui_toast_traffic_fail",
  audit: "gui_toast_audit_fail", ven: "gui_toast_ven_fail", policy_usage: "gui_toast_pu_fail",
  rule_hit_count: "gui_toast_rhc_fail", readiness: "gui_toast_readiness_fail",
  policy_diff: "gui_toast_policy_diff_fail", policy_resolver: "gui_toast_policy_resolver_fail",
  app_summary: "gui_toast_app_summary_fail",
};

function kpiLine(kpis) {
  return (kpis || []).map(function (k) { return k.label + ": " + k.value; }).join(" | ");
}

/** POST rt.endpoint (JSON, or multipart/form-data when `file` is given) and
 * drive the docked progress card off the real response. `hooks` =
 * {refreshList, onNeedsEnablement} — supplied by mountReports's closure. */
function runGenerate(rt, source, body, file, hooks) {
  if (liveProgress) stopProgress();
  const steps = stepsFor(rt, source);
  const p = progress.start(t(rt.genKey), steps);
  p.el.dataset.cov = "XC-07";
  liveProgress = p;
  let settled = false;
  let analysingTimer = null;
  if (rt.id === "audit") {
    // dashboard.js:998-1000 — a 3000ms timer marks the second step only if
    // the request is still in flight; cleared the instant it resolves.
    analysingTimer = window.setTimeout(function () {
      if (!settled && liveProgress === p) p.step(1);
    }, 3000);
  }
  const req = file ? api.postForm(rt.endpoint, toFormData(body, file)) : api.post(rt.endpoint, body);
  req.then(function (res) {
    settled = true;
    if (analysingTimer) window.clearTimeout(analysingTimer);
    if (liveProgress !== p) return; // navigated away, or superseded by another generate
    if (res && res.ok && res.job_id) {
      p.step(1); // advance into the "running in background" step
      pollReportJob(res.job_id, rt, p, hooks);
    } else {
      settleGenerate(rt, res, p, hooks);
    }
  });
}

/** GET /api/reports/jobs/<job_id> every POLL_MS until status is done/error or
 * POLL_DEADLINE_MS elapses — _pollReportJob transcribed (dashboard.js:866-895),
 * including its own quirk of treating a transient fetch error as "keep
 * polling" rather than a terminal failure. */
function pollReportJob(jobId, rt, p, hooks) {
  const deadline = Date.now() + POLL_DEADLINE_MS;

  function finish(ok, s) {
    livePollTimer = null;
    if (liveProgress !== p) return;
    if (ok) {
      p.done();
      toast.ok(asyncDoneToast(rt, s));
      hooks.refreshList();
    } else {
      const msg = (s && s.error) || t(TOAST_FAIL[rt.id] || "gui_err_generic");
      p.fail(msg);
      toast.crit(msg);
    }
  }

  function tick() {
    if (liveProgress !== p) return;
    livePollTimer = window.setTimeout(function () {
      if (liveProgress !== p) return;
      if (Date.now() >= deadline) { finish(false, null); return; }
      api.get("/api/reports/jobs/" + encodeURIComponent(jobId)).then(function (s) {
        if (liveProgress !== p) return;
        if (s && s.status === "done") { finish(true, s); return; }
        if (s && s.status === "error") { finish(false, s); return; }
        tick(); // still running
      }).catch(function () {
        tick(); // transient fetch error — keep polling until the deadline
      });
    }, POLL_MS);
  }

  tick();
}

function asyncDoneToast(rt, s) {
  if (rt.id === "app_summary") return t("gui_toast_app_summary_done");
  const msg = tf("gui_toast_flows_count", { n: (s && s.record_count) || 0 });
  return tf("gui_toast_traffic_done", { msg: msg });
}

/** Terminal handling for a synchronous response (every non-async type), and
 * for the immediate-failure path of an async POST (validation rejected
 * before a job was ever created — no job_id). */
function settleGenerate(rt, res, p, hooks) {
  const ok = !!(res && res.ok);
  if (ok) {
    switch (rt.id) {
      case "audit":
        toast.ok(tf("gui_toast_audit_done", { msg: tf("gui_toast_events_count", { n: res.record_count || 0 }) }));
        break;
      case "ven": {
        const kpi = kpiLine(res.kpis);
        toast.ok(kpi ? tf("gui_toast_ven_done_kpi", { kpi: kpi }) : t("gui_toast_ven_done"));
        break;
      }
      case "readiness": {
        const kpi = kpiLine(res.kpis);
        toast.ok(kpi ? tf("gui_toast_readiness_done_kpi", { kpi: kpi }) : t("gui_toast_readiness_done"));
        break;
      }
      case "policy_diff":
        toast.ok(t("gui_toast_policy_diff_done"));
        break;
      case "policy_resolver":
        if (res.files && res.files.length) toast.ok(t("gui_toast_policy_resolver_done"));
        else toast.info(t("gui_toast_policy_resolver_empty"));
        break;
      case "policy_usage":
        toast.ok(tf("gui_toast_pu_done", { count: res.record_count || 0 }));
        break;
      case "rule_hit_count":
        toast.ok(tf("gui_toast_rhc_done", { count: res.record_count || 0 }));
        break;
      default:
        toast.ok(t("gui_gen_done"));
    }
    p.done();
    hooks.refreshList();
    return;
  }
  // dashboard.js:1265-1300 — RHC's two soft-fail shapes get their own framing
  // instead of the generic failure toast below.
  if (rt.id === "rule_hit_count" && res && res.needs_enablement) {
    p.fail(res.error || t("gui_toast_rhc_fail"));
    if (hooks.onNeedsEnablement) hooks.onNeedsEnablement(res.state);
    return;
  }
  if (rt.id === "rule_hit_count" && res && res.pull_timeout) {
    const msg = res.error || t("gui_rhc_pull_timeout");
    p.fail(msg);
    toast.warn(msg);
    return;
  }
  // dashboard.js:633-640 _handlePartialReport — ok:false but files DID land
  // for at least one format; A3: check the real per-item signal, not `ok`.
  if (res && res.partial) {
    const msg = tf("gui_toast_report_partial", { formats: (res.failed_formats || []).join(", ") });
    p.fail(msg);
    toast.warn(msg);
    hooks.refreshList();
    return;
  }
  const msg = (res && res.error) || t(TOAST_FAIL[rt.id] || "gui_err_generic");
  p.fail(msg);
  toast.crit(msg);
}

/** Builds the multipart body for a CSV-source generate from the same `b` that
 * repaint() built for the JSON path — same key set, `file` swapped for the
 * real Blob. Sent through api.postForm() (header, point 13): api.mjs's
 * post() only sends JSON, so CSV upload needs the multipart sibling —
 * same CSRF-refresh-and-retry as every other write in this app. */
function toFormData(b, file) {
  const fd = new FormData();
  Object.keys(b || {}).forEach(function (k) {
    if (k === "file") return;
    const v = b[k];
    if (v === undefined || v === null) return;
    fd.append(k, typeof v === "object" ? JSON.stringify(v) : String(v));
  });
  fd.append("file", file);
  return fd;
}

// ══════════════════════════════════════════════════════════ mount ════════════

async function mountReports(root, ctx) {
  const handles = {};
  // Registered synchronously, before the first await (Task 7 report §9.6) —
  // and so is the teardown that drops them again (Task 12d). The state object
  // itself never needed the load: only its FIELDS come from `d`, and they are
  // filled in by the render callback below. Registering the teardown down
  // there meant a mount that ended on the XC-10 error card registered none at
  // all, and its three rp:* palette commands followed the operator out of the
  // area. installTeardown only reads state.torn/state.tableHandle, both of
  // which are safe to find absent.
  const state = { torn: false };
  installTeardown(state);
  drawer.registerAudit("rp-gen", function () { return handles.open ? handles.open("traffic") : null; });
  // Seeds a selection first: the bulk bar and its confirm only exist when rows
  // are picked, so an opener that skipped the selection would show the gate an
  // empty dialog that no operator could ever reach.
  modal.registerAudit("rp-bulk-delete", function () { return handles.auditBulk ? handles.auditBulk() : null; });
  modal.registerAudit("rp-rhc-enable", function () { return handles.enableRhc ? handles.enableRhc() : null; });
  audit.register("rp-progress", function () {
    if (liveProgress) return;
    // See header, point 9: this must never fire a real generate — it is the
    // same callback every area's coverage-anchor e2e drives via
    // window.__openAllForAudit(). The idle first-step state is all XC-07
    // needs to be visible; nothing here ever calls .step()/.done()/.fail().
    const idleRt = rtypeOf("audit") || RTYPES[0];
    const p = progress.start(t(idleRt.genKey), stepsFor(idleRt, "api"));
    p.el.dataset.cov = "XC-07";
    liveProgress = p;
  });
  palette.registerFor(ROUTE, cmdSpec("rp:gen-traffic", t("gui_gen_traffic_title"), function () { if (handles.open) handles.open("traffic"); }));
  palette.registerFor(ROUTE, cmdSpec("rp:gen-audit", t("gui_gen_audit_title"), function () { if (handles.open) handles.open("audit"); }));
  palette.registerFor(ROUTE, cmdSpec("rp:outputs", t("gui_report_output"), function () { if (handles.focusOutputs) handles.focusOutputs(); }));

  root.appendChild(areaHead(t("gui_nav_reports"), ROUTE));
  const wrap = el("div", { class: "wb" });
  const main = el("div", { class: "wb-main" });
  const aside = el("aside", { class: "wb-aside" });
  wrap.appendChild(main);
  wrap.appendChild(aside);
  root.appendChild(wrap);

  await withErrorCard(main, "reports (" + SNAPS.length + ")",
    function () {
      return Promise.all([loadAll(SNAPS), loadRhc()]).then(function (pair) {
        const d = pair[0];
        d.rhc_enablement = pair[1];
        d.fb_browse = null; // filled in by the background fetch below, once it lands
        return d;
      });
    },
    function (d) {
      if (ctx.stale()) return;

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
      state.rhc = d.rhc_enablement || {};
      // state.torn is NOT reset here: the teardown above may already have
      // fired (a navigation while this load was in flight), and clearing the
      // flag would let this mount's background fb_browse resolution repaint a
      // board that is gone.

      // fb_browse (header, point 12): real GET, fetched in the background so
      // a cold-cache PCE outage never blocks the rest of the page. genDrawer
      // reads d.fb_browse at the moment a filters-drawer actually opens, by
      // which point this has almost always resolved — and if it has not,
      // FilterBar's own "type to search" state is what shows meanwhile
      // (same degrade investigate.mjs's prefetchFilterCorpus documents).
      api.load("fb_browse").catch(function () { return null; }).then(function (browse) {
        if (!state.torn) d.fb_browse = browse;
      });

      const schedules = (d.report_schedules && d.report_schedules.schedules) || [];
      const schedByType = {};
      schedules.forEach(function (s) {
        const ty = s.report_type || "";
        if (ty && !schedByType[ty]) schedByType[ty] = s;
      });
      let latestByType = {};
      let countByType = {};
      function recomputeDerived() {
        latestByType = {};
        countByType = {};
        state.reports.forEach(function (r) {
          if (!r._type) return;
          countByType[r._type] = (countByType[r._type] || 0) + 1;
          if (!latestByType[r._type] || r.mtime > latestByType[r._type]) latestByType[r._type] = r.mtime;
        });
      }
      recomputeDerived();

      // hooks feeds runGenerate/settleGenerate what they need from this
      // closure without threading `state`/`handles` through every module-level
      // function's argument list. Populated below, before either can be
      // invoked by a real user action.
      const hooks = {};

      handles.open = function (id) {
        const rt = rtypeOf(id) || RTYPES[0];
        const spec = genDrawer(rt, d, state.lang, hooks);
        const h = drawer.open(spec);
        if (spec.body._filterBar) h.onClose(function () { spec.body._filterBar.destroy(); });
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
      const catPanel = panel("RP-01", t("gui_rp_catalogue"));
      const catMeta = el("span", { class: "meta" });
      catPanel.head.appendChild(catMeta);
      const grid = el("div", { class: "rpgrid" });
      const untypedNoteHost = el("div");
      catPanel.body.appendChild(grid);
      catPanel.body.appendChild(note(t("gui_rp_cat_note")));
      catPanel.body.appendChild(untypedNoteHost);
      main.appendChild(catPanel);

      function paintCatalogue() {
        catMeta.textContent = tf("gui_rp_cat_meta", { types: RTYPES.length, files: state.reports.length });
        clear(grid);
        RTYPES.forEach(function (rt) {
          const card = el("article", { class: "rpcard", "data-rtype": rt.id });
          card.appendChild(el("div", { class: "rpcard-h" },
            el("code", { text: rt.id }),
            el("span", { class: "rpcard-sched", text: schedChip(schedByType[rt.id]) })));
          card.appendChild(el("b", { text: t(rt.titleKey) }));
          card.appendChild(el("p", { text: t(rt.descKey) }));
          const secs = el("div", { class: "chips" });
          rt.sections.forEach(function (s) { secs.appendChild(el("span", null, el("b", { text: t(SECTION_LABELS[s] || s) }))); });
          card.appendChild(secs);
          const last = el("div", { class: "rpcard-last" },
            el("span", { class: "k", text: t("gui_rp_last") }),
            el("span", { class: "v mono", text: lastStamp(latestByType[rt.id]) }),
            el("span", { class: "n mono", text: tf("gui_rp_files_n", { n: countByType[rt.id] || 0 }) }));
          card.appendChild(last);
          card.appendChild(btn("btn primary", t("gui_gen_generate"), function () { handles.open(rt.id); }));
          grid.appendChild(card);
        });
        // The note must not hardcode these three numbers: rawEmpty (no sidecar at
        // all) splits into recovered (saved by the filename-prefix rule above) and
        // stillUntyped (genuinely unlabeled) — recomputed from the live list so a
        // real report gone stale (or generated) can't silently drift the copy.
        clear(untypedNoteHost);
        const rawEmpty = state.reports.filter(function (r) { return !(r.report_type || ""); });
        const recovered = rawEmpty.filter(function (r) { return !!r._type; });
        const stillUntyped = state.reports.filter(function (r) { return !r._type; });
        untypedNoteHost.appendChild(note(tf("gui_rp_untyped_note", {
          total: state.reports.length,
          rawEmpty: rawEmpty.length,
          recovered: recovered.length,
          stillUntyped: stillUntyped.length
        })));
      }
      paintCatalogue();

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
      outPanel.body.appendChild(note(t("gui_rp_out_note")));
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

      /* Refetches /api/reports (real GET) and repaints everything derived from
       * it. Called after every mutation (delete, bulk-delete, a completed
       * generate) instead of guessing which rows a partial success touched —
       * the server's own listing is the only source of truth for A1/A3-style
       * "did this actually happen" questions. */
      function refreshReportsList() {
        return api.reload("reports_list").then(function (rl) {
          if (state.torn) return;
          state.reports = ((rl && rl.reports) || []).map(function (r) {
            const c = {};
            Object.keys(r).forEach(function (k) { c[k] = r[k]; });
            c._type = derivedType(r);
            return c;
          });
          state.reports.sort(function (a, b) { return b.mtime - a.mtime; });
          state.selected = state.selected.filter(function (fn) {
            return state.reports.some(function (r) { return r.filename === fn; });
          });
          recomputeDerived();
          paintCatalogue();
          paintOut();
          paintFloat();
        }).catch(function (e) {
          if (state.torn) return;
          toast.crit(errText(e && e.data ? e.data : e));
        });
      }
      hooks.refreshList = refreshReportsList;
      hooks.onNeedsEnablement = function (stateLabel) { return handles.enableRhc(stateLabel); };

      /* dashboard.js:209-220 — one DELETE per file, then a reload; here the
       * reload is the real refreshReportsList() above. */
      function deleteOne(r) {
        return modal.confirm(confirmSpec(tf("gui_delete_confirm", { filename: r.filename }),
          [tf("gui_rp_del_one", { filename: r.filename }), t("gui_rp_del_norecover")],
          function () {
            return api.del("/api/reports/" + encodeURIComponent(r.filename)).then(function (res) {
              if (!res || res.ok !== true) {
                toast.crit(errText(res));
                return false;
              }
              toast.ok(tf("gui_deleted_ok", { filename: r.filename }));
              return refreshReportsList().then(function () { return true; });
            });
          }));
      }

      /* dashboard.js:159-181 — one POST /api/reports/bulk-delete carrying every
       * filename; the response splits into `deleted` and `errors` (A3: both are
       * inspected — {ok:true} alone does not mean every file was removed). */
      handles.bulkDelete = function () {
        const names = state.selected.slice();
        const impact = [tf("gui_delete_selected_confirm", { count: names.length })].concat(names.slice(0, 6));
        if (names.length > 6) impact.push(tf("gui_rp_del_more", { n: names.length - 6 }));
        impact.push(t("gui_rp_del_bulk_partial"));
        impact.push(t("gui_rp_del_norecover"));
        return modal.confirm(confirmSpec(t("gui_delete_selected"), impact, function () {
          return api.post("/api/reports/bulk-delete", { filenames: names, lang: state.lang }).then(function (res) {
            if (!res || res.ok !== true) {
              toast.crit(errText(res));
              return false;
            }
            const deleted = Number(res.deleted) || 0;
            const errors = res.errors || [];
            return refreshReportsList().then(function () {
              if (deleted > 0) toast.ok(tf("gui_deleted_count", { count: deleted }));
              if (errors.length) toast.warn(errors.join("; "));
              return true;
            });
          });
        }));
      };

      function paintFloat() {
        clear(floatHost);
        if (!state.selected.length) return;
        floatHost.appendChild(el("div", { class: "floatbar", "data-tone": "crit" },
          el("span", { text: t("gui_selected") + " " }),
          el("b", { text: String(state.selected.length) }),
          btn("btn danger", t("gui_delete_selected"), function () { handles.bulkDelete(); }),
          btn("btn ghost", t("gui_rp_sel_clear"), function () { state.selected = []; paintFloat(); paintOut(); })));
      }

      function typeCell(r) {
        if (!r._type) return el("span", { class: "chips" }, el("span", { class: "off", text: t("gui_rp_untyped") }));
        const rt = rtypeOf(r._type);
        return el("span", { class: "chips" }, el("span", null, el("b", { text: rt ? t(rt.titleKey) : r._type })));
      }

      function paintOut() {
        const rows = visibleReports();
        const size = 15;
        const pages = Math.max(1, Math.ceil(rows.length / size));
        if (state.page >= pages) state.page = pages - 1;
        const slice = rows.slice(state.page * size, state.page * size + size);
        outMeta.textContent = tf("gui_rp_out_meta", { shown: rows.length, total: state.reports.length });

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
              el("small", { text: r.summary || t("gui_rp_no_summary") }));
          })),
          col("type", t("gui_col_type"), widthCell(170, typeCell)),
          col("mtime", t("gui_col_date_created"), widthCell(150, function (r) {
            return el("code", { class: "mono", text: lastStamp(r.mtime) });
          })),
          col("size", t("gui_col_size"), widthCell(90, function (r) { return sizeText(r.size); })),
          col("act", t("gui_actions"), widthCell(190, function (r) {
            const box = el("div", { class: "rowacts" });
            const isHtml = /\.html?$/i.test(String(r.filename));
            // reports.py:286-298 — GET /reports/<filename>, ?download=1 forces
            // an attachment. Real links, not the toast stubs the mockup quoted
            // an endpoint shape the backend has never had (header, point 6).
            const href = "/reports/" + encodeURIComponent(r.filename);
            if (isHtml) box.appendChild(el("a", { class: "btn ghost", href: href, target: "_blank", rel: "noopener", text: t("gui_btn_view") }));
            box.appendChild(el("a", { class: "btn ghost", href: href + "?download=1", text: t("gui_btn_download") }));
            box.appendChild(btn("btn danger", t("gui_btn_delete"), function () { deleteOne(r); }));
            return box;
          })),
        ];

        state.tableHandle = table.render(outHost, tableSpec(columns, slice, pageSpec(state.page, size, rows.length), function (next) {
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
      const rhcPanel = panel("RP-05", t("gui_btn_rhc_report"));
      const rhcMeta = el("span", { class: "meta" });
      rhcPanel.head.appendChild(rhcMeta);
      const rhcBody = el("div");
      rhcPanel.body.appendChild(rhcBody);
      aside.appendChild(rhcPanel);

      // check_enablement() (rule_hit_count_enablement.py) returns one of
      // seven English `detail` shapes: five fixed strings (the two "both
      // X" states, the two "missing: X" partial states, and the unsupported
      // branch's no-version-evidence message) and two more from that same
      // unsupported branch that interpolate a live PCE version string (and,
      // for one of them, the two version-floor constants) — those can't be
      // a literal-string match. Fixed strings map straight to an i18n key;
      // the two interpolated ones are matched by a stable `^PCE version `
      // prefix regex (no trailing `$` anchor) rather than a full-sentence
      // equality check, so a wording tweak after the captured groups
      // doesn't silently fall back to raw English — only a changed PREFIX
      // does, and tests/test_rhc_detail_matches_backend_shapes.py fails the
      // build if the backend's possible shapes and this map/regex pair ever
      // drift apart.
      const RHC_DETAIL_KEYS = {
        "PCE report template and VEN scopes both enabled": "gui_rp_rhc_detail_enabled",
        "PCE report template and VEN scopes both disabled": "gui_rp_rhc_detail_disabled",
        "missing: VEN firewall_settings scopes": "gui_rp_rhc_detail_missing_ven",
        "missing: PCE report template": "gui_rp_rhc_detail_missing_pce",
        "report template not found — PCE below version floor (SaaS 24.2.0 / on-prem 23.5.10) or feature absent":
          "gui_rp_rhc_detail_unsupported_no_evidence",
      };
      const RHC_BELOW_FLOOR_RE = /^PCE version (\S+) below floor \(SaaS >= (\S+) \/ on-prem >= (\S+)\)/;
      const RHC_MEETS_FLOOR_RE = /^PCE version (\S+) meets conservative floor \(on-prem >= (\S+)\)/;
      function rhcDetailText(rhc) {
        const raw = String((rhc && rhc.detail) || "");
        const direct = RHC_DETAIL_KEYS[raw];
        if (direct) return t(direct);
        const belowFloor = RHC_BELOW_FLOOR_RE.exec(raw);
        if (belowFloor) {
          return tf("gui_rp_rhc_detail_below_floor", {
            version: belowFloor[1], saas_floor: belowFloor[2], onprem_floor: belowFloor[3],
          });
        }
        const meetsFloor = RHC_MEETS_FLOOR_RE.exec(raw);
        if (meetsFloor) {
          return tf("gui_rp_rhc_detail_meets_floor", { version: meetsFloor[1], onprem_floor: meetsFloor[2] });
        }
        return raw;
      }

      function paintRhc() {
        const rhc = state.rhc || {};
        // Real GET, real failure (header, point 12) — e.g. the PCE is down.
        // Rendered honestly instead of hiding the panel or guessing a state.
        if (rhc._error) {
          rhcPanel.dataset.tone = "crit";
          rhcMeta.textContent = "—";
          clear(rhcBody);
          rhcBody.appendChild(note(rhc._error));
          rhcBody.appendChild(btn("btn primary", t("gui_errcard_retry"), function () {
            loadRhc().then(function (r) {
              if (state.torn) return;
              state.rhc = r || {};
              paintRhc();
            });
          }));
          return;
        }
        const rhcOn = rhc.state === "enabled";
        rhcPanel.dataset.tone = rhcOn ? "ok" : "warn";
        rhcMeta.textContent = String(rhc.state || "—");
        clear(rhcBody);
        rhcBody.appendChild(el("ul", { class: "stack" },
          el("li", { "data-tone": rhcOn ? "ok" : "warn" },
            el("span", { class: "dot" }),
            el("span", { class: "s", text: t("gui_rp_rhc_state") }),
            el("span", { class: "c", text: String(rhc.state || "—") })),
          el("li", { "data-tone": rhc.pce_report_enabled ? "ok" : "warn" },
            el("span", { class: "dot" }),
            el("span", { class: "s", text: t("gui_rp_rhc_pce") }),
            el("span", { class: "c", text: String(!!rhc.pce_report_enabled) })),
          el("li", { "data-tone": rhc.ven_scopes_enabled ? "ok" : "warn" },
            el("span", { class: "dot" }),
            el("span", { class: "s", text: t("gui_rp_rhc_ven") }),
            el("span", { class: "c", text: String(!!rhc.ven_scopes_enabled) }))));
        rhcBody.appendChild(note(rhcDetailText(rhc)));
        rhcBody.appendChild(btn(rhcOn ? "btn ghost" : "btn danger", t("gui_rp_rhc_enable"), function () { handles.enableRhc(); }));
        if (rhcOn) rhcBody.appendChild(note(t("gui_rhc_enabled_ok")));
        else rhcBody.appendChild(note(t("gui_rhc_use_pu_hint")));
        rhcBody.appendChild(note(t("gui_rp_rhc_reactive")));
      }

      /* dashboard.js:1295-1306 — the confirm is a window.confirm carrying the
       * whole warning; here the same sentence becomes the modal's impact list
       * (XC-08), and OK really POSTs /api/rule_hit_count/enable (header,
       * point 5). `stateLabel` lets a failed rule_hit_count generate reuse
       * this with the state it just observed rather than the panel's own,
       * possibly stale, snapshot. */
      handles.enableRhc = function (stateLabel) {
        const label = stateLabel || (state.rhc && state.rhc.state) || "";
        return modal.confirm(confirmSpec(t("gui_btn_rhc_report"), [
          tf("gui_rhc_needs_enable_confirm", { state: label }),
          t("gui_rp_rhc_i_draft"),
          t("gui_rp_rhc_i_all"),
          t("gui_rp_rhc_i_cli"),
        ], function () {
          return api.post("/api/rule_hit_count/enable", { lang: state.lang }).then(function (res) {
            if (!res || res.ok !== true) {
              toast.crit(tf("gui_rhc_enable_failed", { error: (res && res.error) || "" }));
              return false;
            }
            toast.ok(t("gui_rhc_enabled_ok"));
            return api.reload("rhc_enablement").then(function (rhc) {
              if (!state.torn) { state.rhc = rhc || {}; paintRhc(); }
              return true;
            }).catch(function () { return true; });
          });
        }));
      };
      paintRhc();

      // ── RP-08 report language ──────────────────────────────────────────
      const langPanel = panel("RP-08", t("gui_report_lang_label"));
      const uiLang = (d.status && d.status.language) || "—";
      langPanel.body.appendChild(el("div", { class: "kv" },
        el("span", { text: t("gui_rp_lang_ui") }), el("b", { class: "mono", text: uiLang })));
      const langSel = selectField(LANGS, state.lang, function (v) {
        state.lang = v;
        toast.info(tf("gui_rp_lang_set", { lang: v }));
      });
      langSel.dataset.field = "lang";
      langPanel.body.appendChild(labelled(t("gui_report_lang_label"), langSel));
      langPanel.body.appendChild(note(t("gui_rp_lang_note")));
      aside.appendChild(langPanel);

      // ── RP-09 label lookup ─────────────────────────────────────────────
      const labels = (d.labels && d.labels.labels) || [];
      const labelPanel = panel("RP-09", t("gui_app_label_field"));
      withMeta(labelPanel, tf("gui_rp_labels_n", { n: labels.length }));
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
            toast.info(tf("gui_rp_label_pick", { label: v }));
          });
          labelChips.appendChild(chip);
        });
      }
      labelSearch.addEventListener("input", paintLabels);
      labelPanel.body.appendChild(labelSearch);
      labelPanel.body.appendChild(labelChips);
      labelPanel.body.appendChild(note(t("gui_rp_labels_note")));
      aside.appendChild(labelPanel);
      paintLabels();

      // ── RP-03 progress + async polling ─────────────────────────────────
      const progPanel = panel("RP-03", t("gui_rp_progress_title"));
      progPanel.body.appendChild(note(t("gui_rp_progress_body")));
      const stepList = el("ol", { class: "steplist" });
      [["gui_rp_path_api", "gui_gen_step_fetching"], ["gui_rp_path_csv", "gui_gen_step_parsing"],
        ["gui_rp_path_audit", "gui_gen_step_analysing"], ["gui_rp_path_async", "gui_gen_step_running_bg"],
        ["gui_rp_path_done", "gui_gen_done"]].forEach(function (pair) {
          stepList.appendChild(el("li", null,
            el("span", { class: "s", text: t(pair[1]) }),
            el("span", { class: "r", text: t(pair[0]) })));
        });
      progPanel.body.appendChild(stepList);
      progPanel.body.appendChild(note(tf("gui_rp_poll_note", { interval: 2, deadline: 30 })));
      progPanel.body.appendChild(note(t("gui_rp_async_types")));
      aside.appendChild(progPanel);

      // ── RP-04 partial results ──────────────────────────────────────────
      const partPanel = panel("RP-04", t("gui_rp_partial_title"));
      partPanel.dataset.tone = "warn";
      partPanel.body.appendChild(el("div", { class: "strip", "data-tone": "warn" },
        el("span", { text: tf("gui_toast_report_partial", { formats: "csv, xlsx" }) })));
      partPanel.body.appendChild(note(t("gui_rp_partial_body")));
      partPanel.body.appendChild(el("ul", { class: "stack" },
        el("li", null, el("code", { class: "c", text: "partial" }), el("span", { class: "s", text: t("gui_rp_partial_k1") })),
        el("li", null, el("code", { class: "c", text: "failed_formats" }), el("span", { class: "s", text: t("gui_rp_partial_k2") })),
        el("li", null, el("code", { class: "c", text: "files" }), el("span", { class: "s", text: t("gui_rp_partial_k3") }))));
      partPanel.body.appendChild(note(t("gui_rp_partial_where")));
      aside.appendChild(partPanel);
    });
}

/* S2 teardown. Same shape as overview.mjs/investigate.mjs: self-unsubscribing,
 * fires on the first navigation away from this mount. It does not need to
 * cancel the poll timer or close the progress card itself — stopProgress()
 * (module-level, registered once above) already does that on any route
 * change away from #/reports, and both teardown paths are reachable no
 * matter which one the router fires first. This one additionally destroys
 * the output table handle, closes any drawer/modal this mount left open, and
 * drops this route's palette commands. state.torn also guards
 * refreshReportsList()'s background repaint against firing after teardown. */
function installTeardown(state) {
  const unsubscribe = router.onChange(function (path) {
    if (state.torn) return;
    state.torn = true;
    unsubscribe();
    if (state.tableHandle) {
      try { state.tableHandle.destroy(); } catch (e) { console.error("[reports] table teardown failed", e); }
      state.tableHandle = null;
    }
    drawer.closeAll();
    modal.closeAll();
    palette.setRoute(path);
  });
}

export { mountReports };
