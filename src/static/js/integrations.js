// Integrations tab: switcher + shared helpers + per-pane renderers.
(function () {
  'use strict';

  // Escape user-provided text before inserting into markup.
  // Used throughout this module — NEVER inline user data without this.
  function escapeAttr(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
  window.escapeAttr = escapeAttr;

  function integrationsSwitch(name) {
    ['overview', 'cache', 'siem', 'dlq'].forEach(function (n) {
      var pane = document.getElementById('it-pane-' + n);
      if (pane) pane.style.display = (n === name) ? '' : 'none';
    });
    document.querySelectorAll('#p-integrations .sub-tab').forEach(function (btn) {
      // After M1 (CSP) the buttons use data-action/data-args instead of onclick.
      var args = [];
      try { args = JSON.parse(btn.getAttribute('data-args') || '[]'); } catch (_) { args = []; }
      btn.classList.toggle('active', args[0] === name);
    });
    if (name === 'overview') renderOverview();
    else if (name === 'cache') renderCache();
    else if (name === 'siem') renderSiem();
    else if (name === 'dlq') renderDlq();
  }
  window.integrationsSwitch = integrationsSwitch;

  // Hook into the project's existing switchTab to auto-render Overview on
  // first visit. integrations.js loads BEFORE tabs.js (which defines
  // switchTab), so an immediate wrap would no-op. Try once now, otherwise
  // wrap on DOMContentLoaded — by then tabs.js has parsed.
  function wrapSwitchTab() {
    var originalSwitchTab = window.switchTab;
    if (typeof originalSwitchTab !== 'function') return false;
    if (originalSwitchTab.__integrationsWrapped) return true;
    var wrapped = function (name) {
      var r = originalSwitchTab.apply(this, arguments);
      if (name === 'integrations') integrationsSwitch('overview');
      return r;
    };
    wrapped.__integrationsWrapped = true;
    window.switchTab = wrapped;
    return true;
  }
  if (!wrapSwitchTab()) {
    document.addEventListener('DOMContentLoaded', wrapSwitchTab);
  }

  // Placeholder renderers — later tasks replace each body.
  async function renderOverview() {}
  async function renderCache() {}
  async function renderSiem() {}
  async function renderDlq() {}

  // Expose for later tasks.
  window._integrations = {
    renderOverview: function () { return renderOverview(); },
    renderCache: function () { return renderCache(); },
    renderSiem: function () { return renderSiem(); },
    renderDlq: function () { return renderDlq(); },
    setRender: function (name, fn) {
      if (name === 'overview') renderOverview = fn;
      else if (name === 'cache') renderCache = fn;
      else if (name === 'siem') renderSiem = fn;
      else if (name === 'dlq') renderDlq = fn;
    },
  };
})();

// ── Cache sub-tab ────────────────────────────────────────────────────────────
window._integrations.setRender('cache', async function renderCache() {
  var el = document.getElementById('it-pane-cache');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  var stRes, cfgRes, status, s;
  try {
    var results = await Promise.all([
      fetch('/api/cache/status'), fetch('/api/cache/settings')
    ]);
    stRes = results[0]; cfgRes = results[1];
    status = await stRes.json();
    s = await cfgRes.json();
  } catch (err) {
    el.innerHTML = '<p style="color:red">Failed to load cache data: ' + escapeAttr(String(err)) + '</p>';
    return;
  }

  var header = buildCacheStatusCards(status, s);
  var form = buildCacheForm(s);
  el.innerHTML = header + form;
  el.dataset.settings = JSON.stringify(s);
  renderTrafficFilter(s);
  renderTrafficSampling(s);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function buildCacheStatusCards(status, s) {
  var events     = Number(status.events      || 0);
  var trafficRaw = Number(status.traffic_raw || 0);
  var trafficAgg = Number(status.traffic_agg || 0);
  var stateClass = s.enabled ? 'ok' : 'err';
  var stateText  = s.enabled
    ? '<span style="color:var(--success)">✓ ' + escapeAttr(_t('gui_cache_enabled')) + '</span>'
    : '<span style="color:var(--danger)">✗ ' + escapeAttr(_t('gui_cache_disabled')) + '</span>';
  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card card-' + stateClass + '">'
    + '<div class="label" data-i18n="gui_cache_status">Cache Status</div>'
    + '<div class="value" style="font-size:1.05rem;">' + stateText + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_ov_events">events</div>'
    + '<div class="value">' + events.toLocaleString() + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_cache_card_traffic_raw">Traffic Raw</div>'
    + '<div class="value">' + trafficRaw.toLocaleString() + '</div>'
    + '</div>'
    + '<div class="card card-ok">'
    + '<div class="label" data-i18n="gui_cache_card_traffic_agg">Traffic Agg</div>'
    + '<div class="value">' + trafficAgg.toLocaleString() + '</div>'
    + '</div>'
    + '</div>'
    + '<div class="toolbar" style="margin-bottom:16px;">'
    + '<button class="btn btn-sm" data-action="cacheBackfill" data-i18n="gui_backfill">Backfill</button>'
    + '<button class="btn btn-sm" data-action="cacheRetentionNow" data-i18n="gui_retention_now">Retention now</button>'
    + '</div>';
}

function buildCacheForm(s) {
  var dbPath = escapeAttr(s.db_path);
  return '<form id="cache-form">'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_basic">Basic</legend>'
    + '<div class="chk" style="margin-bottom:14px;">'
    + '<label><input type="checkbox" name="enabled"' + (s.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_cache_enabled">Enabled</span></label>'
    + '</div>'
    + '<div class="form-group">'
    + '<label data-i18n="gui_cache_db_path">DB path</label>'
    + '<input name="db_path" value="' + dbPath + '">'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_retention">Retention (days)</legend>'
    + '<div class="form-row-3">'
    + '<div class="form-group"><label data-i18n="gui_ov_events">events</label>'
    + '<input type="number" name="events_retention_days" min="1" value="' + Number(s.events_retention_days || 90) + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_card_traffic_raw">Traffic Raw</label>'
    + '<input type="number" name="traffic_raw_retention_days" min="1" value="' + Number(s.traffic_raw_retention_days || 30) + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_card_traffic_agg">Traffic Agg</label>'
    + '<input type="number" name="traffic_agg_retention_days" min="1" value="' + Number(s.traffic_agg_retention_days || 30) + '"></div>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_polling">Polling (seconds)</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label>events_poll_interval_seconds</label>'
    + '<input type="number" name="events_poll_interval_seconds" min="30" value="' + Number(s.events_poll_interval_seconds || 30) + '"></div>'
    + '<div class="form-group"><label>traffic_poll_interval_seconds</label>'
    + '<input type="number" name="traffic_poll_interval_seconds" min="60" value="' + Number(s.traffic_poll_interval_seconds || 60) + '"></div>'
    + '</div>'
    + '</fieldset>'
    + '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_throughput">Throughput</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label>rate_limit_per_minute</label>'
    + '<input type="number" name="rate_limit_per_minute" min="10" max="500" value="' + Number(s.rate_limit_per_minute || 100) + '"></div>'
    + '<div class="form-group"><label>async_threshold_events</label>'
    + '<input type="number" name="async_threshold_events" min="1" max="10000" value="' + Number(s.async_threshold_events || 1000) + '"></div>'
    + '</div>'
    + '</fieldset>'
    + '<div id="cache-form-extra"></div>'
    + '<div style="display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:8px;">'
    + '<div id="cache-banner" style="flex:1;display:none;"></div>'
    + '<button type="button" class="btn btn-primary" onclick="cacheSave()" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</form>';
}

async function cacheSave() {
  var form = document.getElementById('cache-form');
  var data = Object.fromEntries(new FormData(form));
  var pane = document.getElementById('it-pane-cache');
  var existing = JSON.parse(pane.dataset.settings);
  var payload = Object.assign({}, existing, {
    enabled: form.elements['enabled'].checked,
    db_path: data.db_path,
    events_retention_days: Number(data.events_retention_days),
    traffic_raw_retention_days: Number(data.traffic_raw_retention_days),
    traffic_agg_retention_days: Number(data.traffic_agg_retention_days),
    events_poll_interval_seconds: Number(data.events_poll_interval_seconds),
    traffic_poll_interval_seconds: Number(data.traffic_poll_interval_seconds),
    rate_limit_per_minute: Number(data.rate_limit_per_minute),
    async_threshold_events: Number(data.async_threshold_events),
    traffic_filter: (typeof window.collectTrafficFilter === 'function')
      ? window.collectTrafficFilter() : existing.traffic_filter,
    traffic_sampling: (typeof window.collectTrafficSampling === 'function')
      ? window.collectTrafficSampling() : existing.traffic_sampling,
  });
  var resp = await fetch('/api/cache/settings', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
    body: JSON.stringify(payload),
  });
  var body = await resp.json();
  var banner = document.getElementById('cache-banner');
  if (body.ok) {
    showRestartBanner(banner);
  } else {
    banner.style.display = 'block';
    banner.textContent = 'Validation error:';
    var ul = document.createElement('ul');
    Object.entries(body.errors || {}).forEach(function(entry) {
      var li = document.createElement('li');
      li.textContent = entry[0] + ': ' + entry[1];
      ul.appendChild(li);
    });
    banner.appendChild(ul);
  }
}

function showRestartBanner(target) {
  target.style.display = 'block';
  target.innerHTML = '';
  var wrap = document.createElement('div');
  wrap.className = 'banner';
  var span = document.createElement('span');
  span.setAttribute('data-i18n', 'gui_restart_required_banner');
  span.textContent = 'Settings saved. Restart monitor to apply scheduling changes.';
  var restartBtn = document.createElement('button');
  restartBtn.className = 'btn btn-primary';
  restartBtn.setAttribute('data-i18n', 'gui_restart_monitor_btn');
  restartBtn.textContent = 'Restart Monitor';
  restartBtn.addEventListener('click', function() { doDaemonRestart(restartBtn, span); });
  var dismissBtn = document.createElement('button');
  dismissBtn.className = 'btn';
  dismissBtn.setAttribute('data-i18n', 'gui_dismiss');
  dismissBtn.textContent = 'Dismiss';
  dismissBtn.addEventListener('click', function() { target.style.display = 'none'; });
  wrap.appendChild(span);
  wrap.appendChild(restartBtn);
  wrap.appendChild(dismissBtn);
  target.appendChild(wrap);
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

async function doDaemonRestart(btn, msgSpan) {
  btn.disabled = true;
  var original = btn.textContent;
  btn.textContent = '…';
  try {
    var resp = await fetch('/api/daemon/restart', {method: 'POST', headers: {'X-CSRF-Token': _csrfToken()}});
    var body = await resp.json();
    if (resp.status === 409) {
      msgSpan.textContent = _t('gui_daemon_external_restart_hint');
      msgSpan.removeAttribute('data-i18n');
      btn.style.display = 'none';
      return;
    }
    if (body.ok) {
      btn.textContent = '✓';
      msgSpan.textContent = _t('gui_restart_success');
      msgSpan.removeAttribute('data-i18n');
      setTimeout(function() {
        if (btn.parentElement && btn.parentElement.parentElement) {
          btn.parentElement.parentElement.style.display = 'none';
        }
      }, 1500);
    } else {
      btn.textContent = original;
      btn.disabled = false;
      alert(_t('gui_restart_failed') + ': ' + (body.error || ''));
    }
  } catch (exc) {
    btn.textContent = original;
    btn.disabled = false;
    alert(_t('gui_restart_failed') + ': ' + exc);
  }
}

// Open the Cache Backfill modal with a sensible default (last 7 days).
function cacheBackfill() {
  if (typeof setDateRange === 'function') setDateRange('cb', 7);
  var src = document.getElementById('cb-source');
  if (src) src.value = 'events';
  var result = document.getElementById('cb-result');
  if (result) { result.style.display = 'none'; result.textContent = ''; }
  if (typeof openModal === 'function') openModal('m-cache-backfill');
}

async function submitCacheBackfill() {
  var sourceEl = document.getElementById('cb-source');
  var startEl = document.getElementById('cb-start');
  var endEl = document.getElementById('cb-end');
  var btn = document.getElementById('cb-submit');
  var result = document.getElementById('cb-result');
  var source = (sourceEl && sourceEl.value) || 'events';
  var start = startEl && startEl.value;
  var end = endEl && endEl.value;
  if (!start || !end) {
    if (result) {
      result.style.display = 'block';
      result.style.color = 'var(--danger)';
      result.textContent = (typeof _t === 'function' ? _t('gui_cb_dates_required') : 'Start and end dates are required.');
    }
    return;
  }
  if (btn) btn.disabled = true;
  if (result) {
    result.style.display = 'block';
    result.style.color = 'var(--dim)';
    result.textContent = (typeof _t === 'function' ? _t('gui_cb_running') : 'Running…');
  }
  try {
    var r = await fetch('/api/cache/backfill', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({source: source, since: start, until: end}),
    });
    var body = await r.json().catch(function() { return {}; });
    if (!r.ok) {
      if (result) {
        result.style.color = 'var(--danger)';
        result.textContent = 'Backfill failed: ' + (body.error || r.status);
      }
      return;
    }
    if (result) {
      result.style.color = 'var(--accent2,var(--fg))';
      result.textContent = 'Done — source: ' + source
        + ' · inserted: ' + (body.inserted || 0)
        + ' · duplicates: ' + (body.duplicates || 0)
        + ' · total: ' + (body.total_rows || 0)
        + ' · ' + (body.elapsed_seconds || 0) + 's';
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function cacheRetentionNow() {
  if (!confirm('Run retention purge now? This will delete cache rows older than the configured retention days.')) return;
  var r = await fetch('/api/cache/retention/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
  });
  var body = await r.json().catch(function() { return {}; });
  if (!r.ok) {
    alert('Retention failed: ' + (body.error || r.status));
    return;
  }
  alert('Retention done — events: ' + (body.events || 0)
    + ', traffic_raw: ' + (body.traffic_raw || 0)
    + ', traffic_agg: ' + (body.traffic_agg || 0)
    + ', dead_letter: ' + (body.dead_letter || 0));
}
window.cacheBackfill = cacheBackfill;
window.submitCacheBackfill = submitCacheBackfill;
window.cacheRetentionNow = cacheRetentionNow;

// ── Cache traffic_filter section ────────────────────────────────────────────
function renderTrafficFilter(s) {
  var tf = s.traffic_filter || {};
  var actions   = ['blocked', 'potentially_blocked', 'allowed'];
  var protocols = ['TCP', 'UDP', 'ICMP'];
  var envVals  = (tf.workload_label_env || []).map(escapeAttr).join(',');
  var portVals = escapeAttr((tf.ports || []).map(Number).join(','));
  var ipVals   = (tf.exclude_src_ips || []).map(escapeAttr).join(',');

  var html = '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_traffic_filter">Traffic Filter</legend>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_actions">Actions</label>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;padding:4px 0;">'
    + actions.map(function(a) {
        return '<label style="display:inline-flex;align-items:center;gap:6px;">'
          + '<input type="checkbox" name="tf-action" value="' + escapeAttr(a) + '"'
          + ((tf.actions || []).indexOf(a) >= 0 ? ' checked' : '') + '> '
          + escapeAttr(a) + '</label>';
      }).join('')
    + '</div></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_protocols">Protocols</label>'
    + '<div style="display:flex;gap:12px;flex-wrap:wrap;padding:4px 0;">'
    + protocols.map(function(p) {
        return '<label style="display:inline-flex;align-items:center;gap:6px;">'
          + '<input type="checkbox" name="tf-protocol" value="' + escapeAttr(p) + '"'
          + ((tf.protocols || []).indexOf(p) >= 0 ? ' checked' : '') + '> '
          + escapeAttr(p) + '</label>';
      }).join('')
    + '</div></div>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_workload_env">Workload label env</label>'
    + '<input id="tf-env" value="' + envVals + '" placeholder="prod,staging"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_ports">Ports</label>'
    + '<input id="tf-ports" value="' + portVals + '" placeholder="22,443,..."></div>'
    + '</div>'
    + '<div class="form-group"><label data-i18n="gui_cache_tf_exclude_ips">Exclude src IPs</label>'
    + '<input id="tf-ips" value="' + ipVals + '" placeholder="10.0.0.1,..."></div>'
    + '<div id="tf-validation-hints" style="color:var(--danger);font-size:.8rem;"></div>'
    + '</fieldset>';

  var extra = document.getElementById('cache-form-extra');
  if (extra) extra.innerHTML = html;
}

window.collectTrafficFilter = function () {
  function pick(sel) {
    return Array.from(document.querySelectorAll(sel)).map(function(el) { return el.value; });
  }
  function parse(id) {
    var el = document.getElementById(id);
    return (el ? el.value : '').split(',').map(function(x) { return x.trim(); }).filter(Boolean);
  }
  return {
    actions: pick('input[name="tf-action"]:checked'),
    workload_label_env: parse('tf-env'),
    ports: parse('tf-ports').map(Number).filter(function(n) { return Number.isFinite(n); }),
    protocols: pick('input[name="tf-protocol"]:checked'),
    exclude_src_ips: parse('tf-ips'),
  };
};

function validateIp(s) {
  if (/^(\d{1,3}\.){3}\d{1,3}$/.test(s)) {
    return s.split('.').every(function(o) { return Number(o) <= 255; });
  }
  return /^[\da-fA-F:]+$/.test(s) && s.indexOf(':') >= 0;
}

function validateTrafficFilterHints() {
  var hints = [];
  var ipsEl = document.getElementById('tf-ips');
  var ips = (ipsEl ? ipsEl.value : '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
  ips.forEach(function(ip) { if (!validateIp(ip)) hints.push(_t('gui_err_invalid_ip') + ': ' + ip); });
  var portsEl = document.getElementById('tf-ports');
  var ports = (portsEl ? portsEl.value : '').split(',').map(function(s) { return s.trim(); }).filter(Boolean);
  ports.forEach(function(p) {
    var n = Number(p);
    if (!Number.isInteger(n) || n < 1 || n > 65535) hints.push(_t('gui_err_port_range') + ': ' + p);
  });
  var el = document.getElementById('tf-validation-hints');
  if (el) el.textContent = hints.join(' · ');
}

const _debouncedTrafficFilterHints = window.debounce(function(target) {
  validateTrafficFilterHints();
  setTimeout(() => target.classList.remove('input-loading'), 50);
}, 300);
document.addEventListener('input', function(e) {
  if (e.target && (e.target.id === 'tf-ips' || e.target.id === 'tf-ports')) {
    e.target.classList.add('input-loading');
    _debouncedTrafficFilterHints(e.target);
  }
});

// ── Cache traffic_sampling section ───────────────────────────────────────────
function renderTrafficSampling(s) {
  var ts      = s.traffic_sampling || {};
  var ratio   = Number(ts.sample_ratio_allowed || 1);
  var maxRows = Number(ts.max_rows_per_batch || 200000);
  var html = '<fieldset>'
    + '<legend data-i18n="gui_cache_sec_traffic_sampling">Traffic Sampling</legend>'
    + '<div class="form-row">'
    + '<div class="form-group"><label data-i18n="gui_cache_ts_ratio">sample_ratio_allowed</label>'
    + '<input type="number" id="ts-ratio" min="1" value="' + ratio + '"></div>'
    + '<div class="form-group"><label data-i18n="gui_cache_ts_max_rows">max_rows_per_batch</label>'
    + '<input type="number" id="ts-max" min="1" max="200000" value="' + maxRows + '"></div>'
    + '</div>'
    + '</fieldset>';
  var extra = document.getElementById('cache-form-extra');
  if (extra) extra.insertAdjacentHTML('beforeend', html);
}

window.collectTrafficSampling = function () {
  var ratioEl = document.getElementById('ts-ratio');
  var maxEl = document.getElementById('ts-max');
  return {
    sample_ratio_allowed: Number(ratioEl ? ratioEl.value : 1),
    max_rows_per_batch: Number(maxEl ? maxEl.value : 200000),
  };
};

// ── SIEM sub-tab ─────────────────────────────────────────────────────────────
window._integrations.setRender('siem', async function renderSiem() {
  var el = document.getElementById('it-pane-siem');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  var fw, destsBody, status;
  try {
    var results = await Promise.all([
      fetch('/api/siem/forwarder').then(function(r) { return r.json(); }),
      fetch('/api/siem/destinations').then(function(r) { return r.json(); }),
      fetch('/api/siem/status').then(function(r) { return r.json(); }),
    ]);
    fw = results[0]; destsBody = results[1]; status = results[2];
  } catch (err) {
    el.innerHTML = '<p style="color:red">Failed to load SIEM data: ' + escapeAttr(String(err)) + '</p>';
    return;
  }
  var dests = destsBody.destinations || destsBody || [];

  el.innerHTML = buildSiemForwarderForm(fw) + buildSiemDestinationsSection();

  var tbody = document.getElementById('siem-dest-tbody');
  var perDest = (status && status.per_destination) || {};
  var rows = dests.map(function(d) { return buildSiemRow(d, perDest[d.name] || {}); }).join('');
  tbody.innerHTML = rows || '<tr><td colspan="6" style="color:var(--dim);">(none)</td></tr>';
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function _siemStatusBadge(d, st) {
  if (!d.enabled) {
    return '<span class="status-badge warn"><span class="dot warn"></span>'
      + escapeAttr(_t('gui_siem_status_disabled')) + '</span>';
  }
  if (Number(st.failed || 0) > 0) {
    return '<span class="status-badge err"><span class="dot err"></span>'
      + escapeAttr(_t('gui_siem_status_error')) + '</span>';
  }
  return '<span class="status-badge ok"><span class="dot ok"></span>'
    + escapeAttr(_t('gui_siem_status_healthy')) + '</span>';
}

function buildSiemForwarderForm(fw) {
  return '<section class="rs-glass" style="margin-bottom:16px;">'
    + '<h3 style="color:var(--accent2);margin:0 0 14px;" data-i18n="gui_siem_forwarder">Forwarder</h3>'
    + '<div class="form-row">'
    + '<div class="form-group">'
    + '<label data-i18n="gui_siem_dispatch_tick">dispatch_tick_seconds</label>'
    + '<input type="number" id="siem-tick" min="1" value="' + Number(fw.dispatch_tick_seconds || 10) + '">'
    + '</div>'
    + '<div class="form-group">'
    + '<label data-i18n="gui_siem_dlq_max">dlq_max_per_dest</label>'
    + '<input type="number" id="siem-dlq-max" min="100" value="' + Number(fw.dlq_max_per_dest || 500) + '">'
    + '</div>'
    + '</div>'
    + '<div class="chk" style="margin-bottom:14px;">'
    + '<label><input type="checkbox" id="siem-enabled"' + (fw.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_enabled">Enabled</span></label>'
    + '</div>'
    + '<div style="display:flex;justify-content:flex-end;">'
    + '<button class="btn btn-primary btn-sm" onclick="siemSaveForwarder()" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</section>';
}

function buildSiemDestinationsSection() {
  return '<section class="rs-glass">'
    + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
    + '<h3 style="color:var(--accent2);margin:0;" data-i18n="gui_siem_destinations">Destinations</h3>'
    + '<button class="btn btn-sm" onclick="siemOpenDestModal()" data-i18n="gui_siem_add">+ Add</button>'
    + '</div>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup>'
    + '<col style="width:18%"><col style="width:10%"><col style="width:13%"><col style="width:25%"><col style="width:16%"><col>'
    + '</colgroup>'
    + '<thead><tr>'
    + '<th data-i18n="gui_siem_th_name">Name</th>'
    + '<th data-i18n="gui_siem_th_transport">Transport</th>'
    + '<th data-i18n="gui_siem_th_format">Format</th>'
    + '<th data-i18n="gui_siem_th_endpoint">Endpoint</th>'
    + '<th data-i18n="gui_siem_th_status">Status</th>'
    + '<th data-i18n="gui_siem_th_actions">Actions</th>'
    + '</tr></thead>'
    + '<tbody id="siem-dest-tbody"></tbody>'
    + '</table>'
    + '</div>'
    + '</section>'
    + '<div id="siem-banner" style="margin-top:12px;"></div>'
    + '<div id="siem-modal-host"></div>';
}

function buildSiemRow(d, st) {
  var nameEnc = encodeURIComponent(d.name).replace(/'/g, '%27');
  var dim = d.enabled ? '' : ' <span style="color:var(--dim);font-size:.8rem;">(disabled)</span>';
  return '<tr>'
    + '<td><b>' + escapeAttr(d.name) + '</b>' + dim + '</td>'
    + '<td><code>' + escapeAttr(d.transport) + '</code></td>'
    + '<td><code>' + escapeAttr(d.format) + '</code></td>'
    + '<td title="' + escapeAttr(d.endpoint) + '">' + escapeAttr(d.endpoint) + '</td>'
    + '<td>' + _siemStatusBadge(d, st) + '</td>'
    + '<td style="white-space:nowrap;">'
    + '<button class="btn btn-sm" onclick="siemTestDest(\'' + nameEnc + '\')" data-i18n="gui_siem_test">Test</button> '
    + '<button class="btn btn-sm" onclick="siemOpenDestModal(\'' + nameEnc + '\')" data-i18n="gui_siem_edit">Edit</button> '
    + '<button class="btn btn-sm btn-danger" onclick="siemDeleteDest(\'' + nameEnc + '\')" data-i18n="gui_siem_delete">Delete</button>'
    + '</td>'
    + '</tr>';
}

async function siemSaveForwarder() {
  var payload = {
    enabled: document.getElementById('siem-enabled').checked,
    dispatch_tick_seconds: Number(document.getElementById('siem-tick').value),
    dlq_max_per_dest: Number(document.getElementById('siem-dlq-max').value),
  };
  var resp = await fetch('/api/siem/forwarder', {
    method: 'PUT',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
    body: JSON.stringify(payload),
  });
  var body = await resp.json();
  var banner = document.getElementById('siem-banner');
  if (body.ok) {
    showRestartBanner(banner);
  } else {
    banner.textContent = 'Validation error: ' + JSON.stringify(body.errors || body.error || '');
  }
}

async function siemDeleteDest(nameEnc) {
  var name = decodeURIComponent(nameEnc);
  var confirmMsg = (typeof _t === 'function') ? _t('gui_confirm_delete') : 'Delete this destination?';
  if (!confirm(confirmMsg)) return;
  var r = await fetch('/api/siem/destinations/' + encodeURIComponent(name), {method: 'DELETE', headers: {'X-CSRF-Token': _csrfToken()}});
  if (!r.ok) { alert('Delete failed: HTTP ' + r.status); return; }
  window._integrations.renderSiem();
}

async function siemOpenDestModal(nameEnc) {
  var name = nameEnc ? decodeURIComponent(nameEnc) : null;
  var dest = {
    name: '', enabled: true, transport: 'udp', format: 'cef',
    endpoint: '', tls_verify: true, tls_ca_bundle: '', hec_token: '',
    batch_size: 100, source_types: ['audit', 'traffic'], max_retries: 10
  };
  if (name) {
    try {
      var body = await fetch('/api/siem/destinations').then(function(r) { return r.json(); });
      var all = body.destinations || body || [];
      var found = all.filter(function(d) { return d.name === name; })[0];
      if (found) dest = Object.assign(dest, found);
    } catch (err) {
      // If fetch fails, proceed with default values
      console.warn('Could not load destination data:', err);
    }
  }
  document.getElementById('siem-modal-host').innerHTML = buildDestModal(dest, name);
  siemToggleCondFields();
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

function buildDestModal(dest, editName) {
  var nameVal = escapeAttr(dest.name);
  var endpoint = escapeAttr(dest.endpoint);
  var caBundle = escapeAttr(dest.tls_ca_bundle || '');
  var hecToken = escapeAttr(dest.hec_token || '');
  var readonly = editName ? ' readonly' : '';
  var editAttr = editName ? encodeURIComponent(editName).replace(/'/g, '%27') : '';
  var titleKey = editName ? 'gui_siem_modal_title_edit' : 'gui_siem_modal_title_add';
  var titleText = editName ? 'Edit' : 'Add';
  var sourceTypes = dest.source_types || [];

  function mkOpts(list, cur) {
    return list.map(function(v) {
      return '<option' + (v === cur ? ' selected' : '') + '>' + escapeAttr(v) + '</option>';
    }).join('');
  }

  return '<div class="modal-backdrop" onclick="siemCloseModal(event)">'
    + '<div class="modal" onclick="event.stopPropagation()">'
    + '<h2 data-i18n="' + titleKey + '">' + titleText + ' destination</h2>'
    + '<h3 data-i18n="gui_siem_sec_basic">Basic</h3>'
    + '<label>name: <input id="md-name" value="' + nameVal + '"' + readonly + '></label>'
    + '<label><input type="checkbox" id="md-enabled"' + (dest.enabled ? ' checked' : '') + '>'
    + ' <span data-i18n="gui_siem_enabled">Enabled</span></label>'
    + '<div>source_types:'
    + ' <label><input type="checkbox" name="md-st" value="audit"' + (sourceTypes.indexOf('audit') >= 0 ? ' checked' : '') + '> audit</label>'
    + ' <label><input type="checkbox" name="md-st" value="traffic"' + (sourceTypes.indexOf('traffic') >= 0 ? ' checked' : '') + '> traffic</label>'
    + '</div>'
    + '<h3 data-i18n="gui_siem_sec_transport">Transport</h3>'
    + '<label>transport: <select id="md-transport" onchange="siemToggleCondFields()">'
    + mkOpts(['udp', 'tcp', 'tls', 'hec'], dest.transport)
    + '</select></label>'
    + '<label>format: <select id="md-format">'
    + mkOpts(['cef', 'json', 'syslog_cef', 'syslog_json'], dest.format)
    + '</select></label>'
    + '<label>endpoint: <input id="md-endpoint" value="' + endpoint + '"></label>'
    + '<div id="md-tls-section">'
    + '<h3 data-i18n="gui_siem_sec_tls">TLS</h3>'
    + '<label><input type="checkbox" id="md-tls-verify"' + (dest.tls_verify ? ' checked' : '') + '> tls_verify</label>'
    + '<label>tls_ca_bundle: <input id="md-tls-ca" value="' + caBundle + '"></label>'
    + '</div>'
    + '<div id="md-hec-section">'
    + '<h3 data-i18n="gui_siem_sec_hec">HEC</h3>'
    + '<label>hec_token: <input type="password" id="md-hec-token" value="' + hecToken + '"></label>'
    + '</div>'
    + '<h3 data-i18n="gui_siem_sec_batch">Batch</h3>'
    + '<label>batch_size (1-10000): <input type="number" id="md-batch" min="1" max="10000" value="' + Number(dest.batch_size) + '"></label>'
    + '<label>max_retries (&gt;=0): <input type="number" id="md-retries" min="0" value="' + Number(dest.max_retries) + '"></label>'
    + '<div id="md-banner" style="margin-top:10px;color:var(--danger);"></div>'
    + '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px;">'
    + '<button class="btn" onclick="siemCloseModal(event)" data-i18n="gui_cancel">Cancel</button>'
    + '<button class="btn" onclick="siemTestDestInline()" data-i18n="gui_siem_test_inline">Test Connection</button>'
    + '<button class="btn btn-primary" onclick="siemSaveDest(\'' + editAttr + '\')" data-i18n="gui_save">Save</button>'
    + '</div>'
    + '</div>'
    + '</div>';
}

function siemToggleCondFields() {
  var transport = document.getElementById('md-transport');
  if (!transport) return;
  var t = transport.value;
  var tlsEl = document.getElementById('md-tls-section');
  var hecEl = document.getElementById('md-hec-section');
  if (tlsEl) tlsEl.style.display = (t === 'tls' || t === 'hec') ? '' : 'none';
  if (hecEl) hecEl.style.display = (t === 'hec') ? '' : 'none';
}

function siemCloseModal() {
  var host = document.getElementById('siem-modal-host');
  if (host) host.innerHTML = '';
}

async function siemSaveDest(editNameEnc) {
  var editName = editNameEnc ? decodeURIComponent(editNameEnc) : '';
  var sourceTypes = Array.from(document.querySelectorAll('input[name="md-st"]:checked'))
    .map(function(el) { return el.value; });
  var payload = {
    name: editName || document.getElementById('md-name').value.trim(),
    enabled: document.getElementById('md-enabled').checked,
    transport: document.getElementById('md-transport').value,
    format: document.getElementById('md-format').value,
    endpoint: document.getElementById('md-endpoint').value.trim(),
    tls_verify: document.getElementById('md-tls-verify').checked,
    tls_ca_bundle: document.getElementById('md-tls-ca').value.trim() || null,
    hec_token: document.getElementById('md-hec-token').value || null,
    batch_size: Number(document.getElementById('md-batch').value),
    max_retries: Number(document.getElementById('md-retries').value),
    source_types: sourceTypes.length ? sourceTypes : ['audit', 'traffic'],
  };
  var resp, body;
  try {
    if (editName) {
      resp = await fetch('/api/siem/destinations/' + encodeURIComponent(editName), {
        method: 'PUT', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
        body: JSON.stringify(payload),
      });
    } else {
      resp = await fetch('/api/siem/destinations', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
        body: JSON.stringify(payload),
      });
    }
    body = await resp.json();
  } catch (err) {
    document.getElementById('md-banner').textContent = 'Save failed: ' + String(err);
    return;
  }
  if (resp.ok && body.ok !== false) {
    siemCloseModal();
    await window._integrations.renderSiem();
    showRestartBanner(document.getElementById('siem-banner'));
  } else {
    var banner = document.getElementById('md-banner');
    if (banner) banner.textContent = 'Save failed: ' + (body.error || JSON.stringify(body.errors || body));
  }
}

async function siemTestDest(nameEnc) {
  var name = decodeURIComponent(nameEnc);
  var resp, body;
  try {
    resp = await fetch('/api/siem/destinations/' + encodeURIComponent(name) + '/test', {method: 'POST', headers: {'X-CSRF-Token': _csrfToken()}});
    body = await resp.json();
  } catch (err) {
    alert('Test error: ' + String(err));
    return;
  }
  var msg = body.ok
    ? '✓ ' + _t('gui_siem_test_ok') + ' (' + _t('gui_siem_test_latency') + ': ' + Number(body.latency_ms) + ' ms)'
    : '✗ ' + _t('gui_siem_test_fail') + ': ' + String(body.error || '');
  alert(msg);
}

async function siemTestDestInline() {
  var banner = document.getElementById('md-banner');
  if (!banner) return;
  banner.style.color = '';
  banner.textContent = 'Testing…';
  var name = (document.getElementById('md-name') || {}).value || '';
  name = name.trim();
  if (!name) {
    banner.textContent = 'Enter name, then Save, then Test.';
    return;
  }
  var resp, body;
  try {
    resp = await fetch('/api/siem/destinations/' + encodeURIComponent(name) + '/test', {method: 'POST', headers: {'X-CSRF-Token': _csrfToken()}});
    body = await resp.json();
  } catch (err) {
    banner.textContent = 'Test error: ' + String(err);
    return;
  }
  if (resp.status === 404) {
    banner.textContent = 'Destination not yet saved. Save first, then Test.';
  } else if (body.ok) {
    banner.style.color = 'var(--ok, green)';
    banner.textContent = '✓ ' + _t('gui_siem_test_ok') + ' (' + _t('gui_siem_test_latency') + ': ' + Number(body.latency_ms) + ' ms)';
  } else {
    banner.style.color = 'var(--danger)';
    banner.textContent = '✗ ' + _t('gui_siem_test_fail') + ': ' + String(body.error || '');
  }
}
window.siemTestDest = siemTestDest;
window.siemTestDestInline = siemTestDestInline;

window.siemSaveForwarder = siemSaveForwarder;
window.siemDeleteDest = siemDeleteDest;
window.siemOpenDestModal = siemOpenDestModal;
window.siemToggleCondFields = siemToggleCondFields;
window.siemCloseModal = siemCloseModal;
window.siemSaveDest = siemSaveDest;

// ── DLQ sub-tab ──────────────────────────────────────────────────────────────
var _dlqPage = 1;
var DLQ_PAGE_SIZE = 50;
var DLQ_MAX_PAGE = Math.floor(500 / DLQ_PAGE_SIZE); // API cap is 500 entries

window._integrations.setRender('dlq', async function renderDlq() {
  var el = document.getElementById('it-pane-dlq');
  if (!el) return;
  el.innerHTML = buildDlqSkeleton();
  await populateDlqDestinations();
  await dlqSearch();
  if (typeof window.i18nApply === 'function') window.i18nApply();
});

function _fmtShortDt(iso) {
  if (!iso) return '—';
  var d = new Date(iso);
  if (isNaN(d.getTime())) return String(iso);
  var M = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return M[d.getMonth()] + ' ' + String(d.getDate()).padStart(2, '0')
    + ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

function buildDlqSkeleton() {
  return '<div class="toolbar" style="background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);padding:10px 14px;margin-bottom:10px;">'
    + '<div class="form-group" style="margin:0;min-width:130px;">'
    + '<label data-i18n="gui_dlq_filter_dest">Destination</label>'
    + '<select id="dlq-dest" style="width:100%;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:6px 8px;color:var(--fg);font-size:.83rem;">'
    + '<option value="" data-i18n="gui_dlq_filter_all">All</option></select>'
    + '</div>'
    + '<div class="form-group" style="margin:0;flex:1;min-width:140px;">'
    + '<label data-i18n="gui_dlq_filter_reason">Reason contains</label>'
    + '<input id="dlq-reason" style="width:100%;background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:6px 8px;color:var(--fg);font-size:.83rem;">'
    + '</div>'
    + '<button class="btn btn-sm" onclick="dlqSearch()" style="align-self:flex-end;" data-i18n="gui_dlq_search">Search</button>'
    + '<span class="spacer"></span>'
    + '<button class="btn btn-sm" onclick="dlqSelectAll()" style="align-self:flex-end;" data-i18n="gui_dlq_select_all">Select All</button>'
    + '<button class="btn btn-sm" onclick="dlqReplaySelected()" style="align-self:flex-end;" data-i18n="gui_dlq_replay_selected">Replay</button>'
    + '<button class="btn btn-sm btn-warn" onclick="dlqPurgeSelected()" style="align-self:flex-end;" data-i18n="gui_dlq_purge_selected">Purge</button>'
    + '<button class="btn btn-sm btn-danger" onclick="dlqPurgeAll()" style="align-self:flex-end;" data-i18n="gui_dlq_purge_all">Purge ALL</button>'
    + '<button class="btn btn-sm" onclick="dlqExport()" style="align-self:flex-end;" data-i18n="gui_dlq_export">Export CSV</button>'
    + '</div>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup><col style="width:32px"><col style="width:15%"><col style="width:12%"><col><col style="width:110px"><col style="width:55px"><col style="width:130px"></colgroup>'
    + '<thead><tr>'
    + '<th></th>'
    + '<th data-i18n="gui_dlq_th_dest">Dest</th>'
    + '<th data-i18n="gui_dlq_th_event_id">Event ID</th>'
    + '<th data-i18n="gui_dlq_th_reason">Reason</th>'
    + '<th data-i18n="gui_dlq_th_failed_at">Failed At</th>'
    + '<th data-i18n="gui_dlq_th_retries">Retries</th>'
    + '<th></th>'
    + '</tr></thead>'
    + '<tbody id="dlq-tbody"></tbody>'
    + '</table>'
    + '</div>'
    + '<div id="dlq-pager" style="margin-top:8px;"></div>'
    + '<div id="dlq-modal-host"></div>';
}

async function populateDlqDestinations() {
  try {
    var body = await fetch('/api/siem/destinations').then(function(r) { return r.json(); });
    var dests = body.destinations || body || [];
    var sel = document.getElementById('dlq-dest');
    if (!sel) return;
    dests.forEach(function(d) {
      var opt = document.createElement('option');
      opt.value = d.name;
      opt.textContent = d.name;
      sel.appendChild(opt);
    });
  } catch (err) {
    console.warn('Could not load destinations for DLQ filter:', err);
  }
}

async function dlqSearch() {
  _dlqPage = 1;
  await _dlqLoadPage();
}

async function _dlqLoadPage() {
  var destEl = document.getElementById('dlq-dest');
  var reasonEl = document.getElementById('dlq-reason');
  var dest = destEl ? destEl.value : '';
  var reason = reasonEl ? reasonEl.value.trim() : '';

  var q = new URLSearchParams();
  if (dest) q.set('dest', dest);
  // Fetch enough for current page (API has no offset)
  q.set('limit', String(DLQ_PAGE_SIZE * _dlqPage));

  var allEntries = [];
  try {
    var body = await fetch('/api/siem/dlq?' + q.toString()).then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
    allEntries = body.entries || body || [];
  } catch (err) {
    var tbody = document.getElementById('dlq-tbody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="7" style="color:red">Failed to load: ' + escapeAttr(String(err)) + '</td></tr>';
    return;
  }

  // Client-side reason filter
  if (reason) {
    var reasonLower = reason.toLowerCase();
    allEntries = allEntries.filter(function(e) {
      return (e.last_error || '').toLowerCase().indexOf(reasonLower) >= 0;
    });
  }

  var pageEntries = allEntries.slice((_dlqPage - 1) * DLQ_PAGE_SIZE, _dlqPage * DLQ_PAGE_SIZE);
  window._dlqCurrentEntries = pageEntries;
  var tbody = document.getElementById('dlq-tbody');
  if (!tbody) return;
  tbody.innerHTML = pageEntries.map(buildDlqRow).join('')
    || '<tr><td colspan="7" style="color:var(--dim);" data-i18n="gui_dlq_empty">(no DLQ entries)</td></tr>';

  var pager = document.getElementById('dlq-pager');
  if (pager) {
    var hasMore = allEntries.length >= DLQ_PAGE_SIZE * _dlqPage;
    var atMax = _dlqPage >= DLQ_MAX_PAGE;
    pager.innerHTML = _t('gui_dlq_page') + ' ' + _dlqPage + ' · '
      + '<button class="btn" onclick="dlqPrevPage()"' + (_dlqPage <= 1 ? ' disabled' : '') + '>‹</button>'
      + ' <button class="btn" onclick="dlqNextPage()"' + (!hasMore || atMax ? ' disabled' : '') + '>›</button>';
  }
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

function buildDlqRow(e) {
  var id     = Number(e.id);
  var reason = String(e.last_error || '');
  return '<tr>'
    + '<td><input type="checkbox" class="dlq-chk" value="' + id + '"></td>'
    + '<td><code>' + escapeAttr(e.destination || e.source_table || '') + '</code></td>'
    + '<td style="font-size:.78rem;color:var(--dim);">' + escapeAttr(String(e.source_id || '')) + '</td>'
    + '<td title="' + escapeAttr(reason) + '">' + escapeAttr(reason) + '</td>'
    + '<td style="font-size:.78rem;color:var(--dim);">' + escapeAttr(_fmtShortDt(e.quarantined_at)) + '</td>'
    + '<td style="text-align:center;">' + Number(e.retries || 0) + '</td>'
    + '<td style="white-space:nowrap;">'
    + '<button class="btn btn-sm" onclick="dlqView(' + id + ')" data-i18n="gui_dlq_view">View</button> '
    + '<button class="btn btn-sm" onclick="dlqReplay([' + id + '])" data-i18n="gui_dlq_replay">Replay</button>'
    + '</td>'
    + '</tr>';
}

function dlqPrevPage() { if (_dlqPage > 1) { _dlqPage--; _dlqLoadPage(); } }
function dlqNextPage() { if (_dlqPage < DLQ_MAX_PAGE) { _dlqPage++; _dlqLoadPage(); } }

// ── DLQ bulk actions ─────────────────────────────────────────────────────────

function dlqSelectAll() {
  document.querySelectorAll('.dlq-chk').forEach(function(c) { c.checked = true; });
}

function _dlqSelectedIds() {
  return Array.from(document.querySelectorAll('.dlq-chk:checked')).map(function(c) { return Number(c.value); });
}

async function dlqReplaySelected() {
  var ids = _dlqSelectedIds();
  if (!ids.length) return;
  var dest = (document.getElementById('dlq-dest') || {}).value || '';
  if (!dest) { alert('Select a destination filter first.'); return; }
  try {
    var r = await fetch('/api/siem/dlq/replay', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({dest: dest, limit: ids.length}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
  } catch (err) { alert('Replay error: ' + String(err)); return; }
  dlqSearch();
}

async function dlqReplay(ids) {
  var dest = (document.getElementById('dlq-dest') || {}).value || '';
  if (!dest) { alert('Select a destination filter first.'); return; }
  try {
    var r = await fetch('/api/siem/dlq/replay', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({dest: dest, limit: ids.length || 1}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
  } catch (err) { alert('Replay error: ' + String(err)); return; }
  dlqSearch();
}

async function dlqPurgeSelected() {
  var ids = _dlqSelectedIds();
  if (!ids.length) return;
  var dest = (document.getElementById('dlq-dest') || {}).value || '';
  if (!dest) { alert('Select a destination filter first.'); return; }
  if (!confirm('Purge ' + ids.length + ' entries from ' + dest + '?')) return;
  try {
    var r = await fetch('/api/siem/dlq/purge', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({dest: dest, older_than_days: 0}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
  } catch (err) { alert('Purge error: ' + String(err)); return; }
  dlqSearch();
}

async function dlqPurgeAll() {
  var dest = (document.getElementById('dlq-dest') || {}).value || '';
  if (!dest) { alert('Pick a destination first.'); return; }
  var confirmMsg = (typeof _t === 'function') ? _t('gui_dlq_confirm_purge_all') : 'Type the destination name to confirm Purge ALL';
  var typed = prompt(confirmMsg, '');
  if (typed !== dest) return;
  try {
    var r = await fetch('/api/siem/dlq/purge', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': _csrfToken()},
      body: JSON.stringify({dest: dest, older_than_days: 0}),
    });
    if (!r.ok) { alert('Request failed: HTTP ' + r.status); return; }
  } catch (err) { alert('Purge error: ' + String(err)); return; }
  dlqSearch();
}

function dlqExport() {
  var destEl = document.getElementById('dlq-dest');
  var dest = destEl ? destEl.value : '';
  var q = new URLSearchParams();
  if (dest) q.set('dest', dest);
  var a = document.createElement('a');
  a.href = '/api/siem/dlq/export?' + q.toString();
  a.download = 'dlq.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function dlqView(id) {
  var entry = null;
  if (window._dlqCurrentEntries) {
    entry = window._dlqCurrentEntries.filter(function(e) { return Number(e.id) === id; })[0] || null;
  }
  if (!entry) { alert('Entry not found'); return; }

  var host = document.getElementById('dlq-modal-host');
  if (!host) return;
  host.innerHTML = '';
  var backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.addEventListener('click', function() { host.innerHTML = ''; });
  var modal = document.createElement('div');
  modal.className = 'modal';
  modal.addEventListener('click', function(e) { e.stopPropagation(); });

  var title = document.createElement('h3');
  title.setAttribute('data-i18n', 'gui_dlq_modal_title');
  title.textContent = 'DLQ entry detail';
  modal.appendChild(title);

  [
    ['Destination', entry.destination || entry.source_table],
    ['Event ID', entry.source_id],
    ['Reason', entry.last_error],
    ['Failed at', entry.quarantined_at],
    ['Retries', entry.retries],
  ].forEach(function(pair) {
    var d = document.createElement('div');
    var b = document.createElement('b');
    b.textContent = pair[0];
    d.appendChild(b);
    d.appendChild(document.createTextNode(': ' + (pair[1] == null ? '' : pair[1])));
    modal.appendChild(d);
  });

  if (entry.payload_preview) {
    var pre = document.createElement('pre');
    pre.style.cssText = 'background:var(--bg3);padding:10px;overflow:auto;max-height:400px;';
    pre.textContent = entry.payload_preview;
    modal.appendChild(pre);
  }

  var row = document.createElement('div');
  row.style.textAlign = 'right';
  var btn = document.createElement('button');
  btn.className = 'btn';
  btn.setAttribute('data-i18n', 'gui_close');
  btn.textContent = 'Close';
  btn.addEventListener('click', function() { host.innerHTML = ''; });
  row.appendChild(btn);
  modal.appendChild(row);
  backdrop.appendChild(modal);
  host.appendChild(backdrop);
  if (typeof window.i18nApply === 'function') window.i18nApply();
}

window.dlqSearch = dlqSearch;
window._dlqLoadPage = _dlqLoadPage;
window.dlqPrevPage = dlqPrevPage;
window.dlqNextPage = dlqNextPage;
window.dlqSelectAll = dlqSelectAll;
window.dlqReplaySelected = dlqReplaySelected;
window.dlqReplay = dlqReplay;
window.dlqPurgeSelected = dlqPurgeSelected;
window.dlqPurgeAll = dlqPurgeAll;
window.dlqExport = dlqExport;
window.dlqView = dlqView;

// ── Overview sub-tab ─────────────────────────────────────────────────────────
function _buildOvCards(cache, siemStatus, totalPending, totalSent, totalFailed, totalDlq) {
  var siemClass = totalFailed > 0 ? 'card-err' : 'card-ok';
  var dlqClass  = totalDlq  > 0 ? 'card-warn' : 'card-ok';
  var cacheEvents  = Number(cache.events      || 0);
  var cacheTraffic = Number(cache.traffic_raw || 0) + Number(cache.traffic_agg || 0);
  var failedColor  = totalFailed > 0 ? 'var(--danger)' : 'var(--dim)';
  var queueInner = '<div style="display:flex;gap:16px;margin-top:6px;">'
    + '<div><div style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_pending">pending</div>'
    + '<div style="font-size:1.3rem;color:var(--accent2);font-weight:700;">' + totalPending + '</div></div>'
    + '<div><div style="font-size:.7rem;color:var(--success);" data-i18n="gui_ov_sent">sent</div>'
    + '<div style="font-size:1.3rem;color:var(--success);font-weight:700;">' + totalSent + '</div></div>'
    + '<div><div style="font-size:.7rem;color:' + failedColor + ';" data-i18n="gui_ov_failed">failed</div>'
    + '<div style="font-size:1.3rem;color:' + failedColor + ';font-weight:700;">' + totalFailed + '</div></div>'
    + '</div>';
  return '<div class="cards" style="margin-bottom:16px;">'
    + '<div class="card card-neutral">'
    + '<div class="label" data-i18n="gui_ov_cache_lag">Cache Rows</div>'
    + '<div class="value" style="font-size:.95rem;line-height:1.5;">'
    + cacheEvents.toLocaleString() + ' <span style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_events">events</span><br>'
    + cacheTraffic.toLocaleString() + ' <span style="font-size:.7rem;color:var(--dim);" data-i18n="gui_ov_traffic">traffic</span>'
    + '</div>'
    + '</div>'
    + '<div class="card card-neutral">'
    + '<div class="label" data-i18n="gui_ov_siem_destinations">SIEM Destinations</div>'
    + '<div class="value">' + siemStatus.length + '</div>'
    + '<div style="font-size:.75rem;color:var(--dim);">' + _t('gui_ov_destinations_fmt').replace('{n}', siemStatus.length) + '</div>'
    + '</div>'
    + '<div class="card ' + siemClass + '">'
    + '<div class="label" data-i18n="gui_ov_siem_queue">SIEM Queue</div>'
    + queueInner
    + '</div>'
    + '<div class="card ' + dlqClass + '">'
    + '<div class="label" data-i18n="gui_ov_dlq_total">DLQ Total</div>'
    + '<div class="value">' + totalDlq + '</div>'
    + '</div>'
    + '</div>';
}

function _buildOvRecentTable(siemStatus) {
  var rows = '';
  if (siemStatus.length === 0) {
    rows = '<tr><td colspan="5" style="color:var(--dim);padding:16px 10px;" data-i18n="gui_ov_no_events">(no recent events)</td></tr>';
  } else {
    siemStatus.forEach(function(d) {
      var failStyle = Number(d.failed || 0) > 0 ? ' style="color:var(--danger)"' : '';
      rows += '<tr>'
        + '<td><code>' + escapeAttr(d.destination || '') + '</code></td>'
        + '<td>' + Number(d.pending || 0) + '</td>'
        + '<td style="color:var(--success)">' + Number(d.sent || 0) + '</td>'
        + '<td' + failStyle + '>' + Number(d.failed || 0) + '</td>'
        + '<td>' + Number(d.dlq || 0) + '</td>'
        + '</tr>';
    });
  }
  return '<h3 style="color:var(--accent2);font-size:.9rem;font-weight:700;margin:16px 0 8px;" data-i18n="gui_ov_recent_events">Recent dispatch events</h3>'
    + '<div class="table-container">'
    + '<table class="rule-table">'
    + '<colgroup>'
    + '<col style="width:30%"><col style="width:14%"><col style="width:18%"><col style="width:14%"><col style="width:24%">'
    + '</colgroup>'
    + '<thead><tr>'
    + '<th data-i18n="gui_dlq_th_dest">Dest</th>'
    + '<th data-i18n="gui_ov_pending">pending</th>'
    + '<th data-i18n="gui_ov_sent">sent</th>'
    + '<th data-i18n="gui_ov_failed">failed</th>'
    + '<th data-i18n="gui_ov_dlq">DLQ</th>'
    + '</tr></thead>'
    + '<tbody>' + rows + '</tbody>'
    + '</table>'
    + '</div>';
}

window._integrations.setRender('overview', async function renderOverview() {
  var el = document.getElementById('it-pane-overview');
  if (!el) return;
  el.innerHTML = '<p class="subtitle" data-i18n="gui_it_loading">Loading...</p>';

  var cache, siem;
  try {
    var results = await Promise.all([
      fetch('/api/cache/status').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
      fetch('/api/siem/status').then(function(r) { return r.ok ? r.json() : Promise.resolve(null); }),
    ]);
    cache = results[0] || {};
    siem  = results[1] || {status: []};
  } catch (err) {
    el.textContent = '';
    var p = document.createElement('p');
    p.style.color = 'var(--danger,red)';
    p.textContent = _t('gui_ov_load_error').replace('{err}', String(err));
    el.appendChild(p);
    return;
  }

  var siemStatus = siem.status || [];
  var totalPending = 0, totalSent = 0, totalFailed = 0, totalDlq = 0;
  siemStatus.forEach(function(d) {
    totalPending += Number(d.pending || 0);
    totalSent    += Number(d.sent    || 0);
    totalFailed  += Number(d.failed  || 0);
    totalDlq     += Number(d.dlq     || 0);
  });

  el.innerHTML = _buildOvCards(cache, siemStatus, totalPending, totalSent, totalFailed, totalDlq)
               + _buildOvRecentTable(siemStatus);
  if (typeof window.i18nApply === 'function') window.i18nApply();
});
