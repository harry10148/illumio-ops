/* ─── Tabs ────────────────────────────────────────────────────────── */
function switchTab(id, updateUrl = true) {
  document.querySelectorAll('.tab').forEach((tabBtn) => {
    const active = tabBtn.dataset.tab === id;
    tabBtn.classList.toggle('active', active);
    tabBtn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  $('p-' + id).classList.add('active');
  if (id === 'rules') loadRules();
  if (id === 'settings') loadSettings();
  if (id === 'dashboard') loadDashboard();
  if (id === 'reports') loadReports();
  if (id === 'rule-scheduler') rsLoadTab();
  if (updateUrl) updateUrlState('tab', id);
}
