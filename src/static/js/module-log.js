// ═══ Module Log Viewer ═══
let _mlCurrentModule = null;

function mlOpen(moduleName) {
  _mlCurrentModule = moduleName || null;
  const modal = $('ml-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  mlLoadModules().then(() => {
    if (moduleName) {
      const sel = $('ml-module-select');
      if (sel) sel.value = moduleName;
    }
    mlLoadLogs();
  });
}

function mlClose() {
  const modal = $('ml-modal');
  if (modal) modal.style.display = 'none';
}

// Close on backdrop click
document.addEventListener('DOMContentLoaded', () => {
  const modal = $('ml-modal');
  if (modal) modal.addEventListener('click', e => { if (e.target === modal) mlClose(); });
});

async function mlLoadModules() {
  try {
    const res = await fetch('/api/logs');
    const data = await res.json();
    const sel = $('ml-module-select');
    if (!sel) return;
    const modules = data.modules || [];
    // Rebuild options via DOM to keep text safe and allow data-i18n.
    while (sel.firstChild) sel.removeChild(sel.firstChild);
    modules.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m.name;
      const key = m.i18n_key || '';
      const label = (key && _translations[key]) || m.label || m.name;
      const count = m.count ? ' (' + m.count + ')' : '';
      opt.textContent = label + count;
      if (key) opt.setAttribute('data-i18n', key);
      sel.appendChild(opt);
    });
    if (_mlCurrentModule) sel.value = _mlCurrentModule;
  } catch (e) { /* ignore */ }
}

async function mlLoadLogs() {
  const sel = $('ml-module-select');
  const out = $('ml-log-output');
  if (!sel || !out) return;
  const mod = sel.value;
  _mlCurrentModule = mod;
  out.textContent = 'Loading...';
  try {
    const res = await fetch(`/api/logs/${mod}?n=200`);
    const data = await res.json();
    const entries = data.entries || [];
    if (!entries.length) {
      out.textContent = 'No log entries yet.';
      return;
    }
    const lines = [];
    for (let i = entries.length - 1; i >= 0; i--) {
      const e = entries[i];
      lines.push(`${e.ts} [${e.level}] ${e.msg}`);
    }
    out.textContent = lines.join('\n');
  } catch (e) {
    out.textContent = 'Error: ' + e.message;
  }
}
