// store-map.mjs — snapshot id -> real backend endpoint.
//
// This is a line-by-line transcription of every GET entry in
// design/v2/tools/endpoints.yaml (the single source of truth — do not add,
// remove, or reshape an entry here without a matching change there first).
// POST entries in that file (traffic_search, top10) are intentionally
// excluded: per the plan, areas call api.post(path, body) directly with the
// path/body documented at the call site, rather than routing POST through
// this id-keyed map.
//
// Each value is either:
//   - a literal path string (including any query string, verbatim from the
//     yaml), or
//   - a function `(params) => path` for the three entries whose real path
//     depends on a value the yaml itself only resolves at snapshot-capture
//     time (its `path_from` field, e.g. "rs_rulesets.items[0].id").
//
// ── The three `path_from` entries ──────────────────────────────────────
// endpoints.yaml resolves `path_from` by running the *previous* GET in the
// same capture pass and pulling one field out of its response
// (`resolve_path_from()` in capture_snapshots.py) — a capture-time-only
// mechanism with no runtime equivalent in this app. There is no "first
// ruleset" or "first schedule" concept a live page can default to, so the
// only faithful option is to require the caller to supply the value it
// already has in hand (e.g. an area that just rendered a ruleset row knows
// that row's id). Decision: keep these three ids in GET_MAP, but make each
// value a function that reads its parameter out of `params` and interpolates
// it into the path — this is what the brief's Step 1 calls "由呼叫端帶參數"
// (`api.load("rs_ruleset_detail", { rs_id })`). The parameter key names below
// are the exact Flask route variable names (`<rs_id>`, `<schedule_id>`,
// `<module_name>`), not a generic "id", so a caller reading this file can see
// directly which value each route wants without cross-referencing the yaml.
//   - rs_ruleset_detail:   params.rs_id       -> /api/rule_scheduler/rulesets/<rs_id>
//   - report_sched_history: params.schedule_id -> /api/report-schedules/<schedule_id>/history
//   - module_log_sample:    params.module_name -> /api/logs/<module_name>
//
// ── The three GET entries filed under the yaml's "POST" section ─────────
// workload_search, fb_suggest, and fb_browse have method: GET in the yaml
// despite sitting under its "── POST ──" comment banner (the banner groups
// them with traffic_search/top10 because they were captured together as
// interactive-panel endpoints, not because they share a method). Per the
// yaml's own comments these three were captured with one fixed example query
// string apiece (an empty workload search, "q=web" for suggest, "type=label"
// for browse) — a capture-time example, not a runtime path. Only
// workload_search survives here, as a function of its caller's parameters;
// the two fb_* ids are gone (see the note below).
//
// ── Task 5 (investigate area): two of those fixed example query strings
//    become parameterised ────────────────────────────────────────────────
// The sentence above predicted this exactly ("when built, will almost
// certainly issue its own dynamic query string"). #/investigate/workloads
// searches by name/ip_address/hostname and #/investigate/events runs a real
// three-level catalogue cascade plus offset paging, so `workload_search` and
// `events_viewer` are now `(params) => path` functions of the same shape the
// three `path_from` entries already use.
//
// Neither the endpoint nor the yaml's captured example changes: called with
// no params each function returns its yaml path byte for byte
// ("/api/workloads?name=&ip_address=&hostname=" and
// "/api/events/viewer?limit=100"), so the id -> endpoint mapping this file
// transcribes is untouched — only the query string a CALLER may now vary is
// new. The parameter names are the Flask route's own request.args names
// (actions.py:218-263 api_search_workloads reads name/hostname/ip_address/
// max_results; events.py:24-52 api_events_viewer reads mins/limit/offset/
// search/category/type_group/event_type), so a caller reading this file sees
// which value each query wants without cross-referencing the route.
// ── fb_suggest / fb_browse: removed outright (2026-08-17) ───────────────
// Those two entries were the captured example query strings —
// "?q=web&types=label&limit=10" and "?type=label&offset=0&limit=20" — and
// the object filter selector was wired to them literally, which is how the
// shipped bar came to search one captured page of labels for every category
// and every keystroke. The bar now issues its own query strings (one per
// keystroke, per category opened, plus type=_totals), built in
// core/filter-objects.mjs, so there is no id-keyed path left to map: an
// entry here can only carry ONE query string, and these endpoints need a
// different one on every call. They remain in endpoints.yaml because that
// file is the frozen snapshot-capture manifest and the captures were real;
// tests/test_v2_coverage_live.py records this as the one deliberate
// asymmetry between the two files.

/**
 * qs(params, keys) -> query string over `keys`, in the order given.
 * A key whose value is null/undefined is emitted as an empty value (the
 * shipping GUI does the same: quarantine.js:518-534 always sends all three
 * workload fields, empty or not, and both routes treat "" as "no filter").
 */
function qs(params, keys) {
  const p = new URLSearchParams();
  const src = params || {};
  keys.forEach(function (k) {
    const v = src[k];
    p.set(k, v === null || v === undefined ? "" : String(v));
  });
  return p.toString();
}

export const GET_MAP = {
  // ── plain GET, no payload ──────────────────────────────────────────────
  status: "/api/status",
  dashboard_overview: "/api/dashboard/overview",
  dashboard_queries: "/api/dashboard/queries",
  dashboard_snapshot: "/api/dashboard/snapshot",
  dashboard_audit: "/api/dashboard/audit_summary",
  dashboard_pu: "/api/dashboard/policy_usage_summary",
  reports_list: "/api/reports",
  // v3 alert records (3A): the inbox list, one record, and the flow query a
  // traffic/bandwidth alert's rule rebuilds (spec §4a/§4b).
  alerts(params) {
    const p = params || {};
    return "/api/alerts?" + qs({ page: p.page || 1, page_size: p.page_size || 4, status: p.status || "", type: p.type || "" },
      ["page", "page_size", "status", "type"]);
  },
  alert_detail(params) { return "/api/alerts/" + encodeURIComponent(params.id); },
  alert_traffic_query(params) { return "/api/alerts/" + encodeURIComponent(params.id) + "/traffic_query"; },
  report_schedules: "/api/report-schedules",
  rhc_enablement: "/api/rule_hit_count/enablement",
  rules: "/api/rules",
  event_catalog: "/api/event-catalog",
  // Parameterised — see the "Task 5" note in the header. No params reproduces
  // the yaml's captured path exactly: "/api/events/viewer?limit=100".
  events_viewer(params) {
    if (!params) return "/api/events/viewer?limit=100";
    return "/api/events/viewer?" + qs(params,
      ["mins", "limit", "offset", "search", "category", "type_group", "event_type"]);
  },
  rs_status: "/api/rule_scheduler/status",
  rs_rulesets: "/api/rule_scheduler/rulesets",
  rs_schedules: "/api/rule_scheduler/schedules",
  rs_logs: "/api/rule_scheduler/logs",
  settings: "/api/settings",
  alert_plugins: "/api/alert-plugins",
  security: "/api/security",
  tls_status: "/api/tls/status",
  labels: "/api/labels",
  logs_index: "/api/logs",
  ui_translations: "/api/ui_translations",

  // ── SIEM / cache endpoints ───────────────────────────────────────────
  siem_status: "/api/siem/status",
  siem_destinations: "/api/siem/destinations",
  siem_forwarder: "/api/siem/forwarder",
  siem_dlq: "/api/siem/dlq",
  cache_status: "/api/cache/status",
  cache_lag: "/api/cache/lag",
  cache_health: "/api/cache/health",
  cache_throughput: "/api/cache/throughput",
  cache_settings: "/api/cache/settings",
  archive_status: "/api/cache/archive/status",

  // ── path_from entries — caller supplies the id, see header comment ────
  rs_ruleset_detail(params) {
    return "/api/rule_scheduler/rulesets/" + encodeURIComponent((params || {}).rs_id);
  },
  report_sched_history(params) {
    return "/api/report-schedules/" + encodeURIComponent((params || {}).schedule_id) + "/history";
  },
  module_log_sample(params) {
    return "/api/logs/" + encodeURIComponent((params || {}).module_name);
  },

  // ── GET entries filed under the yaml's POST banner — see header comment ─
  // Parameterised — see the "Task 5" note in the header. No params reproduces
  // the yaml's captured path exactly: "/api/workloads?name=&ip_address=&hostname=".
  workload_search(params) {
    return "/api/workloads?" + qs(params, ["name", "ip_address", "hostname"]);
  },

};
