/* ─── Skeleton helpers for tab switch (Phase 1 quick win) ────────── */
// Uses createElement + replaceChildren — no innerHTML, no XSS surface.
// Targets '.data-area' inside each panel; silently no-ops if not present.
// Add class="data-area" to a panel's content container to activate.
function showSkeletonCards(containerSelector, count = 3) {
  const el = document.querySelector(containerSelector);
  if (!el) return;
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < count; i++) {
    const div = document.createElement('div');
    div.className = 'skeleton';
    if (i % 3 === 0) div.classList.add('skeleton-card');
    fragment.appendChild(div);
  }
  el.replaceChildren(fragment);
}

function hideSkeletonCards(containerSelector) {
  // No-op hook: the caller's render flow replaces skeleton divs with real
  // content via replaceChildren/append. Provided for explicit cleanup paths.
  void containerSelector;
}

/* ─── Tabs ────────────────────────────────────────────────────────── */
function switchTab(id, updateUrl = true) {
  document.querySelectorAll('.tab').forEach((tabBtn) => {
    const active = tabBtn.dataset.tab === id;
    tabBtn.classList.toggle('active', active);
    tabBtn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  $('p-' + id).classList.add('active');
  if (id === 'rules') { showSkeletonCards('#p-rules .data-area', 3); loadRules(); }
  if (id === 'settings') loadSettings();
  if (id === 'dashboard') { showSkeletonCards('#p-dashboard .data-area', 3); loadDashboard(); }
  if (id === 'traffic-workload') {
    if (typeof ensureTrafficWorkloadLayout === 'function') ensureTrafficWorkloadLayout();
    if (typeof loadDashboardQueries === 'function') { showSkeletonCards('#p-traffic-workload .data-area', 3); loadDashboardQueries(); }
  }
  if (id === 'events') { showSkeletonCards('#p-events .data-area', 3); loadEventViewer(true); }
  if (id === 'reports') { showSkeletonCards('#p-reports .data-area', 3); loadReports(); }
  if (id === 'rule-scheduler') rsLoadTab();
  if (typeof updateBulkBar === 'function') updateBulkBar();
  if (updateUrl) updateUrlState('tab', id);
}
