/* ─── Actions ─────────────────────────────────────────────────────── */
async function runAction(name) {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] Running ' + name + '...';
  const r = await post('/api/actions/' + name, {});
  alog(r.output || 'Done.');
  if (name === 'best-practices') { loadRules(); loadDashboard() }
  toast('✅ ' + name + ' completed');
}
async function runDebug() {
  $('a-log').textContent = '[' + new Date().toLocaleTimeString() + '] Running debug mode...';
  const r = await post('/api/actions/debug', { mins: $('a-debug-mins').value, pd_sel: $('a-debug-pd').value });
  alog(r.output || 'Done.');
  toast('✅ Debug completed');
}

/* ─── Init ────────────────────────────────────────────────────────── */
async function stopGui() {
  if (!confirm('Stop the Web GUI server? The browser page will close.')) return;
  try { await post('/api/shutdown', {}); } catch (e) { }
  document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:12px"><h1 style="color:var(--accent2)">Web GUI Stopped</h1><p style="color:var(--dim)">You may close this tab. Restart from CLI or use --gui.</p></div>';
}

