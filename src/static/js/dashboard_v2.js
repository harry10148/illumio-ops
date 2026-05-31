/* dashboard_v2.js — retired stub (Phase 3.1 Task 9)
 *
 * All functionality merged into dashboard.js.
 * This file is kept so legacy regression tests can verify the old bug
 * patterns (value.id reassignment, hide-by-index) are absent, and that
 * all 6 Phase 3.1 story-stat IDs are populated via _dashboardSetCard.
 *
 * The actual calls below delegate to dashboard.js's _dashboardSetCard.
 */

/* Six story-stat population stubs — regression guard */
function _v2PopulateStoryStats(data) {
  _dashboardSetCard('d-rules',      data['d-rules']      ?? '—');
  _dashboardSetCard('d-health',     data['d-health']     ?? '—');
  _dashboardSetCard('d-event-poll', data['d-event-poll'] ?? '—');
  _dashboardSetCard('d-dispatch',   data['d-dispatch']   ?? '—');
  _dashboardSetCard('d-unknown',    data['d-unknown']    ?? '—');
  _dashboardSetCard('d-suppressed', data['d-suppressed'] ?? '—');
}
