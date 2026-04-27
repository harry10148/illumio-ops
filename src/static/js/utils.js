/* ─── Helpers ─────────────────────────────────────────────────────── */
const $ = s => document.getElementById(s);
function _csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : '';
}
function _setCsrfToken(token) {
  if (!token) return;
  let meta = document.querySelector('meta[name="csrf-token"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute('name', 'csrf-token');
    document.head.appendChild(meta);
  }
  meta.setAttribute('content', token);
}
async function _refreshCsrfToken() {
  const r = await fetch('/api/csrf-token');
  const data = await r.json();
  _setCsrfToken(data.csrf_token);
  return data.csrf_token;
}
function _withFreshCsrf(opt = {}) {
  const method = (opt.method || 'GET').toUpperCase();
  if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return opt;
  const headers = new Headers(opt.headers || {});
  headers.set('X-CSRF-Token', _csrfToken());
  return { ...opt, headers };
}
const api = async (url, opt = {}) => {
  const parse = async (response) => {
    try {
      return await response.json();
    } catch (_) {
      return { ok: false, error: response.statusText || `HTTP ${response.status}` };
    }
  };
  let r = await fetch(url, _withFreshCsrf(opt));
  let data = await parse(r);
  const method = (opt.method || 'GET').toUpperCase();
  if (r.status === 400 && data && data.code === 'csrf_error' && method !== 'GET') {
    if (data.csrf_token) _setCsrfToken(data.csrf_token);
    else await _refreshCsrfToken();
    r = await fetch(url, _withFreshCsrf(opt));
    data = await parse(r);
  }
  return data;
};
const post = (url, body) => api(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken() }, body: JSON.stringify(body) });
const put = (url, body) => api(url, { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken() }, body: JSON.stringify(body) });
const del = url => api(url, { method: 'DELETE', headers: { 'X-CSRF-Token': _csrfToken() } });
const rv = name => document.querySelector(`input[name="${name}"]:checked`)?.value;
const setRv = (name, val) => { const r = document.querySelector(`input[name="${name}"][value="${val}"]`); if (r) r.checked = true };
const escapeHtml = (unsafe) => {
  return (unsafe == null ? '' : String(unsafe))
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
};
let _editIdx = null; // null = add mode, number = edit mode
let _dashboardQueries = [];

let _translations = {};
let _timezone = 'local';

function _t(key) {
  const value = _translations ? _translations[key] : undefined;
  if (typeof value === 'string' && value.trim() !== '') return value;
  return `[MISSING:${key}]`;
}

function _tzOffsetHours() {
  const tz = _timezone || 'local';
  if (!tz || tz === 'UTC') return 0;
  if (tz === 'local') return -(new Date().getTimezoneOffset() / 60);
  const m = tz.match(/^UTC([+-])(\d+(?:\.\d+)?)$/);
  if (!m) return 0;
  return parseFloat(m[1] + m[2]);
}

function _detectBrowserTimezone() {
  const offsetHours = -(new Date().getTimezoneOffset() / 60);
  if (offsetHours === 0) return 'UTC';
  const sign = offsetHours > 0 ? '+' : '-';
  const abs = Math.abs(offsetHours);
  return `UTC${sign}${abs % 1 === 0 ? abs : abs}`;
}
function _utcToLocal(utcHour) {
  const off = _tzOffsetHours();
  return Math.floor(((utcHour + off) % 24 + 24) % 24);
}
function _localToUtc(localHour) {
  const off = _tzOffsetHours();
  return Math.floor(((localHour - off) % 24 + 24) % 24);
}
function _tzDisplayLabel() {
  return (_timezone && _timezone !== 'local') ? _timezone : 'Local';
}

const _TZ_OPTIONS = [
  ['local','Local (Server Time)'],
  ['UTC','UTC'],
  ['UTC-12','UTC-12'],['UTC-11','UTC-11'],['UTC-10','UTC-10'],['UTC-9','UTC-9'],
  ['UTC-8','UTC-8'],['UTC-7','UTC-7'],['UTC-6','UTC-6'],['UTC-5','UTC-5'],
  ['UTC-4','UTC-4'],['UTC-3','UTC-3'],['UTC-2','UTC-2'],['UTC-1','UTC-1'],
  ['UTC+1','UTC+1'],['UTC+2','UTC+2'],['UTC+3','UTC+3'],['UTC+4','UTC+4'],
  ['UTC+5','UTC+5'],['UTC+5.5','UTC+5.5'],['UTC+6','UTC+6'],['UTC+7','UTC+7'],
  ['UTC+8','UTC+8'],['UTC+9','UTC+9'],['UTC+9.5','UTC+9.5'],['UTC+10','UTC+10'],
  ['UTC+11','UTC+11'],['UTC+12','UTC+12']
];

function populateTzSelect(selectId, selectedValue) {
  const sel = $(selectId);
  if (!sel) return;
  const val = selectedValue || _timezone || 'local';
  sel.innerHTML = _TZ_OPTIONS.map(([v, label]) =>
    `<option value="${v}"${v === val ? ' selected' : ''}>${label}</option>`
  ).join('');
}

const UI_PREF_KEYS = {
  themeMode: 'illumio_gui_theme_mode',
  density: 'illumio_gui_density'
};

function getStoredThemeMode() {
  const mode = localStorage.getItem(UI_PREF_KEYS.themeMode) || 'auto';
  return ['auto', 'dark', 'light'].includes(mode) ? mode : 'auto';
}

function getStoredDensity() {
  const density = localStorage.getItem(UI_PREF_KEYS.density) || 'compact';
  return ['compact', 'comfortable'].includes(density) ? density : 'compact';
}

function applyThemeMode(mode) {
  const preferLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
  const resolved = mode === 'auto'
    ? (preferLight ? 'light' : 'dark')
    : mode;
  document.documentElement.setAttribute('data-theme', resolved);
  const metaTheme = document.querySelector('meta[name="theme-color"]');
  if (metaTheme) metaTheme.setAttribute('content', resolved === 'light' ? '#F8FAFC' : '#0F172A');
  const sel = $('ui-theme-mode');
  if (sel) sel.value = mode;
}

function applyDensity(density) {
  document.documentElement.setAttribute('data-density', density);
  const sel = $('ui-density');
  if (sel) sel.value = density;
}

function initUiPreferences() {
  applyThemeMode(getStoredThemeMode());
  applyDensity(getStoredDensity());
}

function updateUrlState(key, value) {
  try {
    const u = new URL(window.location.href);
    if (!value) u.searchParams.delete(key);
    else u.searchParams.set(key, value);
    history.replaceState({}, '', u.toString());
  } catch (_) { }
}

function onUiThemeModeChange(mode) {
  localStorage.setItem(UI_PREF_KEYS.themeMode, mode);
  applyThemeMode(mode);
}

function onUiDensityChange(density) {
  localStorage.setItem(UI_PREF_KEYS.density, density);
  applyDensity(density);
}

if (window.matchMedia) {
  const media = window.matchMedia('(prefers-color-scheme: light)');
  media.addEventListener('change', () => {
    if (getStoredThemeMode() === 'auto') {
      applyThemeMode('auto');
    }
  });
}

function formatDateZ(utcString) {
  if (!utcString) return "";
  let d = new Date(utcString);
  if (isNaN(d.getTime())) {
    if (!utcString.endsWith('Z')) {
      d = new Date(utcString + 'Z');
    }
  }
  if (isNaN(d.getTime())) return utcString;

  let targetDate = d;
  if (_timezone !== 'local' && _timezone.startsWith('UTC')) {
    let offsetStr = _timezone.replace('UTC', '');
    let offsetHours = parseFloat(offsetStr) || 0;
    let ms = d.getTime() + (offsetHours * 3600000);
    targetDate = new Date(ms);
    const pad = n => n.toString().padStart(2, '0');
    return `${targetDate.getUTCFullYear()}-${pad(targetDate.getUTCMonth() + 1)}-${pad(targetDate.getUTCDate())} ${pad(targetDate.getUTCHours())}:${pad(targetDate.getUTCMinutes())}:${pad(targetDate.getUTCSeconds())}`;
  } else {
    const pad = n => n.toString().padStart(2, '0');
    return `${targetDate.getFullYear()}-${pad(targetDate.getMonth() + 1)}-${pad(targetDate.getDate())} ${pad(targetDate.getHours())}:${pad(targetDate.getMinutes())}:${pad(targetDate.getSeconds())}`;
  }
}

let _labelDimensions = {
  'role': { bg: '#ce93d8', fg: '#ffffff' },
  'app': { bg: '#42a5f5', fg: '#ffffff' },
  'env': { bg: '#26a69a', fg: '#ffffff' },
  'loc': { bg: '#857ad6', fg: '#ffffff' }
};

function sortLabels(labels) {
  if (!labels || !labels.length) return [];
  const order = { 'role': 1, 'app': 2, 'env': 3, 'loc': 4 };
  return labels.slice().sort((a, b) => {
    const keyA = a.key.toLowerCase();
    const keyB = b.key.toLowerCase();
    const rankA = order[keyA] || 99;
    const rankB = order[keyB] || 99;
    if (rankA !== rankB) return rankA - rankB;
    return keyA.localeCompare(keyB);
  });
}

function renderLabelsHtml(labels) {
  if (!labels || !labels.length) return '';
  return sortLabels(labels).map(l => {
    const cMap = _labelDimensions[l.key] || { bg: '#e1ecf4', fg: '#2c5e77' };
    const cssDef = `background:${cMap.bg};color:${cMap.fg};padding:1px 4px;border-radius:4px;font-size:9px;margin-right:2px;display:inline-block;white-space:nowrap;margin-top:2px;`;
    let classStr = 'lbl';
    if (l.key === 'Quarantine') classStr += ' lbl-quarantine';
    return `<span class="${classStr}" style="${cssDef}">${escapeHtml(l.key)}:${escapeHtml(l.value)}</span>`;
  }).join('');
}

let _activePopover = null;

function showCellPopover(event, title, items) {
  event.stopPropagation();
  if (_activePopover) {
    _activePopover.remove();
    _activePopover = null;
  }

  const pop = document.createElement('div');
  pop.className = 'cell-popover';

  let html = `<h4>${escapeHtml(title)} (${items.length} ITEMS)</h4><ul>`;
  items.forEach(it => { html += `<li>${escapeHtml(it)}</li>`; });
  html += '</ul>';

  pop.innerHTML = html;
  document.body.appendChild(pop);

  const rect = event.currentTarget.getBoundingClientRect();
  const popRect = pop.getBoundingClientRect();

  let top = rect.bottom + window.scrollY + 5;
  let left = rect.left + window.scrollX;

  // Ensure it doesn't go off screen
  if (left + popRect.width > window.innerWidth) {
    left = window.innerWidth - popRect.width - 20;
  }
  if (top + popRect.height > window.innerHeight + window.scrollY) {
    top = rect.top + window.scrollY - popRect.height - 5;
  }

  pop.style.top = top + 'px';
  pop.style.left = left + 'px';

  _activePopover = pop;
}

document.addEventListener('click', function (e) {
  if (_activePopover && !_activePopover.contains(e.target)) {
    _activePopover.remove();
    _activePopover = null;
  }
});

async function init() {
  await loadTranslations();
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  const validTabs = ['dashboard', 'traffic-workload', 'events', 'rules', 'reports', 'settings', 'rule-scheduler'];
  const initialTab = (tab && validTabs.includes(tab)) ? tab : 'dashboard';
  switchTab(initialTab, false);
  const qtab = params.get('qtab');
  if (qtab && ['traffic', 'workloads', 'legacy'].includes(qtab)) {
    switchQTab(qtab, false);
  }
  // Refresh dashboard status every 30s
  setInterval(() => { if (document.querySelector('.tab.active[data-tab="dashboard"]')) loadDashboard(); }, 30000);
  setInterval(() => { if (document.querySelector('.tab.active[data-tab="events"]')) loadEventViewer(true); }, 45000);
}

document.addEventListener('DOMContentLoaded', init);

function hideAll() {
  // Helper to close popovers when clicking outside
}

async function loadTranslations() {
  const init = window._INIT_TRANSLATIONS;
  if (init && 'sched_enabled_short' in init && 'status_ok' in init) {
    _translations = init;
  } else {
    _translations = await api('/api/ui_translations');
  }
  applyI18n(document);
  initTableResizers();
}

window.i18nApply = function(root) { applyI18n(root); };

function applyI18n(root = document) {
  const scope = root && root.querySelectorAll ? root : document;
  const nodes = [];
  if (scope !== document && scope.hasAttribute) nodes.push(scope);
  nodes.push(...scope.querySelectorAll('[data-i18n],[data-i18n-html],[data-i18n-placeholder],[data-i18n-title]'));

  nodes.forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key && _translations[key]) {
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.type === 'button' || el.type === 'submit') el.value = _translations[key];
        else if (el.placeholder !== undefined) el.placeholder = _translations[key];
      } else {
        const icon = el.querySelector('svg');
        if (icon) {
          const textNodes = Array.from(el.childNodes).filter(n => n.nodeType === Node.TEXT_NODE);
          if (textNodes.length) textNodes[textNodes.length - 1].textContent = ' ' + _translations[key];
          else el.appendChild(document.createTextNode(' ' + _translations[key]));
        } else {
          el.textContent = _translations[key];
        }
      }
    }

    const htmlKey = el.getAttribute('data-i18n-html');
    if (htmlKey && _translations[htmlKey]) {
      el.innerHTML = _translations[htmlKey];
    }

    const placeholderKey = el.getAttribute('data-i18n-placeholder');
    if (placeholderKey && _translations[placeholderKey] && el.placeholder !== undefined) {
      el.placeholder = _translations[placeholderKey];
    }

    const titleKey = el.getAttribute('data-i18n-title');
    if (titleKey && _translations[titleKey]) {
      el.title = _translations[titleKey];
    }
  });
}

function initTableResizers() {
  document.querySelectorAll('.rule-table').forEach(table => {
    const ths = table.querySelectorAll('th');
    ths.forEach(th => {
      if (th.querySelector('.resizer')) return;
      const resizer = document.createElement('div');
      resizer.classList.add('resizer');
      th.appendChild(resizer);
      let startX, startWidth;
      resizer.addEventListener('mousedown', function (e) {
        startX = e.pageX;
        startWidth = th.offsetWidth;
        document.body.style.cursor = 'col-resize';
        const onMouseMove = (e) => {
          const newWidth = startWidth + (e.pageX - startX);
          th.style.width = Math.max(newWidth, 30) + 'px';
        };
        const onMouseUp = () => {
          document.body.style.cursor = 'default';
          document.removeEventListener('mousemove', onMouseMove);
          document.removeEventListener('mouseup', onMouseUp);
        };
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
      });
    });
  });
}

let _toastTimer = null;
function toast(msg, type) {
  // type: 'err'|'warn'|'info' or falsy for success
  const t = $('toast');
  const icons = { err: '✕', warn: '⚠', info: 'ℹ' };
  const cls = type === 'err' ? ' err' : type === 'warn' ? ' warn' : type === 'info' ? ' info' : '';
  t.innerHTML = `<span class="toast-icon">${icons[type] || '✓'}</span><span>${escapeHtml(msg)}</span><button class="toast-close" onclick="this.parentElement.className='toast'" aria-label="Close">✕</button>`;
  t.className = 'toast' + cls + ' show';
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => t.className = 'toast', 4000);
}
function dlog(msg) { const l = $('d-log'); l.textContent += '\n[' + new Date().toLocaleTimeString() + '] ' + msg; l.scrollTop = l.scrollHeight }
function slog(msg) { const l = $('s-log'); if (l) { l.textContent += '\n[' + new Date().toLocaleTimeString() + '] ' + msg; l.scrollTop = l.scrollHeight } }
function alog(msg) { const l = $('a-log'); l.textContent += '\n' + msg; l.scrollTop = l.scrollHeight }
