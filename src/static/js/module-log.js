// ═══ Module Log Viewer ═══
let _mlCurrentModule = null;
let _mlPrevFocus = null;

function _mlEscHandler(e) { if (e.key === 'Escape') mlClose(); }

function mlOpen(moduleName) {
  hdrMenuClose();
  _mlCurrentModule = moduleName || null;
  const modal = $('ml-modal');
  if (!modal) return;
  _mlPrevFocus = document.activeElement;
  modal.style.display = 'flex';
  // Keyboard access: move focus into the dialog and allow Escape to close.
  const sel = $('ml-module-select');
  if (sel) sel.focus();
  document.addEventListener('keydown', _mlEscHandler);
  mlLoadModules().then(() => {
    if (moduleName) {
      const s = $('ml-module-select');
      if (s) s.value = moduleName;
    }
    mlLoadLogs();
  });
}

function mlClose() {
  const modal = $('ml-modal');
  if (modal) modal.style.display = 'none';
  document.removeEventListener('keydown', _mlEscHandler);
  if (_mlPrevFocus && typeof _mlPrevFocus.focus === 'function') _mlPrevFocus.focus();
  _mlPrevFocus = null;
}

// Close on backdrop click
document.addEventListener('DOMContentLoaded', () => {
  const modal = $('ml-modal');
  if (modal) modal.addEventListener('click', e => { if (e.target === modal) mlClose(); });
});

async function mlLoadModules() {
  try {
    const res = await fetch('/api/logs');
    if (!res.ok) return;
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
      const label = (key && _t(key)) || m.label || m.name;
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
  out.textContent = _t('gui_ml_loading');
  try {
    const res = await fetch(`/api/logs/${mod}?n=200`);
    if (!res.ok) { out.textContent = _t('gui_ml_error_prefix') + ': HTTP ' + res.status; return; }
    const data = await res.json();
    const entries = data.entries || [];
    if (!entries.length) {
      out.textContent = _t('gui_ml_empty');
      return;
    }
    const lines = [];
    for (let i = entries.length - 1; i >= 0; i--) {
      const e = entries[i];
      lines.push(`${e.ts} [${e.level}] ${e.msg}`);
    }
    out.textContent = lines.join('\n');
  } catch (e) {
    out.textContent = _t('gui_ml_error_prefix') + ': ' + e.message;
  }
}
