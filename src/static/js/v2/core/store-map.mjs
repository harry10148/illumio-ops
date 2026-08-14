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
// for browse) — real interactivity in these panels is out of scope for this
// task (T5/investigate area) and, when built, will almost certainly issue
// its own dynamic query string rather than replay this fixed example. They
// are transcribed here verbatim anyway, per the global instruction to
// transcribe every GET entry including its query string and invent nothing
// beyond what the yaml states.

export const GET_MAP = {
  // ── plain GET, no payload ──────────────────────────────────────────────
  status: "/api/status",
  dashboard_overview: "/api/dashboard/overview",
  dashboard_queries: "/api/dashboard/queries",
  dashboard_snapshot: "/api/dashboard/snapshot",
  dashboard_audit: "/api/dashboard/audit_summary",
  dashboard_pu: "/api/dashboard/policy_usage_summary",
  reports_list: "/api/reports",
  report_schedules: "/api/report-schedules",
  rhc_enablement: "/api/rule_hit_count/enablement",
  rules: "/api/rules",
  event_catalog: "/api/event-catalog",
  events_viewer: "/api/events/viewer?limit=100",
  rs_status: "/api/rule_scheduler/status",
  rs_rulesets: "/api/rule_scheduler/rulesets",
  rs_schedules: "/api/rule_scheduler/schedules",
  rs_logs: "/api/rule_scheduler/logs",
  settings: "/api/settings",
  alert_plugins: "/api/alert-plugins",
  security: "/api/security",
  tls_status: "/api/tls/status",
  pce_profiles: "/api/pce-profiles",
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
  workload_search: "/api/workloads?name=&ip_address=&hostname=",
  fb_suggest: "/api/filter-objects/suggest?q=web&types=label&limit=10",
  fb_browse: "/api/filter-objects/browse?type=label&offset=0&limit=20",
};
